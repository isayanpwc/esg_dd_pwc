"""
Canonical sample dataset loader.

When a deal has no registered data source, the platform can fall back to the
bundled dataset in `data/` so the pipeline has something to work on. That folder
is **synthetic** — every company, supplier and penalty in it is invented — so
everything loaded through here is marked as sample data and benchmark rows keep
their `illustrative` provenance, which the report exporter refuses to publish.

The dataset does not match the canonical schema column-for-column (82% of names
line up), so this module carries the mapping. Four tables need real work:

* `esg_metric_data`      — different names for the key columns
* `esg_metric_master`    — `higher_is_better` is the **inverse** of `direction`
* `deal_master`          — different names, and the deal id must be rewritten
* `fx_rate_reference`    — a different model entirely (base-currency-relative
                           rows vs the pair-based rows the exposure module needs)

The `higher_is_better` inversion is the dangerous one: mapping it straight onto
`direction` would flip the sense of every greenwashing check that asks whether a
restatement flatters the trend. It is converted explicitly below.
"""

import os

from sqlalchemy import select

from esg.db.models import DealMaster, EsgMetricData, IngestionRun
from esg.db.scope import require_principal
from esg.etl import loader
from esg.security import audit, rbac

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"
)

# Reference tables first: the loader's foreign-key checks require the parents to
# exist before the children reference them.
LOAD_ORDER = (
    "company_master",
    "esg_metric_master",
    "facility_master",
    "supplier_master",
    "regulation_master",
    "regulatory_requirement",
    "company_financials",
    "fx_rate_reference",
    "deal_master",
    "esg_document_register",
    "esg_metric_data",
    "esg_target",
    "compliance_assessment",
    "controversy_record",
    "legal_penalty",
    "certification",
    "supplier_esg_assessment",
    "esg_risk_opportunity",
)

# source column -> canonical column, per table. Tables absent here already match.
COLUMN_MAP = {
    "esg_metric_data": {
        "metric_record_id": "record_id",
        "metric_value": "value",
        "document_id": "source_document_id",
        "estimated_flag": "is_estimated",
        "human_verified_flag": "human_verified",
    },
    "esg_metric_master": {
        "standard_unit": "unit",
    },
    "deal_master": {
        "target_company_id": "company_id",
        "deal_stage": "deal_status",
        "deal_team_lead": "deal_lead",
    },
}

# Columns present in the source but with no canonical home. Dropped explicitly
# rather than silently, so a future schema change surfaces here.
DROP_COLUMNS = {
    "esg_metric_data": ("original_value", "original_unit", "assurance_status"),
    "esg_metric_master": ("higher_is_better",),  # converted to `direction` first
    "deal_master": ("confidentiality_level", "base_currency", "data_cutoff_date",
                    "status"),
}


class SeedError(RuntimeError):
    pass


def available():
    return os.path.isdir(DATA_DIR)


def _source_path(table):
    return os.path.join(DATA_DIR, f"{table}.csv")


def has_registered_sources(session, deal_id):
    """True when this deal already has ingested data of its own."""
    existing = session.execute(
        select(IngestionRun).where(IngestionRun.deal_id == deal_id).limit(1)
    ).scalars().first()
    if existing is not None:
        return True
    metrics = session.execute(
        select(EsgMetricData).where(EsgMetricData.deal_id == deal_id).limit(1)
    ).scalars().first()
    return metrics is not None


def _read(table):
    import pandas as pd

    path = _source_path(table)
    if not os.path.exists(path):
        return None
    return pd.read_csv(path)


def _convert_metric_master(frame):
    """higher_is_better -> direction, preserving meaning.

    Mapping the column across as-is would invert every direction: the canonical
    `direction` says which way is *better* as a word ("lower"/"higher"), while
    the source flags whether higher is better as a boolean.
    """
    if "higher_is_better" not in frame.columns:
        return frame

    def to_direction(value):
        text = str(value).strip().lower()
        if text in {"true", "yes", "y", "1"}:
            return "higher"
        if text in {"false", "no", "n", "0"}:
            return "lower"
        return None

    frame = frame.copy()
    frame["direction"] = frame["higher_is_better"].map(to_direction)
    return frame


def _convert_fx(frame):
    """Base-relative rows -> the pair-based rows the exposure module reads.

    The source says "1 unit of base currency buys `rate_to_base_currency` of
    `currency_code`". The canonical model wants an explicit from/to pair, and
    the only pair the exposure code looks up is <currency>/USD.
    """
    import pandas as pd

    rows = []
    for _, row in frame.iterrows():
        code = str(row.get("currency_code", "")).strip().upper()
        base = str(row.get("base_currency", "")).strip().upper()
        rate = row.get("rate_to_base_currency")
        if not code or not base or pd.isna(rate) or float(rate) == 0:
            continue
        if base == "USD":
            # rate = units of `code` per USD -> USD per unit of `code`
            rows.append({"from_currency": code, "to_currency": "USD",
                         "rate": 1.0 / float(rate), "rate_date": row.get("as_of_date"),
                         "source": "canonical sample dataset"})
        elif code == "USD":
            rows.append({"from_currency": base, "to_currency": "USD",
                         "rate": float(rate), "rate_date": row.get("as_of_date"),
                         "source": "canonical sample dataset"})
    return pd.DataFrame(rows)


def _project(table, frame, deal_id):
    """Rename, convert and scope one source frame onto the canonical schema."""
    if table == "esg_metric_master":
        frame = _convert_metric_master(frame)
    if table == "fx_rate_reference":
        frame = _convert_fx(frame)

    frame = frame.rename(columns=COLUMN_MAP.get(table, {}))
    drops = [c for c in DROP_COLUMNS.get(table, ()) if c in frame.columns]
    if drops:
        frame = frame.drop(columns=drops)

    if "deal_id" in frame.columns:
        # Every row is re-pointed at the caller's deal, so sample data can never
        # land in — or leak across — a different engagement.
        frame = frame.copy()
        frame["deal_id"] = deal_id
    if table == "deal_master":
        frame = frame.copy()
        frame["deal_id"] = deal_id
        frame = frame.head(1)
    return frame


def load_canonical_dataset(session, deal_id, max_quarantine_pct=100.0):
    """Load the bundled dataset into a deal. Returns a per-table report."""
    principal = require_principal()
    rbac.check(rbac.INGEST_DATA, deal_id=deal_id, principal=principal)

    if not available():
        raise SeedError(
            f"No canonical dataset directory at {DATA_DIR}. Nothing to load."
        )

    report = []
    for table in LOAD_ORDER:
        frame = _read(table)
        if frame is None or frame.empty:
            report.append({"table": table, "status": "absent", "rows": 0})
            continue

        if table not in loader.validation.SPECS:
            # No validation spec means no canonical target — skip rather than
            # guess a schema.
            report.append({"table": table, "status": "no_spec", "rows": len(frame)})
            continue

        projected = _project(table, frame, deal_id)
        try:
            run = loader.load_frame(
                session, projected, table, deal_id=deal_id,
                source_name=f"canonical-sample:{table}", mappings=[],
                max_quarantine_pct=max_quarantine_pct,
            )
        except loader.GateFailure as exc:
            report.append({"table": table, "status": "rejected",
                           "rows": len(projected), "reason": str(exc)})
            continue

        report.append({
            "table": table,
            "status": run.status,
            "rows": run.rows_read,
            "loaded": run.rows_loaded,
            "updated": run.rows_updated,
            "quarantined": run.rows_quarantined,
        })

    loaded = sum(r.get("loaded", 0) or 0 for r in report)
    quarantined = sum(r.get("quarantined", 0) or 0 for r in report)

    audit.record(
        session, principal.username, "ingestion.sample_data_loaded",
        entity_type="deal_master", entity_id=deal_id, deal_id=deal_id,
        detail={"tables": len(report), "rows_loaded": loaded,
                "rows_quarantined": quarantined},
    )
    session.flush()

    return {
        "deal_id": deal_id,
        "tables": report,
        "rows_loaded": loaded,
        "rows_quarantined": quarantined,
        "provenance": "synthetic-sample",
        "warning": (
            "This is the bundled SYNTHETIC dataset. Every company, supplier and "
            "penalty in it is fictional. Label any figure derived from it as "
            "illustrative; it must not inform a real investment decision, and "
            "benchmarks built on it are refused for client export."
        ),
    }


def ensure_data(session, deal_id):
    """Load the sample dataset only if the deal has nothing.

    The fallback the platform uses when a deal is opened with no source
    registered. Returns None when real data is already present — it never
    overwrites an engagement's own data.
    """
    if has_registered_sources(session, deal_id):
        return None
    if session.get(DealMaster, deal_id) is None:
        raise SeedError(f"Deal {deal_id!r} does not exist or is not in scope.")
    return load_canonical_dataset(session, deal_id)
