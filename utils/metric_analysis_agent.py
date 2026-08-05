"""
ESG Metric Analysis Agent — backend engine.

Analyses standardised ESG metrics after source registration and loading.
All functions are deterministic (no LLM calls).

Tools:
  get_metric_records        — filter and retrieve metric observations
  get_metric_definition     — look up a metric's master definition
  validate_metric_units     — check unit compatibility per metric
  calculate_metric_trend    — YoY change, percentage change, CAGR
  calculate_intensity       — emissions/energy/incident intensity ratios
  calculate_target_progress — actual vs expected linear progress
  detect_metric_anomalies   — rule-based, Z-score, MAD anomaly detection
  find_missing_metrics      — identify gaps in expected metric coverage
  get_metric_evidence       — trace a metric value to its source document
  run_full_analysis         — orchestrate all steps for a single metric
"""

import math
import os
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

_QUALITY_FLAGS_THRESHOLDS = {
    "low_confidence": 0.80,
    "low_data_quality": 0.80,
    "yoy_change_threshold_pct": 50.0,
    "zscore_threshold": 2.5,
}


# ════════════════════════════════════════════════════════════
#  Data loaders (cached by caller via st.cache_data)
# ════════════════════════════════════════════════════════════

def _load_csv(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def load_metric_data():
    return _load_csv("esg_metric_data.csv")


def load_metric_master():
    return _load_csv("esg_metric_master.csv")


def load_document_register():
    return _load_csv("esg_document_register.csv")


def load_company_financials():
    return _load_csv("company_financials.csv")


def load_facility_master():
    return _load_csv("facility_master.csv")


def load_esg_targets():
    return _load_csv("esg_target.csv")


def load_metric_crosswalk():
    return _load_csv("metric_standard_crosswalk.csv")


# ════════════════════════════════════════════════════════════
#  Tool 1 — get_metric_records
# ════════════════════════════════════════════════════════════

def get_metric_records(
    deal_id=None,
    company_id=None,
    reporting_year=None,
    esg_pillar=None,
    metric_code=None,
    facility_id=None,
):
    df = load_metric_data()
    if df.empty:
        return df

    master = load_metric_master()

    if deal_id:
        df = df[df["deal_id"] == deal_id]
    if company_id:
        df = df[df["company_id"] == company_id]
    if reporting_year:
        df = df[df["reporting_year"] == int(reporting_year)]
    if metric_code:
        df = df[df["metric_code"] == metric_code]
    if facility_id:
        df = df[df["facility_id"] == facility_id]

    if esg_pillar and not master.empty:
        pillar_codes = master[master["esg_pillar"].str.lower() == esg_pillar.lower()]["metric_code"].tolist()
        df = df[df["metric_code"].isin(pillar_codes)]

    return df.sort_values(["metric_code", "reporting_year"]).reset_index(drop=True)


# ════════════════════════════════════════════════════════════
#  Tool 2 — get_metric_definition
# ════════════════════════════════════════════════════════════

def get_metric_definition(metric_code):
    master = load_metric_master()
    if master.empty:
        return None
    row = master[master["metric_code"] == metric_code]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


# ════════════════════════════════════════════════════════════
#  Tool 3 — validate_metric_units
# ════════════════════════════════════════════════════════════

def validate_metric_units(records_df):
    master = load_metric_master()
    if master.empty or records_df.empty:
        return []

    expected_units = dict(zip(master["metric_code"], master["unit"]))
    issues = []

    for _, row in records_df.iterrows():
        mc = row.get("metric_code", "")
        actual = str(row.get("unit", "")).strip()
        expected = expected_units.get(mc, "")
        if expected and actual.lower() != expected.lower():
            issues.append({
                "record_id": row.get("record_id", ""),
                "metric_code": mc,
                "reporting_year": row.get("reporting_year"),
                "expected_unit": expected,
                "actual_unit": actual,
                "flag": "Incompatible unit",
            })
    return issues


# ════════════════════════════════════════════════════════════
#  Tool 4 — validate_metric_quality  (Step 2 checks)
# ════════════════════════════════════════════════════════════

def validate_metric_quality(records_df):
    if records_df.empty:
        return []

    flags_list = []

    for _, row in records_df.iterrows():
        rid = row.get("record_id", "")
        mc = row.get("metric_code", "")
        year = row.get("reporting_year")
        flags = []

        if pd.isna(row.get("source_document_id")) or str(row.get("source_document_id", "")).strip() == "":
            flags.append("Missing source document")

        if pd.isna(row.get("source_page")) or str(row.get("source_page", "")).strip() == "":
            flags.append("Missing source page")

        conf = row.get("confidence_score")
        if pd.notna(conf) and float(conf) < _QUALITY_FLAGS_THRESHOLDS["low_confidence"]:
            flags.append(f"Low confidence score ({conf})")

        dq = row.get("data_quality_score")
        if pd.notna(dq) and float(dq) < _QUALITY_FLAGS_THRESHOLDS["low_data_quality"]:
            flags.append(f"Low data-quality score ({dq})")

        if str(row.get("is_estimated", "")).strip().lower() == "yes":
            flags.append("Estimated value")

        if str(row.get("is_audited", "")).strip().lower() != "yes":
            flags.append("Unaudited")

        if str(row.get("human_verified", "")).strip().lower() != "yes":
            flags.append("Not human verified")

        status = "Pass" if not flags else "Qualified"
        flags_list.append({
            "record_id": rid,
            "metric_code": mc,
            "reporting_year": year,
            "quality_status": status,
            "quality_flags": flags,
        })
    return flags_list


def _check_duplicates(records_df):
    if records_df.empty:
        return []
    dupes = records_df[records_df.duplicated(
        subset=["company_id", "metric_code", "reporting_year", "facility_id"],
        keep=False,
    )]
    if dupes.empty:
        return []
    return dupes[["record_id", "company_id", "metric_code", "reporting_year"]].to_dict("records")


# ════════════════════════════════════════════════════════════
#  Tool 5 — calculate_metric_trend  (Step 3)
# ════════════════════════════════════════════════════════════

def calculate_metric_trend(company_id, metric_code, facility_id=None):
    records = get_metric_records(company_id=company_id, metric_code=metric_code, facility_id=facility_id)
    if records.empty or len(records) < 2:
        return None

    records = records.sort_values("reporting_year").reset_index(drop=True)
    years = records["reporting_year"].tolist()
    values = records["value"].tolist()

    trends = []
    for i in range(1, len(values)):
        prev_val = values[i - 1]
        curr_val = values[i]
        abs_change = curr_val - prev_val

        if prev_val != 0:
            pct_change = round((abs_change / prev_val) * 100, 2)
        else:
            pct_change = None

        trends.append({
            "from_year": years[i - 1],
            "to_year": years[i],
            "previous_value": prev_val,
            "current_value": curr_val,
            "absolute_change": round(abs_change, 2),
            "yoy_change_pct": pct_change,
        })

    cagr = None
    start_val = values[0]
    end_val = values[-1]
    n_years = years[-1] - years[0]
    if n_years > 0 and start_val > 0 and end_val > 0:
        cagr = round(((end_val / start_val) ** (1 / n_years) - 1) * 100, 2)

    return {
        "company_id": company_id,
        "metric_code": metric_code,
        "period": f"{years[0]}–{years[-1]}",
        "data_points": len(values),
        "latest_yoy_change_pct": trends[-1]["yoy_change_pct"] if trends else None,
        "cagr_pct": cagr,
        "trend_detail": trends,
    }


# ════════════════════════════════════════════════════════════
#  Tool 6 — calculate_intensity  (Step 4)
# ════════════════════════════════════════════════════════════

def calculate_intensity(company_id, reporting_year):
    records = get_metric_records(company_id=company_id, reporting_year=reporting_year)
    financials = load_company_financials()

    if records.empty or financials.empty:
        return {}

    fin_row = financials[
        (financials["company_id"] == company_id)
        & (financials["reporting_year"] == int(reporting_year))
    ]
    if fin_row.empty:
        return {}

    revenue = float(fin_row.iloc[0]["annual_revenue"])
    employees = int(fin_row.iloc[0]["employee_count"])
    currency = fin_row.iloc[0].get("reporting_currency", "")

    def _get_val(mc):
        r = records[records["metric_code"] == mc]
        if r.empty:
            return None
        return float(r.iloc[0]["value"])

    scope1 = _get_val("ENV_SCOPE1")
    scope2 = _get_val("ENV_SCOPE2")
    scope3 = _get_val("ENV_SCOPE3")
    energy = _get_val("ENV_ENERGY")
    data_breaches = _get_val("GOV_DATA_BREACH")

    total_s12 = None
    if scope1 is not None and scope2 is not None:
        total_s12 = scope1 + scope2

    result = {
        "company_id": company_id,
        "reporting_year": int(reporting_year),
        "revenue": revenue,
        "employee_count": employees,
        "currency": currency,
        "intensities": [],
    }

    if total_s12 is not None and revenue > 0:
        result["intensities"].append({
            "name": "Scope 1+2 intensity (tCO2e per M revenue)",
            "value": round(total_s12 / revenue * 1_000_000, 4),
            "numerator": total_s12,
            "denominator": revenue,
        })

    if total_s12 is not None and employees > 0:
        result["intensities"].append({
            "name": "Scope 1+2 per employee (tCO2e)",
            "value": round(total_s12 / employees, 4),
            "numerator": total_s12,
            "denominator": employees,
        })

    if scope3 is not None and revenue > 0:
        result["intensities"].append({
            "name": "Scope 3 intensity (tCO2e per M revenue)",
            "value": round(scope3 / revenue * 1_000_000, 4),
            "numerator": scope3,
            "denominator": revenue,
        })

    if energy is not None and employees > 0:
        result["intensities"].append({
            "name": "Energy per employee (MWh)",
            "value": round(energy / employees, 2),
            "numerator": energy,
            "denominator": employees,
        })

    if data_breaches is not None and employees > 0:
        result["intensities"].append({
            "name": "Data breach incident rate (per 1 000 employees)",
            "value": round(data_breaches / employees * 1000, 4),
            "numerator": data_breaches,
            "denominator": employees,
        })

    return result


# ════════════════════════════════════════════════════════════
#  Tool 7 — calculate_target_progress  (Step 5)
# ════════════════════════════════════════════════════════════

def calculate_target_progress(company_id, metric_code=None, reporting_year=None):
    targets = load_esg_targets()
    if targets.empty:
        return []

    t = targets[targets["company_id"] == company_id]
    if metric_code:
        t = t[t["metric_code"] == metric_code]

    if t.empty:
        return []

    current_year = int(reporting_year) if reporting_year else int(datetime.now().year)
    results = []

    for _, row in t.iterrows():
        base_year = int(row["base_year"])
        target_year = int(row["target_year"])
        base_value = float(row["base_value"])
        target_value = float(row["target_value"])

        metric_records = get_metric_records(company_id=company_id, metric_code=row["metric_code"])
        if not metric_records.empty:
            yr_match = metric_records[metric_records["reporting_year"] == current_year]
            if not yr_match.empty:
                current_value = float(yr_match.iloc[0]["value"])
            else:
                current_value = float(row.get("current_value", 0))
        else:
            current_value = float(row.get("current_value", 0))

        ttype = str(row.get("target_type", "")).lower()

        if ttype in ("net-zero", "absolute") and base_value != target_value:
            if target_value < base_value:
                actual_pct = round((base_value - current_value) / (base_value - target_value) * 100, 1)
            else:
                actual_pct = round((current_value - base_value) / (target_value - base_value) * 100, 1)
        elif ttype == "intensity" and base_value != target_value:
            if target_value < base_value:
                actual_pct = round((base_value - current_value) / (base_value - target_value) * 100, 1)
            else:
                actual_pct = round((current_value - base_value) / (target_value - base_value) * 100, 1)
        else:
            actual_pct = 0.0

        actual_pct = max(0.0, min(actual_pct, 100.0))

        expected_pct = 0.0
        if target_year != base_year:
            expected_pct = round((current_year - base_year) / (target_year - base_year) * 100, 1)
            expected_pct = max(0.0, min(expected_pct, 100.0))

        variance = round(actual_pct - expected_pct, 1)
        if variance >= 5:
            status = "Ahead of linear pathway"
        elif variance >= -5:
            status = "Broadly on track"
        else:
            status = "Behind target"

        results.append({
            "target_id": row.get("target_id"),
            "target_name": row.get("target_name"),
            "metric_code": row["metric_code"],
            "base_year": base_year,
            "base_value": base_value,
            "target_year": target_year,
            "target_value": target_value,
            "current_year": current_year,
            "current_value": round(current_value, 2),
            "actual_progress_pct": actual_pct,
            "expected_progress_pct": expected_pct,
            "variance_pp": variance,
            "target_status": status,
        })

    return results


# ════════════════════════════════════════════════════════════
#  Tool 8 — detect_metric_anomalies  (Step 6)
# ════════════════════════════════════════════════════════════

def detect_metric_anomalies(company_id, metric_code=None):
    if metric_code:
        records = get_metric_records(company_id=company_id, metric_code=metric_code)
    else:
        records = get_metric_records(company_id=company_id)

    if records.empty or len(records) < 2:
        return []

    anomalies = []
    threshold_pct = _QUALITY_FLAGS_THRESHOLDS["yoy_change_threshold_pct"]
    zscore_limit = _QUALITY_FLAGS_THRESHOLDS["zscore_threshold"]

    for mc, group in records.groupby("metric_code"):
        group = group.sort_values("reporting_year").reset_index(drop=True)
        values = group["value"].tolist()
        years = group["reporting_year"].tolist()

        if len(values) < 2:
            continue

        for i in range(1, len(values)):
            prev = values[i - 1]
            curr = values[i]
            if prev != 0:
                pct = abs((curr - prev) / prev * 100)
                if pct > threshold_pct:
                    anomalies.append({
                        "metric_code": mc,
                        "reporting_year": years[i],
                        "method": "Rule-based YoY threshold",
                        "value": curr,
                        "previous_value": prev,
                        "yoy_change_pct": round(pct, 1),
                        "threshold_pct": threshold_pct,
                        "severity": "High" if pct > threshold_pct * 2 else "Medium",
                    })

        if len(values) >= 3:
            mean_val = sum(values) / len(values)
            if len(values) >= 5:
                std_val = (sum((v - mean_val) ** 2 for v in values) / len(values)) ** 0.5
            else:
                sorted_vals = sorted(values)
                median_val = sorted_vals[len(sorted_vals) // 2]
                mad = sorted(abs(v - median_val) for v in values)[len(values) // 2]
                std_val = mad * 1.4826 if mad > 0 else 0

            if std_val > 0:
                for i, v in enumerate(values):
                    if len(values) >= 5:
                        z = (v - mean_val) / std_val
                    else:
                        median_val = sorted(values)[len(values) // 2]
                        z = (v - median_val) / std_val

                    if abs(z) > zscore_limit:
                        already = any(
                            a["metric_code"] == mc
                            and a["reporting_year"] == years[i]
                            for a in anomalies
                        )
                        if not already:
                            anomalies.append({
                                "metric_code": mc,
                                "reporting_year": years[i],
                                "method": "MAD-based Z-score" if len(values) < 5 else "Z-score",
                                "value": v,
                                "z_score": round(z, 2),
                                "threshold": zscore_limit,
                                "severity": "High" if abs(z) > zscore_limit * 1.5 else "Medium",
                            })

    return anomalies


# ════════════════════════════════════════════════════════════
#  Tool 9 — find_missing_metrics
# ════════════════════════════════════════════════════════════

def find_missing_metrics(company_id, reporting_year, esg_pillar=None):
    master = load_metric_master()
    if master.empty:
        return []

    if esg_pillar:
        expected = master[master["esg_pillar"].str.lower() == esg_pillar.lower()]
    else:
        expected = master

    records = get_metric_records(company_id=company_id, reporting_year=reporting_year)
    reported_codes = set(records["metric_code"].tolist()) if not records.empty else set()

    missing = []
    for _, row in expected.iterrows():
        mc = row["metric_code"]
        if mc not in reported_codes:
            missing.append({
                "metric_code": mc,
                "metric_name": row["metric_name"],
                "esg_pillar": row["esg_pillar"],
                "category": row["category"],
                "reporting_year": int(reporting_year),
            })
    return missing


def find_missing_historical_years(company_id, metric_code, expected_start=2020, expected_end=2024):
    records = get_metric_records(company_id=company_id, metric_code=metric_code)
    if records.empty:
        return list(range(expected_start, expected_end + 1))

    reported_years = set(records["reporting_year"].tolist())
    return [y for y in range(expected_start, expected_end + 1) if y not in reported_years]


# ════════════════════════════════════════════════════════════
#  Tool 10 — get_metric_evidence
# ════════════════════════════════════════════════════════════

def get_metric_evidence(record_id=None, company_id=None, metric_code=None, reporting_year=None):
    if record_id:
        data = load_metric_data()
        row = data[data["record_id"] == record_id]
        if row.empty:
            return None
        row = row.iloc[0]
    else:
        records = get_metric_records(company_id=company_id, metric_code=metric_code, reporting_year=reporting_year)
        if records.empty:
            return None
        row = records.iloc[0]

    doc_id = row.get("source_document_id", "")
    doc_register = load_document_register()

    doc_info = None
    if not doc_register.empty and doc_id:
        doc_match = doc_register[doc_register["document_id"] == doc_id]
        if not doc_match.empty:
            doc_info = doc_match.iloc[0].to_dict()

    return {
        "record_id": row.get("record_id"),
        "metric_code": row.get("metric_code"),
        "reporting_year": row.get("reporting_year"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "document_id": doc_id,
        "source_page": row.get("source_page"),
        "confidence_score": row.get("confidence_score"),
        "extraction_method": row.get("extraction_method"),
        "document": doc_info,
    }


# ════════════════════════════════════════════════════════════
#  Orchestrator — run_full_analysis
# ════════════════════════════════════════════════════════════

def run_full_analysis(company_id, metric_code, reporting_year):
    records = get_metric_records(
        company_id=company_id,
        metric_code=metric_code,
        reporting_year=reporting_year,
    )
    if records.empty:
        return {"error": f"No records found for {metric_code} / {company_id} / {reporting_year}"}

    row = records.iloc[0]
    defn = get_metric_definition(metric_code) or {}

    unit_issues = validate_metric_units(records)
    quality = validate_metric_quality(records)
    quality_entry = quality[0] if quality else {}

    trend = calculate_metric_trend(company_id, metric_code)
    latest_yoy = trend["latest_yoy_change_pct"] if trend else None

    intensity = calculate_intensity(company_id, reporting_year)

    target_results = calculate_target_progress(company_id, metric_code, reporting_year)
    target_entry = target_results[0] if target_results else None

    anomalies = detect_metric_anomalies(company_id, metric_code)

    evidence = get_metric_evidence(company_id=company_id, metric_code=metric_code, reporting_year=reporting_year)

    return {
        "metric_code": metric_code,
        "metric_name": defn.get("metric_name", metric_code),
        "esg_pillar": defn.get("esg_pillar", ""),
        "year": int(reporting_year),
        "value": float(row["value"]),
        "unit": row.get("unit", ""),
        "quality_status": quality_entry.get("quality_status", ""),
        "quality_flags": quality_entry.get("quality_flags", []),
        "unit_issues": unit_issues,
        "yoy_change_pct": latest_yoy,
        "cagr_pct": trend["cagr_pct"] if trend else None,
        "trend_period": trend["period"] if trend else None,
        "target_progress_pct": target_entry["actual_progress_pct"] if target_entry else None,
        "expected_progress_pct": target_entry["expected_progress_pct"] if target_entry else None,
        "target_status": target_entry["target_status"] if target_entry else None,
        "anomalies": anomalies,
        "intensity_metrics": intensity.get("intensities", []),
        "evidence": {
            "document_id": evidence.get("document_id") if evidence else None,
            "page": evidence.get("source_page") if evidence else None,
        },
    }


def get_available_companies():
    data = load_metric_data()
    if data.empty:
        return []
    return sorted(data["company_id"].unique().tolist())


def get_available_metrics(company_id=None):
    data = load_metric_data()
    if data.empty:
        return []
    if company_id:
        data = data[data["company_id"] == company_id]
    return sorted(data["metric_code"].unique().tolist())


def get_available_years(company_id=None, metric_code=None):
    data = load_metric_data()
    if data.empty:
        return []
    if company_id:
        data = data[data["company_id"] == company_id]
    if metric_code:
        data = data[data["metric_code"] == metric_code]
    return sorted(data["reporting_year"].unique().tolist())


def get_company_name(company_id):
    cm = _load_csv("company_master.csv")
    if cm.empty:
        return company_id
    row = cm[cm["company_id"] == company_id]
    if row.empty:
        return company_id
    return row.iloc[0].get("company_name", company_id)
