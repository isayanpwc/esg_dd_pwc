"""
Report sign-off gate.

A red-flag report is a professional deliverable, so release is gated on a named
person signing the *exact content* being released. Signatures are bound to a
SHA-256 of the rendered bytes: change a number after sign-off and the signature
no longer applies, which is the property that makes it worth anything.

Admin deliberately cannot sign — administering the platform is not the same as
taking responsibility for advice. See rbac.SIGNOFF_ROLES.
"""

import hashlib
import uuid

from sqlalchemy import select

from esg import clock
from esg.db.models import ReportSignoff
from esg.db.scope import require_principal
from esg.security import audit, rbac


class SignoffError(RuntimeError):
    pass


class NotReleasable(SignoffError):
    """Raised when a report is exported without complete sign-off."""


def content_hash(payload):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def open_signoff(session, report_id, deal_id, content, report_kind="red_flag_report",
                 required_roles=None):
    """Register a report for sign-off, pinned to its content hash."""
    principal = require_principal()
    rbac.check(rbac.EXPORT_REPORT, deal_id=deal_id, principal=principal)

    digest = content_hash(content)
    roles = tuple(required_roles or rbac.SIGNOFF_ROLES)

    existing = session.execute(
        select(ReportSignoff).where(ReportSignoff.report_id == report_id)
    ).scalars().all()
    for row in existing:
        if row.content_sha256 != digest:
            # Content changed: previous signatures no longer cover it.
            row.signed_by = None
            row.signed_at = None
            row.decision = None
            row.comment = "Invalidated — report content changed after signing."
            row.content_sha256 = digest

    have = {row.required_role for row in existing}
    for role in roles:
        if role in have:
            continue
        session.add(ReportSignoff(
            signoff_id=uuid.uuid4().hex[:32],
            deal_id=deal_id,
            report_id=report_id,
            report_kind=report_kind,
            content_sha256=digest,
            required_role=role,
        ))

    audit.record(
        session, principal.username, "report.signoff_opened",
        entity_type="report_signoff", entity_id=report_id, deal_id=deal_id,
        detail={"content_sha256": digest, "required_roles": list(roles)},
    )
    session.flush()
    return digest


def sign(session, report_id, content, decision="Approved", comment=None):
    """Record a signature against the exact content presented."""
    principal = require_principal()
    digest = content_hash(content)

    rows = session.execute(
        select(ReportSignoff).where(ReportSignoff.report_id == report_id)
    ).scalars().all()
    if not rows:
        raise SignoffError(f"No sign-off is open for report {report_id!r}.")

    deal_id = rows[0].deal_id
    rbac.check(rbac.SIGN_OFF_REPORT, deal_id=deal_id, principal=principal)

    slot = next((r for r in rows if r.required_role == principal.role), None)
    if slot is None:
        raise SignoffError(
            f"Role {principal.role!r} is not a required signatory for this report "
            f"(required: {', '.join(sorted(r.required_role for r in rows))})."
        )
    if slot.content_sha256 != digest:
        raise SignoffError(
            "The report content has changed since sign-off was opened. Reopen "
            "sign-off against the current version before signing."
        )
    if slot.signed_by:
        raise SignoffError(f"Already signed by {slot.signed_by}.")
    if decision not in ("Approved", "Rejected"):
        raise SignoffError("Decision must be Approved or Rejected.")

    slot.signed_by = principal.username
    slot.signed_at = clock.now()
    slot.decision = decision
    slot.comment = comment

    audit.record(
        session, principal.username, "report.signed",
        entity_type="report_signoff", entity_id=report_id, deal_id=deal_id,
        detail={"role": principal.role, "decision": decision,
                "content_sha256": digest, "comment": comment},
    )
    return slot


def status(session, report_id):
    rows = session.execute(
        select(ReportSignoff).where(ReportSignoff.report_id == report_id)
    ).scalars().all()
    if not rows:
        return {"report_id": report_id, "open": False, "releasable": False,
                "signatures": []}
    approved = [r for r in rows if r.decision == "Approved"]
    rejected = [r for r in rows if r.decision == "Rejected"]
    return {
        "report_id": report_id,
        "open": True,
        "content_sha256": rows[0].content_sha256,
        "releasable": len(approved) == len(rows) and not rejected,
        "rejected": bool(rejected),
        "signatures": [
            {"role": r.required_role, "signed_by": r.signed_by,
             "signed_at": r.signed_at, "decision": r.decision, "comment": r.comment}
            for r in sorted(rows, key=lambda r: r.required_role)
        ],
        "outstanding": [r.required_role for r in rows if not r.signed_by],
    }


def require_releasable(session, report_id, content):
    """Gate the export itself."""
    state = status(session, report_id)
    digest = content_hash(content)

    if not state["open"]:
        raise NotReleasable(
            f"Report {report_id!r} has no sign-off record. Open sign-off before export."
        )
    if state["content_sha256"] != digest:
        raise NotReleasable(
            "The content being exported does not match what was signed. "
            "Reopen sign-off for the current version."
        )
    if state["rejected"]:
        raise NotReleasable("A required signatory rejected this report.")
    if not state["releasable"]:
        raise NotReleasable(
            "Outstanding sign-off from: " + ", ".join(state["outstanding"])
        )
    return state
