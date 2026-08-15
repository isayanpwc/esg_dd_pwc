"""Framework versioning, sign-off, IRs, Scope 3, retention and erasure."""

from datetime import date, timedelta

import pytest

from esg.analysis import scope3
from esg.db import repository
from esg.db.models import (
    ComplianceAssessment, InformationRequest, RegulatoryRequirement,
    SupplierEsgAssessment, SupplierMaster,
)
from esg.db.scope import Principal, bind_principal, no_principal
from esg.deal import information_requests as irs
from esg.deal import signoff
from esg.frameworks import registry
from esg.privacy import retention
from esg.security import audit, provisioning

# ════════════════════════════════════════════════════════════════════
#  Framework versioning
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def frameworks(session, admin):
    with bind_principal(admin):
        results = registry.install_all(session, admin)
        session.commit()
    return results


def test_seed_packs_install(session, frameworks):
    assert len(frameworks) >= 2
    assert all(r["installed"] > 0 for r in frameworks)
    with bind_principal(Principal("u", "a", "Admin", {}, all_deals=True)):
        total = repository.count(session, RegulatoryRequirement)
    assert total >= 40


def test_packs_declare_partial_coverage_rather_than_implying_completeness(session, frameworks):
    with bind_principal(Principal("u", "a", "Admin", {}, all_deals=True)):
        report = registry.coverage_report(session)
    brsr = next(r for r in report if r["regulation_id"] == "REG001")
    assert brsr["completeness"] == "partial-extract"
    assert brsr["coverage_pct"] is not None and brsr["coverage_pct"] < 100
    assert "Not the complete BRSR schedule" in brsr["caveat"]


def test_requirements_resolve_by_effective_date(session, frameworks):
    with bind_principal(Principal("u", "a", "Admin", {}, all_deals=True)):
        in_force_2025 = registry.requirements_in_force(session, "REG001", date(2025, 3, 31))
        in_force_2022 = registry.requirements_in_force(session, "REG001", date(2022, 3, 31))
    assert in_force_2025, "BRSR Core applies to FY2025"
    assert in_force_2022 == [], (
        "assessing FY2022 against a 2023 ruleset would score the target on rules "
        "that did not yet exist"
    )


def test_assessing_a_period_with_no_ruleset_is_refused(session, frameworks):
    with bind_principal(Principal("u", "a", "Admin", {}, all_deals=True)):
        with pytest.raises(registry.FrameworkError, match="were in force"):
            registry.resolve_ruleset_version(session, "REG001", date(2019, 1, 1))


def test_installing_a_new_version_closes_the_previous_window(session, frameworks, tmp_path):
    import json

    pack = {
        "regulation": {"regulation_id": "REG001", "regulation_name": "SEBI BRSR Core"},
        "ruleset_version": "2027-core",
        "effective_from": "2027-04-01",
        "coverage": {"completeness": "partial-extract", "estimated_total_datapoints": 1000},
        "requirements": [
            {"requirement_code": "BRSR-CORE-NEW", "requirement_name": "New KPI"},
        ],
    }
    path = tmp_path / "brsr_2027.json"
    path.write_text(json.dumps(pack), encoding="utf-8")

    admin = Principal("u", "a", "Admin", {}, all_deals=True)
    with bind_principal(admin):
        registry.install_pack(session, str(path), admin)
        session.commit()

        version_2025 = registry.resolve_ruleset_version(session, "REG001", date(2025, 6, 1))
        version_2028 = registry.resolve_ruleset_version(session, "REG001", date(2028, 6, 1))

    assert version_2025 == "2023-core"
    assert version_2028 == "2027-core"


# ════════════════════════════════════════════════════════════════════
#  Sign-off
# ════════════════════════════════════════════════════════════════════

REPORT_BYTES = b"Red flag report v1: three material findings."


@pytest.fixture
def roles(deal_setup):
    return {
        **deal_setup,
        "manager_d1": Principal("u-m", "deal_manager", "Manager", {"D1": "Owner"}),
        "admin_d1": Principal("u-ad", "platform_admin", "Admin", {"D1": "Owner"}),
    }


def test_export_without_signoff_is_refused(session, roles):
    with bind_principal(roles["analyst"]):
        with pytest.raises(signoff.NotReleasable, match="no sign-off record"):
            signoff.require_releasable(session, "RPT1", REPORT_BYTES)


def test_manager_signature_makes_it_releasable(session, roles):
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT1", "D1", REPORT_BYTES)
        session.commit()
        with pytest.raises(signoff.NotReleasable, match="Outstanding sign-off"):
            signoff.require_releasable(session, "RPT1", REPORT_BYTES)

    with bind_principal(roles["manager_d1"]):
        signoff.sign(session, "RPT1", REPORT_BYTES, "Approved", "Checked to workings")
        session.commit()
        state = signoff.require_releasable(session, "RPT1", REPORT_BYTES)
    assert state["releasable"] is True


def test_changing_content_after_signing_invalidates_release(session, roles):
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT2", "D1", REPORT_BYTES)
        session.commit()
    with bind_principal(roles["manager_d1"]):
        signoff.sign(session, "RPT2", REPORT_BYTES, "Approved")
        session.commit()

    tampered = b"Red flag report v1: two material findings."
    with bind_principal(roles["analyst"]):
        with pytest.raises(signoff.NotReleasable, match="does not match what was signed"):
            signoff.require_releasable(session, "RPT2", tampered)


def test_reopening_after_a_change_clears_prior_signatures(session, roles):
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT3", "D1", REPORT_BYTES)
        session.commit()
    with bind_principal(roles["manager_d1"]):
        signoff.sign(session, "RPT3", REPORT_BYTES, "Approved")
        session.commit()

    revised = b"Red flag report v2: four material findings."
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT3", "D1", revised)
        session.commit()
        state = signoff.status(session, "RPT3")
    assert state["releasable"] is False
    assert state["signatures"][0]["signed_by"] is None


def test_analyst_cannot_sign(session, roles):
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT4", "D1", REPORT_BYTES)
        session.commit()
        with pytest.raises(PermissionError):
            signoff.sign(session, "RPT4", REPORT_BYTES, "Approved")


def test_admin_cannot_sign_off_a_deliverable(session, roles):
    """Administering the platform is not professional responsibility."""
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT5", "D1", REPORT_BYTES)
        session.commit()
    with bind_principal(roles["admin_d1"]):
        with pytest.raises(PermissionError):
            signoff.sign(session, "RPT5", REPORT_BYTES, "Approved")


def test_rejection_blocks_release(session, roles):
    with bind_principal(roles["analyst"]):
        signoff.open_signoff(session, "RPT6", "D1", REPORT_BYTES)
        session.commit()
    with bind_principal(roles["manager_d1"]):
        signoff.sign(session, "RPT6", REPORT_BYTES, "Rejected", "Exposure unsupported")
        session.commit()
    with bind_principal(roles["analyst"]):
        with pytest.raises(signoff.NotReleasable, match="rejected"):
            signoff.require_releasable(session, "RPT6", REPORT_BYTES)


# ════════════════════════════════════════════════════════════════════
#  Information requests
# ════════════════════════════════════════════════════════════════════

def test_ir_lifecycle(session, roles):
    with bind_principal(roles["analyst"]):
        request = irs.raise_request(
            session, "D1", "C1", "Provide FY24 Scope 1 workings",
            priority="High", due_date=date.today() - timedelta(days=2),
        )
        session.commit()
        assert request.reference == "IR-001"

        register = irs.register(session, "D1")
        assert register[0]["status"] == irs.OVERDUE

        irs.record_response(session, request.ir_id, response_document_id="DOC9")
        session.commit()
        assert irs.register(session, "D1")[0]["status"] == irs.RESPONDED

        irs.close(session, request.ir_id, "Workings reconciled")
        session.commit()
        assert irs.register(session, "D1")[0]["status"] == irs.CLOSED


def test_irs_generated_from_material_compliance_gaps(session, roles, admin):
    with bind_principal(admin):
        session.add_all([
            RegulatoryRequirement(
                requirement_id="REQX", regulation_id="REG001",
                requirement_code="BRSR-CORE-1", requirement_name="Scope 1 emissions",
                source_citation="BRSR Core KPI 1",
            ),
            ComplianceAssessment(
                compliance_id="CA1", deal_id="D1", company_id="C1",
                requirement_id="REQX", reporting_year=2024,
                compliance_status="Non-compliant", severity="Critical",
                gap_description="No Scope 1 disclosure located.",
            ),
            ComplianceAssessment(
                compliance_id="CA2", deal_id="D1", company_id="C1",
                requirement_id="REQY", reporting_year=2024,
                compliance_status="Partial", severity="Low",
                gap_description="Minor omission.",
            ),
        ])
        session.commit()

    with bind_principal(roles["analyst"]):
        created = irs.from_compliance_gaps(session, "D1", "C1", 2024)
        session.commit()

    assert len(created) == 1, "only material gaps should raise an IR"
    assert "Scope 1 emissions" in created[0].title
    assert created[0].priority == "High"
    assert "BRSR Core KPI 1" in created[0].detail


def test_ir_generation_is_idempotent(session, roles, admin):
    with bind_principal(admin):
        session.add(ComplianceAssessment(
            compliance_id="CA3", deal_id="D1", company_id="C1",
            requirement_id="REQZ", reporting_year=2024,
            compliance_status="Non-compliant", severity="High",
        ))
        session.commit()
    with bind_principal(roles["analyst"]):
        first = irs.from_compliance_gaps(session, "D1", "C1", 2024)
        session.commit()
        second = irs.from_compliance_gaps(session, "D1", "C1", 2024)
        session.commit()
    assert len(first) == 1 and second == []


def test_outstanding_at_signing_flags_unquantified_risk(session, roles):
    with bind_principal(roles["analyst"]):
        irs.raise_request(session, "D1", "C1", "Open item", priority="High")
        session.commit()
        summary = irs.outstanding_at_signing(session, "D1")
    assert summary["count"] == 1
    assert "warranty" in summary["note"]


def test_irs_are_deal_scoped(session, roles):
    with bind_principal(roles["analyst"]):
        irs.raise_request(session, "D1", "C1", "Deal one item")
        session.commit()
    with bind_principal(roles["manager"]):
        assert repository.count(session, InformationRequest) == 0


# ════════════════════════════════════════════════════════════════════
#  Scope 3
# ════════════════════════════════════════════════════════════════════

@pytest.fixture
def supply_chain(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([
            SupplierMaster(supplier_id="S1", supplier_name="Chip Foundry Ltd",
                           country="Taiwan", tier="1", annual_spend=40_000_000,
                           spend_currency="USD", criticality="Critical"),
            SupplierMaster(supplier_id="S2", supplier_name="Logistics Co",
                           country="India", tier="1", annual_spend=5_000_000,
                           spend_currency="USD", criticality="Medium"),
            SupplierMaster(supplier_id="S3", supplier_name="Contract Assembly",
                           country="Vietnam", tier="2", annual_spend=2_000_000,
                           spend_currency="USD", criticality="High"),
        ])
        session.commit()
        session.add_all([
            SupplierEsgAssessment(
                supplier_assessment_id="SA1", deal_id="D1", supplier_id="S1",
                company_id="C1", scope3_category="1", scope3_emissions_tco2e=80_000,
                emissions_basis=scope3.ESTIMATED_SPEND, human_rights_risk="Low",
                audit_status="Completed", overall_esg_score=61,
            ),
            SupplierEsgAssessment(
                supplier_assessment_id="SA2", deal_id="D1", supplier_id="S2",
                company_id="C1", scope3_category="4", scope3_emissions_tco2e=20_000,
                emissions_basis=scope3.MEASURED, human_rights_risk="Low",
                audit_status="Completed", overall_esg_score=70,
            ),
            SupplierEsgAssessment(
                supplier_assessment_id="SA3", deal_id="D1", supplier_id="S3",
                company_id="C1", scope3_category="1", scope3_emissions_tco2e=10_000,
                emissions_basis=scope3.MEASURED, human_rights_risk="High",
                audit_status="Not started", overall_esg_score=38,
            ),
        ])
        session.commit()
    return deal_setup


def test_scope3_inventory_separates_measured_from_spend_estimated(session, supply_chain):
    with bind_principal(supply_chain["analyst"]):
        result = scope3.inventory(session, "C1", industry="IT Services & Consulting")

    assert result["total_tco2e"] == 110_000
    # 10,000 of category 1 and all 20,000 of category 4 are measured.
    assert result["measured_tco2e"] == pytest.approx(30_000, abs=1)
    assert result["measured_share"] == pytest.approx(0.273, abs=0.01)
    assert "measured_share" in result["caveat"]


def test_unreported_material_categories_are_named_gaps_not_zeros(session, supply_chain):
    with bind_principal(supply_chain["analyst"]):
        result = scope3.inventory(session, "C1", industry="IT Services & Consulting")
    gap_categories = {g["category"] for g in result["gaps"]}
    # Business travel, commuting, capital goods and use-of-sold-products are
    # material for IT services and are absent from the data.
    assert {2, 6, 7, 11} <= gap_categories
    assert all(g["status"] == "not reported" for g in result["gaps"])
    assert result["completeness"] < 1.0


def test_sector_materiality_changes_which_gaps_matter():
    it_categories = set(scope3.material_categories("IT Services & Consulting"))
    manufacturing = set(scope3.material_categories("Manufacturing"))
    assert 11 in it_categories
    assert {3, 5, 12} <= manufacturing
    assert manufacturing != it_categories


def test_supplier_concentration_and_findings(session, supply_chain):
    with bind_principal(supply_chain["analyst"]):
        result = scope3.supplier_concentration(session, "C1", top_n=2)

    assert result["suppliers_assessed"] == 3
    assert result["concentration_pct"] == pytest.approx(95.7, abs=0.5)
    assert [s["supplier_name"] for s in result["top_suppliers"]][0] == "Chip Foundry Ltd"

    findings = result["findings"]
    assert any("human-rights risk" in f["finding"] for f in findings)
    assert any(f["severity"] == "High" for f in findings)
    assert result["critical_unaudited"][0]["supplier_name"] == "Contract Assembly"


# ════════════════════════════════════════════════════════════════════
#  Retention and erasure
# ════════════════════════════════════════════════════════════════════

@pytest.fixture
def person(session):
    with no_principal():
        account = provisioning.bootstrap_admin(
            session, "dania@pwc.com", "dania", "a-long-enough-passphrase"
        )
        session.commit()
    return account


def test_subject_access_returns_what_is_held(session, person):
    actor = Principal(person.user_id, person.username, "Admin", {}, all_deals=True)
    with bind_principal(actor):
        payload = retention.subject_access(session, "dania@pwc.com", actor)
    assert len(payload) == 1
    assert payload[0]["email"] == "dania@pwc.com"
    assert payload[0]["activity_events"]


def test_erasure_redacts_pii_but_keeps_the_audit_chain_verifiable(session, person):
    actor = Principal(person.user_id, person.username, "Admin", {}, all_deals=True)
    with bind_principal(actor):
        result = retention.erase_subject(session, "dania@pwc.com", actor)
        session.commit()

        refreshed = session.get(type(person), person.user_id)
        assert refreshed.full_name == retention.TOMBSTONE
        assert "dania@pwc.com" not in refreshed.email
        assert refreshed.password_hash is None
        assert refreshed.is_active is False

        ok, problems = audit.verify_chain(session)
    assert ok, problems
    assert result["retained"], "retained audit rows must be disclosed to the subject"
    assert "hash chain" in result["retained"][0]["reason"]


def test_erasure_of_unknown_subject_is_an_error_not_a_silent_success(session, person):
    actor = Principal(person.user_id, person.username, "Admin", {}, all_deals=True)
    with bind_principal(actor):
        with pytest.raises(retention.RetentionError, match="No account matches"):
            retention.erase_subject(session, "nobody@pwc.com", actor)


def test_retention_report_never_proposes_deleting_audit_rows(session, person):
    with no_principal():
        report = retention.report(session)
    assert "never deleted" in report["note"]
