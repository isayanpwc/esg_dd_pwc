"""Credibility of the output: exposure methodology, benchmark provenance,
greenwashing checks.

These are golden-file style tests over the scoring maths — the numbers are
asserted exactly, so a change in methodology has to be a deliberate edit to a
test rather than a silent drift in a client-facing figure.
"""

import pytest

from esg.assurance import greenwashing
from esg.benchmarks import provenance
from esg.db.models import (
    CompanyFinancials, EsgDocumentRegister, EsgMetricData, EsgMetricMaster,
    EsgTarget, ExposureRun, FacilityMaster, FxRateReference, LegalPenalty,
    PeerBenchmarkData,
)
from esg.db.scope import bind_principal
from esg.methodology import exposure

# ════════════════════════════════════════════════════════════════════
#  Exposure methodology
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def financials(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([
            CompanyFinancials(company_id="C1", reporting_year=2024,
                              annual_revenue=500_000_000, reporting_currency="USD"),
            FxRateReference(from_currency="INR", to_currency="USD", rate=0.012,
                            rate_date=__import__("datetime").date(2026, 1, 1),
                            source="test"),
        ])
        session.commit()
    return deal_setup


def test_levied_penalties_are_quantified_and_summed(session, financials):
    penalties = [
        LegalPenalty(penalty_id="P1", deal_id="D1", company_id="C1", amount=250_000,
                     currency="USD", regulator_body="SEBI"),
        LegalPenalty(penalty_id="P2", deal_id="D1", company_id="C1", amount=1_000_000,
                     currency="INR", regulator_body="CPCB"),
    ]
    result = exposure.from_levied_penalties(session, penalties)

    assert result["basis"] == exposure.OBSERVED
    assert result["disclosure"] == exposure.QUANTIFIED
    # 250,000 USD + (1,000,000 INR x 0.012) = 262,000
    assert result["point_estimate_usd"] == 262_000.00
    assert result["low_usd"] == result["high_usd"] == 262_000.00
    assert result["confidence_label"] == "High"


def test_penalty_without_an_fx_rate_is_excluded_not_guessed(session, financials):
    penalties = [
        LegalPenalty(penalty_id="P3", deal_id="D1", company_id="C1", amount=5_000,
                     currency="ZWL", regulator_body="Other"),
    ]
    result = exposure.from_levied_penalties(session, penalties)
    assert result["point_estimate_usd"] == 0.0
    assert any("excluded" in note for note in result["inputs"]["detail"])


def test_expected_value_returns_a_range_and_no_point_estimate(session, financials):
    result = exposure.expected_value_range("High", 4, 500_000_000)

    assert result["basis"] == exposure.UNCALIBRATED
    assert result["disclosure"] == exposure.INDICATIVE
    assert result["point_estimate_usd"] is None, (
        "an uncalibrated model must not emit a single precise-looking number"
    )
    # revenue x probability x share, at both ends of both ranges
    assert result["low_usd"] == pytest.approx(500_000_000 * 0.30 * 0.010)
    assert result["high_usd"] == pytest.approx(500_000_000 * 0.65 * 0.040)
    assert result["low_usd"] < result["high_usd"]


def test_expected_value_publishes_its_parameter_provenance(session, financials):
    result = exposure.expected_value_range("Medium", 3, 100_000_000)
    provenance_note = result["inputs"]["parameter_provenance"]
    assert "CRYSTALLISATION_PROBABILITY" in provenance_note
    assert "calibration" in provenance_note["CRYSTALLISATION_PROBABILITY"].lower()
    assert "must not be presented as a quantified exposure" in result["basis_note"]


def test_sensitivity_shows_each_driver(session, financials):
    result = exposure.expected_value_range("High", 4, 500_000_000)
    drivers = {row["driver"] for row in result["sensitivity"] if "driver" in row}
    assert drivers == {"crystallisation_probability", "impact_share_of_revenue", "revenue"}
    baseline = result["sensitivity"][0]["baseline_usd"]
    halved = next(r for r in result["sensitivity"]
                  if r.get("driver") == "revenue" and r["change"] == "-50%")
    assert halved["exposure_usd"] == pytest.approx(baseline * 0.5)


def test_no_revenue_means_no_estimate_rather_than_zero(session, financials):
    result = exposure.expected_value_range("Critical", 5, None)
    assert result["low_usd"] is None and result["point_estimate_usd"] is None
    assert result["confidence_label"] == "Not quantifiable"


def test_quantify_prefers_observed_evidence_over_the_model(session, financials):
    penalties = [LegalPenalty(penalty_id="P9", deal_id="D1", company_id="C1",
                              amount=10_000, currency="USD")]
    with bind_principal(financials["analyst"]):
        run, result = exposure.quantify(
            session, {"finding_id": "F1", "severity": "Critical", "impact_score": 5},
            company_id="C1", deal_id="D1", evidence_penalties=penalties,
        )
        session.commit()
    assert result["method"] == "levied_penalty"
    assert run.methodology_version == exposure.METHODOLOGY_VERSION


def test_run_is_pinned_to_a_methodology_version(session, financials):
    with bind_principal(financials["analyst"]):
        run, _ = exposure.quantify(
            session, {"finding_id": "F2", "severity": "High", "impact_score": 4},
            company_id="C1", deal_id="D1",
        )
        session.commit()
    assert run.methodology_version == exposure.METHODOLOGY_VERSION
    assert run.sensitivity_json and run.inputs_json


def test_unreviewed_exposure_cannot_enter_a_deliverable(session, financials):
    with bind_principal(financials["analyst"]):
        run, _ = exposure.quantify(
            session, {"finding_id": "F3", "severity": "High", "impact_score": 4},
            company_id="C1", deal_id="D1",
        )
        session.commit()
        with pytest.raises(exposure.ReviewRequired, match="has not been reviewed"):
            exposure.require_review(run)


def test_manager_review_unlocks_it(session, financials):
    from esg.db.scope import Principal

    with bind_principal(financials["analyst"]):
        run, _ = exposure.quantify(
            session, {"finding_id": "F4", "severity": "High", "impact_score": 4},
            company_id="C1", deal_id="D1",
        )
        session.commit()

    manager = Principal("u-m1", "deal_manager", "Manager", {"D1": "Owner"})
    with bind_principal(manager):
        exposure.review(session, run.exposure_run_id, "Reviewed against workings")
        session.commit()
        assert exposure.require_review(run) is run


def test_analyst_cannot_review_their_own_exposure(session, financials):
    with bind_principal(financials["analyst"]):
        run, _ = exposure.quantify(
            session, {"finding_id": "F5", "severity": "High", "impact_score": 4},
            company_id="C1", deal_id="D1",
        )
        session.commit()
        with pytest.raises(PermissionError):
            exposure.review(session, run.exposure_run_id)


def test_presentation_never_renders_an_indicative_run_as_a_single_number(session, financials):
    with bind_principal(financials["analyst"]):
        run, _ = exposure.quantify(
            session, {"finding_id": "F6", "severity": "High", "impact_score": 4},
            company_id="C1", deal_id="D1",
        )
        session.commit()
    shown = exposure.present(run)
    assert shown["disclosure"] == exposure.INDICATIVE
    assert "–" in shown["label"] and "indicative" in shown["label"]


# ════════════════════════════════════════════════════════════════════
#  Benchmark provenance
# ════════════════════════════════════════════════════════════════════

def _peer(name, provenance_value, metric="ENV_SCOPE1", value=100.0):
    return PeerBenchmarkData(
        benchmark_record_id=f"BM-{name}-{provenance_value}",
        peer_company_name=name, industry="IT Services", country="India",
        reporting_year=2024, metric_code=metric, metric_value=value,
        normalised_value=value, provenance=provenance_value,
        source_name="test source",
    )


def test_shipped_demo_data_is_not_publishable(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([_peer(f"Fictional {i}", provenance.ILLUSTRATIVE)
                         for i in range(12)])
        session.commit()

    cohort = provenance.cohort_provenance(session, "ENV_SCOPE1")
    assert cohort["provenance"] == provenance.ILLUSTRATIVE
    assert cohort["publishable"] is False
    assert "not real peers" in cohort["label"]["badge"]
    with pytest.raises(provenance.BenchmarkProvenanceError, match="illustrative"):
        provenance.require_publishable(cohort, "the red-flag report")


def test_licensed_cohort_is_publishable(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([_peer(f"Real Co {i}", provenance.LICENSED) for i in range(12)])
        session.commit()
    cohort = provenance.cohort_provenance(session, "ENV_SCOPE1")
    assert cohort["publishable"] is True
    assert provenance.require_publishable(cohort) is cohort


def test_one_synthetic_peer_contaminates_the_cohort(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([_peer(f"Real Co {i}", provenance.LICENSED) for i in range(11)]
                        + [_peer("Made Up Ltd", provenance.ILLUSTRATIVE)])
        session.commit()
    cohort = provenance.cohort_provenance(session, "ENV_SCOPE1")
    assert cohort["provenance"] == provenance.ILLUSTRATIVE
    assert cohort["publishable"] is False


def test_annotation_cannot_be_omitted_by_the_ui(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([_peer(f"Fictional {i}", provenance.ILLUSTRATIVE) for i in range(6)])
        session.commit()
    cohort = provenance.cohort_provenance(session, "ENV_SCOPE1")
    annotated = provenance.annotate({"percentile": 62}, cohort)
    assert annotated["publishable"] is False
    assert annotated["display_suffix"] == " (illustrative data)"
    assert "ILLUSTRATIVE" in annotated["provenance_label"]


@pytest.mark.parametrize("peers,level", [(12, "quartile"), (6, "directional"), (3, "insufficient")])
def test_cohort_size_governs_the_claim(session, admin, deal_setup, peers, level):
    with bind_principal(admin):
        session.add_all([_peer(f"Co {i}", provenance.LICENSED) for i in range(peers)])
        session.commit()
    cohort = provenance.cohort_provenance(session, "ENV_SCOPE1")
    assert provenance.sufficiency(cohort)["level"] == level


# ════════════════════════════════════════════════════════════════════
#  Greenwashing checks
# ════════════════════════════════════════════════════════════════════

@pytest.fixture
def assurance_setup(session, admin, deal_setup):
    from datetime import date

    with bind_principal(admin):
        session.add_all([
            EsgMetricMaster(metric_code="ENV_SCOPE1", metric_name="Scope 1",
                            esg_pillar="Environment", unit="tCO2e", direction="lower"),
            FacilityMaster(facility_id="F1", company_id="C1", facility_name="Plant A"),
            FacilityMaster(facility_id="F2", company_id="C1", facility_name="Plant B"),
            FacilityMaster(facility_id="F3", company_id="C1", facility_name="Plant C"),
            EsgDocumentRegister(document_id="DOC1", deal_id="D1", company_id="C1",
                                document_name="Sustainability Report 2024.pdf",
                                document_date=date(2024, 6, 1)),
        ])
        session.commit()
    return deal_setup


def _metric(record_id, value, facility_id=None, year=2024, page=10, **kwargs):
    return EsgMetricData(
        record_id=record_id, deal_id="D1", company_id="C1",
        metric_code="ENV_SCOPE1", reporting_year=year, value=value,
        facility_id=facility_id, source_document_id="DOC1", source_page=page,
        **kwargs,
    )


def test_group_total_below_facility_sum_is_flagged_with_citations(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add_all([
            _metric("G1", 8_000, page=42),          # group disclosure
            _metric("F1R", 5_000, facility_id="F1", page=88),
            _metric("F2R", 6_000, facility_id="F2", page=89),
        ])
        session.commit()

        result = greenwashing.reconcile_reported_to_operational(
            session, "C1", "ENV_SCOPE1", 2024
        )

    assert result is not None
    assert result["reported_value"] == 8_000
    assert result["bottom_up_value"] == 11_000
    assert result["gap_pct"] == pytest.approx(-27.27, abs=0.01)
    assert result["severity"] == "High"
    assert result["reported_citation"] == "Sustainability Report 2024.pdf, p.42"
    assert result["facilities_missing"] == ["F3"]
    assert "27.3% below" in result["finding"]


def test_reconciliation_within_tolerance_is_not_a_finding(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add_all([
            _metric("G2", 10_200),
            _metric("F1R", 5_000, facility_id="F1"),
            _metric("F2R", 5_000, facility_id="F2"),
        ])
        session.commit()
        assert greenwashing.reconcile_reported_to_operational(
            session, "C1", "ENV_SCOPE1", 2024
        ) is None


def test_favourable_base_year_restatement_is_flagged(session, assurance_setup):
    """Raising the base year makes later reductions look bigger. For a
    lower-is-better metric that flatters the trend."""
    with bind_principal(assurance_setup["analyst"]):
        session.add_all([
            _metric("BASE_ORIG", 10_000, year=2020, page=30),
            _metric("CURRENT", 7_000, year=2024, page=31),
        ])
        session.commit()
        session.add(_metric("BASE_RESTATED", 13_000, year=2020, page=55,
                            supersedes_record_id="BASE_ORIG"))
        session.commit()

        findings = greenwashing.detect_restatements(session, "C1")

    assert len(findings) == 1
    finding = findings[0]
    assert finding["original_value"] == 10_000 and finding["restated_value"] == 13_000
    assert finding["delta_pct"] == pytest.approx(30.0)
    assert finding["favourable_to_target"] is True
    assert finding["severity"] == "High"
    assert finding["original_citation"] == "Sustainability Report 2024.pdf, p.30"


def test_immaterial_restatement_is_ignored(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add(_metric("R_ORIG", 10_000, year=2020))
        session.commit()
        session.add(_metric("R_NEW", 10_200, year=2020,
                            supersedes_record_id="R_ORIG"))
        session.commit()
        assert greenwashing.detect_restatements(session, "C1") == []


def test_audited_flag_without_assurance_on_file_is_flagged(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add(_metric("A1", 5_000, is_audited=True, page=12))
        session.commit()
        findings = greenwashing.unassured_claims(session, "C1", 2024,
                                                 assured_metric_codes=[])
    assert len(findings) == 1
    assert findings[0]["metric_code"] == "ENV_SCOPE1"
    assert findings[0]["citation"] == "Sustainability Report 2024.pdf, p.12"


def test_assured_metric_is_not_flagged(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add(_metric("A2", 5_000, is_audited=True))
        session.commit()
        findings = greenwashing.unassured_claims(
            session, "C1", 2024, assured_metric_codes=["ENV_SCOPE1"]
        )
    assert findings == []


def test_overstated_target_progress_is_flagged(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add_all([
            _metric("T_LATEST", 9_000, year=2024, page=60),
            EsgTarget(target_id="TGT1", deal_id="D1", company_id="C1",
                      metric_code="ENV_SCOPE1", base_year=2020, base_value=10_000,
                      target_year=2030, target_value=5_000, progress_pct=60.0),
        ])
        session.commit()
        findings = greenwashing.target_progress_divergence(session, "C1")

    assert len(findings) == 1
    # Moved 1,000 of a required 5,000 reduction = 20% implied, 60% claimed.
    assert findings[0]["implied_progress_pct"] == pytest.approx(20.0)
    assert findings[0]["claimed_progress_pct"] == 60.0
    assert findings[0]["gap_pct_points"] == pytest.approx(40.0)
    assert findings[0]["severity"] == "High"


def test_run_all_orders_by_severity(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add_all([
            _metric("X_G", 4_000, page=42),
            _metric("X_F1", 5_000, facility_id="F1"),
            _metric("X_F2", 5_000, facility_id="F2"),
            _metric("X_A", 100, is_audited=True, year=2024, facility_id="F3"),
        ])
        session.commit()
        findings = greenwashing.run_all(session, "C1", 2024,
                                        assured_metric_codes=[])

    severities = [f["severity"] for f in findings]
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    assert severities == sorted(severities, key=lambda s: order[s])
    assert any(f["check"] == "reported_vs_operational" for f in findings)


def test_greenwashing_findings_are_deal_scoped(session, assurance_setup):
    with bind_principal(assurance_setup["analyst"]):
        session.add_all([
            _metric("S_G", 8_000),
            _metric("S_F1", 5_000, facility_id="F1"),
            _metric("S_F2", 6_000, facility_id="F2"),
        ])
        session.commit()

    with bind_principal(assurance_setup["manager"]):
        assert greenwashing.reconcile_reported_to_operational(
            session, "C1", "ENV_SCOPE1", 2024
        ) is None
