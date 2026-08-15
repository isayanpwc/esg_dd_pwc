"""
Greenwashing detection with something behind it.

Four independent checks, each producing a finding a reviewer can verify against
source pages rather than a score to trust:

1. Reported vs operational reconciliation — a disclosed total that does not
   reconcile to the sum of its facility-level parts.
2. Restatement detection — prior-year figures quietly revised in a later
   filing, and whether the revision flatters the trend.
3. Assurance coverage — claims presented as assured where no assurance covers
   the metric.
4. Target-trajectory divergence — progress claimed against a target that the
   underlying data does not support.

Each returns evidence: the values compared, the documents and pages they came
from, and the size of the gap. Nothing here scores a company; it points at
specific numbers that do not agree.
"""

from sqlalchemy import select

from esg.db.models import (
    EsgDocumentRegister, EsgMetricData, EsgTarget, FacilityMaster,
)

# A gap below this is measurement noise, not misstatement.
RECONCILIATION_TOLERANCE_PCT = 5.0
MATERIAL_RESTATEMENT_PCT = 10.0

SEVERITY_BY_GAP = ((50.0, "Critical"), (25.0, "High"), (10.0, "Medium"))


def _severity(gap_pct):
    for threshold, label in SEVERITY_BY_GAP:
        if abs(gap_pct) >= threshold:
            return label
    return "Low"


def _citation(session, record):
    if not record.source_document_id:
        return None
    document = session.get(EsgDocumentRegister, record.source_document_id)
    if document is None:
        return None
    return f"{document.document_name}, p.{record.source_page}"


# ── 1. reported vs operational ──

def reconcile_reported_to_operational(session, company_id, metric_code,
                                      reporting_year, tolerance_pct=None):
    """Compare a group-level disclosure against the sum of facility rows.

    A group total materially below the sum of its parts is the classic
    understatement pattern; materially above usually means double counting or
    an undisclosed boundary change. Both are findings.
    """
    tolerance = RECONCILIATION_TOLERANCE_PCT if tolerance_pct is None else tolerance_pct

    rows = session.execute(
        select(EsgMetricData).where(
            EsgMetricData.company_id == company_id,
            EsgMetricData.metric_code == metric_code,
            EsgMetricData.reporting_year == reporting_year,
        )
    ).scalars().all()

    group_rows = [r for r in rows if not r.facility_id]
    facility_rows = [r for r in rows if r.facility_id]

    if not group_rows or not facility_rows:
        return None

    reported = max(group_rows, key=lambda r: (r.human_verified or False, r.value or 0))
    bottom_up = sum(r.value or 0 for r in facility_rows)
    if not reported.value:
        return None

    gap = reported.value - bottom_up
    gap_pct = gap / bottom_up * 100 if bottom_up else 0.0

    if abs(gap_pct) <= tolerance:
        return None

    known_facilities = session.execute(
        select(FacilityMaster).where(FacilityMaster.company_id == company_id)
    ).scalars().all()
    covered = {r.facility_id for r in facility_rows}
    missing = [f.facility_id for f in known_facilities if f.facility_id not in covered]

    direction = "below" if gap < 0 else "above"
    return {
        "check": "reported_vs_operational",
        "metric_code": metric_code,
        "reporting_year": reporting_year,
        "severity": _severity(gap_pct),
        "reported_value": reported.value,
        "bottom_up_value": round(bottom_up, 4),
        "gap": round(gap, 4),
        "gap_pct": round(gap_pct, 2),
        "facilities_included": len(facility_rows),
        "facilities_missing": missing,
        "reported_citation": _citation(session, reported),
        "facility_citations": [c for c in (_citation(session, r) for r in facility_rows) if c],
        "finding": (
            f"Group-level {metric_code} for {reporting_year} is {abs(gap_pct):.1f}% "
            f"{direction} the sum of {len(facility_rows)} facility disclosures "
            f"({reported.value:,.2f} reported vs {bottom_up:,.2f} bottom-up)."
            + (f" {len(missing)} known facilities have no data." if missing else "")
        ),
        "why_it_matters": (
            "A total that does not reconcile to its parts indicates an undisclosed "
            "boundary, an excluded site, or double counting. Ask for the "
            "consolidation workings."
        ),
    }


# ── 2. restatements ──

def detect_restatements(session, company_id, material_pct=None):
    """Find figures revised by a later filing.

    Promotion supersedes rather than overwrites (esg.documents.promote), so the
    original reading is still on file to compare against.
    """
    threshold = MATERIAL_RESTATEMENT_PCT if material_pct is None else material_pct

    revisions = session.execute(
        select(EsgMetricData).where(
            EsgMetricData.company_id == company_id,
            EsgMetricData.supersedes_record_id.is_not(None),
        )
    ).scalars().all()

    findings = []
    for revised in revisions:
        original = session.get(EsgMetricData, revised.supersedes_record_id)
        if original is None or not original.value:
            continue
        delta = (revised.value or 0) - original.value
        delta_pct = delta / abs(original.value) * 100

        if abs(delta_pct) < threshold:
            continue

        flatters = _flatters_the_story(session, company_id, revised, delta)
        findings.append({
            "check": "restatement",
            "metric_code": revised.metric_code,
            "reporting_year": revised.reporting_year,
            "severity": _severity(delta_pct) if flatters else "Low",
            "original_value": original.value,
            "restated_value": revised.value,
            "delta": round(delta, 4),
            "delta_pct": round(delta_pct, 2),
            "original_citation": _citation(session, original),
            "restated_citation": _citation(session, revised),
            "favourable_to_target": flatters,
            "finding": (
                f"{revised.metric_code} for {revised.reporting_year} was restated "
                f"from {original.value:,.2f} to {revised.value:,.2f} "
                f"({delta_pct:+.1f}%)."
            ),
            "why_it_matters": (
                "A prior-year revision that improves the reported trend deserves "
                "scrutiny: ask what changed in the methodology and whether the "
                "revision was disclosed."
                if flatters else
                "Restatement recorded for completeness; it does not flatter the trend."
            ),
        })
    return findings


def _flatters_the_story(session, company_id, record, delta):
    """Whether a restatement improves the apparent trajectory.

    Restating a *base year* upward makes subsequent reductions look larger; for
    a metric where lower is better, that is a favourable revision.
    """
    from esg.db.models import EsgMetricMaster

    master = session.get(EsgMetricMaster, record.metric_code)
    lower_is_better = (master.direction or "").lower() in {"lower", "down", "decrease"} if master else True

    years = session.execute(
        select(EsgMetricData.reporting_year).where(
            EsgMetricData.company_id == company_id,
            EsgMetricData.metric_code == record.metric_code,
        )
    ).scalars().all()
    is_base_year = bool(years) and record.reporting_year == min(years)

    if is_base_year:
        return delta > 0 if lower_is_better else delta < 0
    return delta < 0 if lower_is_better else delta > 0


# ── 3. assurance coverage ──

def unassured_claims(session, company_id, reporting_year, assured_metric_codes=None):
    """Metrics presented as audited where no assurance is on file."""
    assured = set(assured_metric_codes or ())
    rows = session.execute(
        select(EsgMetricData).where(
            EsgMetricData.company_id == company_id,
            EsgMetricData.reporting_year == reporting_year,
        )
    ).scalars().all()

    findings = []
    for row in rows:
        if row.is_audited and row.metric_code not in assured:
            findings.append({
                "check": "assurance_gap",
                "metric_code": row.metric_code,
                "reporting_year": reporting_year,
                "severity": "Medium",
                "citation": _citation(session, row),
                "finding": (
                    f"{row.metric_code} is flagged as audited but no assurance "
                    "statement on file covers it."
                ),
                "why_it_matters": (
                    "Request the assurance report and check its scope — limited "
                    "assurance over selected metrics is often presented as if it "
                    "covered the whole disclosure."
                ),
            })
    return findings


# ── 4. target trajectory ──

def target_progress_divergence(session, company_id, tolerance_pct=5.0):
    """Compare claimed target progress against what the metric data supports."""
    targets = session.execute(
        select(EsgTarget).where(EsgTarget.company_id == company_id)
    ).scalars().all()

    findings = []
    for target in targets:
        if target.progress_pct is None or not target.metric_code:
            continue
        if target.base_value in (None, 0) or target.target_value is None:
            continue

        latest = session.execute(
            select(EsgMetricData)
            .where(
                EsgMetricData.company_id == company_id,
                EsgMetricData.metric_code == target.metric_code,
            )
            .order_by(EsgMetricData.reporting_year.desc())
        ).scalars().first()
        if latest is None or latest.value is None:
            continue

        span = target.target_value - target.base_value
        if span == 0:
            continue
        implied = (latest.value - target.base_value) / span * 100
        gap = target.progress_pct - implied

        if abs(gap) <= tolerance_pct:
            continue

        findings.append({
            "check": "target_progress_divergence",
            "metric_code": target.metric_code,
            "target_id": target.target_id,
            "severity": _severity(gap),
            "claimed_progress_pct": target.progress_pct,
            "implied_progress_pct": round(implied, 2),
            "gap_pct_points": round(gap, 2),
            "latest_value": latest.value,
            "latest_year": latest.reporting_year,
            "citation": _citation(session, latest),
            "finding": (
                f"Target {target.target_id} claims {target.progress_pct:.1f}% progress, "
                f"but {latest.reporting_year} data implies {implied:.1f}% "
                f"({gap:+.1f} percentage points)."
            ),
            "why_it_matters": (
                "Overstated progress against a public target is a disclosure risk "
                "in its own right. Reconcile the claim to the underlying data."
            ),
        })
    return findings


# ── orchestration ──

def run_all(session, company_id, reporting_year, metric_codes=None,
            assured_metric_codes=None):
    """Run every check and return findings ordered by severity."""
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    findings = []

    for metric_code in metric_codes or _metrics_for(session, company_id, reporting_year):
        result = reconcile_reported_to_operational(
            session, company_id, metric_code, reporting_year
        )
        if result:
            findings.append(result)

    findings.extend(detect_restatements(session, company_id))
    findings.extend(unassured_claims(session, company_id, reporting_year,
                                     assured_metric_codes))
    findings.extend(target_progress_divergence(session, company_id))

    return sorted(findings, key=lambda f: order.get(f["severity"], 9))


def _metrics_for(session, company_id, reporting_year):
    return session.execute(
        select(EsgMetricData.metric_code)
        .where(
            EsgMetricData.company_id == company_id,
            EsgMetricData.reporting_year == reporting_year,
        )
        .distinct()
    ).scalars().all()
