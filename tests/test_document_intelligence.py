"""Document intelligence: ingestion, extraction, citations, promotion.

The properties that matter for due diligence are asserted here: a figure is
always traceable to a page, a scanned page never reads as an empty one, and
nothing machine-read reaches the analysis without a human accept.
"""

import pytest

from esg.db import repository
from esg.db.models import DocumentPage, EsgMetricData, MetricCandidate
from esg.db.scope import bind_principal
from esg.documents import extract, ingest, ocr, promote

REPORT = """Sustainability Report 2024 — Novabyte Technologies Ltd

Environmental Performance for FY2023-24

Scope 1 (direct) GHG emissions were 12,480 tCO2e in FY2023-24.
Scope 2 emissions (market-based) totalled 45.2 ktCO2e.
Total energy consumption was 1,250 GWh.
The share of renewable electricity reached 34.5%.
Water withdrawal: 890 ML across all facilities.

Social
Percentage of women employees: 28.4%
Employee attrition rate stood at 14.2%.
Number of fatalities: 0

Governance
Percentage of independent directors: 50%
"""


@pytest.fixture
def report_file(tmp_path):
    path = tmp_path / "sustainability_report_2024.txt"
    path.write_text(REPORT, encoding="utf-8")
    return str(path)


@pytest.fixture
def ingested(session, deal_setup, report_file):
    with bind_principal(deal_setup["analyst"]):
        document = ingest.ingest_document(
            session, report_file, deal_id="D1", company_id="C1",
            document_type="Sustainability Report", reporting_year=2024,
        )
        session.commit()
    return document, deal_setup


# ── extraction unit behaviour (no database) ──

def test_units_are_converted_to_the_expected_unit():
    found = {c["metric_code"]: c for c in extract.extract_from_text(REPORT, 1, 2024)}
    assert found["ENV_SCOPE2"]["value"] == 45200.0
    assert found["ENV_SCOPE2"]["unit"] == "tCO2e"
    assert found["ENV_ENERGY_TOTAL"]["value"] == 1_250_000.0
    assert found["ENV_ENERGY_TOTAL"]["unit"] == "MWh"


def test_fiscal_year_resolves_to_the_closing_year():
    assert extract.resolve_fiscal_year("FY2023-24") == 2024
    assert extract.resolve_fiscal_year("2019-20") == 2020
    assert extract.resolve_fiscal_year("2024") == 2024
    found = {c["metric_code"]: c for c in extract.extract_from_text(REPORT, 1, 2024)}
    assert found["ENV_SCOPE1"]["reporting_year"] == 2024


def test_a_unit_on_the_following_line_is_not_borrowed():
    """'fatalities: 0' sits directly above a line ending in '%'. The zero is a
    count, and mislabelling it as a percentage would be a real misreading."""
    found = {c["metric_code"]: c for c in extract.extract_from_text(REPORT, 1, 2024)}
    assert found["SOC_FATALITIES"]["value"] == 0.0
    assert found["SOC_FATALITIES"]["unit"] == "count"


def test_a_year_is_not_mistaken_for_a_value():
    text = "Scope 1 emissions\n2023 2024\n11,000 12,480"
    found = extract.extract_from_text(text, 1)
    assert all(c["value"] not in (2023.0, 2024.0) for c in found)


def test_prose_without_a_number_yields_no_candidate():
    text = "Scope 3 emissions were not assured this year and remain under review."
    assert extract.extract_from_text(text, 1) == []


def test_negative_and_grouped_numbers_parse():
    assert extract.parse_number("(890)") == -890.0
    assert extract.parse_number("1,234.5") == 1234.5


def test_indian_scale_words():
    text = "Total waste generated 2.5 lakh tonnes"
    found = extract.extract_from_text(text, 1)
    assert found and found[0]["value"] == 250000.0


# ── ingestion ──

def test_ingestion_stores_one_row_per_page(session, ingested):
    document, deal_setup = ingested
    with bind_principal(deal_setup["analyst"]):
        pages = repository.fetch_all(session, DocumentPage,
                                     DocumentPage.document_id == document.document_id)
    assert document.processing_status == ingest.STATUS_PROCESSED
    assert document.page_count == len(pages) >= 1
    assert all(p.page_number > 0 for p in pages)


def test_document_content_is_hashed_and_deduplicated(session, ingested, report_file):
    document, deal_setup = ingested
    with bind_principal(deal_setup["analyst"]):
        again = ingest.ingest_document(
            session, report_file, deal_id="D1", company_id="C1",
        )
        session.commit()
    assert again.document_id == document.document_id
    assert len(document.content_sha256) == 64


def test_file_path_is_encrypted_at_rest(session, ingested):
    from sqlalchemy import text

    document, _ = ingested
    stored = session.execute(
        text("SELECT file_path FROM esg_document_register WHERE document_id=:d"),
        {"d": document.document_id},
    ).scalar()
    assert "sustainability_report" not in stored


def test_documents_are_deal_scoped(session, ingested):
    from esg.db.models import EsgDocumentRegister

    _, deal_setup = ingested
    with bind_principal(deal_setup["manager"]):
        assert repository.count(session, EsgDocumentRegister) == 0


def test_unsupported_format_is_rejected(session, deal_setup, tmp_path):
    path = tmp_path / "model.xlsb"
    path.write_bytes(b"\x00\x01")
    with bind_principal(deal_setup["analyst"]):
        with pytest.raises(ingest.UnsupportedDocument, match="not a supported"):
            ingest.ingest_document(session, str(path), deal_id="D1", company_id="C1")


def test_image_only_page_is_flagged_not_treated_as_empty(session, deal_setup, tmp_path):
    """The failure mode this guards: a scanned disclosure reading as an absent
    one, which would understate the target's compliance."""
    path = tmp_path / "scanned_consent_order.txt"
    path.write_text("   ", encoding="utf-8")
    with bind_principal(deal_setup["analyst"]):
        document = ingest.ingest_document(session, str(path), deal_id="D1",
                                          company_id="C1")
        session.commit()
        assert document.processing_status == ingest.STATUS_NEEDS_OCR
        assert "manual review" in document.processing_error
        gaps = ingest.pages_needing_review(session, deal_id="D1")
    assert len(gaps) == 1 and gaps[0].is_image_only


def test_ocr_backend_absent_by_default_and_fails_loudly():
    assert ocr.available() is False
    with pytest.raises(ocr.OcrUnavailable, match="not been treated as empty"):
        ocr.NullBackend().image_to_text(b"")


# ── candidates and citations ──

def test_extraction_persists_candidates_with_page_citations(session, ingested):
    document, deal_setup = ingested
    with bind_principal(deal_setup["analyst"]):
        created = extract.extract_document(session, document.document_id)
        session.commit()

    assert created
    for candidate in created:
        assert candidate.document_id == document.document_id
        assert candidate.page_number >= 1
        assert candidate.char_start is not None and candidate.char_end is not None
        assert candidate.snippet
        assert candidate.status == "Pending"


def test_extraction_is_idempotent(session, ingested):
    document, deal_setup = ingested
    with bind_principal(deal_setup["analyst"]):
        first = extract.extract_document(session, document.document_id)
        session.commit()
        second = extract.extract_document(session, document.document_id)
        session.commit()
        total = repository.count(session, MetricCandidate)
    assert second == []
    assert total == len(first)


def test_candidates_do_not_reach_the_analysis_table_on_their_own(session, ingested):
    """Extraction alone must not populate esg_metric_data."""
    document, deal_setup = ingested
    with bind_principal(deal_setup["analyst"]):
        extract.extract_document(session, document.document_id)
        session.commit()
        assert repository.count(session, EsgMetricData) == 0


# ── promotion ──

@pytest.fixture
def candidates(session, ingested):
    document, deal_setup = ingested
    with bind_principal(deal_setup["analyst"]):
        extract.extract_document(session, document.document_id)
        session.commit()
        pending = extract.pending_candidates(session, deal_id="D1")
    return pending, deal_setup, document


def test_accepting_a_candidate_writes_the_citation_with_it(session, candidates):
    pending, deal_setup, document = candidates
    target = next(c for c in pending if c.metric_code == "ENV_SCOPE1")

    with bind_principal(deal_setup["analyst"]):
        record = promote.accept(session, target.candidate_id)
        session.commit()

        assert record.source_document_id == document.document_id
        assert record.source_page == target.page_number
        assert record.human_verified is True
        assert record.value == 12480.0

        citation = promote.citation_for(session, record.record_id)
    assert citation["page"] == target.page_number
    assert "sustainability_report_2024" in citation["document_name"]
    assert citation["reference"].endswith(f"p.{target.page_number}")


def test_reviewer_can_correct_the_machine_reading(session, candidates):
    pending, deal_setup, _ = candidates
    target = next(c for c in pending if c.metric_code == "SOC_ATTRITION")

    with bind_principal(deal_setup["analyst"]):
        record = promote.accept(session, target.candidate_id, corrected_value=15.0)
        session.commit()
    assert record.value == 15.0
    # The original machine reading survives on the candidate.
    assert target.value == 14.2


def test_a_candidate_cannot_be_promoted_twice(session, candidates):
    pending, deal_setup, _ = candidates
    with bind_principal(deal_setup["analyst"]):
        promote.accept(session, pending[0].candidate_id)
        session.commit()
        with pytest.raises(promote.PromotionError, match="already been reviewed"):
            promote.accept(session, pending[0].candidate_id)


def test_rejection_requires_a_reason(session, candidates):
    pending, deal_setup, _ = candidates
    with bind_principal(deal_setup["analyst"]):
        with pytest.raises(promote.PromotionError, match="reason is required"):
            promote.reject(session, pending[0].candidate_id, reason="  ")
        candidate = promote.reject(session, pending[0].candidate_id,
                                   reason="Refers to the prior year")
        session.commit()
    assert candidate.status == "Rejected"


def test_viewer_cannot_promote(session, candidates):
    from esg.db.scope import ScopeViolation

    pending, deal_setup, _ = candidates
    with bind_principal(deal_setup["viewer"]):
        with pytest.raises((ScopeViolation, PermissionError)):
            promote.accept(session, pending[0].candidate_id)


def test_restatement_supersedes_rather_than_overwrites(session, candidates, tmp_path):
    """A later filing revising a prior figure must leave both readings visible —
    that divergence is itself a finding."""
    pending, deal_setup, _ = candidates
    first = next(c for c in pending if c.metric_code == "ENV_SCOPE1")

    with bind_principal(deal_setup["analyst"]):
        original = promote.accept(session, first.candidate_id)
        session.commit()

        revised_path = tmp_path / "annual_report_restated.txt"
        revised_path.write_text(
            "Restated figures for FY2023-24\n"
            "Scope 1 (direct) GHG emissions were 13,900 tCO2e in FY2023-24.\n",
            encoding="utf-8",
        )
        revised_doc = ingest.ingest_document(
            session, str(revised_path), deal_id="D1", company_id="C1",
            document_type="Annual Report", reporting_year=2024,
        )
        session.commit()
        new_candidates = extract.extract_document(session, revised_doc.document_id)
        session.commit()

        restated = promote.accept(
            session,
            next(c for c in new_candidates if c.metric_code == "ENV_SCOPE1").candidate_id,
        )
        session.commit()

        rows = repository.fetch_all(
            session, EsgMetricData, EsgMetricData.metric_code == "ENV_SCOPE1"
        )

    assert restated.supersedes_record_id == original.record_id
    assert "Superseded" in restated.restatement_reason
    assert len(rows) == 2, "both the original and the restated reading must survive"
