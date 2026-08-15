"""
Financial exposure — versioned, bounded, and honest about its basis.

What this replaces
------------------
The previous calculation was `probability x revenue x impact_pct`, where both
coefficients came from hardcoded maps (0.15–0.70 and 0.3%–5%) with no stated
source. It returned a single precise-looking number. If such a figure informs a
price adjustment, its basis has to be defensible — and inventing coefficients
is not a basis.

What it does instead
--------------------
1. Every method declares its EVIDENCE BASIS and a calibration status. Methods
   grounded in observed amounts (a levied penalty, a booked provision, a quoted
   remediation cost) are marked `observed`. The expected-value model is marked
   `uncalibrated`, because it rests on judgement parameters that PwC has not
   empirically fitted.

2. Uncalibrated methods produce a RANGE, never a point estimate, and refuse to
   be marked as a quantified exposure. They must be labelled `indicative` in
   any output. The caller cannot opt out of that.

3. Every result carries a SENSITIVITY table showing how the answer moves with
   each driver, so a reviewer sees which assumption the number depends on.

4. Nothing reaches a client deliverable without review: `require_review()`
   blocks report inclusion until a Manager has signed the specific run.

Calibrating the judgement parameters is a methodology task for the ESG and
Deals practice, not a coding one. Where they need to be replaced, the constant
is marked CALIBRATION REQUIRED and the value is deliberately conservative.
"""

import json
import uuid

from esg import clock
from esg.db.models import CompanyFinancials, ExposureRun, FxRateReference, LegalPenalty
from esg.db.scope import require_principal
from esg.security import audit, rbac

METHODOLOGY_VERSION = "2026.08-draft"

# Calibration status of a method's inputs.
OBSERVED = "observed"          # amounts taken from documents or filings
BENCHMARKED = "benchmarked"    # from a cited external dataset
UNCALIBRATED = "uncalibrated"  # judgement parameters, not empirically fitted

# Whether a figure may be presented as a quantified exposure.
QUANTIFIED = "quantified"
INDICATIVE = "indicative"


class MethodologyError(RuntimeError):
    pass


class ReviewRequired(MethodologyError):
    """Raised when an unreviewed exposure is pulled into a deliverable."""


# ────────────────────────────────────────────────────────────────────
#  Judgement parameters
#
#  CALIBRATION REQUIRED — these are placeholders pending empirical work by
#  the practice. They are expressed as ranges rather than points precisely
#  because a single value would imply a precision that does not exist. The
#  midpoint is not privileged; consumers must use the range.
# ────────────────────────────────────────────────────────────────────

CRYSTALLISATION_PROBABILITY = {
    # severity: (low, high) probability that the exposure crystallises
    "Critical": (0.45, 0.85),
    "High": (0.30, 0.65),
    "Medium": (0.15, 0.45),
    "Low": (0.05, 0.20),
}

IMPACT_AS_REVENUE_SHARE = {
    # impact score 1–5: (low, high) share of annual revenue if it crystallises
    5: (0.020, 0.080),
    4: (0.010, 0.040),
    3: (0.005, 0.020),
    2: (0.002, 0.010),
    1: (0.0005, 0.003),
}

PARAMETER_PROVENANCE = {
    "CRYSTALLISATION_PROBABILITY": (
        "Placeholder. Requires calibration against PwC's own realised-outcome "
        "data for comparable ESG findings. Not derived from published research."
    ),
    "IMPACT_AS_REVENUE_SHARE": (
        "Placeholder. Requires calibration against observed remediation, fine "
        "and business-interruption costs by sector and finding category."
    ),
}


# ────────────────────────────────────────────────────────────────────
#  Methods
# ────────────────────────────────────────────────────────────────────

def _fx_to_usd(session, amount, currency):
    if amount is None:
        return None, None
    if not currency or currency.upper() == "USD":
        return float(amount), "1.0 (already USD)"
    from sqlalchemy import select

    row = session.execute(
        select(FxRateReference)
        .where(
            FxRateReference.from_currency == currency.upper(),
            FxRateReference.to_currency == "USD",
        )
        .order_by(FxRateReference.rate_date.desc())
    ).scalars().first()
    if row is None:
        return None, f"No {currency.upper()}/USD rate available"
    return float(amount) * row.rate, f"{currency.upper()}/USD {row.rate} on {row.rate_date}"


def from_levied_penalties(session, penalties):
    """Sum of penalties actually levied. The most defensible figure available:
    the amount exists in a regulator's order."""
    total, notes = 0.0, []
    for penalty in penalties:
        converted, fx_note = _fx_to_usd(session, penalty.amount, penalty.currency)
        if converted is None:
            notes.append(f"{penalty.penalty_id}: excluded — {fx_note}")
            continue
        total += converted
        notes.append(
            f"{penalty.penalty_id} ({penalty.regulator_body or 'regulator'}): "
            f"{penalty.amount} {penalty.currency} -> {converted:,.0f} USD [{fx_note}]"
        )

    return {
        "method": "levied_penalty",
        "basis": OBSERVED,
        "disclosure": QUANTIFIED,
        "point_estimate_usd": round(total, 2),
        "low_usd": round(total, 2),
        "high_usd": round(total, 2),
        "confidence_label": "High",
        "inputs": {"penalty_count": len(penalties), "detail": notes},
        "sensitivity": [],
        "basis_note": (
            "Sum of penalty amounts recorded against the target, converted at the "
            "latest available reference rate. No probability weighting is applied "
            "because these amounts have already been levied."
        ),
    }


def from_booked_provision(amount_usd, source_note):
    """Management's own booked provision — an admission against interest, and
    audited, so it carries weight without adjustment."""
    return {
        "method": "booked_provision",
        "basis": OBSERVED,
        "disclosure": QUANTIFIED,
        "point_estimate_usd": round(float(amount_usd), 2),
        "low_usd": round(float(amount_usd), 2),
        "high_usd": round(float(amount_usd), 2),
        "confidence_label": "High",
        "inputs": {"source": source_note},
        "sensitivity": [],
        "basis_note": (
            "Provision recognised in the target's own audited financial statements. "
            "Used unadjusted."
        ),
    }


def from_quoted_remediation(low_usd, high_usd, source_note):
    """A quoted or engineered cost to fix — e.g. an abatement capex estimate."""
    low, high = sorted((float(low_usd), float(high_usd)))
    return {
        "method": "quoted_remediation",
        "basis": OBSERVED,
        "disclosure": QUANTIFIED,
        "point_estimate_usd": round((low + high) / 2, 2),
        "low_usd": round(low, 2),
        "high_usd": round(high, 2),
        "confidence_label": "Medium",
        "inputs": {"source": source_note},
        "sensitivity": [],
        "basis_note": (
            "Range taken from a quoted or engineered remediation cost. The midpoint "
            "is reported for convenience only; the range is the finding."
        ),
    }


def expected_value_range(severity, impact_score, revenue_usd, revenue_note=None):
    """Judgement-based exposure, as a range with sensitivity.

    This is the successor to the old point estimate. It is explicitly
    `indicative`: the parameters are uncalibrated, so presenting a single
    number would misrepresent what is known.
    """
    if revenue_usd is None or revenue_usd <= 0:
        return {
            "method": "expected_value",
            "basis": UNCALIBRATED,
            "disclosure": INDICATIVE,
            "point_estimate_usd": None,
            "low_usd": None,
            "high_usd": None,
            "confidence_label": "Not quantifiable",
            "inputs": {"revenue_usd": revenue_usd, "revenue_note": revenue_note},
            "sensitivity": [],
            "basis_note": (
                "No usable revenue figure for the target, so no revenue-proportional "
                "estimate can be made. Reported as a qualitative finding only."
            ),
        }

    probability = CRYSTALLISATION_PROBABILITY.get(severity, CRYSTALLISATION_PROBABILITY["Medium"])
    share = IMPACT_AS_REVENUE_SHARE.get(impact_score, IMPACT_AS_REVENUE_SHARE[3])

    low = revenue_usd * probability[0] * share[0]
    high = revenue_usd * probability[1] * share[1]

    sensitivity = _sensitivity(revenue_usd, probability, share)

    return {
        "method": "expected_value",
        "basis": UNCALIBRATED,
        "disclosure": INDICATIVE,
        "point_estimate_usd": None,  # withheld on purpose
        "low_usd": round(low, 2),
        "high_usd": round(high, 2),
        "confidence_label": "Indicative only",
        "inputs": {
            "severity": severity,
            "impact_score": impact_score,
            "revenue_usd": revenue_usd,
            "revenue_note": revenue_note,
            "probability_range": probability,
            "revenue_share_range": share,
            "parameter_provenance": PARAMETER_PROVENANCE,
        },
        "sensitivity": sensitivity,
        "basis_note": (
            "Indicative range only. Computed as revenue x crystallisation "
            "probability x impact share, where both parameters are uncalibrated "
            "judgement inputs pending empirical fitting by the practice. This "
            "figure must not be presented as a quantified exposure, and no single "
            "point estimate is produced because the underlying parameters do not "
            "support that precision."
        ),
    }


def _sensitivity(revenue_usd, probability, share):
    """How much the range moves when one driver moves. Shows the reviewer which
    assumption is actually carrying the number."""
    mid_probability = sum(probability) / 2
    mid_share = sum(share) / 2
    baseline = revenue_usd * mid_probability * mid_share

    rows = []
    for label, factor in (("-50%", 0.5), ("+50%", 1.5)):
        rows.append({
            "driver": "crystallisation_probability",
            "change": label,
            "exposure_usd": round(revenue_usd * mid_probability * factor * mid_share, 2),
            "vs_baseline_pct": round((factor - 1) * 100, 1),
        })
        rows.append({
            "driver": "impact_share_of_revenue",
            "change": label,
            "exposure_usd": round(revenue_usd * mid_probability * mid_share * factor, 2),
            "vs_baseline_pct": round((factor - 1) * 100, 1),
        })
        rows.append({
            "driver": "revenue",
            "change": label,
            "exposure_usd": round(revenue_usd * factor * mid_probability * mid_share, 2),
            "vs_baseline_pct": round((factor - 1) * 100, 1),
        })
    return [{"baseline_usd": round(baseline, 2)}] + rows


# ────────────────────────────────────────────────────────────────────
#  Orchestration
# ────────────────────────────────────────────────────────────────────

def quantify(session, finding, company_id, deal_id, evidence_penalties=None,
             booked_provision_usd=None, remediation_range=None):
    """Choose the strongest available basis and persist the run.

    Preference order is by evidence quality, not by which produces the largest
    number: levied penalties, then booked provisions, then quoted remediation,
    then the indicative model.
    """
    principal = require_principal()
    rbac.check(rbac.RUN_ASSESSMENT, deal_id=deal_id, principal=principal)

    if evidence_penalties:
        result = from_levied_penalties(session, evidence_penalties)
    elif booked_provision_usd:
        result = from_booked_provision(booked_provision_usd, "target financial statements")
    elif remediation_range:
        result = from_quoted_remediation(*remediation_range, "quoted remediation estimate")
    else:
        revenue_usd, note = latest_revenue_usd(session, company_id)
        result = expected_value_range(
            finding.get("severity", "Medium"),
            finding.get("impact_score", 3),
            revenue_usd,
            note,
        )

    run = ExposureRun(
        exposure_run_id=uuid.uuid4().hex[:32],
        deal_id=deal_id,
        finding_id=finding.get("finding_id", "unassigned"),
        company_id=company_id,
        methodology_version=METHODOLOGY_VERSION,
        method=result["method"],
        point_estimate_usd=result["point_estimate_usd"],
        low_usd=result["low_usd"],
        high_usd=result["high_usd"],
        confidence_label=result["confidence_label"],
        inputs_json=json.dumps(result["inputs"], default=str),
        sensitivity_json=json.dumps(result["sensitivity"], default=str),
        basis=f"[{result['basis']}/{result['disclosure']}] {result['basis_note']}",
        computed_at=clock.now(),
    )
    session.add(run)
    audit.record(
        session, principal.username, "exposure.computed",
        entity_type="exposure_run", entity_id=run.exposure_run_id, deal_id=deal_id,
        detail={"method": result["method"], "basis": result["basis"],
                "disclosure": result["disclosure"],
                "low": result["low_usd"], "high": result["high_usd"]},
    )
    session.flush()
    return run, result


def latest_revenue_usd(session, company_id):
    from sqlalchemy import select

    row = session.execute(
        select(CompanyFinancials)
        .where(CompanyFinancials.company_id == company_id)
        .order_by(CompanyFinancials.reporting_year.desc())
    ).scalars().first()
    if row is None or not row.annual_revenue:
        return None, "No financials on file"
    converted, note = _fx_to_usd(session, row.annual_revenue, row.reporting_currency)
    return converted, f"FY{row.reporting_year} revenue; {note}"


def review(session, exposure_run_id, decision_note=None):
    """A Manager signs off an exposure run, making it eligible for a report."""
    principal = require_principal()
    run = session.get(ExposureRun, exposure_run_id)
    if run is None:
        raise MethodologyError("Exposure run not found or not in scope.")
    rbac.check(rbac.REVIEW_EXPOSURE, deal_id=run.deal_id, principal=principal)

    run.reviewed_by = principal.username
    run.reviewed_at = clock.now()
    audit.record(session, principal.username, "exposure.reviewed",
                 entity_type="exposure_run", entity_id=exposure_run_id,
                 deal_id=run.deal_id, detail={"note": decision_note})
    return run


def require_review(run):
    """Gate for report generation."""
    if run.reviewed_by is None:
        raise ReviewRequired(
            f"Exposure run {run.exposure_run_id} has not been reviewed. "
            "A quantified exposure cannot enter a client deliverable until a "
            "Manager has signed the specific run."
        )
    return run


def present(run):
    """How a run may be shown. Indicative runs never render as a single number."""
    indicative = "/indicative]" in (run.basis or "")
    if indicative or run.point_estimate_usd is None:
        if run.low_usd is None:
            return {
                "label": "Not quantified",
                "detail": "Qualitative finding — no defensible monetary estimate.",
                "disclosure": INDICATIVE,
            }
        return {
            "label": f"USD {run.low_usd:,.0f} – {run.high_usd:,.0f} (indicative)",
            "detail": ("Indicative range from uncalibrated judgement parameters. "
                       "Not a quantified exposure."),
            "disclosure": INDICATIVE,
        }
    return {
        "label": f"USD {run.point_estimate_usd:,.0f}",
        "detail": run.basis,
        "disclosure": QUANTIFIED,
    }
