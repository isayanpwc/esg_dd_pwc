"""Deal isolation is the control that stops one deal team seeing another's
target. These tests assert it holds on read, on write, and when forgotten."""

import pytest
from sqlalchemy import select

from esg.db import repository
from esg.db.models import ComplianceAssessment, DealMaster, EsgMetricData
from esg.db.scope import (
    NoPrincipalBound, Principal, ScopeViolation, all_deals_principal,
    bind_principal,
)


def _metric(deal_id, record_id, value=100.0):
    return EsgMetricData(
        record_id=record_id, deal_id=deal_id, company_id="C1",
        metric_code="ENV_SCOPE1", reporting_year=2024, value=value,
    )


@pytest.fixture
def seeded(session, admin, deal_setup):
    with bind_principal(admin):
        session.add_all([_metric("D1", "R1"), _metric("D2", "R2", 999.0)])
        session.commit()
    return deal_setup


def test_read_returns_only_permitted_deals(session, seeded):
    with bind_principal(seeded["analyst"]):
        rows = session.query(EsgMetricData).all()
    assert [r.record_id for r in rows] == ["R1"]


def test_other_deal_is_invisible_not_merely_forbidden(session, seeded):
    """The row must not come back at all — an empty result, not an error,
    because the existence of D2 is itself confidential."""
    with bind_principal(seeded["analyst"]):
        assert session.get(EsgMetricData, "R2") is None
        assert session.query(EsgMetricData).filter_by(record_id="R2").first() is None


def test_manager_on_other_deal_sees_its_own_only(session, seeded):
    with bind_principal(seeded["manager"]):
        rows = session.query(EsgMetricData).all()
    assert [r.record_id for r in rows] == ["R2"]


def test_query_without_principal_is_refused(session, seeded):
    with pytest.raises(NoPrincipalBound):
        session.query(EsgMetricData).all()


def test_reference_tables_need_no_deal_scope(session, seeded):
    from esg.db.models import CompanyMaster

    assert session.query(CompanyMaster).count() == 2


def test_write_to_unpermitted_deal_is_blocked(session, seeded):
    with bind_principal(seeded["analyst"]):
        session.add(_metric("D2", "R3"))
        with pytest.raises(ScopeViolation, match="may not insert"):
            session.commit()
        session.rollback()


def test_read_only_grant_cannot_write_its_own_deal(session, seeded):
    with bind_principal(seeded["viewer"]):
        session.add(_metric("D1", "R4"))
        with pytest.raises(ScopeViolation, match="read-only|may not insert"):
            session.commit()
        session.rollback()


def test_update_is_scoped_too(session, seeded):
    with bind_principal(seeded["analyst"]):
        row = session.get(EsgMetricData, "R1")
        row.value = 123.0
        session.commit()
        assert session.get(EsgMetricData, "R1").value == 123.0


def test_joins_do_not_leak_the_other_deal(session, seeded):
    """A join is where hand-written filters usually get forgotten."""
    with bind_principal(seeded["analyst"]):
        rows = session.execute(
            select(EsgMetricData, DealMaster).join(
                DealMaster, DealMaster.deal_id == EsgMetricData.deal_id
            )
        ).all()
    assert {d.deal_id for _, d in rows} == {"D1"}


def test_aggregate_counts_only_permitted_rows(session, seeded):
    with bind_principal(seeded["analyst"]):
        assert repository.count(session, EsgMetricData) == 1


def test_unfilterable_aggregate_form_is_refused_not_silently_leaked(session, seeded):
    """Query.count() hides the entity in a subquery. It must fail loudly
    rather than return every deal's rows."""
    with bind_principal(seeded["analyst"]):
        with pytest.raises(ScopeViolation, match="repository.count"):
            session.query(EsgMetricData).count()


def test_group_counts_are_scoped(session, seeded):
    with bind_principal(seeded["analyst"]):
        assert repository.group_count(
            session, EsgMetricData, EsgMetricData.deal_id
        ) == {"D1": 1}


def test_admin_needs_explicit_escalation_for_cross_deal(session, seeded):
    plain_admin = Principal("u-a2", "admin2", "Admin", {"D1": "Owner"})
    with bind_principal(plain_admin):
        assert repository.count(session, EsgMetricData) == 1

    escalated = all_deals_principal(plain_admin, reason="regulator request REF-1")
    with bind_principal(escalated):
        assert repository.count(session, EsgMetricData) == 2


def test_escalation_requires_admin_and_a_reason(session, seeded):
    with pytest.raises(ScopeViolation, match="requires role Admin"):
        all_deals_principal(seeded["manager"], reason="curiosity")
    with pytest.raises(ScopeViolation, match="stated reason"):
        all_deals_principal(Principal("u", "a", "Admin", {}), reason="  ")


def test_scope_survives_a_second_scoped_table(session, seeded, admin):
    with bind_principal(admin):
        session.add(ComplianceAssessment(
            compliance_id="CA1", deal_id="D2", company_id="C2",
            requirement_id="REQ001", reporting_year=2024,
            compliance_status="Non-compliant",
        ))
        session.commit()

    with bind_principal(seeded["analyst"]):
        assert repository.count(session, ComplianceAssessment) == 0
    with bind_principal(seeded["manager"]):
        assert repository.count(session, ComplianceAssessment) == 1
