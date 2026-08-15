"""Access control: provisioning, roles, deal grants, and the audit chain.

The behaviour these lock down is the one that was previously absent — a user
cannot choose their own role, and no capability check is advisory.
"""

import pytest

from esg.db import repository
from esg.db.models import UserAccount
from esg.db.scope import Principal, ScopeViolation, bind_principal, no_principal
from esg.security import acl, audit, provisioning, rbac


@pytest.fixture
def root(session):
    with no_principal():
        account = provisioning.bootstrap_admin(
            session, "root@pwc.com", "root", "correct-horse-battery"
        )
        session.commit()
    return Principal(account.user_id, account.username, "Admin", {}, all_deals=True)


# ── provisioning ──

def test_bootstrap_admin_only_works_on_an_empty_table(session, root):
    with pytest.raises(provisioning.ProvisioningError, match="empty user table"):
        provisioning.bootstrap_admin(session, "second@pwc.com", "second", "another-long-one")


def test_invite_flow_assigns_the_role_the_admin_chose(session, root):
    invite, token = provisioning.create_invite(session, "ana@pwc.com", "Analyst", root)
    session.commit()

    account = provisioning.accept_invite(session, token, "ana", "a-sufficiently-long-pw")
    session.commit()
    assert account.role == "Analyst"
    assert account.provisioned_by == "root"


def test_invitee_cannot_choose_their_own_role(session, root):
    """The old signup form had a role dropdown. accept_invite takes no role
    argument at all, so escalation at signup is not expressible."""
    import inspect as _inspect

    params = _inspect.signature(provisioning.accept_invite).parameters
    assert "role" not in params


def test_token_is_single_use(session, root):
    _, token = provisioning.create_invite(session, "b@pwc.com", "Viewer", root)
    session.commit()
    provisioning.accept_invite(session, token, "bee", "another-long-password")
    session.commit()
    with pytest.raises(provisioning.ProvisioningError, match="already been used"):
        provisioning.accept_invite(session, token, "bee2", "yet-another-long-pw")


def test_expired_invite_is_rejected(session, root):
    from datetime import timedelta

    from esg import clock

    invite, token = provisioning.create_invite(session, "c@pwc.com", "Viewer", root)
    invite.expires_at = clock.now() - timedelta(hours=1)
    session.commit()
    with pytest.raises(provisioning.ProvisioningError, match="expired"):
        provisioning.accept_invite(session, token, "cee", "a-long-enough-password")


def test_revoked_invite_is_rejected(session, root):
    invite, token = provisioning.create_invite(session, "d@pwc.com", "Viewer", root)
    session.commit()
    provisioning.revoke_invite(session, invite.invite_id, root)
    session.commit()
    with pytest.raises(provisioning.ProvisioningError, match="revoked"):
        provisioning.accept_invite(session, token, "dee", "a-long-enough-password")


def test_non_admin_cannot_invite(session, root):
    analyst = Principal("u2", "ana", "Analyst", {})
    with pytest.raises(rbac.Unauthorised):
        provisioning.create_invite(session, "e@pwc.com", "Admin", analyst)


def test_domain_allowlist_is_enforced(session, root, monkeypatch):
    from esg import config

    monkeypatch.setenv("ESG_EMAIL_DOMAINS", "pwc.com")
    config.reload_settings()
    with pytest.raises(provisioning.ProvisioningError, match="allowlist"):
        provisioning.create_invite(session, "outsider@gmail.com", "Viewer", root)
    # Subdomains of an allowed domain are accepted.
    provisioning.create_invite(session, "in@in.pwc.com", "Viewer", root)


def test_admin_cannot_change_their_own_role(session, root):
    with pytest.raises(provisioning.ProvisioningError, match="your own role"):
        provisioning.set_role(session, root.user_id, "Viewer", root)


# ── authentication ──

def test_authenticate_succeeds_and_fails_indistinguishably(session, root):
    account = provisioning.authenticate(session, "root", "correct-horse-battery")
    assert account.username == "root"

    with pytest.raises(provisioning.AuthenticationError) as wrong_pw:
        provisioning.authenticate(session, "root", "nope")
    with pytest.raises(provisioning.AuthenticationError) as no_user:
        provisioning.authenticate(session, "ghost", "nope")
    assert str(wrong_pw.value) == str(no_user.value)


def test_lockout_after_repeated_failures(session, root):
    for _ in range(provisioning.MAX_FAILED_LOGINS):
        with pytest.raises(provisioning.AuthenticationError):
            provisioning.authenticate(session, "root", "wrong")
    session.commit()
    with pytest.raises(provisioning.AuthenticationError, match="locked"):
        provisioning.authenticate(session, "root", "correct-horse-battery")


def test_sso_subject_must_be_provisioned_first(session, root):
    with pytest.raises(provisioning.AuthenticationError, match="not provisioned"):
        provisioning.authenticate_sso(session, "idp|unknown-subject")


def test_password_policy_prefers_length(session):
    assert provisioning.check_password_strength("short")[0] is False
    assert provisioning.check_password_strength("aaaaaaaaaaaaaaaaaaaa")[0] is True
    assert provisioning.check_password_strength("Abcdef123!xyz")[0] is True
    assert provisioning.check_password_strength("abcdefghijkl")[0] is False


# ── PII handling ──

def test_email_is_encrypted_at_rest_but_still_findable(session, root):
    from sqlalchemy import text

    raw = session.execute(
        text("SELECT email FROM user_account WHERE username='root'")
    ).scalar()
    assert "root@pwc.com" not in raw

    with no_principal():
        found = repository.fetch_one(
            session, UserAccount,
            UserAccount.email_hash == provisioning.email_hash("root@pwc.com"),
        )
    assert found.email == "root@pwc.com"


# ── capabilities ──

def test_role_capability_matrix():
    assert rbac.has_capability("Viewer", rbac.VIEW_DEAL)
    assert not rbac.has_capability("Viewer", rbac.EDIT_FINDING)
    assert rbac.has_capability("Manager", rbac.SIGN_OFF_REPORT)
    assert not rbac.has_capability("Analyst", rbac.SIGN_OFF_REPORT)
    assert not rbac.has_capability("Admin", rbac.SIGN_OFF_REPORT), (
        "administering the platform must not confer professional sign-off"
    )


def test_capability_check_needs_deal_access_too(session):
    analyst = Principal("u", "ana", "Analyst", {"D1": "Editor"})
    with bind_principal(analyst):
        assert rbac.check(rbac.EDIT_FINDING, deal_id="D1")
        with pytest.raises(ScopeViolation, match="No access to deal"):
            rbac.check(rbac.EDIT_FINDING, deal_id="D2")


def test_read_only_grant_blocks_write_capability(session):
    viewer = Principal("u", "vw", "Analyst", {"D1": "ReadOnly"})
    with bind_principal(viewer):
        assert rbac.check(rbac.VIEW_DEAL, deal_id="D1")
        with pytest.raises(ScopeViolation, match="read-only"):
            rbac.check(rbac.EDIT_FINDING, deal_id="D1")


def test_allows_is_the_boolean_form(session):
    viewer = Principal("u", "vw", "Viewer", {"D1": "ReadOnly"})
    with bind_principal(viewer):
        assert rbac.allows(rbac.VIEW_DEAL, "D1") is True
        assert rbac.allows(rbac.EDIT_FINDING, "D1") is False
        assert rbac.allows(rbac.VIEW_DEAL, "D2") is False


# ── deal grants ──

def test_grant_then_revoke_changes_visibility(session, root, deal_setup):
    _, token = provisioning.create_invite(session, "new@pwc.com", "Analyst", root)
    session.commit()
    account = provisioning.accept_invite(session, token, "newby", "a-long-enough-pw")
    session.commit()

    principal = acl.principal_for(session, account)
    assert principal.deal_ids == frozenset()

    acl.grant(session, "D1", account.user_id, "Editor", root)
    session.commit()
    assert acl.principal_for(session, account).deal_permissions == {"D1": "Editor"}

    acl.revoke(session, "D1", account.user_id, root)
    session.commit()
    assert acl.principal_for(session, account).deal_ids == frozenset()


def test_revoked_grant_is_retained_for_history(session, root, deal_setup):
    _, token = provisioning.create_invite(session, "h@pwc.com", "Analyst", root)
    session.commit()
    account = provisioning.accept_invite(session, token, "hist", "a-long-enough-pw")
    acl.grant(session, "D1", account.user_id, "Editor", root)
    session.commit()
    acl.revoke(session, "D1", account.user_id, root)
    session.commit()

    active = acl.grants_for_deal(session, "D1", root)
    historic = acl.grants_for_deal(session, "D1", root, include_revoked=True)
    assert len(active) == 0 and len(historic) == 1
    assert historic[0].revoked_date is not None


# ── audit chain ──

def test_audit_chain_verifies(session, root):
    provisioning.create_invite(session, "x@pwc.com", "Viewer", root)
    session.commit()
    ok, problems = audit.verify_chain(session)
    assert ok, problems


def test_tampering_with_a_row_is_detected(session, root):
    from sqlalchemy import text

    provisioning.create_invite(session, "y@pwc.com", "Viewer", root)
    session.commit()
    session.execute(text("UPDATE audit_event SET actor='someone_else' WHERE seq=1"))
    session.commit()

    ok, problems = audit.verify_chain(session)
    assert not ok
    assert any("edited in place" in p for p in problems)


def test_deleting_a_row_is_detected(session, root):
    from sqlalchemy import text

    provisioning.create_invite(session, "z@pwc.com", "Viewer", root)
    provisioning.create_invite(session, "z2@pwc.com", "Viewer", root)
    session.commit()
    session.execute(text("DELETE FROM audit_event WHERE seq=2"))
    session.commit()

    ok, problems = audit.verify_chain(session)
    assert not ok
    assert any("altered or removed" in p for p in problems)
