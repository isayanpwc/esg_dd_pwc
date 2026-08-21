"""
Streamlit session <-> esg.security bridge.

The previous version wrote logged_in/user/role straight into session_state and
was the whole of authorisation. Roles now come from a provisioned account and
deal visibility from the ACL, so this module's job is narrower: authenticate,
build the Principal, keep it in the session, and bind it around anything that
touches the database.

Every view that reads deal data must go through session_scope() or
bind_session_principal(); a query outside that binding fails closed in
esg.db.scope rather than returning another deal's rows.
"""

import contextlib

import streamlit as st

from esg.db import engine as db_engine
from esg.db.scope import Principal, bind_principal
from esg.security import acl, provisioning, rbac

_PRINCIPAL_KEY = "esg_principal"


def login_user(identifier, password):
    """Returns (ok, message). Never reveals which half of the pair was wrong."""
    try:
        with db_engine.session() as session:
            account = provisioning.authenticate(session, identifier, password)
            principal = acl.principal_for(session, account)
            st.session_state["logged_in"] = True
            st.session_state["user"] = account.username
            st.session_state["role"] = account.role
            st.session_state["full_name"] = account.full_name
            st.session_state["must_change_password"] = account.must_change_password
            st.session_state[_PRINCIPAL_KEY] = principal
            return True, ""
    except provisioning.AuthenticationError as exc:
        return False, str(exc)


def redeem_invite(token, username, password):
    """Accept an admin-issued invitation. The role comes from the invite."""
    try:
        with db_engine.session() as session:
            account = provisioning.accept_invite(session, token, username, password)
            return True, f"Account created with the {account.role} role. You can sign in now."
    except provisioning.ProvisioningError as exc:
        return False, str(exc)


def logout_user():
    for key in ("logged_in", "user", "role", "full_name", _PRINCIPAL_KEY,
                "must_change_password"):
        st.session_state.pop(key, None)


def is_logged_in():
    return bool(st.session_state.get("logged_in")) and current_principal() is not None


def get_current_user():
    return st.session_state.get("user")


def get_current_role():
    return st.session_state.get("role")


def current_principal():
    return st.session_state.get(_PRINCIPAL_KEY)


def refresh_principal():
    """Re-read the ACL — call after deal access changes so a revoked grant
    takes effect without the user signing out and in again."""
    principal = current_principal()
    if principal is None:
        return None
    with db_engine.session() as session:
        from esg.db.models import UserAccount
        from esg.db.scope import no_principal

        with no_principal():
            account = session.get(UserAccount, principal.user_id)
        if account is None or not account.is_active:
            logout_user()
            return None
        refreshed = acl.principal_for(session, account)
    st.session_state[_PRINCIPAL_KEY] = refreshed
    st.session_state["role"] = refreshed.role
    return refreshed


@contextlib.contextmanager
def session_scope():
    """Database session with the signed-in principal bound.

    Use this for every database access in a view:

        with session_scope() as session:
            ...
    """
    principal = current_principal()
    if principal is None:
        raise PermissionError("Not signed in.")
    # Nesting order matters: db_engine.session() commits as *its* context
    # exits, so the principal has to outlive it. Bound the other way round the
    # flush happens with nothing bound and every deal-scoped write fails.
    with bind_principal(principal):
        with db_engine.session() as session:
            yield session


@contextlib.contextmanager
def bind_session_principal():
    """Bind the principal without opening a session — for callers that already
    hold one."""
    principal = current_principal()
    if principal is None:
        raise PermissionError("Not signed in.")
    with bind_principal(principal):
        yield principal


# ── capability helpers for view code ──

def can(capability, deal_id=None):
    """Whether to render a control. Never the only check — the service layer
    re-checks, so a hidden button is convenience, not security."""
    principal = current_principal()
    if principal is None:
        return False
    return rbac.allows(capability, deal_id, principal)


def require(capability, deal_id=None, message=None):
    """Render an access-denied panel and return False when not permitted."""
    if can(capability, deal_id):
        return True
    st.error(message or "You do not have permission for this action.")
    return False


def accessible_deals():
    principal = current_principal()
    return sorted(principal.deal_ids) if principal else []


def is_admin():
    return get_current_role() == "Admin"


def require_admin():
    if is_admin():
        return True
    st.error("Access Denied — this section requires Admin privileges.")
    return False
