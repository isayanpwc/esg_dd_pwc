"""
Regulatory Compliance Agent -- backend engine.

Evaluates whether available ESG disclosures and supporting evidence appear
to satisfy applicable regulatory requirements.  It does NOT issue a legal
opinion; it provides an evidence-based compliance assessment for
due-diligence review.

Primary tables:
    regulation_master, regulatory_requirement, company_master,
    facility_master, deal_master, esg_metric_data, esg_document_register,
    certification, legal_penalty

Benchmark table (for comparison):
    compliance_assessment

Tools:
  determine_regulation_applicability  -- Step 1
  get_regulatory_requirements         -- Step 2
  retrieve_requirement_evidence       -- Step 3
  calculate_requirement_completeness  -- Step 4
  assess_preliminary_compliance       -- Step 5
  get_related_penalties               -- penalty lookup
  get_certification_status            -- certification lookup
  generate_remediation_action         -- Step 6 remediation
  run_full_compliance_assessment      -- orchestrate Steps 1-6
"""

import json
import os
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

COMPLIANCE_THRESHOLDS = {
    "compliant_min": 100,
    "partial_min": 60,
    "non_compliant_below": 60,
}

SEVERITY_WEIGHTS = {
    "mandatory_factor": {"Yes": 1.5, "No": 1.0},
    "evidence_gap_factor": {"none": 2.0, "partial": 1.3, "complete": 0.5},
    "enforcement_factor": {"known": 1.5, "none": 1.0},
    "criticality_base": {"Critical": 4.0, "High": 3.0, "Medium": 2.0, "Low": 1.0},
}

SEVERITY_SCORE_BANDS = [
    (9.0, "Critical"),
    (5.0, "High"),
    (2.5, "Medium"),
    (0.0, "Low"),
]

APPLICABILITY_RULES = {
    "REG001": {"countries": ["India"], "industries": ["IT Services & Consulting", "Software & Cloud"]},
    "REG002": {"countries": ["Switzerland", "Germany", "United Kingdom"], "industries": None},
    "REG003": {"countries": None, "industries": None},
    "REG004": {"countries": None, "industries": None},
    "REG005": {"countries": ["India"], "industries": None},
    "REG006": {"countries": ["Switzerland", "Germany", "United Kingdom"], "industries": None},
    "REG007": {"countries": ["United States"], "industries": None},
    "REG008": {"countries": None, "industries": None},
    "REG009": {"countries": ["United States"], "industries": None},
    "REG010": {"countries": None, "industries": None},
    "REG011": {"countries": None, "industries": None},
    "REG012": {"countries": ["United States"], "industries": None},
}


# ════════════════════════════════════════════════════════════
#  Data loaders
# ════════════════════════════════════════════════════════════

def _load_csv(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def load_regulation_master():
    return _load_csv("regulation_master.csv")


def load_regulatory_requirements():
    return _load_csv("regulatory_requirement.csv")


def load_company_master():
    return _load_csv("company_master.csv")


def load_facility_master():
    return _load_csv("facility_master.csv")


def load_deal_master():
    return _load_csv("deal_master.csv")


def load_metric_data():
    return _load_csv("esg_metric_data.csv")


def load_document_register():
    return _load_csv("esg_document_register.csv")


def load_certification():
    return _load_csv("certification.csv")


def load_legal_penalty():
    return _load_csv("legal_penalty.csv")


def load_compliance_assessment():
    return _load_csv("compliance_assessment.csv")


def load_company_financials():
    return _load_csv("company_financials.csv")


# ════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════

def get_company_name(company_id):
    cm = load_company_master()
    if cm.empty:
        return company_id
    row = cm[cm["company_id"] == company_id]
    if row.empty:
        return company_id
    return row.iloc[0].get("company_name", company_id)


def get_available_companies():
    deals = load_deal_master()
    if not deals.empty:
        return sorted(deals["company_id"].unique().tolist())
    cm = load_company_master()
    if cm.empty:
        return []
    return sorted(cm["company_id"].unique().tolist())


def get_available_deals():
    deals = load_deal_master()
    if deals.empty:
        return []
    return deals.to_dict("records")


def get_available_years():
    md = load_metric_data()
    if md.empty:
        return []
    return sorted(md["reporting_year"].unique().tolist())


def get_deal_for_company(company_id):
    deals = load_deal_master()
    if deals.empty:
        return None
    row = deals[deals["company_id"] == company_id]
    if row.empty:
        return None
    return row.iloc[0]["deal_id"]


# ════════════════════════════════════════════════════════════
#  Tool 1 -- determine_regulation_applicability
# ════════════════════════════════════════════════════════════

def determine_regulation_applicability(company_id, regulation_id, reporting_year=None):
    """Determine whether a regulation is applicable to a company.

    Returns one of:
        Applicable | Not applicable | Potentially applicable |
        Insufficient applicability data
    """
    reg_master = load_regulation_master()
    company_master = load_company_master()

    if reg_master.empty or company_master.empty:
        return {
            "regulation_id": regulation_id,
            "company_id": company_id,
            "applicability": "Insufficient applicability data",
            "reasons": ["Missing regulation or company reference data"],
        }

    reg = reg_master[reg_master["regulation_id"] == regulation_id]
    comp = company_master[company_master["company_id"] == company_id]

    if reg.empty:
        return {
            "regulation_id": regulation_id,
            "company_id": company_id,
            "applicability": "Insufficient applicability data",
            "reasons": [f"Regulation {regulation_id} not found in master data"],
        }
    if comp.empty:
        return {
            "regulation_id": regulation_id,
            "company_id": company_id,
            "applicability": "Insufficient applicability data",
            "reasons": [f"Company {company_id} not found in master data"],
        }

    reg_row = reg.iloc[0]
    comp_row = comp.iloc[0]

    company_country = str(comp_row.get("country", "")).strip()
    company_industry = str(comp_row.get("industry", "")).strip()
    regulation_name = reg_row.get("regulation_name", regulation_id)
    mandatory = str(reg_row.get("mandatory_flag", "")).strip()

    if reporting_year:
        eff_date = str(reg_row.get("effective_date", ""))
        if eff_date and eff_date != "nan":
            try:
                eff_year = int(eff_date[:4])
                if int(reporting_year) < eff_year:
                    return {
                        "regulation_id": regulation_id,
                        "company_id": company_id,
                        "regulation_name": regulation_name,
                        "applicability": "Not applicable",
                        "reasons": [
                            f"Reporting year {reporting_year} precedes regulation effective date {eff_date}"
                        ],
                    }
            except (ValueError, IndexError):
                pass

    rules = APPLICABILITY_RULES.get(regulation_id)
    reasons = []

    if rules is None:
        return {
            "regulation_id": regulation_id,
            "company_id": company_id,
            "regulation_name": regulation_name,
            "applicability": "Potentially applicable",
            "reasons": ["No applicability rules defined for this regulation"],
        }

    country_match = None
    if rules["countries"] is not None:
        if company_country in rules["countries"]:
            country_match = True
            reasons.append(f"Company country ({company_country}) is within regulation jurisdiction")
        else:
            fac = load_facility_master()
            if not fac.empty:
                fac_countries = set(
                    fac[fac["company_id"] == company_id]["country"].dropna().tolist()
                )
                overlap = fac_countries & set(rules["countries"])
                if overlap:
                    country_match = True
                    reasons.append(
                        f"Company has facilities in jurisdiction countries: {', '.join(sorted(overlap))}"
                    )
                else:
                    country_match = False
                    reasons.append(
                        f"Company country ({company_country}) and facilities are outside jurisdiction"
                    )
            else:
                country_match = False
                reasons.append(f"Company country ({company_country}) is outside regulation jurisdiction")
    else:
        country_match = True
        reasons.append("Regulation has global applicability")

    industry_match = None
    if rules["industries"] is not None:
        if company_industry in rules["industries"]:
            industry_match = True
            reasons.append(f"Company industry ({company_industry}) matches regulation scope")
        else:
            industry_match = False
            reasons.append(f"Company industry ({company_industry}) is outside regulation scope")
    else:
        industry_match = True
        reasons.append("Regulation applies across industries")

    penalties = get_related_penalties(company_id, regulation_id)
    if penalties:
        reasons.append(
            f"Enforcement history exists: {len(penalties)} penalty/inquiry record(s) on file"
        )

    if country_match and industry_match:
        applicability = "Applicable"
    elif penalties:
        applicability = "Applicable"
        reasons.append("Overridden to Applicable due to existing enforcement history")
    elif country_match is False and industry_match is False:
        applicability = "Not applicable"
    elif country_match is False or industry_match is False:
        applicability = "Not applicable"
    else:
        applicability = "Potentially applicable"

    return {
        "regulation_id": regulation_id,
        "company_id": company_id,
        "regulation_name": regulation_name,
        "mandatory_flag": mandatory,
        "applicability": applicability,
        "reasons": reasons,
    }


# ════════════════════════════════════════════════════════════
#  Tool 2 -- get_regulatory_requirements
# ════════════════════════════════════════════════════════════

def get_regulatory_requirements(regulation_id):
    """Retrieve all requirements for a given regulation."""
    reqs = load_regulatory_requirements()
    if reqs.empty:
        return []
    filtered = reqs[reqs["regulation_id"] == regulation_id]
    if filtered.empty:
        return []
    return filtered.to_dict("records")


# ════════════════════════════════════════════════════════════
#  Tool 3 -- retrieve_requirement_evidence
# ════════════════════════════════════════════════════════════

def retrieve_requirement_evidence(company_id, requirement_id, reporting_year, deal_id=None):
    """Check whether the evidence for a single requirement is present."""
    reqs = load_regulatory_requirements()
    if reqs.empty:
        return {"requirement_id": requirement_id, "error": "No regulatory requirements data"}

    req_row = reqs[reqs["requirement_id"] == requirement_id]
    if req_row.empty:
        return {"requirement_id": requirement_id, "error": f"Requirement {requirement_id} not found"}

    req = req_row.iloc[0]
    required_metric = str(req.get("required_metric", "")).strip()
    required_doc_type = str(req.get("required_document_type", "")).strip()
    mandatory = str(req.get("mandatory_flag", "")).strip()
    criticality = str(req.get("criticality", "")).strip()

    if not deal_id:
        deal_id = get_deal_for_company(company_id)

    metric_data = load_metric_data()
    doc_register = load_document_register()

    metric_present = False
    metric_correct_year = False
    metric_correct_unit = False
    metric_audited = False
    evidence_page_present = False
    metric_value = None
    metric_unit = None
    source_doc_id = None

    if not metric_data.empty and required_metric:
        filters = (metric_data["company_id"] == company_id) & (metric_data["metric_code"] == required_metric)
        if deal_id:
            filters = filters & (metric_data["deal_id"] == deal_id)
        metric_rows = metric_data[filters]

        if not metric_rows.empty:
            metric_present = True
            year_rows = metric_rows[metric_rows["reporting_year"] == int(reporting_year)]
            if not year_rows.empty:
                metric_correct_year = True
                row = year_rows.iloc[0]
                metric_value = row.get("value")
                metric_unit = str(row.get("unit", "")).strip()
                metric_correct_unit = bool(metric_unit and metric_unit != "" and metric_unit != "nan")
                metric_audited = str(row.get("is_audited", "")).strip().lower() == "yes"
                source_doc_id = row.get("source_document_id")
                sp = row.get("source_page")
                evidence_page_present = pd.notna(sp) and str(sp).strip() not in ("", "nan")

    doc_present = False
    doc_correct_year = False
    doc_audited = False
    doc_id = None

    if not doc_register.empty and required_doc_type:
        doc_filters = (doc_register["company_id"] == company_id)
        if deal_id:
            doc_filters = doc_filters & (doc_register["deal_id"] == deal_id)
        doc_rows = doc_register[doc_filters]

        if not doc_rows.empty:
            type_rows = doc_rows[
                doc_rows["document_type"].str.lower().str.contains(
                    required_doc_type.lower(), na=False
                )
            ]
            if not type_rows.empty:
                doc_present = True
                year_docs = type_rows[type_rows["reporting_year"] == int(reporting_year)]
                if not year_docs.empty:
                    doc_correct_year = True
                    doc_row = year_docs.iloc[0]
                    doc_id = doc_row.get("document_id")
                    doc_audited = str(doc_row.get("audited_flag", "")).strip().lower() == "yes"

    return {
        "requirement_id": requirement_id,
        "requirement_name": req.get("requirement_name", requirement_id),
        "regulation_id": req.get("regulation_id"),
        "company_id": company_id,
        "deal_id": deal_id,
        "reporting_year": int(reporting_year),
        "required_metric": required_metric,
        "mandatory_flag": mandatory,
        "criticality": criticality,
        "evidence": {
            "metric_present": metric_present,
            "metric_correct_year": metric_correct_year,
            "metric_correct_unit": metric_correct_unit,
            "metric_audited": metric_audited,
            "evidence_page_present": evidence_page_present,
            "document_present": doc_present,
            "document_correct_year": doc_correct_year,
            "document_audited": doc_audited,
        },
        "metric_value": metric_value,
        "metric_unit": metric_unit,
        "source_document_id": source_doc_id or doc_id,
    }


# ════════════════════════════════════════════════════════════
#  Tool 4 -- calculate_requirement_completeness
# ════════════════════════════════════════════════════════════

def calculate_requirement_completeness(evidence_result):
    """Calculate a completeness score from the evidence dict."""
    ev = evidence_result.get("evidence", {})

    components = {
        "metric_present": ev.get("metric_present", False),
        "document_present": ev.get("document_present", False),
        "correct_reporting_period": ev.get("metric_correct_year", False),
        "evidence_page_present": ev.get("evidence_page_present", False),
        "adequate_assurance": ev.get("metric_audited", False) or ev.get("document_audited", False),
    }

    weights = {
        "metric_present": 0.30,
        "document_present": 0.25,
        "correct_reporting_period": 0.20,
        "evidence_page_present": 0.10,
        "adequate_assurance": 0.15,
    }

    present_count = sum(1 for v in components.values() if v)
    total_count = len(components)
    score = round(sum(weights[k] * 100 for k, v in components.items() if v), 1)

    return {
        "requirement_id": evidence_result.get("requirement_id"),
        "components": components,
        "present_count": present_count,
        "total_count": total_count,
        "completeness_score": score,
    }


# ════════════════════════════════════════════════════════════
#  Tool 5 -- assess_preliminary_compliance
# ════════════════════════════════════════════════════════════

def assess_preliminary_compliance(evidence_result, completeness_result, applicability_result=None):
    """Assign preliminary compliance status and severity.

    Guardrail: the agent says 'Available evidence indicates a disclosure
    gap', never 'The company has violated the regulation'.
    """
    score = completeness_result.get("completeness_score", 0)
    components = completeness_result.get("components", {})
    mandatory = str(evidence_result.get("mandatory_flag", "No")).strip()
    criticality = str(evidence_result.get("criticality", "Medium")).strip()

    applicability = "Applicable"
    if applicability_result:
        applicability = applicability_result.get("applicability", "Applicable")

    if applicability in ("Not applicable",):
        return {
            "requirement_id": evidence_result.get("requirement_id"),
            "compliance_status": "Not applicable",
            "completeness_score": score,
            "severity": "Low",
            "severity_score": 0.0,
            "gap_description": f"Regulation not applicable to this entity",
            "applicability": applicability,
        }

    if applicability in ("Insufficient applicability data",):
        return {
            "requirement_id": evidence_result.get("requirement_id"),
            "compliance_status": "Insufficient evidence",
            "completeness_score": score,
            "severity": "Medium",
            "severity_score": 0.0,
            "gap_description": "Applicability could not be determined from available data",
            "applicability": applicability,
        }

    critical_missing = False
    if mandatory == "Yes" and not components.get("metric_present", False):
        critical_missing = True

    if score >= COMPLIANCE_THRESHOLDS["compliant_min"] and not critical_missing:
        status = "Compliant"
    elif score >= COMPLIANCE_THRESHOLDS["partial_min"] and not critical_missing:
        status = "Partially compliant"
    else:
        status = "Non-compliant"

    gaps = []
    if not components.get("metric_present", False):
        gaps.append(f"Required metric ({evidence_result.get('required_metric', 'N/A')}) not disclosed")
    if not components.get("correct_reporting_period", False) and components.get("metric_present", False):
        gaps.append("Metric not available for the required reporting period")
    if not components.get("document_present", False):
        gaps.append("Required supporting document not available")
    if not components.get("evidence_page_present", False) and components.get("metric_present", False):
        gaps.append("Evidence page reference not available")
    if not components.get("adequate_assurance", False) and components.get("metric_present", False):
        gaps.append("Disclosure exists but is not independently assured")

    gap_description = "; ".join(gaps) if gaps else ""
    if status == "Compliant":
        gap_description = ""

    mf = SEVERITY_WEIGHTS["mandatory_factor"].get(mandatory, 1.0)

    if not components.get("metric_present", False):
        ef = SEVERITY_WEIGHTS["evidence_gap_factor"]["none"]
    elif score < 100:
        ef = SEVERITY_WEIGHTS["evidence_gap_factor"]["partial"]
    else:
        ef = SEVERITY_WEIGHTS["evidence_gap_factor"]["complete"]

    penalties = get_related_penalties(evidence_result.get("company_id"), evidence_result.get("regulation_id"))
    enf = SEVERITY_WEIGHTS["enforcement_factor"]["known"] if penalties else SEVERITY_WEIGHTS["enforcement_factor"]["none"]

    crit_base = SEVERITY_WEIGHTS["criticality_base"].get(criticality, 2.0)
    severity_score = round(crit_base * mf * ef * enf, 2)

    severity_label = "Low"
    for threshold, label in SEVERITY_SCORE_BANDS:
        if severity_score >= threshold:
            severity_label = label
            break

    return {
        "requirement_id": evidence_result.get("requirement_id"),
        "compliance_status": status,
        "completeness_score": score,
        "severity": severity_label,
        "severity_score": severity_score,
        "gap_description": gap_description,
        "applicability": applicability,
        "severity_factors": {
            "criticality_base": crit_base,
            "mandatory_factor": mf,
            "evidence_gap_factor": ef,
            "enforcement_factor": enf,
        },
    }


# ════════════════════════════════════════════════════════════
#  Tool 6 -- get_related_penalties
# ════════════════════════════════════════════════════════════

def get_related_penalties(company_id, regulation_id=None):
    """Look up penalties / enforcement actions for a company."""
    penalties = load_legal_penalty()
    if penalties.empty:
        return []

    filtered = penalties[penalties["company_id"] == company_id]
    if regulation_id:
        filtered = filtered[filtered["regulation_id"] == regulation_id]

    if filtered.empty:
        return []
    return filtered.to_dict("records")


# ════════════════════════════════════════════════════════════
#  Tool 7 -- get_certification_status
# ════════════════════════════════════════════════════════════

def get_certification_status(company_id):
    """Return certifications held by a company."""
    certs = load_certification()
    if certs.empty:
        return []

    filtered = certs[certs["company_id"] == company_id]
    if filtered.empty:
        return []
    return filtered.to_dict("records")


# ════════════════════════════════════════════════════════════
#  Tool 8 -- generate_remediation_action
# ════════════════════════════════════════════════════════════

_REMEDIATION_TEMPLATES = {
    "metric_not_disclosed": (
        "Initiate data collection for {metric} and include in next reporting cycle"
    ),
    "metric_wrong_year": (
        "Ensure {metric} is disclosed for reporting year {year}"
    ),
    "document_missing": (
        "Prepare and publish the required {doc_type} covering reporting year {year}"
    ),
    "not_assured": (
        "Obtain limited or reasonable assurance over {metric} from an independent auditor"
    ),
    "evidence_page_missing": (
        "Record the specific page or section reference for {metric} in the source document"
    ),
    "penalty_open": (
        "Address open enforcement action related to {regulation}: {description}"
    ),
}


def generate_remediation_action(evidence_result, compliance_result):
    """Generate remediation actions based on identified gaps."""
    status = compliance_result.get("compliance_status", "")
    if status in ("Compliant", "Not applicable"):
        return []

    components = compliance_result.get("components", {})
    if not components:
        ev = evidence_result.get("evidence", {})
        components = {
            "metric_present": ev.get("metric_present", False),
            "document_present": ev.get("document_present", False),
            "correct_reporting_period": ev.get("metric_correct_year", False),
            "evidence_page_present": ev.get("evidence_page_present", False),
            "adequate_assurance": ev.get("metric_audited", False) or ev.get("document_audited", False),
        }

    metric = evidence_result.get("required_metric", "the required metric")
    year = evidence_result.get("reporting_year", "the reporting year")
    doc_type = "Sustainability Report"
    regulation_id = evidence_result.get("regulation_id", "")

    actions = []

    if not components.get("metric_present", False):
        actions.append({
            "priority": "High",
            "action": _REMEDIATION_TEMPLATES["metric_not_disclosed"].format(metric=metric),
            "category": "Data collection",
        })

    if components.get("metric_present", False) and not components.get("correct_reporting_period", False):
        actions.append({
            "priority": "High",
            "action": _REMEDIATION_TEMPLATES["metric_wrong_year"].format(metric=metric, year=year),
            "category": "Reporting period",
        })

    if not components.get("document_present", False):
        actions.append({
            "priority": "High",
            "action": _REMEDIATION_TEMPLATES["document_missing"].format(doc_type=doc_type, year=year),
            "category": "Document preparation",
        })

    if components.get("metric_present", False) and not components.get("adequate_assurance", False):
        actions.append({
            "priority": "Medium",
            "action": _REMEDIATION_TEMPLATES["not_assured"].format(metric=metric),
            "category": "Assurance",
        })

    if components.get("metric_present", False) and not components.get("evidence_page_present", False):
        actions.append({
            "priority": "Low",
            "action": _REMEDIATION_TEMPLATES["evidence_page_missing"].format(metric=metric),
            "category": "Documentation",
        })

    penalties = get_related_penalties(evidence_result.get("company_id"), regulation_id)
    for p in penalties:
        if str(p.get("status", "")).lower() not in ("resolved",):
            actions.append({
                "priority": "Critical",
                "action": _REMEDIATION_TEMPLATES["penalty_open"].format(
                    regulation=regulation_id,
                    description=p.get("description", ""),
                ),
                "category": "Enforcement",
            })

    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    actions.sort(key=lambda a: priority_order.get(a["priority"], 99))

    return actions


# ════════════════════════════════════════════════════════════
#  Orchestrator -- run_full_compliance_assessment
# ════════════════════════════════════════════════════════════

def run_full_compliance_assessment(company_id, regulation_id, reporting_year, deal_id=None):
    """Orchestrate Steps 1-6 for every requirement under a regulation."""
    if not deal_id:
        deal_id = get_deal_for_company(company_id)

    applicability = determine_regulation_applicability(company_id, regulation_id, reporting_year)
    requirements = get_regulatory_requirements(regulation_id)

    if not requirements:
        return {
            "regulation_id": regulation_id,
            "company_id": company_id,
            "deal_id": deal_id,
            "reporting_year": int(reporting_year),
            "applicability": applicability,
            "requirements_assessed": 0,
            "results": [],
            "summary": {
                "total": 0,
                "compliant": 0,
                "partially_compliant": 0,
                "non_compliant": 0,
                "not_applicable": 0,
                "insufficient_evidence": 0,
                "overall_score": 0,
            },
        }

    results = []
    for req in requirements:
        req_id = req["requirement_id"]

        evidence = retrieve_requirement_evidence(company_id, req_id, reporting_year, deal_id)
        completeness = calculate_requirement_completeness(evidence)
        compliance = assess_preliminary_compliance(evidence, completeness, applicability)
        remediation = generate_remediation_action(evidence, compliance)

        results.append({
            "regulation_id": regulation_id,
            "requirement_id": req_id,
            "requirement_name": req.get("requirement_name", req_id),
            "required_metric": req.get("required_metric", ""),
            "applicability": compliance.get("applicability", applicability.get("applicability", "")),
            "compliance_status": compliance["compliance_status"],
            "completeness_score": completeness["completeness_score"],
            "severity": compliance["severity"],
            "severity_score": compliance.get("severity_score", 0),
            "gap_description": compliance.get("gap_description", ""),
            "remediation_actions": remediation,
            "evidence_components": completeness.get("components", {}),
            "evidence_document_ids": [
                evidence.get("source_document_id")
            ] if evidence.get("source_document_id") else [],
        })

    statuses = [r["compliance_status"] for r in results]
    scores = [r["completeness_score"] for r in results]

    summary = {
        "total": len(results),
        "compliant": statuses.count("Compliant"),
        "partially_compliant": statuses.count("Partially compliant"),
        "non_compliant": statuses.count("Non-compliant"),
        "not_applicable": statuses.count("Not applicable"),
        "insufficient_evidence": statuses.count("Insufficient evidence"),
        "overall_score": round(sum(scores) / len(scores), 1) if scores else 0,
    }

    return {
        "regulation_id": regulation_id,
        "regulation_name": applicability.get("regulation_name", regulation_id),
        "company_id": company_id,
        "company_name": get_company_name(company_id),
        "deal_id": deal_id,
        "reporting_year": int(reporting_year),
        "applicability": applicability,
        "requirements_assessed": len(results),
        "results": results,
        "summary": summary,
        "certifications": get_certification_status(company_id),
        "penalties": get_related_penalties(company_id),
    }


def run_multi_regulation_assessment(company_id, reporting_year, deal_id=None):
    """Run compliance assessment across ALL regulations for a company."""
    regs = load_regulation_master()
    if regs.empty:
        return []

    all_results = []
    for _, reg_row in regs.iterrows():
        reg_id = reg_row["regulation_id"]
        result = run_full_compliance_assessment(company_id, reg_id, reporting_year, deal_id)
        all_results.append(result)

    return all_results


def get_benchmark_assessment(company_id, requirement_id, reporting_year, deal_id=None):
    """Retrieve the existing compliance_assessment record for benchmarking."""
    ca = load_compliance_assessment()
    if ca.empty:
        return None

    filters = (ca["company_id"] == company_id) & (ca["requirement_id"] == requirement_id) & (ca["reporting_year"] == int(reporting_year))
    if deal_id:
        filters = filters & (ca["deal_id"] == deal_id)

    rows = ca[filters]
    if rows.empty:
        return None
    return rows.iloc[0].to_dict()


# ════════════════════════════════════════════════════════════
#  Regulation abbreviations & helpers for Regulatory Tracker
# ════════════════════════════════════════════════════════════

REGULATION_ABBREVIATIONS = {
    "REG001": "BRSR",
    "REG002": "CSRD",
    "REG003": "GRI",
    "REG004": "TCFD",
    "REG005": "DPDP",
    "REG006": "GDPR",
    "REG007": "SEC",
    "REG008": "SASB",
    "REG009": "SOX",
    "REG010": "IFRS S1",
    "REG011": "IFRS S2",
    "REG012": "PCAOB",
}


def get_regulation_abbreviation(regulation_id):
    return REGULATION_ABBREVIATIONS.get(regulation_id, regulation_id)


def get_all_regulation_abbreviations():
    regs = load_regulation_master()
    if regs.empty:
        return {}
    result = {}
    for _, row in regs.iterrows():
        reg_id = row["regulation_id"]
        result[reg_id] = {
            "abbr": REGULATION_ABBREVIATIONS.get(reg_id, reg_id),
            "full_name": row.get("regulation_name", reg_id),
            "mandatory": row.get("mandatory_flag", "No"),
            "jurisdiction": row.get("jurisdiction", ""),
        }
    return result


def extract_gap_analysis(all_results):
    gap_analysis = []

    for reg_result in all_results:
        reg_id = reg_result.get("regulation_id", "")
        abbr = get_regulation_abbreviation(reg_id)
        full_name = reg_result.get("regulation_name", reg_id)
        req_results = reg_result.get("results", [])

        gaps = []
        fixes = []
        for req in req_results:
            status = req.get("compliance_status", "")
            if status in ("Non-compliant", "Partially compliant", "Insufficient evidence"):
                gaps.append({
                    "requirement_id": req.get("requirement_id", ""),
                    "requirement_name": req.get("requirement_name", ""),
                    "status": "Missing",
                    "priority": req.get("severity", "Medium"),
                    "reason": "No data mapping available",
                })
                for action in req.get("remediation_actions", []):
                    fixes.append({
                        "fix_id": f"{abbr}-{req.get('requirement_id', '')}",
                        "action": action.get("action", ""),
                        "priority": action.get("priority", "Medium"),
                        "description": action.get("action", ""),
                    })

        gap_analysis.append({
            "regulation_id": reg_id,
            "abbreviation": abbr,
            "full_name": full_name,
            "gaps": gaps,
            "fix_suggestions": fixes,
            "gap_count": len(gaps),
        })

    updates_data = load_framework_updates()
    pending_updates = [u for u in updates_data.get("updates", []) if u.get("status") == "pending_review"]

    for u in pending_updates:
        fw_abbr = u.get("framework_abbr", "")
        update_id = u.get("update_id", "")
        gap_id = u.get("gap_id", update_id)

        existing = None
        for ga in gap_analysis:
            if ga["abbreviation"] == fw_abbr:
                existing = ga
                break

        severity_map = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
        priority = severity_map.get(u.get("severity", "medium"), "Medium")

        gap_entry = {
            "requirement_id": gap_id,
            "requirement_name": u.get("title", ""),
            "status": "Missing",
            "priority": priority,
            "reason": "No data mapping available",
        }

        fix_entry = {
            "fix_id": gap_id,
            "action": u.get("description", ""),
            "priority": priority,
            "description": u.get("description", ""),
        }

        if existing:
            if not any(g["requirement_id"] == gap_id for g in existing["gaps"]):
                existing["gaps"].append(gap_entry)
                existing["fix_suggestions"].append(fix_entry)
                existing["gap_count"] = len(existing["gaps"])
        else:
            regs = load_regulation_master()
            reg_match = regs[regs["regulation_id"] == u.get("regulation_id", "")]
            full = reg_match.iloc[0]["regulation_name"] if not reg_match.empty else fw_abbr

            gap_analysis.append({
                "regulation_id": u.get("regulation_id", ""),
                "abbreviation": fw_abbr,
                "full_name": full,
                "gaps": [gap_entry],
                "fix_suggestions": [fix_entry],
                "gap_count": 1,
            })

    return gap_analysis


def compute_compliance_summary(all_results):
    if not all_results:
        return {"overall_compliance": 0, "frameworks_analyzed": 0, "total_gaps": 0, "pending_updates": 0}

    scores = []
    for r in all_results:
        summary = r.get("summary", {})
        scores.append(summary.get("overall_score", 0))

    overall = round(sum(scores) / len(scores), 1) if scores else 0

    pending = 0
    try:
        from utils.json_manager import read_json
        updates_data = read_json("framework_updates.json")
        for u in updates_data.get("updates", []):
            if u.get("status") == "pending_review":
                pending += 1
    except Exception:
        pass

    gap_data = extract_gap_analysis(all_results)
    total_gaps = sum(gd["gap_count"] for gd in gap_data)

    return {
        "overall_compliance": overall,
        "frameworks_analyzed": len(all_results),
        "total_gaps": total_gaps,
        "pending_updates": pending,
    }


def extract_radar_chart_data(all_results):
    chart_data = []
    for r in all_results:
        reg_id = r.get("regulation_id", "")
        summary = r.get("summary", {})
        app = r.get("applicability", {})
        chart_data.append({
            "framework": get_regulation_abbreviation(reg_id),
            "full_name": r.get("regulation_name", reg_id),
            "mandatory": app.get("mandatory_flag", "No"),
            "compliance_pct": round(summary.get("overall_score", 0), 1),
            "covered": summary.get("compliant", 0),
            "partial": summary.get("partially_compliant", 0),
            "missing": summary.get("non_compliant", 0),
            "total": summary.get("total", 0),
        })
    return chart_data


def generate_compliance_narrative(all_results, company_name, reporting_year):
    if not all_results:
        return "No assessment data available to generate a narrative."

    summary_stats = compute_compliance_summary(all_results)
    radar_data = extract_radar_chart_data(all_results)
    gap_data = extract_gap_analysis(all_results)
    updates_data = load_framework_updates()
    pending_updates = [u for u in updates_data.get("updates", []) if u.get("status") == "pending_review"]

    overall = summary_stats["overall_compliance"]
    fw_count = summary_stats["frameworks_analyzed"]
    total_gaps = summary_stats["total_gaps"]

    if overall >= 95:
        posture_desc = "strong overall compliance posture with minimal residual risk"
    elif overall >= 80:
        posture_desc = "solid compliance posture with targeted areas requiring remediation"
    elif overall >= 60:
        posture_desc = "moderate compliance posture with material gaps requiring attention"
    else:
        posture_desc = "significant compliance deficiencies requiring immediate executive action"

    sections = []

    sections.append(
        f"## Executive Summary\n\n"
        f"Current compliance stands at **{overall:.1f}%** across {fw_count} regulatory "
        f"framework(s). {company_name} {posture_desc}. "
        f"{'Immediate remediation is recommended for ' + str(total_gaps) + ' identified gap(s).' if total_gaps > 0 else 'No material gaps were identified.'} "
        f"{len(pending_updates)} regulatory update(s) are pending review."
    )

    sections.append("## Compliance Posture\n")
    for rd in radar_data:
        mand_str = "mandatory" if rd["mandatory"] == "Yes" else "voluntary"
        pct = rd["compliance_pct"]
        status_icon = "✅" if pct >= 95 else "⚠️" if pct >= 80 else "❌"
        sections[-1] += (
            f"\n- {status_icon} **{rd['framework']}** ({rd['full_name']}, {mand_str}): "
            f"**{pct:.0f}%** — {rd['covered']}/{rd['total']} requirements covered"
            f"{', ' + str(rd['partial']) + ' partial' if rd['partial'] > 0 else ''}"
            f"{', ' + str(rd['missing']) + ' missing' if rd['missing'] > 0 else ''}"
        )

    critical_gaps = []
    for gd in gap_data:
        for g in gd["gaps"]:
            if g["priority"] in ("Critical", "High"):
                critical_gaps.append({"framework": gd["abbreviation"], "name": g["requirement_name"], "priority": g["priority"]})

    if critical_gaps:
        gap_section = f"## High-Risk Gaps\n\n{len(critical_gaps)} critical or high priority gap(s) require immediate attention:\n"
        for i, g in enumerate(critical_gaps[:10], 1):
            emoji = "\U0001f534" if g["priority"] == "Critical" else "\U0001f7e0"
            gap_section += f"\n{i}. {emoji} **{g['framework']}**: {g['name']} ({g['priority']})"
        sections.append(gap_section)
    else:
        sections.append("## High-Risk Gaps\n\nNo critical or high priority gaps identified.")

    exposure_lines = []
    for r in all_results:
        penalties = r.get("penalties", [])
        open_penalties = [p for p in penalties if p.get("status", "").lower() != "resolved"]
        if open_penalties:
            abbr = get_regulation_abbreviation(r.get("regulation_id", ""))
            exposure_lines.append(f"- **{abbr}**: {len(open_penalties)} open enforcement action(s)")
    if pending_updates:
        for u in pending_updates[:5]:
            exposure_lines.append(f"- **{u.get('framework_abbr', '')}**: {u['title']}")

    if exposure_lines:
        sections.append("## Regulatory Exposure\n\n" + "\n".join(exposure_lines))
    else:
        sections.append("## Regulatory Exposure\n\nNo open enforcement actions or pending regulatory changes.")

    deadlines = []
    for u in pending_updates:
        deadlines.append({"date": u.get("published_date", ""), "framework": u.get("framework_abbr", ""), "title": u["title"]})
    deadlines.sort(key=lambda d: d["date"])
    if deadlines:
        dl_section = "## Upcoming Deadlines\n"
        for d in deadlines[:8]:
            dl_section += f"\n- **{d['date']}** — {d['framework']}: {d['title']}"
        sections.append(dl_section)

    all_fixes = []
    for gd in gap_data:
        for fix in gd["fix_suggestions"][:3]:
            all_fixes.append(fix.get("action", ""))
    if all_fixes:
        rec_section = "## Remediation Priorities\n"
        for i, fix in enumerate(all_fixes[:8], 1):
            rec_section += f"\n{i}. {fix}"
        sections.append(rec_section)

    sections.append(
        "---\n\n*Disclaimer: This assessment is generated from available disclosure evidence "
        "and does not constitute a legal opinion. Where the analysis reports a gap, it "
        "indicates that available evidence suggests a disclosure shortfall, not that "
        "the entity has violated the regulation. Findings should be reviewed by qualified "
        "compliance professionals.*"
    )

    return "\n\n".join(sections)


def generate_executive_narrative_llm(all_results, company_name, reporting_year):
    import requests as _req
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))

    api_url = os.getenv("CLAUDE_API_URL", "")
    api_key = os.getenv("CLAUDE_API_KEY", "")
    model = os.getenv("CLAUDE_MODEL", "vertex_ai.anthropic.claude-opus-4-6")

    if not api_url or not api_key:
        return None, "LLM not configured"

    summary = compute_compliance_summary(all_results)
    radar = extract_radar_chart_data(all_results)
    gaps = extract_gap_analysis(all_results)

    context = json.dumps({
        "company": company_name,
        "year": reporting_year,
        "overall_compliance": summary["overall_compliance"],
        "frameworks_analyzed": summary["frameworks_analyzed"],
        "total_gaps": summary["total_gaps"],
        "pending_updates": summary["pending_updates"],
        "framework_scores": [{"name": r["framework"], "pct": r["compliance_pct"], "covered": r["covered"], "missing": r["missing"], "total": r["total"]} for r in radar],
        "gaps": [{"framework": g["abbreviation"], "count": g["gap_count"], "items": [{"id": gi["requirement_id"], "name": gi["requirement_name"], "priority": gi["priority"]} for gi in g["gaps"][:5]]} for g in gaps if g["gap_count"] > 0],
    }, indent=2, default=str)[:6000]

    system_prompt = (
        "You are a senior ESG compliance analyst at a global advisory firm. "
        "Write an executive-level compliance assessment narrative based on the data provided. "
        "Structure your response with sections: Executive Summary, Compliance Posture, "
        "High-Risk Gaps, Regulatory Exposure, and Remediation Priorities. "
        "Be precise, cite specific frameworks and metrics, and maintain a professional tone. "
        "Do not speculate beyond the data provided."
    )

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate an executive compliance narrative for the following data:\n\n{context}"},
        ],
        "max_tokens": 3000,
        "temperature": 0.3,
    }

    try:
        resp = _req.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        body = resp.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content.strip(), None
    except Exception as e:
        return None, f"LLM call failed: {e}"


# ════════════════════════════════════════════════════════════
#  Structured gap remediation
# ════════════════════════════════════════════════════════════

def generate_structured_remediation(requirement_result, framework_abbr):
    req_id = requirement_result.get("requirement_id", "")
    req_name = requirement_result.get("requirement_name", "")
    metric = requirement_result.get("required_metric", "")
    severity = requirement_result.get("severity", "Medium")
    components = requirement_result.get("evidence_components", {})

    why_reasons = []
    if not components.get("metric_present"):
        why_reasons.append(f"The required metric ({metric}) has not been disclosed in the company's reporting.")
    if components.get("metric_present") and not components.get("correct_reporting_period"):
        why_reasons.append("Metric data exists but not for the required reporting period.")
    if not components.get("document_present"):
        why_reasons.append("No supporting documentation (e.g., sustainability report) has been uploaded or linked.")
    if components.get("metric_present") and not components.get("adequate_assurance"):
        why_reasons.append("The disclosed metric has not been independently assured by an external auditor.")
    if components.get("metric_present") and not components.get("evidence_page_present"):
        why_reasons.append("Source page reference is missing, making evidence traceability incomplete.")

    severity_impacts = {
        "Critical": "Non-compliance may result in regulatory enforcement, fines, or loss of market access. Immediate action required.",
        "High": "Significant compliance risk that could trigger regulatory scrutiny or audit findings. Prioritise for next reporting cycle.",
        "Medium": "Moderate risk to compliance posture. Should be addressed within current reporting period.",
        "Low": "Minor disclosure gap with limited regulatory impact. Address as part of continuous improvement.",
    }

    datasets = []
    if not components.get("metric_present"):
        datasets.append({"name": f"esg_metric_data (metric_code: {metric})", "description": f"Upload metric data rows for {metric} covering the relevant reporting year."})
    if not components.get("document_present"):
        datasets.append({"name": "esg_document_register", "description": "Register the sustainability report or relevant disclosure document."})
    if not components.get("adequate_assurance"):
        datasets.append({"name": "Assurance Statement", "description": "Obtain and upload third-party assurance letter or report."})

    docs_needed = [f"{framework_abbr} compliance checklist for {req_name}"]
    if not components.get("document_present"):
        docs_needed.append("Sustainability Report covering the reporting year")
    if not components.get("adequate_assurance"):
        docs_needed.append("Independent assurance report (limited or reasonable)")
    docs_needed.append("Internal review sign-off and evidence log")

    steps = []
    step_num = 1
    if not components.get("metric_present"):
        steps.append(f"{step_num}. Collect raw data for {metric} from operational systems")
        step_num += 1
        steps.append(f"{step_num}. Upload to the Data Collector page as esg_metric_data with metric_code={metric}")
        step_num += 1
    if not components.get("document_present"):
        steps.append(f"{step_num}. Prepare or obtain the required disclosure document and register it in esg_document_register")
        step_num += 1
    if not components.get("adequate_assurance"):
        steps.append(f"{step_num}. Engage an external auditor to provide assurance over the disclosure")
        step_num += 1
    if not components.get("evidence_page_present"):
        steps.append(f"{step_num}. Record the specific page or section reference in the source document")
        step_num += 1
    steps.append(f"{step_num}. Re-run Compliance Analysis to verify the gap is closed")

    return {
        "requirement_id": req_id,
        "requirement_name": req_name,
        "framework": framework_abbr,
        "severity": severity,
        "why_gap_exists": why_reasons if why_reasons else ["Data mapping is incomplete or has not been configured."],
        "impact_assessment": severity_impacts.get(severity, severity_impacts["Medium"]),
        "required_datasets": datasets if datasets else [{"name": "No additional data required", "description": "Review existing data quality and completeness."}],
        "documentation_needed": docs_needed,
        "how_to_close": steps,
    }


# ════════════════════════════════════════════════════════════
#  Audit trail
# ════════════════════════════════════════════════════════════

def log_compliance_action(user, action, framework="", details="", status=""):
    from utils.json_manager import read_json, write_json
    data = read_json("compliance_audit_trail.json")
    entries = data.get("entries", [])
    entries.append({
        "id": f"AUDIT-{len(entries)+1:04d}",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "action": action,
        "framework": framework,
        "details": details,
        "status": status,
    })
    data["entries"] = entries
    write_json("compliance_audit_trail.json", data)


# ════════════════════════════════════════════════════════════
#  Notifications
# ════════════════════════════════════════════════════════════

def create_notification(user, title, message, category="info", framework=""):
    from utils.json_manager import read_json, write_json
    data = read_json("notifications.json")
    notifications = data.get("notifications", [])
    notifications.append({
        "id": f"NOTIF-{len(notifications)+1:04d}",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "title": title,
        "message": message,
        "category": category,
        "framework": framework,
        "read": False,
    })
    data["notifications"] = notifications
    write_json("notifications.json", data)


def get_notifications(user=None, unread_only=False):
    from utils.json_manager import read_json
    data = read_json("notifications.json")
    notifications = data.get("notifications", [])
    if user:
        notifications = [n for n in notifications if n.get("user") == user or n.get("user") == "all"]
    if unread_only:
        notifications = [n for n in notifications if not n.get("read")]
    return sorted(notifications, key=lambda n: n.get("timestamp", ""), reverse=True)


def mark_notification_read(notification_id):
    from utils.json_manager import read_json, write_json
    data = read_json("notifications.json")
    for n in data.get("notifications", []):
        if n["id"] == notification_id:
            n["read"] = True
            break
    write_json("notifications.json", data)


def mark_all_notifications_read(user=None):
    from utils.json_manager import read_json, write_json
    data = read_json("notifications.json")
    for n in data.get("notifications", []):
        if user is None or n.get("user") == user or n.get("user") == "all":
            n["read"] = True
    write_json("notifications.json", data)


def generate_compliance_notifications(all_results, user):
    summary = compute_compliance_summary(all_results)
    gap_data = extract_gap_analysis(all_results)

    critical_gaps = sum(1 for gd in gap_data for g in gd["gaps"] if g["priority"] in ("Critical", "High"))
    if critical_gaps > 0:
        create_notification(
            user,
            f"{critical_gaps} Critical/High Priority Gaps Detected",
            f"Compliance analysis identified {critical_gaps} critical or high priority gap(s) requiring immediate attention.",
            category="critical_gap",
        )

    if summary["overall_compliance"] < 80:
        create_notification(
            user,
            f"Compliance Score Below Threshold: {summary['overall_compliance']:.1f}%",
            "Overall compliance score has dropped below the 80% threshold. Review gap analysis for remediation steps.",
            category="compliance_drop",
        )

    if summary["pending_updates"] > 0:
        create_notification(
            user,
            f"{summary['pending_updates']} Pending Regulatory Updates",
            "New regulatory changes have been detected and require review. Visit the Global Framework Updates tab.",
            category="regulatory_change",
        )


# ════════════════════════════════════════════════════════════
#  Framework updates persistence
# ════════════════════════════════════════════════════════════

def load_framework_updates():
    from utils.json_manager import read_json
    return read_json("framework_updates.json")


def save_framework_updates(data):
    from utils.json_manager import write_json
    write_json("framework_updates.json", data)


def apply_framework_update(update_id, user="system"):
    data = load_framework_updates()
    fw_abbr = ""
    for u in data.get("updates", []):
        if u["update_id"] == update_id:
            u["status"] = "applied"
            u["reviewed_by"] = user
            u["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fw_abbr = u.get("framework_abbr", "")
            break
    audit = data.get("audit_log", [])
    audit.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": "applied",
        "update_id": update_id,
        "user": user,
    })
    data["audit_log"] = audit
    save_framework_updates(data)
    log_compliance_action(user, "Update Applied", framework=fw_abbr, details=f"Update {update_id} applied", status="applied")


def dismiss_framework_update(update_id, user="system"):
    data = load_framework_updates()
    fw_abbr = ""
    for u in data.get("updates", []):
        if u["update_id"] == update_id:
            u["status"] = "dismissed"
            u["reviewed_by"] = user
            u["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fw_abbr = u.get("framework_abbr", "")
            break
    audit = data.get("audit_log", [])
    audit.append({
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": "dismissed",
        "update_id": update_id,
        "user": user,
    })
    data["audit_log"] = audit
    save_framework_updates(data)
    log_compliance_action(user, "Update Dismissed", framework=fw_abbr, details=f"Update {update_id} dismissed", status="dismissed")


def refresh_framework_updates_check():
    data = load_framework_updates()
    data["last_checked"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    save_framework_updates(data)
    log_compliance_action("system", "Updates Refreshed", details="Framework updates check completed")
    return data
