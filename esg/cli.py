"""
Operator CLI.

Administrative actions that must not live behind a self-service web form:
creating the first Admin, issuing invitations, granting deal access, verifying
the audit chain and running retention purges.

    python -m esg.cli bootstrap-admin --email a@pwc.com --username admin
    python -m esg.cli invite --email b@pwc.com --role Analyst --as admin
    python -m esg.cli grant --deal D001 --user <user_id> --level Editor --as admin
    python -m esg.cli verify-audit
    python -m esg.cli retention-report
    python -m esg.cli list-users
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from esg.db import engine as db_engine
from esg.db.models import UserAccount
from esg.db.scope import Principal, no_principal
from esg.security import acl, audit, provisioning


def _principal_for_username(session, username):
    with no_principal():
        account = session.execute(
            select(UserAccount).where(UserAccount.username == username)
        ).scalar_one_or_none()
    if account is None:
        sys.exit(f"No such user: {username}")
    if not account.is_active:
        sys.exit(f"Account {username} is deactivated.")
    principal = acl.principal_for(session, account)
    # Administrative CLI actions are cross-deal by nature; make that explicit
    # and audited rather than implicit.
    if account.role == "Admin":
        from esg.db.scope import all_deals_principal

        return all_deals_principal(principal, reason="operator CLI")
    return principal


def cmd_bootstrap_admin(args):
    password = args.password or getpass.getpass("Password for the new Admin: ")
    confirm = args.password or getpass.getpass("Confirm: ")
    if password != confirm:
        sys.exit("Passwords do not match.")
    with db_engine.session() as session:
        with no_principal():
            account = provisioning.bootstrap_admin(
                session, args.email, args.username, password
            )
    print(f"Created Admin {account.username} ({account.user_id}).")


def cmd_invite(args):
    with db_engine.session() as session:
        actor = _principal_for_username(session, getattr(args, "as_user"))
        invite, token = provisioning.create_invite(session, args.email, args.role, actor)
    print(f"Invitation for {args.email} as {args.role}, expires "
          f"{invite.expires_at:%Y-%m-%d %H:%M} UTC.")
    print(f"\nOne-time token (shown once, store nowhere):\n\n  {token}\n")


def cmd_revoke_invite(args):
    with db_engine.session() as session:
        actor = _principal_for_username(session, getattr(args, "as_user"))
        provisioning.revoke_invite(session, args.invite_id, actor)
    print(f"Revoked invitation {args.invite_id}.")


def cmd_grant(args):
    with db_engine.session() as session:
        actor = _principal_for_username(session, getattr(args, "as_user"))
        acl.grant(session, args.deal, args.user, args.level, actor)
    print(f"Granted {args.level} on {args.deal} to {args.user}.")


def cmd_revoke(args):
    with db_engine.session() as session:
        actor = _principal_for_username(session, getattr(args, "as_user"))
        acl.revoke(session, args.deal, args.user, actor)
    print(f"Revoked access to {args.deal} for {args.user}.")


def cmd_set_role(args):
    with db_engine.session() as session:
        actor = _principal_for_username(session, getattr(args, "as_user"))
        provisioning.set_role(session, args.user, args.role, actor)
    print(f"Set {args.user} to {args.role}.")


def cmd_list_users(args):
    with db_engine.session() as session:
        with no_principal():
            accounts = session.execute(
                select(UserAccount).order_by(UserAccount.username)
            ).scalars().all()
        print(f"{'username':<24} {'role':<10} {'active':<7} {'deals':<6} user_id")
        for account in accounts:
            principal = acl.principal_for(session, account)
            print(f"{account.username:<24} {account.role:<10} "
                  f"{str(account.is_active):<7} {len(principal.deal_ids):<6} "
                  f"{account.user_id}")


def cmd_verify_audit(args):
    with db_engine.session() as session:
        ok, problems = audit.verify_chain(session)
    if ok:
        print("Audit chain verified — no tampering detected.")
        return
    print(f"AUDIT CHAIN BROKEN — {len(problems)} problem(s):")
    for problem in problems:
        print(f"  - {problem}")
    sys.exit(2)


def cmd_retention_report(args):
    from esg.privacy import retention

    with db_engine.session() as session:
        report = retention.report(session)
    print(f"Documents past retention:  {report['documents_expired']}")
    print(f"Audit events past window:  {report['audit_expired']}")
    print(f"Inactive accounts:         {report['inactive_accounts']}")
    if report["documents_expired"]:
        print("\nRun 'retention-purge --confirm' to action, or extend the window "
              "via ESG_RETENTION_DAYS_DOCUMENTS.")


def cmd_retention_purge(args):
    from esg.privacy import retention

    if not args.confirm:
        sys.exit("Refusing to purge without --confirm.")
    with db_engine.session() as session:
        actor = _principal_for_username(session, getattr(args, "as_user"))
        result = retention.purge_expired(session, actor, dry_run=args.dry_run)
    print(f"{'Would purge' if args.dry_run else 'Purged'}: "
          f"{result['documents']} documents, {result['pages']} pages.")


def cmd_migrate(args):
    import subprocess

    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"])


def build_parser():
    parser = argparse.ArgumentParser(prog="esg", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_actor(p):
        p.add_argument("--as", dest="as_user", required=True,
                       help="username performing the action")
        return p

    p = sub.add_parser("bootstrap-admin", help="create the first Admin (empty table only)")
    p.add_argument("--email", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--password", help="omit to be prompted")
    p.set_defaults(func=cmd_bootstrap_admin)

    p = with_actor(sub.add_parser("invite", help="issue an invitation"))
    p.add_argument("--email", required=True)
    p.add_argument("--role", required=True, choices=("Admin", "Manager", "Analyst", "Viewer"))
    p.set_defaults(func=cmd_invite)

    p = with_actor(sub.add_parser("revoke-invite"))
    p.add_argument("--invite-id", required=True)
    p.set_defaults(func=cmd_revoke_invite)

    p = with_actor(sub.add_parser("grant", help="grant deal access"))
    p.add_argument("--deal", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--level", required=True,
                   choices=("Owner", "Editor", "Reviewer", "ReadOnly"))
    p.set_defaults(func=cmd_grant)

    p = with_actor(sub.add_parser("revoke", help="revoke deal access"))
    p.add_argument("--deal", required=True)
    p.add_argument("--user", required=True)
    p.set_defaults(func=cmd_revoke)

    p = with_actor(sub.add_parser("set-role"))
    p.add_argument("--user", required=True)
    p.add_argument("--role", required=True,
                   choices=("Admin", "Manager", "Analyst", "Viewer"))
    p.set_defaults(func=cmd_set_role)

    sub.add_parser("list-users").set_defaults(func=cmd_list_users)
    sub.add_parser("verify-audit").set_defaults(func=cmd_verify_audit)
    sub.add_parser("retention-report").set_defaults(func=cmd_retention_report)
    sub.add_parser("migrate", help="alembic upgrade head").set_defaults(func=cmd_migrate)

    p = with_actor(sub.add_parser("retention-purge"))
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_retention_purge)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
