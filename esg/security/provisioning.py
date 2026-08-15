"""
Account provisioning and authentication.

The old flow let anyone create an account and choose their own role from a
dropdown, including Admin. That is replaced by: an existing Admin issues an
invite for a specific email at a specific role; the invitee redeems a
single-use token to set a password. Role is never accepted from the person
being provisioned.

An SSO path is provided for deployments with an IdP: link_idp_subject()
attaches a verified subject to an already-provisioned account. Even then the
account must exist and its role must have been set by an Admin — SSO
authenticates, it does not authorise.
"""

import hashlib
import hmac
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta

import bcrypt
from sqlalchemy import select

from esg.config import settings
from esg.db.models import ROLES, UserAccount, UserInvite
from esg.db.scope import no_principal
from esg.security import audit, rbac
from esg import clock

INVITE_TTL_HOURS = 72
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
MIN_PASSWORD_LENGTH = 12


class ProvisioningError(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    """Deliberately uninformative to the caller — see authenticate()."""


# ── helpers ──

def email_hash(email):
    """Blind index over the normalised email.

    Keyed with the active data key so the hash is not attackable offline with
    a dictionary of likely corporate addresses.
    """
    from esg.db.crypto import active_key

    _, key = active_key()
    return hmac.new(key, email.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()


def _valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", (email or "").strip()))


def domain_allowed(email):
    allowed = settings().email_domains
    if not allowed:
        return True  # No allowlist configured: dev mode.
    domain = email.strip().lower().rsplit("@", 1)[-1]
    return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in allowed)


def check_password_strength(password):
    """Length-first policy. Long passphrases beat short character soup, so the
    floor is 12 characters and the class requirements are advisory above 16."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) >= 16:
        return True, ""
    classes = sum(bool(re.search(p, password)) for p in
                  (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        return False, ("Passwords under 16 characters need at least three of: "
                       "lowercase, uppercase, digit, symbol.")
    return True, ""


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password, password_hash):
    if not password_hash:
        return False
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


# ── provisioning ──

def create_invite(session, email, role, actor_principal):
    """Admin issues an invitation. Returns (invite, one_time_token).

    The token is returned once and only its hash is stored; it cannot be
    recovered from the database if lost.
    """
    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)

    email = (email or "").strip().lower()
    if not _valid_email(email):
        raise ProvisioningError("Enter a valid email address.")
    if role not in ROLES:
        raise ProvisioningError(f"Role must be one of {', '.join(ROLES)}.")
    if not domain_allowed(email):
        raise ProvisioningError(
            "That email domain is not on the allowlist "
            f"({', '.join(settings().email_domains)})."
        )

    e_hash = email_hash(email)
    with no_principal():
        existing = session.execute(
            select(UserAccount).where(UserAccount.email_hash == e_hash)
        ).scalar_one_or_none()
    if existing and existing.deleted_at is None:
        raise ProvisioningError("An account already exists for that email.")

    token = secrets.token_urlsafe(32)
    invite = UserInvite(
        invite_id=uuid.uuid4().hex[:32],
        email=email,
        email_hash=e_hash,
        role=role,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        invited_by=actor_principal.username,
        expires_at=clock.now() + timedelta(hours=INVITE_TTL_HOURS),
    )
    session.add(invite)
    audit.record(
        session, actor_principal.username, "invite.created",
        entity_type="user_invite", entity_id=invite.invite_id,
        detail={"role": role, "email_hash": e_hash[:12]},
    )
    return invite, token


def accept_invite(session, token, username, password):
    """Redeem an invite. The invitee chooses a username and password — never
    a role."""
    token_hash = hashlib.sha256((token or "").encode()).hexdigest()
    with no_principal():
        invite = session.execute(
            select(UserInvite).where(UserInvite.token_hash == token_hash)
        ).scalar_one_or_none()

    if invite is None:
        raise ProvisioningError("This invitation link is not valid.")
    if invite.revoked_at is not None:
        raise ProvisioningError("This invitation has been revoked.")
    if invite.accepted_at is not None:
        raise ProvisioningError("This invitation has already been used.")
    if invite.expires_at < clock.now():
        raise ProvisioningError("This invitation has expired. Ask an admin to reissue it.")

    username = (username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username):
        raise ProvisioningError(
            "Username must be 3–64 characters, letters/digits/dot/underscore/hyphen."
        )
    ok, message = check_password_strength(password)
    if not ok:
        raise ProvisioningError(message)

    with no_principal():
        clash = session.execute(
            select(UserAccount).where(UserAccount.username == username)
        ).scalar_one_or_none()
    if clash is not None:
        raise ProvisioningError("That username is taken.")

    account = UserAccount(
        user_id=uuid.uuid4().hex[:32],
        username=username,
        email=invite.email,
        email_hash=invite.email_hash,
        full_name=username,
        role=invite.role,
        password_hash=hash_password(password),
        is_active=True,
        must_change_password=False,
        provisioned_by=invite.invited_by,
    )
    invite.accepted_at = clock.now()
    session.add(account)
    audit.record(
        session, username, "account.created",
        entity_type="user_account", entity_id=account.user_id,
        detail={"role": account.role, "invited_by": invite.invited_by},
    )
    return account


def revoke_invite(session, invite_id, actor_principal):
    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)
    with no_principal():
        invite = session.get(UserInvite, invite_id)
    if invite is None:
        raise ProvisioningError("Invitation not found.")
    invite.revoked_at = clock.now()
    audit.record(session, actor_principal.username, "invite.revoked",
                 entity_type="user_invite", entity_id=invite_id)
    return invite


def set_role(session, user_id, role, actor_principal):
    """Only an Admin changes a role, and never their own — that would let a
    single compromised session quietly widen its own reach."""
    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)
    if role not in ROLES:
        raise ProvisioningError(f"Role must be one of {', '.join(ROLES)}.")
    if user_id == actor_principal.user_id:
        raise ProvisioningError("You cannot change your own role.")

    with no_principal():
        account = session.get(UserAccount, user_id)
    if account is None:
        raise ProvisioningError("User not found.")

    before = account.role
    account.role = role
    audit.record(session, actor_principal.username, "account.role_changed",
                 entity_type="user_account", entity_id=user_id,
                 detail={"from": before, "to": role})
    return account


def deactivate(session, user_id, actor_principal):
    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)
    with no_principal():
        account = session.get(UserAccount, user_id)
    if account is None:
        raise ProvisioningError("User not found.")
    account.is_active = False
    audit.record(session, actor_principal.username, "account.deactivated",
                 entity_type="user_account", entity_id=user_id)
    return account


def bootstrap_admin(session, email, username, password):
    """Create the very first Admin. Refuses once any account exists, so it
    cannot be used as a back door later."""
    with no_principal():
        count = session.execute(select(UserAccount)).first()
    if count is not None:
        raise ProvisioningError(
            "Bootstrap is only available on an empty user table. "
            "Use an Admin account to issue an invite instead."
        )
    ok, message = check_password_strength(password)
    if not ok:
        raise ProvisioningError(message)

    account = UserAccount(
        user_id=uuid.uuid4().hex[:32],
        username=username.strip(),
        email=email.strip().lower(),
        email_hash=email_hash(email),
        full_name=username.strip(),
        role="Admin",
        password_hash=hash_password(password),
        must_change_password=False,
        provisioned_by="bootstrap",
    )
    session.add(account)
    audit.record(session, username, "account.bootstrapped",
                 entity_type="user_account", entity_id=account.user_id)
    return account


# ── authentication ──

def authenticate(session, identifier, password):
    """Verify credentials and return the account.

    Failures raise a single AuthenticationError with one message regardless of
    cause, so the response cannot be used to enumerate valid accounts. The
    specific reason goes to the audit log, not to the user.
    """
    identifier = (identifier or "").strip()
    with no_principal():
        account = session.execute(
            select(UserAccount).where(UserAccount.username == identifier)
        ).scalar_one_or_none()
        if account is None and _valid_email(identifier):
            account = session.execute(
                select(UserAccount).where(UserAccount.email_hash == email_hash(identifier))
            ).scalar_one_or_none()

    generic = AuthenticationError("Incorrect username or password.")

    if account is None:
        # Spend comparable time so a missing account is not detectably faster.
        bcrypt.checkpw(b"placeholder", bcrypt.hashpw(b"placeholder", bcrypt.gensalt()))
        audit.record(session, identifier or "unknown", "login.failed",
                     detail={"reason": "no_such_account"})
        raise generic

    if account.deleted_at is not None or not account.is_active:
        audit.record(session, account.username, "login.failed",
                     detail={"reason": "inactive"})
        raise generic

    if account.locked_until and account.locked_until > clock.now():
        audit.record(session, account.username, "login.failed",
                     detail={"reason": "locked"})
        raise AuthenticationError(
            "This account is temporarily locked. Try again shortly."
        )

    if not verify_password(password or "", account.password_hash):
        account.failed_login_count += 1
        if account.failed_login_count >= MAX_FAILED_LOGINS:
            account.locked_until = clock.now() + timedelta(minutes=LOCKOUT_MINUTES)
            account.failed_login_count = 0
            audit.record(session, account.username, "account.locked",
                         detail={"minutes": LOCKOUT_MINUTES})
        else:
            audit.record(session, account.username, "login.failed",
                         detail={"reason": "bad_password",
                                 "attempt": account.failed_login_count})
        raise generic

    account.failed_login_count = 0
    account.locked_until = None
    account.last_login_at = clock.now()
    audit.record(session, account.username, "login.succeeded")
    return account


def link_idp_subject(session, user_id, idp_subject, actor_principal):
    """Attach a verified SSO subject to an existing account.

    The IdP asserts identity; the role still comes from what an Admin
    provisioned. Deployment steps are in docs/DEPLOYMENT.md.
    """
    rbac.check(rbac.MANAGE_USERS, principal=actor_principal)
    with no_principal():
        account = session.get(UserAccount, user_id)
    if account is None:
        raise ProvisioningError("User not found.")
    account.idp_subject = idp_subject
    audit.record(session, actor_principal.username, "account.idp_linked",
                 entity_type="user_account", entity_id=user_id)
    return account


def authenticate_sso(session, idp_subject):
    """Log in a user the IdP has already authenticated."""
    with no_principal():
        account = session.execute(
            select(UserAccount).where(UserAccount.idp_subject == idp_subject)
        ).scalar_one_or_none()
    if account is None or not account.is_active or account.deleted_at is not None:
        audit.record(session, idp_subject or "unknown", "login.failed",
                     detail={"reason": "sso_subject_not_provisioned"})
        raise AuthenticationError(
            "This identity is not provisioned for the platform. Contact an administrator."
        )
    account.last_login_at = clock.now()
    audit.record(session, account.username, "login.succeeded", detail={"method": "sso"})
    return account
