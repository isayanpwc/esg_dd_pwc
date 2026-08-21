"""Loading the bundled canonical dataset when a deal has no registered source.

These run against the real files in `data/`, so they also serve as a contract
test on that folder: if its schema drifts, these fail rather than the loader
silently dropping columns.
"""

import pytest

from esg.db import repository
from esg.db.models import (
    CompanyMaster, DealMaster, EsgMetricData, EsgMetricMaster, FxRateReference,
)
from esg.db.scope import bind_principal
from esg.etl import seed

pytestmark = pytest.mark.skipif(not seed.available(),
                                reason="data/ directory not present")


@pytest.fixture
def deal(session, admin):
    """A bare deal with no data of its own."""
    with bind_principal(admin):
        session.add_all([
            CompanyMaster(company_id="COMP001", company_name="Target"),
            DealMaster(deal_id="DEAL001", deal_name="Project Cirrus",
                       company_id="COMP001"),
        ])
        session.commit()
    from esg.db.scope import Principal

    return Principal("u1", "analyst", "Analyst", {"DEAL001": "Editor"})


def test_loads_when_the_deal_has_nothing(session, deal):
    with bind_principal(deal):
        assert seed.has_registered_sources(session, "DEAL001") is False
        report = seed.load_canonical_dataset(session, "DEAL001")
        session.commit()

    assert report["rows_loaded"] > 0
    assert report["provenance"] == "synthetic-sample"
    assert "SYNTHETIC" in report["warning"]


def test_metric_columns_are_remapped(session, deal):
    """metric_record_id/metric_value/document_id have different names in the
    source; a straight load would drop them."""
    with bind_principal(deal):
        seed.load_canonical_dataset(session, "DEAL001")
        session.commit()
        rows = repository.fetch_all(session, EsgMetricData)

    assert rows, "no metric rows loaded"
    assert all(r.record_id for r in rows)
    assert any(r.value is not None for r in rows)
    assert all(r.deal_id == "DEAL001" for r in rows)


def test_higher_is_better_is_inverted_not_copied(session, deal):
    """The trap: the source states whether HIGHER is better as a boolean, while
    `direction` names the better direction. Copying it across would flip the
    sense of every greenwashing check that asks if a restatement flatters."""
    with bind_principal(deal):
        seed.load_canonical_dataset(session, "DEAL001")
        session.commit()
        masters = repository.fetch_all(session, EsgMetricMaster)

    directions = {m.metric_code: m.direction for m in masters}
    assert directions, "no metric definitions loaded"
    assert set(directions.values()) <= {"higher", "lower", None}

    # Emissions must be lower-is-better; renewable share must be higher.
    for code, expected in (("ENV_SCOPE1", "lower"), ("ENV_RENEW_PCT", "higher")):
        if code in directions:
            assert directions[code] == expected, (
                f"{code} mapped to {directions[code]!r}; the boolean was copied "
                "rather than converted"
            )


def test_fx_rates_are_converted_to_pairs(session, deal):
    """The source is base-relative; the exposure module needs from/to pairs."""
    with bind_principal(deal):
        seed.load_canonical_dataset(session, "DEAL001")
        session.commit()
        rates = repository.fetch_all(session, FxRateReference)

    assert rates, "no fx rates loaded"
    assert all(r.to_currency == "USD" for r in rates)
    assert all(r.rate and r.rate > 0 for r in rates)


def test_everything_lands_in_the_callers_deal(session, deal):
    """Sample rows carry their own deal ids in the CSVs; they must be
    re-pointed so they cannot leak into another engagement."""
    with bind_principal(deal):
        seed.load_canonical_dataset(session, "DEAL001")
        session.commit()
        rows = repository.fetch_all(session, EsgMetricData)
    assert {r.deal_id for r in rows} == {"DEAL001"}


def test_refuses_to_overwrite_real_data(session, deal):
    with bind_principal(deal):
        session.add(EsgMetricData(
            record_id="REAL1", deal_id="DEAL001", company_id="COMP001",
            metric_code="ENV_SCOPE1", reporting_year=2024, value=1.0,
        ))
        session.commit()

        assert seed.has_registered_sources(session, "DEAL001") is True
        assert seed.ensure_data(session, "DEAL001") is None


def test_ensure_data_loads_only_when_empty(session, deal):
    with bind_principal(deal):
        first = seed.ensure_data(session, "DEAL001")
        session.commit()
        assert first is not None and first["rows_loaded"] > 0

        second = seed.ensure_data(session, "DEAL001")
        assert second is None, "must not reload over data it already loaded"


def test_agent_tool_refuses_without_the_confirmation(session, deal):
    from esg.agentic import tools

    with bind_principal(deal):
        with pytest.raises(tools.ToolError, match="confirm_no_sources"):
            tools.execute("load_canonical_sample_data",
                          {"deal_id": "DEAL001", "confirm_no_sources": False},
                          session, deal)


def test_agent_tool_refuses_when_data_already_exists(session, deal):
    from esg.agentic import tools

    with bind_principal(deal):
        session.add(EsgMetricData(
            record_id="REAL2", deal_id="DEAL001", company_id="COMP001",
            metric_code="ENV_SCOPE1", reporting_year=2024, value=1.0,
        ))
        session.commit()
        with pytest.raises(tools.ToolError, match="already has registered data"):
            tools.execute("load_canonical_sample_data",
                          {"deal_id": "DEAL001", "confirm_no_sources": True},
                          session, deal)


def test_deterministic_run_seeds_an_empty_deal_end_to_end(session, deal):
    """The user-facing behaviour: open a deal with no sources, run the agent,
    and it loads the canonical data and analyses it."""
    from esg.agentic import orchestrator

    with bind_principal(deal):
        run = orchestrator.run_goal(session, "DEAL001", "COMP001",
                                    "Assess the target", planner="deterministic")
        session.commit()
        record = orchestrator.transcript(session, run.run_id)

    called = [s["tool"] for s in record["steps"]]
    assert "load_canonical_sample_data" in called
    assert called.count("assess_data_coverage") == 2, (
        "coverage should be re-checked after loading"
    )
    with bind_principal(deal):
        assert repository.count(session, EsgMetricData) > 0
