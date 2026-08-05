"""
ESG Risk & Opportunity Agent -- Backend engine.

Synthesises outputs from prior agents and source data into actionable
risk/opportunity findings via a 7-step pipeline:
  Step 1  Collect risk signals from CSV sources
  Step 2  Consolidate overlapping signals
  Step 3  Calculate likelihood x impact scores
  Step 4  Assess evidence quality
  Step 5  Quantify financial impact
  Step 6  Identify opportunities
  Step 7  Generate deal recommendations

Data sources:
  esg_risk_opportunity.csv, controversy_record.csv, legal_penalty.csv,
  certification.csv, supplier_esg_assessment.csv, supplier_master.csv,
  company_financials.csv, esg_target.csv, deal_master.csv,
  company_master.csv, fx_rate_reference.csv
"""

import os
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# ════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════

PRIORITY_BANDS = [
    (20, "Critical"),
    (12, "High"),
    (6, "Medium"),
    (1, "Low"),
]

PRIORITY_COLORS = {
    "Critical": "#991B1B",
    "High": "#DC2626",
    "Medium": "#D97706",
    "Low": "#059669",
}

RECOMMENDATION_CATEGORIES = [
    "Additional diligence",
    "Valuation consideration",
    "Contractual protection",
    "Condition precedent",
    "Remediation requirement",
    "Post-merger integration",
    "Value creation",
]

SEVERITY_TO_IMPACT = {
    "Critical": 5,
    "High": 4,
    "Medium": 3,
    "Low": 2,
}

SIGNAL_LIKELIHOOD = {
    "Outstanding legal penalty": 5,
    "Critical controversy": 4,
    "Expired certification": 3,
    "Certification under review": 3,
    "Mandatory compliance gap": 4,
    "Low-quality metric": 2,
    "Below-peer performance": 3,
    "Target off-track": 3,
    "Critical supplier issues": 3,
    "High human-rights risk": 4,
    "Missing supplier carbon data": 2,
}


# ════════════════════════════════════════════════════════════
#  Data loaders
# ════════════════════════════════════════════════════════════

def _load_csv(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def load_risk_opportunity():
    return _load_csv("esg_risk_opportunity.csv")


def load_controversy_records():
    return _load_csv("controversy_record.csv")


def load_legal_penalties():
    return _load_csv("legal_penalty.csv")


def load_certifications():
    return _load_csv("certification.csv")


def load_supplier_assessments():
    return _load_csv("supplier_esg_assessment.csv")


def load_supplier_master():
    return _load_csv("supplier_master.csv")


def load_company_financials():
    return _load_csv("company_financials.csv")


def load_esg_targets():
    return _load_csv("esg_target.csv")


def load_deal_master():
    return _load_csv("deal_master.csv")


def load_company_master():
    return _load_csv("company_master.csv")


def load_fx_rates():
    return _load_csv("fx_rate_reference.csv")


# ════════════════════════════════════════════════════════════
#  Selector helpers
# ════════════════════════════════════════════════════════════

def get_available_deals():
    deals = load_deal_master()
    companies = load_company_master()
    if deals.empty:
        return []
    if not companies.empty:
        deals = deals.merge(companies[["company_id", "company_name"]], on="company_id", how="left")
    else:
        deals["company_name"] = deals["company_id"]
    return deals.to_dict("records")


def get_company_name(company_id):
    companies = load_company_master()
    if companies.empty:
        return company_id
    row = companies[companies["company_id"] == company_id]
    if row.empty:
        return company_id
    return str(row.iloc[0]["company_name"])


def get_deal_name(deal_id):
    deals = load_deal_master()
    if deals.empty:
        return deal_id
    row = deals[deals["deal_id"] == deal_id]
    if row.empty:
        return deal_id
    return str(row.iloc[0]["deal_name"])


# ════════════════════════════════════════════════════════════
#  Currency conversion
# ════════════════════════════════════════════════════════════

def convert_currency(value, from_currency, to_currency):
    if from_currency == to_currency:
        return value, 1.0
    fx = load_fx_rates()
    if fx.empty:
        return value, 1.0
    rate_row = fx[
        (fx["from_currency"] == from_currency) &
        (fx["to_currency"] == to_currency)
    ]
    if not rate_row.empty:
        rate_row = rate_row.sort_values("rate_date", ascending=False)
        rate = float(rate_row.iloc[0]["rate"])
        return round(value * rate, 2), rate
    return value, 1.0


# ════════════════════════════════════════════════════════════
#  Step 1 — Collect risk signals
# ════════════════════════════════════════════════════════════

def collect_risk_signals(deal_id, company_id):
    signals = []

    # --- Controversies ---
    controv = load_controversy_records()
    if not controv.empty:
        mask = (controv["company_id"] == company_id)
        if "deal_id" in controv.columns:
            mask = mask & (controv["deal_id"] == deal_id)
        for _, row in controv[mask].iterrows():
            severity = str(row.get("severity", "Medium"))
            signals.append({
                "signal_type": "Critical controversy",
                "source_table": "controversy_record",
                "source_id": str(row.get("controversy_id", "")),
                "esg_pillar": str(row.get("esg_pillar", "Governance")),
                "category": str(row.get("category", "")),
                "title": str(row.get("summary", "")),
                "description": str(row.get("summary", "")),
                "severity": severity,
                "verified": str(row.get("verified_flag", "No")),
                "raw_data": {
                    "source_type": str(row.get("source_type", "")),
                    "source_name": str(row.get("source_name", "")),
                    "event_date": str(row.get("event_date", "")),
                },
            })

    # --- Legal penalties ---
    penalties = load_legal_penalties()
    if not penalties.empty:
        mask = (penalties["company_id"] == company_id)
        pending = penalties[mask & penalties["status"].isin(["Pending", "Open"])]
        for _, row in pending.iterrows():
            signals.append({
                "signal_type": "Outstanding legal penalty",
                "source_table": "legal_penalty",
                "source_id": str(row.get("penalty_id", "")),
                "esg_pillar": "Governance",
                "category": "Regulatory penalty",
                "title": str(row.get("description", "")),
                "description": str(row.get("description", "")),
                "severity": "High",
                "verified": "Yes",
                "raw_data": {
                    "penalty_amount": float(row.get("penalty_amount", 0)),
                    "penalty_currency": str(row.get("penalty_currency", "")),
                    "penalty_date": str(row.get("penalty_date", "")),
                    "regulation_id": str(row.get("regulation_id", "")),
                },
            })

    # --- Certifications ---
    certs = load_certifications()
    if not certs.empty:
        mask = certs["company_id"] == company_id
        issues = certs[mask & certs["status"].isin(["Expired", "Under Review"])]
        for _, row in issues.iterrows():
            status = str(row.get("status", ""))
            signal_type = ("Expired certification" if status == "Expired"
                           else "Certification under review")
            signals.append({
                "signal_type": signal_type,
                "source_table": "certification",
                "source_id": str(row.get("certification_id", "")),
                "esg_pillar": "Governance",
                "category": "Certifications",
                "title": f"{row.get('certification_name', '')} — {status}",
                "description": f"{row.get('certification_name', '')} issued by "
                               f"{row.get('issuing_body', '')} is {status}",
                "severity": "High" if status == "Expired" else "Medium",
                "verified": "Yes",
                "raw_data": {
                    "certification_name": str(row.get("certification_name", "")),
                    "issuing_body": str(row.get("issuing_body", "")),
                    "expiry_date": str(row.get("expiry_date", "")),
                    "scope": str(row.get("scope", "")),
                },
            })

    # --- Supplier issues ---
    sa = load_supplier_assessments()
    sm = load_supplier_master()
    if not sa.empty:
        sa_mask = sa["company_id"] == company_id
        if "deal_id" in sa.columns:
            sa_mask = sa_mask & (sa["deal_id"] == deal_id)
        sa_filtered = sa[sa_mask].copy()
        if not sa_filtered.empty and "assessment_date" in sa_filtered.columns:
            sa_filtered = (
                sa_filtered.sort_values("assessment_date", ascending=False)
                .drop_duplicates(subset=["supplier_id"], keep="first")
            )
            if not sm.empty:
                sa_filtered = sa_filtered.merge(
                    sm[["supplier_id", "supplier_name", "criticality", "annual_spend",
                        "spend_currency", "tier"]],
                    on="supplier_id", how="left",
                )
            for _, row in sa_filtered.iterrows():
                supplier_name = str(row.get("supplier_name", row.get("supplier_id", "")))
                criticality = str(row.get("criticality", ""))

                esg_score = float(row.get("overall_esg_score", 100))
                if esg_score < 50 and criticality in ("High", "Medium"):
                    signals.append({
                        "signal_type": "Critical supplier issues",
                        "source_table": "supplier_esg_assessment",
                        "source_id": str(row.get("supplier_assessment_id", "")),
                        "esg_pillar": "Governance",
                        "category": "Supply chain",
                        "title": f"Low ESG score for {criticality.lower()}-criticality "
                                 f"supplier {supplier_name}",
                        "description": f"Overall ESG score {esg_score:.1f}/100 "
                                       f"for {criticality}-criticality supplier",
                        "severity": "High" if criticality == "High" else "Medium",
                        "verified": "Yes",
                        "raw_data": {
                            "supplier_id": str(row.get("supplier_id", "")),
                            "overall_esg_score": esg_score,
                            "criticality": criticality,
                        },
                    })

                hr_risk = str(row.get("human_rights_risk", ""))
                if hr_risk == "High":
                    signals.append({
                        "signal_type": "High human-rights risk",
                        "source_table": "supplier_esg_assessment",
                        "source_id": str(row.get("supplier_assessment_id", "")),
                        "esg_pillar": "Social",
                        "category": "Human rights",
                        "title": f"High human-rights risk — {supplier_name}",
                        "description": f"Supplier {supplier_name} flagged with "
                                       f"high human-rights risk",
                        "severity": "High",
                        "verified": "Yes",
                        "raw_data": {
                            "supplier_id": str(row.get("supplier_id", "")),
                            "human_rights_risk": hr_risk,
                        },
                    })

                carbon = str(row.get("carbon_data_available", ""))
                if carbon == "No":
                    signals.append({
                        "signal_type": "Missing supplier carbon data",
                        "source_table": "supplier_esg_assessment",
                        "source_id": str(row.get("supplier_assessment_id", "")),
                        "esg_pillar": "Environmental",
                        "category": "Scope 3 disclosure",
                        "title": f"Missing carbon data — {supplier_name}",
                        "description": f"No carbon data available for supplier "
                                       f"{supplier_name}",
                        "severity": "Medium",
                        "verified": "Yes",
                        "raw_data": {
                            "supplier_id": str(row.get("supplier_id", "")),
                            "carbon_data_available": carbon,
                        },
                    })

                corrective = str(row.get("corrective_action_status", ""))
                if corrective == "Overdue" and criticality in ("High", "Medium"):
                    signals.append({
                        "signal_type": "Critical supplier issues",
                        "source_table": "supplier_esg_assessment",
                        "source_id": str(row.get("supplier_assessment_id", "")),
                        "esg_pillar": "Governance",
                        "category": "Supply chain",
                        "title": f"Overdue corrective action — {supplier_name}",
                        "description": f"Corrective action overdue for "
                                       f"{criticality}-criticality supplier",
                        "severity": "High",
                        "verified": "Yes",
                        "raw_data": {
                            "supplier_id": str(row.get("supplier_id", "")),
                            "corrective_action_status": corrective,
                            "criticality": criticality,
                        },
                    })

    # --- Off-track targets ---
    targets = load_esg_targets()
    if not targets.empty:
        t_mask = (targets["company_id"] == company_id)
        if "deal_id" in targets.columns:
            t_mask = t_mask & (targets["deal_id"] == deal_id)
        off_track = targets[t_mask & (
            targets["on_track_flag"].astype(str).str.strip().str.lower().isin(["no", "false"])
        )]
        for _, row in off_track.iterrows():
            progress = float(row.get("progress_pct", 0))
            expected = float(row.get("expected_pct_linear", 0))
            gap = expected - progress
            severity = "High" if gap > 30 else ("Medium" if gap > 10 else "Low")
            pillar_map = {
                "ENV": "Environmental",
                "SOC": "Social",
                "GOV": "Governance",
            }
            mc = str(row.get("metric_code", ""))
            pillar = "Environmental"
            for prefix, p in pillar_map.items():
                if mc.startswith(prefix):
                    pillar = p
                    break
            signals.append({
                "signal_type": "Target off-track",
                "source_table": "esg_target",
                "source_id": str(row.get("target_id", "")),
                "esg_pillar": pillar,
                "category": "Target progress",
                "title": f"Off-track: {row.get('target_name', '')}",
                "description": f"Progress {progress:.1f}% vs expected "
                               f"{expected:.1f}% (gap {gap:.1f}pp)",
                "severity": severity,
                "verified": "Yes",
                "raw_data": {
                    "target_id": str(row.get("target_id", "")),
                    "metric_code": mc,
                    "progress_pct": progress,
                    "expected_pct_linear": expected,
                    "target_year": str(row.get("target_year", "")),
                    "status": str(row.get("status", "")),
                },
            })

    return signals


# ════════════════════════════════════════════════════════════
#  Step 2 — Consolidate overlapping signals
# ════════════════════════════════════════════════════════════

def consolidate_signals(signals):
    groups = {}
    for sig in signals:
        key = (sig["esg_pillar"], sig["category"])
        groups.setdefault(key, []).append(sig)

    consolidated = []
    for (pillar, category), group in groups.items():
        severities = [s["severity"] for s in group]
        severity_order = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
        max_severity = max(severities, key=lambda s: severity_order.get(s, 0))

        titles = list(dict.fromkeys(s["title"] for s in group))
        descriptions = list(dict.fromkeys(s["description"] for s in group))
        source_ids = list(dict.fromkeys(s["source_id"] for s in group))

        evidence_sources = []
        for s in group:
            evidence_sources.append({
                "source_table": s["source_table"],
                "source_id": s["source_id"],
                "signal_type": s["signal_type"],
                "verified": s.get("verified", "No"),
                "raw_data": s.get("raw_data", {}),
            })

        consolidated.append({
            "esg_pillar": pillar,
            "category": category,
            "title": titles[0] if len(titles) == 1 else "; ".join(titles[:3]),
            "description": descriptions[0] if len(descriptions) == 1
                           else " | ".join(descriptions[:3]),
            "severity": max_severity,
            "signal_count": len(group),
            "signal_types": list(dict.fromkeys(s["signal_type"] for s in group)),
            "source_ids": source_ids,
            "evidence_sources": evidence_sources,
        })

    return consolidated


# ════════════════════════════════════════════════════════════
#  Step 3 — Calculate risk scores
# ════════════════════════════════════════════════════════════

def _get_priority(score):
    for threshold, label in PRIORITY_BANDS:
        if score >= threshold:
            return label
    return "Low"


def calculate_risk_scores(findings):
    for f in findings:
        likelihood = f.get("likelihood_score")
        if likelihood is None:
            signal_types = f.get("signal_types", [])
            if signal_types:
                likelihood = max(SIGNAL_LIKELIHOOD.get(st, 3) for st in signal_types)
            else:
                likelihood = 3
        likelihood = int(likelihood)

        impact = f.get("impact_score")
        if impact is None:
            impact = SEVERITY_TO_IMPACT.get(f.get("severity", "Medium"), 3)
        impact = int(impact)

        raw_score = likelihood * impact

        f["likelihood_score"] = likelihood
        f["impact_score"] = impact
        f["calculated_risk_score"] = raw_score
        f["priority"] = _get_priority(raw_score)

    return findings


# ════════════════════════════════════════════════════════════
#  Step 4 — Assess evidence quality
# ════════════════════════════════════════════════════════════

def assess_evidence_quality(finding):
    sources = finding.get("evidence_sources", [])
    source_count = len(sources)
    verified_count = sum(1 for s in sources if s.get("verified") == "Yes")
    has_penalty = any(s.get("source_table") == "legal_penalty" for s in sources)
    has_controversy = any(s.get("source_table") == "controversy_record" for s in sources)

    if source_count >= 3 or (has_penalty and has_controversy and verified_count >= 1):
        confidence = "Strong"
        confidence_score = 0.90
    elif source_count >= 2:
        confidence = "Moderate"
        confidence_score = 0.75
    else:
        confidence = "Weak"
        confidence_score = 0.55

    review_required = (
        confidence == "Weak"
        or (source_count > 0 and verified_count == 0)
    )

    return {
        "evidence_count": source_count,
        "verified_count": verified_count,
        "evidence_confidence": confidence,
        "confidence_score": confidence_score,
        "review_required": review_required,
    }


# ════════════════════════════════════════════════════════════
#  Step 5 — Quantify financial impact
# ════════════════════════════════════════════════════════════

def quantify_financial_impact(finding, company_id, deal_id):
    sources = finding.get("evidence_sources", [])
    total_penalty = 0.0
    penalty_currency = "USD"
    has_penalty = False

    for s in sources:
        if s.get("source_table") == "legal_penalty":
            raw = s.get("raw_data", {})
            amt = float(raw.get("penalty_amount", 0))
            if amt > 0:
                cur = raw.get("penalty_currency", "USD")
                converted, rate = convert_currency(amt, cur, "USD")
                total_penalty += converted
                has_penalty = True

    if has_penalty:
        return {
            "estimated_amount": total_penalty,
            "currency": "USD",
            "calculation_method": "direct_penalty",
            "source_values": f"Sum of pending penalty amounts",
            "assumptions": "Converted to USD at latest FX rate",
            "confidence_level": "High",
        }

    severity = finding.get("severity", "Medium")
    likelihood = finding.get("likelihood_score", 3)
    probability_map = {"Critical": 0.70, "High": 0.50, "Medium": 0.30, "Low": 0.15}
    probability = probability_map.get(severity, 0.30)

    financials = load_company_financials()
    revenue = 0
    if not financials.empty:
        row = financials[financials["company_id"] == company_id]
        if not row.empty:
            row = row.sort_values("reporting_year", ascending=False)
            revenue = float(row.iloc[0].get("annual_revenue", 0))
            rev_currency = str(row.iloc[0].get("reporting_currency", "USD"))
            if rev_currency != "USD":
                revenue, _ = convert_currency(revenue, rev_currency, "USD")

    if revenue > 0:
        impact_pct_map = {5: 0.05, 4: 0.03, 3: 0.015, 2: 0.008, 1: 0.003}
        impact_pct = impact_pct_map.get(finding.get("impact_score", 3), 0.015)
        estimated = probability * revenue * impact_pct
        return {
            "estimated_amount": round(estimated, 2),
            "currency": "USD",
            "calculation_method": "expected_value",
            "source_values": f"Revenue ${revenue:,.0f} x {probability:.0%} probability "
                             f"x {impact_pct:.1%} impact factor",
            "assumptions": "Based on severity-adjusted probability and revenue-proportional impact",
            "confidence_level": "Medium",
        }

    return {
        "estimated_amount": None,
        "currency": "USD",
        "calculation_method": "not_quantifiable",
        "source_values": "Insufficient data",
        "assumptions": "No financial data available for quantification",
        "confidence_level": "Low",
    }


# ════════════════════════════════════════════════════════════
#  Step 6 — Identify opportunities
# ════════════════════════════════════════════════════════════

def identify_opportunities(deal_id, company_id):
    ro = load_risk_opportunity()
    opportunities = []

    if not ro.empty:
        mask = (ro["finding_type"] == "Opportunity")
        if "deal_id" in ro.columns:
            mask = mask & (ro["deal_id"] == deal_id)
        if "company_id" in ro.columns:
            mask = mask & (ro["company_id"] == company_id)
        for _, row in ro[mask].iterrows():
            opp = {
                "finding_id": str(row.get("finding_id", "")),
                "finding_type": "Opportunity",
                "deal_id": deal_id,
                "company_id": company_id,
                "esg_pillar": str(row.get("esg_pillar", "")),
                "category": str(row.get("category", "")),
                "title": str(row.get("title", "")),
                "description": str(row.get("description", "")),
                "likelihood_score": int(row.get("likelihood_score", 3)),
                "impact_score": int(row.get("impact_score", 3)),
                "stored_overall_score": float(row.get("overall_score", 0)),
                "financial_impact": float(row.get("financial_impact", 0)),
                "financial_impact_currency": str(
                    row.get("financial_impact_currency", "USD")),
                "priority": str(row.get("priority", "Medium")),
                "recommendation": str(row.get("recommendation", "")),
                "evidence_document_id": str(row.get("evidence_document_id", "")),
                "status": str(row.get("status", "Open")),
                "evidence_sources": [],
            }

            fi = opp["financial_impact"]
            fi_cur = opp["financial_impact_currency"]
            if fi > 0:
                usd_val, _ = convert_currency(fi, fi_cur, "USD")
                opp["financial_usd"] = usd_val
                opp["implementation_effort"] = (
                    "Low" if usd_val < 1_000_000
                    else "Medium" if usd_val < 10_000_000
                    else "High"
                )
                opp["payback_period_months"] = (
                    12 if usd_val < 5_000_000
                    else 24 if usd_val < 20_000_000
                    else 36
                )
            else:
                opp["financial_usd"] = 0
                opp["implementation_effort"] = "Low"
                opp["payback_period_months"] = None

            opportunities.append(opp)

    return opportunities


# ════════════════════════════════════════════════════════════
#  Step 7 — Generate deal recommendations
# ════════════════════════════════════════════════════════════

_RECOMMENDATION_MAP = {
    "Critical": [
        ("Contractual protection", "Include escrow, indemnity, or warranty provisions"),
        ("Valuation consideration", "Adjust valuation for identified exposure"),
    ],
    "High": [
        ("Additional diligence", "Commission specialist due diligence"),
        ("Contractual protection", "Include relevant warranty or indemnity"),
    ],
    "Medium": [
        ("Post-merger integration", "Address in first 100-day integration plan"),
        ("Remediation requirement", "Include remediation milestones in deal documentation"),
    ],
    "Low": [
        ("Value creation", "Leverage as value-creation opportunity post-deal"),
    ],
}

_CATEGORY_RECOMMENDATION_MAP = {
    "Data privacy": ("Condition precedent",
                     "Resolution of data-privacy proceedings before close"),
    "Certifications": ("Remediation requirement",
                       "Achieve re-certification before or within 90 days of close"),
    "Regulatory penalty": ("Contractual protection",
                           "Seller indemnity for pre-close penalties"),
    "Supply chain": ("Post-merger integration",
                     "Supplier ESG improvement programme post-close"),
    "Human rights": ("Additional diligence",
                     "Specialist human-rights due diligence"),
    "Scope 3 disclosure": ("Remediation requirement",
                           "Build Scope 3 measurement capability in first 100 days"),
    "Target progress": ("Post-merger integration",
                        "Refresh targets and embed in integration plan"),
}


def generate_deal_recommendations(findings):
    for f in findings:
        if f.get("finding_type") == "Opportunity":
            f["recommendation_category"] = "Value creation"
            if not f.get("recommendation"):
                f["recommendation"] = (
                    f"Leverage {f.get('category', 'this opportunity')} "
                    f"for value creation post-deal"
                )
            continue

        priority = f.get("priority", "Medium")
        category = f.get("category", "")

        rec_pairs = _RECOMMENDATION_MAP.get(priority, [])
        if category in _CATEGORY_RECOMMENDATION_MAP:
            cat_rec = _CATEGORY_RECOMMENDATION_MAP[category]
            rec_pairs = [cat_rec] + rec_pairs

        if rec_pairs:
            f["recommendation_category"] = rec_pairs[0][0]
            if not f.get("recommendation"):
                f["recommendation"] = rec_pairs[0][1]
            f["all_recommendation_categories"] = [
                {"category": r[0], "action": r[1]} for r in rec_pairs
            ]
        else:
            f["recommendation_category"] = "Additional diligence"
            f.setdefault("recommendation", "Conduct further investigation")
            f["all_recommendation_categories"] = []

    return findings


# ════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════

def load_existing_findings(deal_id, company_id):
    ro = load_risk_opportunity()
    if ro.empty:
        return []
    mask = (ro["finding_type"] == "Risk")
    if "deal_id" in ro.columns:
        mask = mask & (ro["deal_id"] == deal_id)
    if "company_id" in ro.columns:
        mask = mask & (ro["company_id"] == company_id)
    findings = []
    for _, row in ro[mask].iterrows():
        fi = float(row.get("financial_impact", 0))
        fi_cur = str(row.get("financial_impact_currency", "USD"))
        fi_usd, _ = convert_currency(fi, fi_cur, "USD")

        f = {
            "finding_id": str(row.get("finding_id", "")),
            "finding_type": "Risk",
            "deal_id": deal_id,
            "company_id": company_id,
            "esg_pillar": str(row.get("esg_pillar", "")),
            "category": str(row.get("category", "")),
            "title": str(row.get("title", "")),
            "description": str(row.get("description", "")),
            "likelihood_score": int(row.get("likelihood_score", 3)),
            "impact_score": int(row.get("impact_score", 3)),
            "stored_overall_score": float(row.get("overall_score", 0)),
            "financial_impact": fi,
            "financial_impact_currency": fi_cur,
            "financial_usd": fi_usd,
            "priority": str(row.get("priority", "Medium")),
            "recommendation": str(row.get("recommendation", "")),
            "evidence_document_id": str(row.get("evidence_document_id", "")),
            "evidence_controversy_id": str(row.get("evidence_controversy_id", "")),
            "status": str(row.get("status", "Open")),
            "evidence_sources": [],
        }
        f["calculated_risk_score"] = f["likelihood_score"] * f["impact_score"]
        findings.append(f)
    return findings


def _enrich_existing_with_signals(existing, signals):
    for f in existing:
        controversy_id = f.get("evidence_controversy_id", "")
        doc_id = f.get("evidence_document_id", "")
        matched = []
        for sig in signals:
            if sig["source_id"] == controversy_id and controversy_id:
                matched.append({
                    "source_table": sig["source_table"],
                    "source_id": sig["source_id"],
                    "signal_type": sig["signal_type"],
                    "verified": sig.get("verified", "No"),
                    "raw_data": sig.get("raw_data", {}),
                })
            elif (sig["category"] == f["category"]
                  and sig["esg_pillar"] == f["esg_pillar"]):
                matched.append({
                    "source_table": sig["source_table"],
                    "source_id": sig["source_id"],
                    "signal_type": sig["signal_type"],
                    "verified": sig.get("verified", "No"),
                    "raw_data": sig.get("raw_data", {}),
                })
        seen = set()
        deduped = []
        for m in matched:
            key = (m["source_table"], m["source_id"])
            if key not in seen:
                seen.add(key)
                deduped.append(m)
        f["evidence_sources"] = deduped
    return existing


def compute_summary(findings):
    risks = [f for f in findings if f.get("finding_type") == "Risk"]
    opps = [f for f in findings if f.get("finding_type") == "Opportunity"]

    total_exposure = sum(f.get("financial_usd", 0) or 0 for f in risks)
    opportunity_value = sum(f.get("financial_usd", 0) or 0 for f in opps)

    priority_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for r in risks:
        p = r.get("priority", "Medium")
        priority_counts[p] = priority_counts.get(p, 0) + 1

    pillar_exposure = {}
    for r in risks:
        pillar = r.get("esg_pillar", "Other")
        pillar_exposure[pillar] = (pillar_exposure.get(pillar, 0)
                                   + (r.get("financial_usd", 0) or 0))

    category_exposure = {}
    for r in risks:
        cat = r.get("category", "Other")
        category_exposure[cat] = (category_exposure.get(cat, 0)
                                  + (r.get("financial_usd", 0) or 0))

    review_count = sum(
        1 for f in findings
        if f.get("evidence", {}).get("review_required", False)
    )

    return {
        "total_findings": len(findings),
        "total_risks": len(risks),
        "total_opportunities": len(opps),
        "critical_count": priority_counts["Critical"],
        "high_count": priority_counts["High"],
        "medium_count": priority_counts["Medium"],
        "low_count": priority_counts["Low"],
        "total_financial_exposure": total_exposure,
        "opportunity_value": opportunity_value,
        "review_required_count": review_count,
        "by_pillar": pillar_exposure,
        "by_category": category_exposure,
        "priority_counts": priority_counts,
    }


def get_risk_matrix_data(findings):
    matrix = [[[] for _ in range(5)] for _ in range(5)]
    for f in findings:
        if f.get("finding_type") != "Risk":
            continue
        li = max(0, min(4, int(f.get("likelihood_score", 1)) - 1))
        im = max(0, min(4, int(f.get("impact_score", 1)) - 1))
        matrix[li][im].append(f.get("finding_id", f.get("title", "")))
    return matrix


# ════════════════════════════════════════════════════════════
#  Orchestrator
# ════════════════════════════════════════════════════════════

def run_risk_opportunity_analysis(deal_id, company_id):
    existing = load_existing_findings(deal_id, company_id)

    signals = collect_risk_signals(deal_id, company_id)

    existing = _enrich_existing_with_signals(existing, signals)

    for f in existing:
        f["evidence"] = assess_evidence_quality(f)

    for f in existing:
        if f.get("financial_impact", 0) and f["financial_impact"] > 0:
            fi_cur = f.get("financial_impact_currency", "USD")
            fi_usd, _ = convert_currency(f["financial_impact"], fi_cur, "USD")
            f["financial"] = {
                "estimated_amount": fi_usd,
                "currency": "USD",
                "calculation_method": "direct_from_assessment",
                "source_values": f"Assessment value {f['financial_impact']:,.0f} "
                                 f"{fi_cur}",
                "assumptions": "From pre-existing risk assessment",
                "confidence_level": "High",
            }
        else:
            f["financial"] = quantify_financial_impact(f, company_id, deal_id)

    existing = generate_deal_recommendations(existing)

    opportunities = identify_opportunities(deal_id, company_id)
    for opp in opportunities:
        opp["evidence"] = {"evidence_count": 1, "verified_count": 1,
                           "evidence_confidence": "Moderate",
                           "confidence_score": 0.75, "review_required": False}
        opp["financial"] = {
            "estimated_amount": opp.get("financial_usd", 0),
            "currency": "USD",
            "calculation_method": "opportunity_estimate",
            "source_values": "From ESG assessment",
            "assumptions": "Indicative estimate",
            "confidence_level": "Medium",
        }
    opportunities = generate_deal_recommendations(opportunities)

    all_findings = existing + opportunities

    summary = compute_summary(all_findings)

    return {
        "deal_id": deal_id,
        "company_id": company_id,
        "company_name": get_company_name(company_id),
        "deal_name": get_deal_name(deal_id),
        "findings": all_findings,
        "summary": summary,
        "signals_collected": len(signals),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
