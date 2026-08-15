"""
Deal access grants — the only thing that makes a deal visible to a user.

Grants are never edited in place. Revoking writes a revoked_date and leaves
the original row, so "who could see this deal in March" remains answerable
after the fact, which is the question that actually gets asked when a wall
crossing is queried.
"""

import uuid
from datetime import date

from sqlalchemy import select

from esg.db.models import PERMISSION_LEVELS, DealAccessControl, UserAccount
from esg.db.scope import Principal, no_principal
from esg.security import audit, rbac
from esg import clock


class AccessError(RuntimeError):
    pass


def grant(session, deal_id, user_id, permission_level, actor_principal):
    rbac.check(rbac.MANAGE_ACL, deal_id=deal_id, principal=actor_principal)
    if permission_level not in PERMISSION_LEVELS:
        raise AccessError(f"Permission level must be one of {', '.join(PERMISSION_LEVELS)}.")

    with no_principal():
        if session.get(UserAccount, user_id) is None:
            raise AccessError("User not found.")
        active = session.execute(
            select(DealAccessControl).where(
                DealAccessControl.deal_id == deal_id,
                DealAccessControl.user_id == user_id,
                DealAccessControl.revoked_date.is_(None),
            )
        ).scalars().all()

    for row in active:
        if row.permission_level == permission_level:
            return row  # Already granted at this level; nothing to do.
        row.revoked_date = clock.today()

    row = DealAccessControl(
        access_id=uuid.uuid4().hex[:32],
        deal_id=deal_id,
        user_id=user_id,
        permission_level=permission_level,
        granted_by=actor_principal.username,
        granted_date=clock.today(),
    )
    session.add(row)
    audit.record(
        session, actor_principal.username, "acl.granted",
        entity_type="deal_access_control", entity_id=row.access_id, deal_id=deal_id,
        detail={"user_id": user_id, "level": permission_level},
    )
    return row


def revoke(session, deal_id, user_id, actor_principal):
    rbac.check(rbac.MANAGE_ACL, deal_id=deal_id, principal=actor_principal)
    with no_principal():
        rows = session.execute(
            select(DealAccessControl).where(
                DealAccessControl.deal_id == deal_id,
                DealAccessControl.user_id == user_id,
                DealAccessControl.revoked_date.is_(None),
            )
        ).scalars().all()
    if not rows:
        raise AccessError("No active grant to revoke.")
    for row in rows:
        row.revoked_date = clock.today()
    audit.record(
        session, actor_principal.username, "acl.revoked",
        entity_type="deal_access_control", entity_id=rows[0].access_id, deal_id=deal_id,
        detail={"user_id": user_id, "grants_revoked": len(rows)},
    )
    return rows


def grants_for_deal(session, deal_id, actor_principal, include_revoked=False):
    rbac.check(rbac.VIEW_DEAL, deal_id=deal_id, principal=actor_principal)
    with no_principal():
        stmt = select(DealAccessControl).where(DealAccessControl.deal_id == deal_id)
        if not include_revoked:
            stmt = stmt.where(DealAccessControl.revoked_date.is_(None))
        return session.execute(stmt.order_by(DealAccessControl.granted_date)).scalars().all()


def principal_for(session, account):
    """Build the request-scoped Principal for a freshly authenticated user."""
    with no_principal():
        rows = session.execute(
            select(DealAccessControl).where(
                DealAccessControl.user_id == account.user_id,
                DealAccessControl.revoked_date.is_(None),
            )
        ).scalars().all()
    return Principal(
        user_id=account.user_id,
        username=account.username,
        role=account.role,
        deal_permissions={r.deal_id: r.permission_level for r in rows},
    )
