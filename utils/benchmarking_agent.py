"""
ESG Benchmarking Agent — Backend engine.

Compares a target company's ESG performance against industry peers
using a 7-step pipeline:
  Step 1  Select comparable peer group (4-tier hierarchy)
  Step 2  Validate peer comparability
  Step 3  Calculate peer statistics (mean, median, quartiles)
  Step 4  Calculate percentile rank (direction-aware)
  Step 5  Normalise performance (intensity metrics)
  Step 6  Currency normalisation
  Step 7  Classify performance (Leading / Above / Below / Lagging)

Data sources:
  peer_benchmark_data.csv, esg_metric_data.csv, esg_metric_master.csv,
  company_master.csv, company_financials.csv, fx_rate_reference.csv,
  esg_target.csv
"""

import os
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

# ════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════

REGION_MAP = {
    "India": "Asia-Pacific",
    "Switzerland": "Europe",
    "United States": "North America",
    "United Kingdom": "Europe",
    "Germany": "Europe",
    "France": "Europe",
    "Japan": "Asia-Pacific",
    "Australia": "Asia-Pacific",
    "Canada": "North America",
    "Singapore": "Asia-Pacific",
    "China": "Asia-Pacific",
    "Brazil": "Latin America",
}

ADJACENT_INDUSTRIES = {
    "IT Services & Consulting": ["Software & Cloud", "Business Process Outsourcing"],
    "Software & Cloud": ["IT Services & Consulting", "Internet & Digital Services"],
    "Business Process Outsourcing": ["IT Services & Consulting"],
    "Internet & Digital Services": ["Software & Cloud"],
}

PERFORMANCE_BANDS = [
    (75, "Leading"),
    (50, "Above Median"),
    (25, "Below Median"),
    (0,  "Lagging"),
]

MIN_PEERS_DIRECTIONAL = 5
MIN_PEERS_QUARTILE = 10

DUPLICATE_COMPANY_MAP = {
    "COMP002": "COMP101",
    "COMP003": "COMP103",
    "COMP004": "COMP104",
}


# ════════════════════════════════════════════════════════════
#  Data loaders
# ════════════════════════════════════════════════════════════

def _load_csv(filename):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def load_peer_benchmark_data():
    df = _load_csv("peer_benchmark_data.csv")
    if df.empty:
        return df
    rename = {}
    if "peer_company_name" in df.columns and "company_id" not in df.columns:
        company_master = _load_csv("company_master.csv")
        if not company_master.empty and "company_name" in company_master.columns and "company_id" in company_master.columns:
            lookup = dict(zip(company_master["company_name"], company_master["company_id"]))
            df["company_id"] = df["peer_company_name"].map(lookup).fillna(df["peer_company_name"])
        else:
            rename["peer_company_name"] = "company_id"
    if "metric_value" in df.columns and "value" not in df.columns:
        rename["metric_value"] = "value"
    if rename:
        df = df.rename(columns=rename)
    return df


def load_esg_metric_data():
    return _load_csv("esg_metric_data.csv")


def load_metric_master():
    return _load_csv("esg_metric_master.csv")


def load_company_master():
    return _load_csv("company_master.csv")


def load_company_financials():
    return _load_csv("company_financials.csv")


def load_fx_rates():
    return _load_csv("fx_rate_reference.csv")


def load_esg_targets():
    return _load_csv("esg_target.csv")


# ════════════════════════════════════════════════════════════
#  Selector helpers
# ════════════════════════════════════════════════════════════

def get_available_companies():
    metric_data = load_esg_metric_data()
    companies = load_company_master()
    if metric_data.empty or companies.empty:
        return []
    ids_with_data = set(metric_data["company_id"].unique())
    result = []
    for _, row in companies.iterrows():
        if row["company_id"] in ids_with_data:
            result.append({
                "company_id": row["company_id"],
                "company_name": row["company_name"],
                "industry": row.get("industry", ""),
                "country": row.get("country", ""),
            })
    return result


def get_available_metrics(company_id=None):
    masters = load_metric_master()
    if masters.empty:
        return []
    peer_data = load_peer_benchmark_data()
    peer_metrics = set(peer_data["metric_code"].unique()) if not peer_data.empty else set()
    metric_data = load_esg_metric_data()
    company_metrics = set()
    if not metric_data.empty:
        df = metric_data
        if company_id:
            df = df[df["company_id"] == company_id]
        company_metrics = set(df["metric_code"].unique())
    benchmarkable = peer_metrics & company_metrics if company_metrics else peer_metrics
    result = []
    for _, row in masters.iterrows():
        code = row["metric_code"]
        if benchmarkable and code not in benchmarkable:
            continue
        result.append({
            "metric_code": code,
            "metric_name": row["metric_name"],
            "esg_pillar": row.get("esg_pillar", ""),
            "unit": row.get("unit", ""),
            "direction": row.get("direction", "neutral"),
        })
    return result


def get_available_years(company_id=None, metric_code=None):
    metric_data = load_esg_metric_data()
    peer_data = load_peer_benchmark_data()
    if metric_data.empty:
        return []
    df = metric_data
    if company_id:
        df = df[df["company_id"] == company_id]
    if metric_code:
        df = df[df["metric_code"] == metric_code]
    target_years = set(df["reporting_year"].unique())
    if not peer_data.empty:
        pdf = peer_data
        if metric_code:
            pdf = pdf[pdf["metric_code"] == metric_code]
        peer_years = set(pdf["reporting_year"].unique())
        common = target_years & peer_years
        if common:
            return sorted(common, reverse=True)
    return sorted(target_years, reverse=True)


# ════════════════════════════════════════════════════════════
#  Step 1 — Select peer group
# ════════════════════════════════════════════════════════════

def select_peer_group(company_id, metric_code, year):
    companies = load_company_master()
    peer_data = load_peer_benchmark_data()

    if companies.empty or peer_data.empty:
        return {"tier": 0, "tier_label": "No data", "peer_ids": [],
                "peer_count": 0, "description": "No peer data available"}

    target_row = companies[companies["company_id"] == company_id]
    if target_row.empty:
        return {"tier": 0, "tier_label": "Unknown company", "peer_ids": [],
                "peer_count": 0, "description": f"Company {company_id} not found"}

    target_industry = target_row.iloc[0]["industry"]
    target_country = target_row.iloc[0]["country"]
    target_region = REGION_MAP.get(target_country, "Other")

    exclude_ids = {company_id}
    for orig, dup in DUPLICATE_COMPANY_MAP.items():
        if company_id == orig:
            exclude_ids.add(dup)
        elif company_id == dup:
            exclude_ids.add(orig)

    relevant_peers = peer_data[
        (peer_data["metric_code"] == metric_code) &
        (peer_data["reporting_year"] == year) &
        (~peer_data["company_id"].isin(exclude_ids))
    ]

    def _get_peer_ids(candidate_ids):
        matched = relevant_peers[relevant_peers["company_id"].isin(candidate_ids)]
        return list(matched["company_id"].unique())

    # Tier 1: same industry + same country
    tier1_companies = set(
        companies[
            (companies["industry"] == target_industry) &
            (companies["country"] == target_country) &
            (~companies["company_id"].isin(exclude_ids))
        ]["company_id"]
    )
    tier1_ids = _get_peer_ids(tier1_companies)
    if len(tier1_ids) >= 1:
        return {
            "tier": 1,
            "tier_label": "Same industry & country",
            "peer_ids": tier1_ids,
            "peer_count": len(tier1_ids),
            "description": f"{target_industry}, {target_country}, {year}",
        }

    # Tier 2: same industry + same region
    region_countries = [c for c, r in REGION_MAP.items() if r == target_region]
    tier2_companies = set(
        companies[
            (companies["industry"] == target_industry) &
            (companies["country"].isin(region_countries)) &
            (~companies["company_id"].isin(exclude_ids))
        ]["company_id"]
    )
    tier2_ids = _get_peer_ids(tier2_companies)
    if len(tier2_ids) >= 1:
        return {
            "tier": 2,
            "tier_label": "Same industry & region",
            "peer_ids": tier2_ids,
            "peer_count": len(tier2_ids),
            "description": f"{target_industry}, {target_region}, {year}",
        }

    # Tier 3: same industry globally
    tier3_companies = set(
        companies[
            (companies["industry"] == target_industry) &
            (~companies["company_id"].isin(exclude_ids))
        ]["company_id"]
    )
    tier3_ids = _get_peer_ids(tier3_companies)
    if len(tier3_ids) >= 1:
        return {
            "tier": 3,
            "tier_label": "Same industry (global)",
            "peer_ids": tier3_ids,
            "peer_count": len(tier3_ids),
            "description": f"{target_industry}, Global, {year}",
        }

    # Tier 4: adjacent industry
    adj = ADJACENT_INDUSTRIES.get(target_industry, [])
    tier4_companies = set(
        companies[
            (companies["industry"].isin(adj)) &
            (~companies["company_id"].isin(exclude_ids))
        ]["company_id"]
    )
    tier4_ids = _get_peer_ids(tier4_companies)
    return {
        "tier": 4,
        "tier_label": "Adjacent industry",
        "peer_ids": tier4_ids,
        "peer_count": len(tier4_ids),
        "description": f"Adjacent industries ({', '.join(adj)}), {year}",
    }


# ════════════════════════════════════════════════════════════
#  Step 2 — Validate peer comparability
# ════════════════════════════════════════════════════════════

def validate_peer_comparability(peer_records, metric_def, year):
    warnings = []
    limitation = None

    if peer_records.empty:
        return {"is_valid": False, "warnings": ["No peer data found"],
                "peer_count": 0, "limitation": "No peers available"}

    peer_count = len(peer_records)

    bad_unit = peer_records[peer_records["unit"] != metric_def.get("unit", "")]
    if not bad_unit.empty:
        warnings.append(f"{len(bad_unit)} peer(s) have mismatched units")

    bad_year = peer_records[peer_records["reporting_year"] != year]
    if not bad_year.empty:
        warnings.append(f"{len(bad_year)} peer(s) have different reporting year")

    if peer_count >= MIN_PEERS_QUARTILE:
        suitability = "Suitable for quartile analysis"
    elif peer_count >= MIN_PEERS_DIRECTIONAL:
        suitability = "Suitable for directional benchmarking"
    else:
        suitability = "Limited peer set — interpret with caution"
        limitation = f"Only {peer_count} peer(s) — below minimum of {MIN_PEERS_DIRECTIONAL} for reliable benchmarking"

    warnings.append(f"Peer count: {peer_count} — {suitability}")

    return {
        "is_valid": peer_count >= 1,
        "warnings": warnings,
        "peer_count": peer_count,
        "limitation": limitation,
        "suitability": suitability,
    }


# ════════════════════════════════════════════════════════════
#  Step 3 — Calculate peer statistics
# ════════════════════════════════════════════════════════════

def calculate_peer_statistics(peer_values):
    if not peer_values or len(peer_values) == 0:
        return {"mean": 0, "median": 0, "q1": 0, "q3": 0, "iqr": 0,
                "std_dev": 0, "min": 0, "max": 0, "count": 0}

    arr = np.array(peer_values, dtype=float)
    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    return {
        "mean": round(float(np.mean(arr)), 2),
        "median": round(float(np.median(arr)), 2),
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "iqr": round(q3 - q1, 2),
        "std_dev": round(float(np.std(arr)), 2),
        "min": round(float(np.min(arr)), 2),
        "max": round(float(np.max(arr)), 2),
        "count": len(arr),
    }


# ════════════════════════════════════════════════════════════
#  Step 4 — Calculate percentile rank
# ════════════════════════════════════════════════════════════

def calculate_percentile(target_value, peer_values, direction="higher_is_better"):
    if not peer_values or len(peer_values) == 0:
        return 50.0

    arr = np.array(peer_values, dtype=float)

    if direction == "lower_is_better":
        count = np.sum(arr > target_value)
    else:
        count = np.sum(arr < target_value)

    return round(float(count / len(arr) * 100), 1)


# ════════════════════════════════════════════════════════════
#  Step 5 — Normalise performance
# ════════════════════════════════════════════════════════════

def normalise_peer_values(company_id, value, metric_def, year):
    unit = metric_def.get("unit", "")
    financials = load_company_financials()

    if financials.empty:
        return {"normalised_value": None, "normalisation_type": None}

    fin_row = financials[
        (financials["company_id"] == company_id) &
        (financials["reporting_year"] == year)
    ]
    if fin_row.empty:
        return {"normalised_value": None, "normalisation_type": None}

    revenue = fin_row.iloc[0].get("annual_revenue", 0)
    employees = fin_row.iloc[0].get("employee_count", 0)

    if unit in ("tCO2e", "MWh", "megalitres", "tonnes") and revenue > 0:
        rev_millions = revenue / 1_000_000
        return {
            "normalised_value": round(value / rev_millions, 4),
            "normalisation_type": f"{unit} per $M revenue",
        }

    if unit in ("incidents", "per million hours") and employees > 0:
        return {
            "normalised_value": round(value / employees * 1000, 4),
            "normalisation_type": f"per 1,000 employees",
        }

    return {"normalised_value": None, "normalisation_type": None}


# ════════════════════════════════════════════════════════════
#  Step 6 — Currency normalisation
# ════════════════════════════════════════════════════════════

def convert_currency(value, from_currency, to_currency, year):
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
#  Step 7 — Classify performance
# ════════════════════════════════════════════════════════════

def classify_performance(percentile):
    for threshold, label in PERFORMANCE_BANDS:
        if percentile >= threshold:
            return label
    return "Lagging"


def get_performance_color(classification):
    return {
        "Leading": "#059669",
        "Above Median": "#2563EB",
        "Below Median": "#D97706",
        "Lagging": "#DC2626",
    }.get(classification, "#6B7280")


# ════════════════════════════════════════════════════════════
#  Distance from median
# ════════════════════════════════════════════════════════════

def calculate_distance_from_median(target_value, median):
    diff = target_value - median
    if median != 0:
        pct = round(diff / abs(median) * 100, 1)
    else:
        pct = 0
    return {"absolute": round(diff, 2), "percentage": pct}


# ════════════════════════════════════════════════════════════
#  Target comparison
# ════════════════════════════════════════════════════════════

def compare_against_target(company_id, metric_code, year):
    targets = load_esg_targets()
    if targets.empty:
        return None

    match = targets[
        (targets["company_id"] == company_id) &
        (targets["metric_code"] == metric_code)
    ]
    if match.empty:
        return None

    row = match.iloc[0]
    return {
        "target_id": row.get("target_id", ""),
        "target_name": row.get("target_name", ""),
        "target_type": row.get("target_type", ""),
        "base_year": int(row.get("base_year", 0)),
        "base_value": float(row.get("base_value", 0)),
        "target_year": int(row.get("target_year", 0)),
        "target_value": float(row.get("target_value", 0)),
        "current_value": float(row.get("current_value", 0)),
        "progress_pct": float(row.get("progress_pct", 0)),
        "on_track_flag": row.get("on_track_flag", "No"),
        "status": row.get("status", "Unknown"),
    }


# ════════════════════════════════════════════════════════════
#  Historical benchmark (multi-year)
# ════════════════════════════════════════════════════════════

def get_historical_benchmark(company_id, metric_code):
    years = get_available_years(company_id, metric_code)
    results = []
    for yr in years:
        res = run_benchmark(company_id, metric_code, yr)
        if res and res.get("peer_count", 0) > 0:
            results.append(res)
    return results


# ════════════════════════════════════════════════════════════
#  Orchestrator — run full benchmark
# ════════════════════════════════════════════════════════════

def run_benchmark(company_id, metric_code, year):
    metric_data = load_esg_metric_data()
    peer_data = load_peer_benchmark_data()
    masters = load_metric_master()
    companies = load_company_master()

    # Get metric definition
    metric_row = masters[masters["metric_code"] == metric_code]
    if metric_row.empty:
        return None
    metric_def = metric_row.iloc[0].to_dict()
    direction = metric_def.get("direction", "neutral")

    # Get target value
    target_records = metric_data[
        (metric_data["company_id"] == company_id) &
        (metric_data["metric_code"] == metric_code) &
        (metric_data["reporting_year"] == year)
    ]
    if target_records.empty:
        return None
    target_value = float(target_records.iloc[0]["value"])

    # Step 1: select peer group
    peer_group = select_peer_group(company_id, metric_code, year)
    if peer_group["peer_count"] == 0:
        return {
            "metric_code": metric_code,
            "metric_name": metric_def.get("metric_name", ""),
            "year": int(year),
            "target_value": target_value,
            "peer_count": 0,
            "peer_group": peer_group["description"],
            "peer_tier": peer_group["tier"],
            "peer_tier_label": peer_group["tier_label"],
            "peer_median": None,
            "peer_mean": None,
            "q1": None, "q3": None, "iqr": None,
            "percentile": None,
            "performance": "No peers available",
            "distance_from_median": None,
            "distance_pct": None,
            "limitation": "No comparable peers found",
            "peer_details": [],
        }

    # Get peer records
    peer_records = peer_data[
        (peer_data["company_id"].isin(peer_group["peer_ids"])) &
        (peer_data["metric_code"] == metric_code) &
        (peer_data["reporting_year"] == year)
    ]

    # Step 2: validate
    validation = validate_peer_comparability(peer_records, metric_def, year)

    # Step 3: calculate statistics
    peer_values = peer_records["value"].astype(float).tolist()
    stats = calculate_peer_statistics(peer_values)

    # Step 4: calculate percentile
    percentile = calculate_percentile(target_value, peer_values, direction)

    # Step 5: normalisation info
    norm = normalise_peer_values(company_id, target_value, metric_def, year)

    # Step 7: classify
    performance = classify_performance(percentile)

    # Distance from median
    dist = calculate_distance_from_median(target_value, stats["median"])

    # Peer details
    peer_details = []
    for _, pr in peer_records.iterrows():
        comp_row = companies[companies["company_id"] == pr["company_id"]]
        comp_name = comp_row.iloc[0]["company_name"] if not comp_row.empty else pr["company_id"]
        comp_country = comp_row.iloc[0].get("country", "") if not comp_row.empty else ""
        comp_industry = comp_row.iloc[0].get("industry", "") if not comp_row.empty else ""
        peer_details.append({
            "company_id": pr["company_id"],
            "company_name": comp_name,
            "country": comp_country,
            "industry": comp_industry,
            "value": float(pr["value"]),
            "unit": pr["unit"],
        })
    peer_details.sort(key=lambda x: x["value"])

    return {
        "metric_code": metric_code,
        "metric_name": metric_def.get("metric_name", ""),
        "esg_pillar": metric_def.get("esg_pillar", ""),
        "unit": metric_def.get("unit", ""),
        "direction": direction,
        "year": int(year),
        "target_value": target_value,
        "peer_count": stats["count"],
        "peer_group": peer_group["description"],
        "peer_tier": peer_group["tier"],
        "peer_tier_label": peer_group["tier_label"],
        "peer_median": stats["median"],
        "peer_mean": stats["mean"],
        "q1": stats["q1"],
        "q3": stats["q3"],
        "iqr": stats["iqr"],
        "std_dev": stats["std_dev"],
        "peer_min": stats["min"],
        "peer_max": stats["max"],
        "percentile": percentile,
        "performance": performance,
        "distance_from_median": dist["absolute"],
        "distance_pct": dist["percentage"],
        "limitation": validation.get("limitation"),
        "suitability": validation.get("suitability", ""),
        "normalised_value": norm.get("normalised_value"),
        "normalisation_type": norm.get("normalisation_type"),
        "peer_details": peer_details,
    }
# ════════════════════════════════════════════════════════════
#  Peer Distribution Categories
# ════════════════════════════════════════════════════════════

def get_distribution_description(category):
    return {
        "🎯Around You": (
            "Peer companies performing within a similar range as the target company."
        ),
        "🏆Leaders": (
            "Top-performing peer companies leading the distribution."
        ),
        "📉Laggards": (
            "Peer companies performing below the market median."
        ),
        "📊Full Distribution": (
            "Complete peer distribution across all benchmarked companies."
        ),
    }.get(
        category,
        "Complete peer distribution across all benchmarked companies."
    )


def filter_peer_distribution(
    peer_details,
    target_value,
    median,
    q1,
    q3,
    category="📊Full Distribution"
):
    """
    Returns filtered peer set based on selected category.
    """

    if not peer_details:
        return []

    peers = list(peer_details)

    if category == "🏆Leaders":

        return [
            p for p in peers
            if float(p["value"]) >= q3
        ]

    elif category == "📉Laggards":

        return [
            p for p in peers
            if float(p["value"]) <= median
        ]

    elif category == "🎯Around You":

        tolerance = abs(target_value) * 0.20

        return [
            p for p in peers
            if abs(float(p["value"]) - target_value)
            <= tolerance
        ]

    return peers


def run_benchmark_summary(company_id, year):
    metrics = get_available_metrics()
    results = []
    for m in metrics:
        res = run_benchmark(company_id, m["metric_code"], year)
        if res and res.get("peer_count", 0) > 0:
            results.append(res)
    return results
