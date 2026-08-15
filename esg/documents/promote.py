"""
Promotion of a reviewed candidate into esg_metric_data.

This is the only route from a document into the analysis tables, and it is
gated on a human decision. The citation travels with the value —
source_document_id and source_page are written from the candidate, not
supplied by the caller — so every promoted figure can be traced back to the
page it was read from.

Promotion also detects restatement: if a value already exists for the same
company, metric and year, the new record supersedes the old one and records
why, rather than overwriting it. Prior-year revisions are a greenwashing
signal, so the history has to survive.
"""

import uuid

from sqlalchemy import select

from esg import clock
from esg.db.models import EsgMetricData, MetricCandidate
from esg.db.scope import require_principal
from esg.security import audit, rbac


class PromotionError(RuntimeError):
    pass


def accept(session, candidate_id, corrected_value=None, corrected_unit=None,
           corrected_year=None, note=None):
    """Confirm a candidate and write it to esg_metric_data.

    A reviewer may correct the value, unit or year; the original machine reading
    stays on the candidate so the correction is visible afterwards.
    """
    principal = require_principal()

    candidate = session.get(MetricCandidate, candidate_id)
    if candidate is None:
        raise PromotionError("Candidate not found or not in scope.")
    rbac.check(rbac.ACCEPT_CANDIDATE, deal_id=candidate.deal_id, principal=principal)

    if candidate.status != "Pending":
        raise PromotionError(
            f"Candidate is {candidate.status}, not Pending — it has already been reviewed."
        )

    value = corrected_value if corrected_value is not None else candidate.value
    unit = corrected_unit or candidate.unit
    year = corrected_year or candidate.reporting_year

    if value is None:
        raise PromotionError("Cannot accept a candidate with no numeric value.")
    if year is None:
        raise PromotionError(
            "Cannot accept a candidate with no reporting year — set one explicitly."
        )

    superseded = _existing_record(session, candidate, year)
    corrected = corrected_value is not None and corrected_value != candidate.value

    record = EsgMetricData(
        record_id=uuid.uuid4().hex[:32],
        deal_id=candidate.deal_id,
        company_id=candidate.company_id,
        metric_code=candidate.metric_code,
        reporting_year=year,
        value=value,
        unit=unit,
        source_document_id=candidate.document_id,
        source_page=candidate.page_number,
        confidence_score=candidate.confidence,
        is_estimated=False,
        is_audited=False,
        human_verified=True,
        extraction_method=candidate.extraction_method or "document_extraction",
        supersedes_record_id=superseded.record_id if superseded else None,
        restatement_reason=(
            f"Superseded by a later reading from document {candidate.document_id} "
            f"page {candidate.page_number}"
            if superseded else None
        ),
    )
    session.add(record)

    candidate.status = "Accepted"
    candidate.reviewed_by = principal.username
    candidate.reviewed_at = clock.now()
    candidate.promoted_record_id = record.record_id

    audit.record(
        session, principal.username, "candidate.accepted",
        entity_type="metric_candidate", entity_id=candidate_id,
        deal_id=candidate.deal_id,
        detail={
            "metric_code": candidate.metric_code,
            "reporting_year": year,
            "value": value,
            "machine_value": candidate.value,
            "corrected": corrected,
            "citation": f"{candidate.document_id}#p{candidate.page_number}",
            "supersedes": superseded.record_id if superseded else None,
            "note": note,
        },
    )
    session.flush()
    return record


def reject(session, candidate_id, reason):
    principal = require_principal()

    candidate = session.get(MetricCandidate, candidate_id)
    if candidate is None:
        raise PromotionError("Candidate not found or not in scope.")
    rbac.check(rbac.ACCEPT_CANDIDATE, deal_id=candidate.deal_id, principal=principal)
    if candidate.status != "Pending":
        raise PromotionError(f"Candidate is already {candidate.status}.")
    if not (reason or "").strip():
        raise PromotionError("A rejection reason is required.")

    candidate.status = "Rejected"
    candidate.reviewed_by = principal.username
    candidate.reviewed_at = clock.now()

    audit.record(
        session, principal.username, "candidate.rejected",
        entity_type="metric_candidate", entity_id=candidate_id,
        deal_id=candidate.deal_id, detail={"reason": reason},
    )
    return candidate


def _existing_record(session, candidate, year):
    """The current live record for this company/metric/year, if any."""
    return session.execute(
        select(EsgMetricData)
        .where(
            EsgMetricData.company_id == candidate.company_id,
            EsgMetricData.metric_code == candidate.metric_code,
            EsgMetricData.reporting_year == year,
        )
        .order_by(EsgMetricData.record_id)
    ).scalars().first()


def citation_for(session, record_id):
    """Human-readable provenance for a promoted figure, for report footnotes."""
    from esg.db.models import EsgDocumentRegister

    record = session.get(EsgMetricData, record_id)
    if record is None or not record.source_document_id:
        return None
    document = session.get(EsgDocumentRegister, record.source_document_id)
    if document is None:
        return None
    return {
        "document_id": document.document_id,
        "document_name": document.document_name,
        "document_type": document.document_type,
        "page": record.source_page,
        "metric_code": record.metric_code,
        "reporting_year": record.reporting_year,
        "value": record.value,
        "unit": record.unit,
        "human_verified": record.human_verified,
        "reference": f"{document.document_name}, p.{record.source_page}",
    }
