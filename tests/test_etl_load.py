"""The load step: mapping projection, the validation gate, quarantine, replay.

These assert the behaviour whose absence meant ingested data never reached the
analysis, plus the gate that stops a broken file being half-loaded.
"""

import json

import pandas as pd
import pytest

from esg.db import repository
from esg.db.models import (
    ColumnMapping, EsgMetricData, EsgMetricMaster, IngestionRun, QuarantinedRow,
)
from esg.db.scope import bind_principal
from esg.etl import loader, transforms, validation


@pytest.fixture
def catalogue(session, admin, deal_setup):
    """Metric definitions the incoming data must reference."""
    with bind_principal(admin):
        session.add_all([
            EsgMetricMaster(metric_code="ENV_SCOPE1", metric_name="Scope 1",
                            esg_pillar="Environment", unit="tCO2e"),
            EsgMetricMaster(metric_code="ENV_SCOPE2", metric_name="Scope 2",
                            esg_pillar="Environment", unit="tCO2e"),
        ])
        session.commit()
    return deal_setup


def _mapping(source_column, target_column, transform=None):
    return ColumnMapping(
        mapping_id=f"M-{source_column}", deal_id="D1", source_id="SRC1",
        source_column=source_column, target_table="esg_metric_data",
        target_column=target_column, transform=transform, status="Approved",
    )


@pytest.fixture
def mapped_source(session, catalogue, admin):
    with bind_principal(admin):
        session.add_all([
            _mapping("Ref", "record_id"),
            _mapping("Entity", "company_id"),
            _mapping("Indicator", "metric_code"),
            _mapping("FY", "reporting_year", transform="fiscal_year_label"),
            _mapping("Amount", "value", transform="to_number"),
            _mapping("UoM", "unit"),
        ])
        session.commit()
    return catalogue


def _frame(rows):
    return pd.DataFrame(rows)


GOOD = [
    {"Ref": "R1", "Entity": "C1", "Indicator": "ENV_SCOPE1", "FY": "FY2023-24",
     "Amount": "1,234.5", "UoM": "tCO2e"},
    {"Ref": "R2", "Entity": "C1", "Indicator": "ENV_SCOPE2", "FY": "FY24",
     "Amount": "(890)", "UoM": "tCO2e"},
]


# ── the gap that is now closed ──

def test_approved_mapping_materializes_into_the_canonical_table(session, mapped_source):
    analyst = mapped_source["analyst"]
    with bind_principal(analyst):
        run = loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                                deal_id="D1", source_id="SRC1")
        session.commit()

        rows = repository.fetch_all(session, EsgMetricData,
                                    order_by=EsgMetricData.record_id)

    assert run.status == "Loaded"
    assert run.rows_loaded == 2
    assert [r.record_id for r in rows] == ["R1", "R2"]
    # The analysis layer reads these columns; they must be typed, not strings.
    assert rows[0].value == 1234.5
    assert rows[0].reporting_year == 2024
    assert rows[1].value == -890.0
    assert rows[0].deal_id == "D1"


def test_loaded_rows_land_in_the_callers_deal_only(session, mapped_source):
    with bind_principal(mapped_source["analyst"]):
        loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                          deal_id="D1", source_id="SRC1")
        session.commit()

    with bind_principal(mapped_source["manager"]):
        assert repository.count(session, EsgMetricData) == 0


def test_unmapped_source_columns_are_not_guessed_through(session, mapped_source):
    rows = [dict(GOOD[0], Surprise="should not appear")]
    with bind_principal(mapped_source["analyst"]):
        loader.load_frame(session, _frame(rows), "esg_metric_data",
                          deal_id="D1", source_id="SRC1")
        session.commit()
        loaded = repository.fetch_one(session, EsgMetricData)
    assert not hasattr(loaded, "Surprise")


def test_load_is_idempotent_on_the_primary_key(session, mapped_source):
    with bind_principal(mapped_source["analyst"]):
        loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                          deal_id="D1", source_id="SRC1")
        session.commit()

        revised = [dict(GOOD[0], Amount="2,000")]
        run = loader.load_frame(session, _frame(revised), "esg_metric_data",
                                deal_id="D1", source_id="SRC1")
        session.commit()

        assert run.rows_updated == 1 and run.rows_loaded == 0
        assert repository.count(session, EsgMetricData) == 2
        assert repository.fetch_one(
            session, EsgMetricData, EsgMetricData.record_id == "R1"
        ).value == 2000.0


def test_loading_without_approved_mappings_is_refused(session, catalogue):
    with bind_principal(catalogue["analyst"]):
        with pytest.raises(loader.LoadError, match="no approved column mappings"):
            loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                              deal_id="D1", source_id="SRC-UNAPPROVED")


def test_pending_mappings_do_not_count_as_approved(session, catalogue, admin):
    with bind_principal(admin):
        pending = _mapping("Ref", "record_id")
        pending.status = "Review required"
        session.add(pending)
        session.commit()
    with bind_principal(catalogue["analyst"]):
        with pytest.raises(loader.LoadError, match="no approved column mappings"):
            loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                              deal_id="D1", source_id="SRC1")


# ── the validation gate ──

def test_bad_rows_are_quarantined_not_dropped(session, mapped_source):
    rows = GOOD + [
        {"Ref": "R3", "Entity": "C1", "Indicator": "ENV_SCOPE1", "FY": "FY24",
         "Amount": "not-a-number", "UoM": "tCO2e"},
        {"Ref": "", "Entity": "C1", "Indicator": "ENV_SCOPE1", "FY": "FY24",
         "Amount": "10", "UoM": "tCO2e"},
    ]
    with bind_principal(mapped_source["analyst"]):
        run = loader.load_frame(session, _frame(rows), "esg_metric_data",
                                deal_id="D1", source_id="SRC1",
                                max_quarantine_pct=60)
        session.commit()

        assert run.status == "LoadedWithQuarantine"
        assert run.rows_loaded == 2 and run.rows_quarantined == 2
        assert repository.count(session, EsgMetricData) == 2

        held = loader.quarantined_rows(session, run_id=run.run_id)
        assert len(held) == 2
        reasons = [json.loads(h.reasons_json) for h in held]
        rules = {issue["rule"] for group in reasons for issue in group}
        assert "numeric" in rules and "required" in rules


def test_unknown_metric_code_is_caught_by_referential_check(session, mapped_source):
    rows = [dict(GOOD[0], Indicator="ENV_NOT_A_METRIC")]
    with bind_principal(mapped_source["analyst"]):
        run = loader.load_frame(session, _frame(rows), "esg_metric_data",
                                deal_id="D1", source_id="SRC1",
                                max_quarantine_pct=100)
        session.commit()
        held = loader.quarantined_rows(session, run_id=run.run_id)
    assert len(held) == 1
    assert any(i["rule"] == "foreign_key" for i in json.loads(held[0].reasons_json))


def test_absurd_reporting_year_is_rejected(session, mapped_source):
    rows = [dict(GOOD[0], FY="1823")]
    with bind_principal(mapped_source["analyst"]):
        run = loader.load_frame(session, _frame(rows), "esg_metric_data",
                                deal_id="D1", source_id="SRC1",
                                max_quarantine_pct=100)
        session.commit()
        held = loader.quarantined_rows(session, run_id=run.run_id)
    assert any(i["rule"] == "year_range" for i in json.loads(held[0].reasons_json))


def test_mostly_broken_file_loads_nothing(session, mapped_source):
    rows = [dict(GOOD[0], Ref=f"R{i}", Amount="rubbish") for i in range(8)] + GOOD
    with bind_principal(mapped_source["analyst"]):
        with pytest.raises(loader.GateFailure) as failure:
            loader.load_frame(session, _frame(rows), "esg_metric_data",
                              deal_id="D1", source_id="SRC1")
        session.commit()

        assert repository.count(session, EsgMetricData) == 0
        assert failure.value.report["rows_quarantined"] == 8
        run = repository.fetch_one(session, IngestionRun)
        assert run.status == "Rejected"


def test_dry_run_reports_without_writing(session, mapped_source):
    with bind_principal(mapped_source["analyst"]):
        run = loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                                deal_id="D1", source_id="SRC1", dry_run=True)
        session.commit()
        assert run.status == "DryRun"
        assert repository.count(session, EsgMetricData) == 0
        assert json.loads(run.gate_report)["rows_valid"] == 2


def test_read_only_user_cannot_load(session, mapped_source):
    from esg.db.scope import ScopeViolation

    with bind_principal(mapped_source["viewer"]):
        with pytest.raises((ScopeViolation, PermissionError)):
            loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                              deal_id="D1", source_id="SRC1")


def test_replay_after_correction_loads_the_fixed_row(session, mapped_source):
    rows = GOOD + [
        {"Ref": "R3", "Entity": "C1", "Indicator": "ENV_SCOPE1", "FY": "FY24",
         "Amount": "oops", "UoM": "tCO2e"},
    ]
    with bind_principal(mapped_source["analyst"]):
        run = loader.load_frame(session, _frame(rows), "esg_metric_data",
                                deal_id="D1", source_id="SRC1",
                                max_quarantine_pct=40)
        session.commit()
        held = loader.quarantined_rows(session, run_id=run.run_id)
        assert len(held) == 1

        loader.replay_quarantined(
            session, run.run_id, corrections={held[0].quarantine_id: {"value": 42.0}},
            max_quarantine_pct=100,
        )
        session.commit()

        assert repository.count(session, EsgMetricData) == 3
        assert repository.fetch_one(
            session, EsgMetricData, EsgMetricData.record_id == "R3"
        ).value == 42.0
        assert repository.fetch_one(
            session, QuarantinedRow, QuarantinedRow.quarantine_id == held[0].quarantine_id
        ).status == "Resolved"


def test_run_is_recorded_with_a_gate_report(session, mapped_source):
    with bind_principal(mapped_source["analyst"]):
        run = loader.load_frame(session, _frame(GOOD), "esg_metric_data",
                                deal_id="D1", source_id="SRC1")
        session.commit()
        report = json.loads(run.gate_report)
    assert report["rows_read"] == 2 and report["quarantine_pct"] == 0.0
    assert run.triggered_by == "analyst"


# ── transforms ──

@pytest.mark.parametrize("label,expected", [
    ("FY24", 2024), ("FY2023-24", 2024), ("2023-24", 2024),
    ("23-24", 2024), ("2024", 2024), ("FY2019-20", 2020),
])
def test_fiscal_year_labels(label, expected):
    assert transforms.apply("fiscal_year_label", label) == expected


@pytest.mark.parametrize("raw,expected", [
    ("1,234.5", 1234.5), ("(890)", -890.0), ("45%", 45.0), (" 12 ", 12.0),
])
def test_number_coercion_handles_spreadsheet_conventions(raw, expected):
    assert validation.coerce_number(raw) == expected


def test_unit_transforms():
    assert transforms.apply("kt_to_t", "1.5") == 1500.0
    assert transforms.apply("percent_to_fraction", "45") == 0.45
    assert transforms.apply("millions_to_units", "2") == 2_000_000


def test_transform_names_are_not_evaluated():
    with pytest.raises(transforms.UnknownTransform):
        transforms.apply("__import__('os').system('echo pwned')", "x")
