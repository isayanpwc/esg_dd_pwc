"""
Role and deal permissions, expressed once as data.

Two independent questions are answered here, and both must pass:

  * Role  — what may this *kind* of user ever do? (platform-wide)
  * Deal  — what may they do on *this* engagement? (per-deal ACL)

An Analyst with Editor rights on deal D1 can edit D1 and nothing else. A
Manager with no ACL row for D1 cannot see D1 at all, regardless of role. The
role never widens deal visibility; only the ACL does.
"""

from functools import wraps

from esg.db.scope import ScopeViolation, current_principal, require_principal

# ── Capabilities ──
VIEW_DEAL = "view_deal"
INGEST_DATA = "ingest_data"
APPROVE_MAPPING = "approve_mapping"
ACCEPT_CANDIDATE = "accept_candidate"
RUN_ASSESSMENT = "run_assessment"
EDIT_FINDING = "edit_finding"
REVIEW_EXPOSURE = "review_exposure"
RAISE_IR = "raise_information_request"
SIGN_OFF_REPORT = "sign_off_report"
EXPORT_REPORT = "export_report"
MANAGE_USERS = "manage_users"
MANAGE_ACL = "manage_deal_access"
VIEW_AUDIT = "view_audit"
PURGE_DATA = "purge_data"

ROLE_CAPABILITIES = {
    "Viewer": frozenset({VIEW_DEAL}),
    "Analyst": frozenset({
        VIEW_DEAL, INGEST_DATA, ACCEPT_CANDIDATE, RUN_ASSESSMENT,
        EDIT_FINDING, RAISE_IR, EXPORT_REPORT,
    }),
    "Manager": frozenset({
        VIEW_DEAL, INGEST_DATA, APPROVE_MAPPING, ACCEPT_CANDIDATE,
        RUN_ASSESSMENT, EDIT_FINDING, REVIEW_EXPOSURE, RAISE_IR,
        SIGN_OFF_REPORT, EXPORT_REPORT, MANAGE_ACL, VIEW_AUDIT,
    }),
    "Admin": frozenset({
        VIEW_DEAL, INGEST_DATA, APPROVE_MAPPING, ACCEPT_CANDIDATE,
        RUN_ASSESSMENT, EDIT_FINDING, REVIEW_EXPOSURE, RAISE_IR,
        EXPORT_REPORT, MANAGE_USERS, MANAGE_ACL, VIEW_AUDIT, PURGE_DATA,
    }),
}

# Capabilities that change deal data, so they additionally need Owner/Editor
# on the deal in question.
WRITE_CAPABILITIES = frozenset({
    INGEST_DATA, APPROVE_MAPPING, ACCEPT_CANDIDATE, RUN_ASSESSMENT,
    EDIT_FINDING, RAISE_IR,
})

# Sign-off is deliberately excluded from Admin: administering the platform is
# not the same as taking professional responsibility for a client deliverable.
SIGNOFF_ROLES = ("Manager",)


class Unauthorised(PermissionError):
    """Role lacks the capability, independent of any deal."""


def capabilities(role):
    return ROLE_CAPABILITIES.get(role, frozenset())


def has_capability(role, capability):
    return capability in capabilities(role)


def check(capability, deal_id=None, principal=None):
    """Raise unless the caller may exercise `capability` (on `deal_id`)."""
    principal = principal or require_principal()

    if not has_capability(principal.role, capability):
        raise Unauthorised(
            f"Role {principal.role!r} cannot {capability!r}"
        )

    if deal_id is None:
        return True

    if not principal.can_read(deal_id):
        # Say "no access" rather than "wrong permission" — whether a deal
        # exists is itself confidential.
        raise ScopeViolation(f"No access to deal {deal_id!r}")

    if capability in WRITE_CAPABILITIES and not principal.can_write(deal_id):
        raise ScopeViolation(
            f"{principal.username!r} has read-only access to deal {deal_id!r}"
        )
    return True


def allows(capability, deal_id=None, principal=None):
    """Boolean form, for deciding whether to render a control."""
    try:
        check(capability, deal_id, principal or current_principal())
        return True
    except (Unauthorised, ScopeViolation, PermissionError):
        return False


def requires(capability, deal_arg=None):
    """Decorator form for service functions.

    `deal_arg` names the keyword argument holding the deal id, so the check
    covers both the role and the specific engagement.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            check(capability, kwargs.get(deal_arg) if deal_arg else None)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
