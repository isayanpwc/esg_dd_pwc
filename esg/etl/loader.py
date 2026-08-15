"""
The load step — the piece that was missing.

Before this, the registration agent profiled a source, asked the model to map
its columns onto canonical tables, recorded approvals and emitted an
"ingestion configuration"… and stopped. Nothing ever wrote the mapped rows into
the canonical tables the five analysis agents read, so ingesting a target's
data had no effect on the analysis. This module closes that gap.

    approved mappings + source frame
        -> rename/transform into canonical columns
        -> validation gate (esg.etl.validation)
        -> upsert good rows into the canonical table
        -> quarantine bad rows with their reasons
        -> IngestionRun row recording what happened

Loads are idempotent on the canonical primary key, so replaying a corrected
file updates rather than duplicates.
"""

import json
import uuid

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select

from esg import clock
from esg.db.models import ColumnMapping, IngestionRun, QuarantinedRow
from esg.db.scope import require_principal
from esg.etl import transforms, validation
from esg.security import audit, rbac


class LoadError(RuntimeError):
    pass


class GateFailure(LoadError):
    """Raised when a run breaches its acceptable-quarantine threshold."""

    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def approved_mappings(session, source_id, target_table=None):
    stmt = select(ColumnMapping).where(
        ColumnMapping.source_id == source_id,
        ColumnMapping.status == "Approved",
        ColumnMapping.target_column.is_not(None),
    )
    if target_table:
        stmt = stmt.where(ColumnMapping.target_table == target_table)
    return session.execute(stmt).scalars().all()


def project_row(source_row, mappings):
    """Apply the approved mapping to one source row.

    Only mapped columns survive: an unmapped source column is not silently
    passed through under a guessed name.
    """
    out = {}
    for mapping in mappings:
        if mapping.source_column not in source_row:
            continue
        value = source_row[mapping.source_column]
        if mapping.transform:
            value = transforms.apply(mapping.transform, value)
        out[mapping.target_column] = value
    return out


def load_frame(session, frame, target_table, deal_id, source_id=None,
               source_name=None, mappings=None, max_quarantine_pct=25.0,
               dry_run=False):
    """Materialize a source frame into a canonical table.

    Returns the IngestionRun. Raises GateFailure when the proportion of
    quarantined rows exceeds max_quarantine_pct, in which case nothing is
    loaded — a file that is mostly broken is a file to fix, not to ingest.
    """
    principal = require_principal()
    rbac.check(rbac.INGEST_DATA, deal_id=deal_id, principal=principal)

    spec = validation.SPECS.get(target_table)
    if spec is None:
        raise LoadError(
            f"No validation spec for {target_table!r}. Add one to "
            "esg.etl.validation.SPECS before loading into it."
        )

    if mappings is None and source_id is not None:
        mappings = approved_mappings(session, source_id, target_table)
    if mappings is None:
        mappings = []
    if source_id is not None and not mappings:
        raise LoadError(
            f"Source {source_id!r} has no approved column mappings for "
            f"{target_table!r}. Approve the mapping before loading."
        )

    run = IngestionRun(
        run_id=uuid.uuid4().hex[:32],
        deal_id=deal_id,
        source_id=source_id,
        source_name=source_name,
        target_table=target_table,
        started_at=clock.now(),
        status="Running",
        triggered_by=principal.username,
    )
    session.add(run)
    session.flush()

    reference_index = validation.build_reference_index(session, spec)
    model = spec.model
    scoped = hasattr(model, "deal_id")
    columns = {c.key for c in sa_inspect(model).mapper.column_attrs}
    pk_names = [c.key for c in sa_inspect(model).mapper.primary_key]

    accepted, quarantined, warnings = [], [], []
    records = frame.to_dict(orient="records")

    for offset, source_row in enumerate(records, start=1):
        projected = project_row(source_row, mappings) if mappings else dict(source_row)
        if scoped:
            projected["deal_id"] = deal_id

        result = validation.validate_row(spec, offset, projected, reference_index)

        unknown = set(result.values) - columns
        for column in sorted(unknown):
            result.values.pop(column)
            result.issues.append(validation.Issue(
                column, "unknown_column",
                f"{column} is not a column of {target_table}; ignored",
                severity=validation.WARNING,
            ))

        missing_pk = [name for name in pk_names if result.values.get(name) in (None, "")]
        if missing_pk:
            result.issues.append(validation.Issue(
                ",".join(missing_pk), "primary_key",
                f"primary key {', '.join(missing_pk)} is empty",
            ))

        if result.ok:
            accepted.append(result)
            warnings.extend(i.as_dict() for i in result.warnings)
        else:
            quarantined.append(result)

    total = len(records)
    quarantine_pct = (len(quarantined) / total * 100) if total else 0.0
    report = {
        "target_table": target_table,
        "rows_read": total,
        "rows_valid": len(accepted),
        "rows_quarantined": len(quarantined),
        "quarantine_pct": round(quarantine_pct, 2),
        "threshold_pct": max_quarantine_pct,
        "warnings": warnings[:200],
        "reason_counts": _reason_counts(quarantined),
    }

    if total and quarantine_pct > max_quarantine_pct:
        run.status = "Rejected"
        run.finished_at = clock.now()
        run.rows_read = total
        run.gate_report = json.dumps(report, default=str)
        audit.record(session, principal.username, "ingestion.rejected",
                     entity_type="ingestion_run", entity_id=run.run_id,
                     deal_id=deal_id, detail=report)
        raise GateFailure(
            f"{len(quarantined)} of {total} rows failed validation "
            f"({quarantine_pct:.1f}% > {max_quarantine_pct}% allowed). "
            "Nothing was loaded.",
            report,
        )

    if dry_run:
        run.status = "DryRun"
        run.finished_at = clock.now()
        run.rows_read = total
        run.gate_report = json.dumps(report, default=str)
        return run

    inserted = updated = 0
    for result in accepted:
        payload = {k: v for k, v in result.values.items() if k in columns}
        key = tuple(payload.get(name) for name in pk_names)
        existing = session.get(model, key if len(key) > 1 else key[0])
        if existing is None:
            session.add(model(**payload))
            inserted += 1
        else:
            for column, value in payload.items():
                if column not in pk_names:
                    setattr(existing, column, value)
            updated += 1

    for result in quarantined:
        session.add(QuarantinedRow(
            quarantine_id=uuid.uuid4().hex[:32],
            deal_id=deal_id,
            run_id=run.run_id,
            target_table=target_table,
            source_row_number=result.row_number,
            payload_json=json.dumps(result.values, default=str),
            reasons_json=json.dumps([i.as_dict() for i in result.issues], default=str),
            severity=validation.ERROR,
        ))

    run.status = "Loaded" if not quarantined else "LoadedWithQuarantine"
    run.finished_at = clock.now()
    run.rows_read = total
    run.rows_loaded = inserted
    run.rows_updated = updated
    run.rows_quarantined = len(quarantined)
    run.gate_report = json.dumps(report, default=str)

    audit.record(
        session, principal.username, "ingestion.loaded",
        entity_type="ingestion_run", entity_id=run.run_id, deal_id=deal_id,
        detail={"target_table": target_table, "inserted": inserted,
                "updated": updated, "quarantined": len(quarantined)},
    )
    session.flush()
    return run


def _reason_counts(quarantined):
    counts = {}
    for result in quarantined:
        for issue in result.errors:
            key = f"{issue.column}:{issue.rule}"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def quarantined_rows(session, run_id=None, target_table=None, status="Quarantined"):
    stmt = select(QuarantinedRow)
    if run_id:
        stmt = stmt.where(QuarantinedRow.run_id == run_id)
    if target_table:
        stmt = stmt.where(QuarantinedRow.target_table == target_table)
    if status:
        stmt = stmt.where(QuarantinedRow.status == status)
    return session.execute(stmt.order_by(QuarantinedRow.source_row_number)).scalars().all()


def replay_quarantined(session, run_id, corrections=None, max_quarantine_pct=25.0):
    """Re-run quarantined rows after correction.

    `corrections` maps quarantine_id -> {column: new value}. Rows that now pass
    are loaded and marked Resolved; rows that still fail stay quarantined
    against the new run, so the trail of what was wrong is never lost.
    """
    import pandas as pd

    principal = require_principal()
    rows = quarantined_rows(session, run_id=run_id)
    if not rows:
        raise LoadError("No quarantined rows for that run.")

    corrections = corrections or {}
    target_table = rows[0].target_table
    deal_id = rows[0].deal_id

    payloads = []
    for row in rows:
        payload = json.loads(row.payload_json)
        payload.update(corrections.get(row.quarantine_id, {}))
        payloads.append(payload)

    run = load_frame(
        session, pd.DataFrame(payloads), target_table, deal_id,
        source_name=f"replay:{run_id}", mappings=[],
        max_quarantine_pct=max_quarantine_pct,
    )

    still_bad = {
        json.loads(q.payload_json).get(k)
        for q in quarantined_rows(session, run_id=run.run_id)
        for k in ("record_id", "company_id")
    }
    for row in rows:
        payload = json.loads(row.payload_json)
        if payload.get("record_id") not in still_bad:
            row.status = "Resolved"
            row.resolved_by = principal.username
            row.resolved_at = clock.now()
            row.replayed_run_id = run.run_id

    audit.record(session, principal.username, "ingestion.replayed",
                 entity_type="ingestion_run", entity_id=run.run_id, deal_id=deal_id,
                 detail={"original_run": run_id, "rows": len(rows)})
    return run
