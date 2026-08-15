"""
Information-request tracker.

The working artefact of a diligence exercise is the IR list: what we asked the
target for, what came back, and what is still open at signing. Findings and
compliance gaps generate IRs, and a response is linked to the document that
answered it — so "we asked and they never answered" is evidenced rather than
remembered.
"""

import uuid

from sqlalchemy import select

from esg import clock
from esg.db.models import ComplianceAssessment, InformationRequest, RegulatoryRequirement
from esg.db.scope import require_principal
from esg.security import audit, rbac

OPEN = "Open"
RESPONDED = "Responded"
CLOSED = "Closed"
OVERDUE = "Overdue"


class InformationRequestError(RuntimeError):
    pass


def raise_request(session, deal_id, company_id, title, detail=None, priority="Medium",
                  linked_requirement_id=None, linked_finding_id=None, due_date=None,
                  reference=None):
    principal = require_principal()
    rbac.check(rbac.RAISE_IR, deal_id=deal_id, principal=principal)

    if not (title or "").strip():
        raise InformationRequestError("An information request needs a title.")

    request = InformationRequest(
        ir_id=uuid.uuid4().hex[:32],
        deal_id=deal_id,
        company_id=company_id,
        reference=reference or _next_reference(session, deal_id),
        title=title.strip(),
        detail=detail,
        priority=priority,
        linked_requirement_id=linked_requirement_id,
        linked_finding_id=linked_finding_id,
        due_date=due_date,
        status=OPEN,
        raised_by=principal.username,
        raised_at=clock.now(),
    )
    session.add(request)
    audit.record(session, principal.username, "ir.raised",
                 entity_type="information_request", entity_id=request.ir_id,
                 deal_id=deal_id, detail={"title": title, "priority": priority})
    session.flush()
    return request


def _next_reference(session, deal_id):
    count = len(session.execute(
        select(InformationRequest).where(InformationRequest.deal_id == deal_id)
    ).scalars().all())
    return f"IR-{count + 1:03d}"


def from_compliance_gaps(session, deal_id, company_id, reporting_year,
                         severities=("Critical", "High")):
    """Generate IRs for material compliance gaps, one per gap, deduplicated."""
    principal = require_principal()
    rbac.check(rbac.RAISE_IR, deal_id=deal_id, principal=principal)

    gaps = session.execute(
        select(ComplianceAssessment).where(
            ComplianceAssessment.company_id == company_id,
            ComplianceAssessment.reporting_year == reporting_year,
            ComplianceAssessment.compliance_status.in_(("Non-compliant", "Partial")),
        )
    ).scalars().all()

    existing = {
        r.linked_requirement_id
        for r in session.execute(
            select(InformationRequest).where(InformationRequest.deal_id == deal_id)
        ).scalars()
    }

    created = []
    for gap in gaps:
        if gap.severity not in severities or gap.requirement_id in existing:
            continue
        requirement = session.get(RegulatoryRequirement, gap.requirement_id)
        name = requirement.requirement_name if requirement else gap.requirement_id
        created.append(raise_request(
            session, deal_id, company_id,
            title=f"Evidence for: {name}",
            detail=(
                f"{gap.gap_description or 'Requirement not evidenced.'}\n\n"
                f"Requirement: {gap.requirement_id}"
                + (f" ({requirement.source_citation})" if requirement
                   and requirement.source_citation else "")
            ),
            priority="High" if gap.severity == "Critical" else "Medium",
            linked_requirement_id=gap.requirement_id,
        ))
        existing.add(gap.requirement_id)
    return created


def record_response(session, ir_id, response_document_id=None, note=None):
    principal = require_principal()
    request = session.get(InformationRequest, ir_id)
    if request is None:
        raise InformationRequestError("Information request not found or not in scope.")
    rbac.check(rbac.RAISE_IR, deal_id=request.deal_id, principal=principal)

    request.status = RESPONDED
    request.responded_at = clock.now()
    request.response_document_id = response_document_id
    if note:
        request.detail = f"{request.detail or ''}\n\nResponse note: {note}".strip()

    audit.record(session, principal.username, "ir.responded",
                 entity_type="information_request", entity_id=ir_id,
                 deal_id=request.deal_id,
                 detail={"document_id": response_document_id})
    return request


def close(session, ir_id, note=None):
    principal = require_principal()
    request = session.get(InformationRequest, ir_id)
    if request is None:
        raise InformationRequestError("Information request not found or not in scope.")
    rbac.check(rbac.RAISE_IR, deal_id=request.deal_id, principal=principal)

    request.status = CLOSED
    request.closed_by = principal.username
    request.closed_at = clock.now()
    audit.record(session, principal.username, "ir.closed",
                 entity_type="information_request", entity_id=ir_id,
                 deal_id=request.deal_id, detail={"note": note})
    return request


def register(session, deal_id, include_closed=True):
    """The IR list, with overdue items marked."""
    stmt = select(InformationRequest).where(InformationRequest.deal_id == deal_id)
    if not include_closed:
        stmt = stmt.where(InformationRequest.status != CLOSED)
    requests = session.execute(stmt.order_by(InformationRequest.reference)).scalars().all()

    today = clock.today()
    rows = []
    for request in requests:
        overdue = (
            request.status == OPEN
            and request.due_date is not None
            and request.due_date < today
        )
        rows.append({
            "ir_id": request.ir_id,
            "reference": request.reference,
            "title": request.title,
            "priority": request.priority,
            "status": OVERDUE if overdue else request.status,
            "raised_by": request.raised_by,
            "raised_at": request.raised_at,
            "due_date": request.due_date,
            "responded_at": request.responded_at,
            "response_document_id": request.response_document_id,
            "linked_requirement_id": request.linked_requirement_id,
            "days_open": (today - request.raised_at.date()).days
            if request.raised_at else None,
        })
    return rows


def outstanding_at_signing(session, deal_id):
    """Unanswered requests — the list that belongs in the closing memo."""
    rows = register(session, deal_id, include_closed=False)
    outstanding = [r for r in rows if r["status"] in (OPEN, OVERDUE)]
    return {
        "count": len(outstanding),
        "high_priority": [r for r in outstanding if r["priority"] == "High"],
        "overdue": [r for r in outstanding if r["status"] == OVERDUE],
        "items": outstanding,
        "note": (
            "Unanswered information requests at signing are unquantified risk. "
            "Each should be reflected in a warranty, an indemnity, or a price "
            "adjustment."
            if outstanding else "All information requests closed."
        ),
    }
