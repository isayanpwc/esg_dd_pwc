"""
Data Registration, Schema Mapping & Validation Agent — backend engine.

Deterministic logic only (no LLM calls):
  register_source, profile_source_schema, infer_primary_keys,
  validate_mapping, compare_schema_versions, run_referential_integrity_checks,
  save_approved_mapping, generate_ingestion_configuration, scoring helpers.

LLM-assisted (called from the view layer):
  identify_target_table, suggest_column_mappings are delegated to the
  Claude API via the view; this module exposes the *prompts* and
  post-processing helpers for those calls.
"""

import hashlib
import json
import os
import re
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")
os.makedirs(DB_DIR, exist_ok=True)

_REGISTRY_FILE = os.path.join(DB_DIR, "source_registry.json")
_PROFILES_FILE = os.path.join(DB_DIR, "schema_profiles.json")
_MAPPINGS_FILE = os.path.join(DB_DIR, "column_mappings.json")


# ════════════════════════════════════════════════════════════
#  JSON helpers
# ════════════════════════════════════════════════════════════

def _read_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ════════════════════════════════════════════════════════════
#  Canonical schema catalogue
# ════════════════════════════════════════════════════════════

CANONICAL_TABLES = {
    "company_master": {
        "description": "Core company dimension table",
        "columns": {
            "company_id": "string",
            "company_name": "string",
            "parent_company": "string",
            "industry": "string",
            "country": "string",
        },
    },
    "company_financials": {
        "description": "Annual financial data per company",
        "columns": {
            "company_id": "string",
            "reporting_year": "integer",
            "annual_revenue": "float",
            "employee_count": "integer",
            "reporting_currency": "string",
        },
    },
    "regulation_master": {
        "description": "Regulatory framework reference data",
        "columns": {
            "regulation_id": "string",
            "regulation_name": "string",
            "jurisdiction": "string",
            "regulatory_body": "string",
            "effective_date": "date",
            "applicable_industry": "string",
            "mandatory_flag": "string",
            "regulation_version": "string",
            "source_url": "string",
        },
    },
    "supplier_master": {
        "description": "Supplier dimension with spend and criticality",
        "columns": {
            "supplier_id": "string",
            "supplier_name": "string",
            "country": "string",
            "tier": "string",
            "annual_spend": "float",
            "spend_currency": "string",
            "criticality": "string",
        },
    },
    "esg_target": {
        "description": "ESG targets and progress tracking",
        "columns": {
            "target_id": "string",
            "deal_id": "string",
            "company_id": "string",
            "metric_code": "string",
            "target_name": "string",
            "target_type": "string",
            "base_year": "integer",
            "base_value": "float",
            "target_year": "integer",
            "target_value": "float",
            "current_value": "float",
            "progress_pct": "float",
            "expected_pct_linear": "float",
            "on_track_flag": "string",
            "sbti_validated_flag": "string",
            "status": "string",
            "evidence_document_id": "string",
        },
    },
    "compliance_assessment": {
        "description": "Compliance assessment records per requirement",
        "columns": {
            "compliance_id": "string",
            "deal_id": "string",
            "company_id": "string",
            "requirement_id": "string",
            "reporting_year": "integer",
            "compliance_status": "string",
            "available_value": "string",
            "gap_description": "string",
            "severity": "string",
            "evidence_document_id": "string",
            "evidence_page": "string",
            "remediation_action": "string",
            "target_date": "string",
        },
    },
    "controversy_record": {
        "description": "ESG controversy / incident log",
        "columns": {
            "controversy_id": "string",
            "company_id": "string",
            "esg_pillar": "string",
            "category": "string",
            "title": "string",
            "description": "string",
            "severity": "string",
            "status": "string",
        },
    },
    "esg_risk_opportunity": {
        "description": "ESG risks and opportunities findings",
        "columns": {
            "finding_id": "string",
            "deal_id": "string",
            "company_id": "string",
            "finding_type": "string",
            "esg_pillar": "string",
            "category": "string",
            "title": "string",
            "description": "string",
            "likelihood_score": "float",
            "impact_score": "float",
            "overall_score": "float",
            "financial_impact": "float",
            "financial_impact_currency": "string",
            "priority": "string",
            "recommendation": "string",
            "status": "string",
        },
    },
    "metric_standard_crosswalk": {
        "description": "Mapping between ESG metrics and reporting standards",
        "columns": {
            "metric_code": "string",
            "standard_name": "string",
            "standard_metric_id": "string",
            "disclosure_requirement": "string",
        },
    },
    "data_value_history": {
        "description": "Time-series ESG metric values",
        "columns": {
            "company_id": "string",
            "metric_code": "string",
            "reporting_year": "integer",
            "value": "float",
            "unit": "string",
        },
    },
    "deal_access_control": {
        "description": "Deal-level access control list",
        "columns": {
            "deal_id": "string",
            "user_id": "string",
            "role": "string",
            "access_level": "string",
        },
    },
    "esg_metric_master": {
        "description": "ESG metric definitions catalogue",
        "columns": {
            "metric_code": "string",
            "metric_name": "string",
            "esg_pillar": "string",
            "category": "string",
            "unit": "string",
            "direction": "string",
            "description": "string",
            "is_intensity": "string",
            "intensity_denominator": "string",
        },
    },
    "esg_metric_data": {
        "description": "Standardised ESG metric observations per company and year",
        "columns": {
            "record_id": "string",
            "deal_id": "string",
            "company_id": "string",
            "metric_code": "string",
            "reporting_year": "integer",
            "value": "float",
            "unit": "string",
            "facility_id": "string",
            "source_document_id": "string",
            "source_page": "integer",
            "confidence_score": "float",
            "data_quality_score": "float",
            "is_estimated": "string",
            "is_audited": "string",
            "human_verified": "string",
            "extraction_method": "string",
        },
    },
    "esg_document_register": {
        "description": "Registry of ESG source documents",
        "columns": {
            "document_id": "string",
            "deal_id": "string",
            "company_id": "string",
            "document_name": "string",
            "document_type": "string",
            "reporting_year": "integer",
            "source_url": "string",
            "upload_date": "date",
            "page_count": "integer",
            "audited_flag": "string",
            "auditor_name": "string",
        },
    },
    "facility_master": {
        "description": "Physical facility dimension table",
        "columns": {
            "facility_id": "string",
            "company_id": "string",
            "facility_name": "string",
            "facility_type": "string",
            "country": "string",
            "city": "string",
            "operational_status": "string",
            "commissioned_year": "integer",
        },
    },
    "regulatory_requirement": {
        "description": "Specific disclosure requirements under each regulation",
        "columns": {
            "requirement_id": "string",
            "regulation_id": "string",
            "requirement_name": "string",
            "requirement_description": "string",
            "required_metric": "string",
            "required_document_type": "string",
            "disclosure_frequency": "string",
            "mandatory_flag": "string",
            "criticality": "string",
        },
    },
    "deal_master": {
        "description": "Deal / engagement dimension table",
        "columns": {
            "deal_id": "string",
            "deal_name": "string",
            "company_id": "string",
            "deal_type": "string",
            "deal_status": "string",
            "start_date": "date",
            "target_close_date": "date",
            "deal_lead": "string",
        },
    },
    "certification": {
        "description": "Certifications held by companies",
        "columns": {
            "certification_id": "string",
            "company_id": "string",
            "certification_name": "string",
            "issuing_body": "string",
            "issue_date": "date",
            "expiry_date": "date",
            "scope": "string",
            "status": "string",
        },
    },
    "legal_penalty": {
        "description": "Regulatory penalties and enforcement actions",
        "columns": {
            "penalty_id": "string",
            "company_id": "string",
            "regulation_id": "string",
            "penalty_type": "string",
            "penalty_amount": "float",
            "penalty_currency": "string",
            "penalty_date": "date",
            "description": "string",
            "status": "string",
            "resolution_date": "date",
        },
    },
}


# ════════════════════════════════════════════════════════════
#  Step 1 — Source registration
# ════════════════════════════════════════════════════════════

def _next_source_id():
    data = _read_json(_REGISTRY_FILE)
    entries = data.get("sources", [])
    if not entries:
        return "SRC_ESG_001"
    nums = []
    for e in entries:
        m = re.search(r"(\d+)$", e.get("source_id", ""))
        if m:
            nums.append(int(m.group(1)))
    return f"SRC_ESG_{max(nums, default=0) + 1:03d}"


def register_source(
    source_name,
    source_type,
    source_location,
    business_domain,
    connection_reference="",
    refresh_frequency="One-time",
    watermark_column="",
    source_owner="",
):
    source_id = _next_source_id()
    record = {
        "source_id": source_id,
        "source_name": source_name,
        "source_type": source_type,
        "source_location": source_location,
        "business_domain": business_domain,
        "connection_reference": connection_reference,
        "refresh_frequency": refresh_frequency,
        "watermark_column": watermark_column,
        "source_owner": source_owner,
        "active_flag": True,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_successful_run": None,
    }
    data = _read_json(_REGISTRY_FILE)
    sources = data.get("sources", [])
    sources.append(record)
    data["sources"] = sources
    _write_json(_REGISTRY_FILE, data)
    return record


def get_registered_sources():
    data = _read_json(_REGISTRY_FILE)
    return data.get("sources", [])


def get_source_by_id(source_id):
    for s in get_registered_sources():
        if s["source_id"] == source_id:
            return s
    return None


def update_source(source_id, updates):
    data = _read_json(_REGISTRY_FILE)
    for s in data.get("sources", []):
        if s["source_id"] == source_id:
            s.update(updates)
            break
    _write_json(_REGISTRY_FILE, data)


# ════════════════════════════════════════════════════════════
#  Step 2 — Schema profiling  (deterministic)
# ════════════════════════════════════════════════════════════

def profile_source_schema(df):
    profiles = []
    total = len(df)
    for col in df.columns:
        series = df[col]
        null_count = int(series.isnull().sum())
        non_null = total - null_count
        distinct = int(series.nunique())
        dup_count = non_null - distinct if non_null > 0 else 0

        inferred = str(series.dtype)
        type_map = {
            "int64": "integer", "int32": "integer",
            "float64": "float", "float32": "float",
            "bool": "boolean", "datetime64[ns]": "datetime",
            "object": "string",
        }
        friendly_type = type_map.get(inferred, inferred)

        samples = series.dropna().head(5).tolist()

        min_val = None
        max_val = None
        date_pattern = None
        numeric_range = None

        if friendly_type in ("integer", "float"):
            numeric = pd.to_numeric(series, errors="coerce")
            min_val = numeric.min()
            max_val = numeric.max()
            if pd.notna(min_val):
                numeric_range = f"{min_val} – {max_val}"
        elif friendly_type == "string":
            sample_str = series.dropna().head(50).astype(str)
            date_re = re.compile(r"^\d{4}-\d{2}-\d{2}")
            if sample_str.str.match(date_re).sum() > len(sample_str) * 0.5:
                friendly_type = "date"
                date_pattern = "YYYY-MM-DD"

        profiles.append({
            "column": col,
            "inferred_type": friendly_type,
            "null_count": null_count,
            "null_pct": round(null_count / max(total, 1) * 100, 1),
            "distinct_count": distinct,
            "uniqueness_pct": round(distinct / max(non_null, 1) * 100, 1),
            "duplicate_count": dup_count,
            "duplicate_pct": round(dup_count / max(total, 1) * 100, 1),
            "min": str(min_val) if min_val is not None and pd.notna(min_val) else None,
            "max": str(max_val) if max_val is not None and pd.notna(max_val) else None,
            "date_pattern": date_pattern,
            "numeric_range": numeric_range,
            "samples": [str(v) for v in samples],
        })
    return profiles


def save_profile(source_id, profiles, row_count):
    data = _read_json(_PROFILES_FILE)
    entries = data.get("profiles", [])
    entries = [e for e in entries if e.get("source_id") != source_id]
    entries.append({
        "source_id": source_id,
        "row_count": row_count,
        "column_count": len(profiles),
        "profiled_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "columns": profiles,
    })
    data["profiles"] = entries
    _write_json(_PROFILES_FILE, data)


def get_profile(source_id):
    data = _read_json(_PROFILES_FILE)
    for p in data.get("profiles", []):
        if p.get("source_id") == source_id:
            return p
    return None


# ════════════════════════════════════════════════════════════
#  Step 2b — Infer primary / foreign keys  (deterministic)
# ════════════════════════════════════════════════════════════

def infer_primary_keys(df, profiles):
    candidates = []
    total = len(df)
    for p in profiles:
        col = p["column"]
        if p["null_count"] == 0 and p["distinct_count"] == total:
            candidates.append(col)
    if not candidates:
        for p in profiles:
            if p["uniqueness_pct"] >= 99.0 and p["null_pct"] == 0:
                candidates.append(p["column"])
    return candidates


def infer_foreign_keys(profiles):
    fk_patterns = {
        "company_id": "company_master.company_id",
        "deal_id": "deal_access_control.deal_id",
        "regulation_id": "regulation_master.regulation_id",
        "supplier_id": "supplier_master.supplier_id",
        "metric_code": "metric_standard_crosswalk.metric_code",
        "requirement_id": "regulation_master.regulation_id",
    }
    found = []
    for p in profiles:
        col = p["column"].lower()
        if col in fk_patterns:
            found.append({
                "column": p["column"],
                "references": fk_patterns[col],
            })
    return found


# ════════════════════════════════════════════════════════════
#  Step 3 — Target table identification  (LLM-assisted)
#  This builds the prompt; the view calls the API.
# ════════════════════════════════════════════════════════════

def build_target_table_prompt(source_name, profiles, sample_records):
    table_descriptions = "\n".join(
        f"- **{name}**: {info['description']}  \n"
        f"  Columns: {', '.join(info['columns'].keys())}"
        for name, info in CANONICAL_TABLES.items()
    )

    col_summary = "\n".join(
        f"- {p['column']} ({p['inferred_type']}, {p['null_pct']}% nulls, "
        f"distinct={p['distinct_count']}, samples={p['samples'][:3]})"
        for p in profiles
    )

    sample_json = json.dumps(sample_records[:3], indent=2, default=str)

    return f"""You are a data-engineering specialist for an ESG data platform.

Given the incoming source **{source_name}** with these columns:
{col_summary}

Sample records:
```json
{sample_json}
```

And the canonical data model with these tables:
{table_descriptions}

Your task:
1. Recommend the SINGLE best-matching canonical target table.
2. State your confidence (0.0–1.0).
3. Give a one-sentence reason.

Respond ONLY with valid JSON (no markdown fences):
{{"recommended_table": "<table_name>", "confidence": 0.XX, "reason": "<one sentence>"}}"""


# ════════════════════════════════════════════════════════════
#  Step 4 — Column mapping  (LLM-assisted)
# ════════════════════════════════════════════════════════════

def build_column_mapping_prompt(source_name, profiles, target_table, sample_records):
    target_info = CANONICAL_TABLES.get(target_table, {})
    target_cols = target_info.get("columns", {})

    col_summary = "\n".join(
        f"- {p['column']} ({p['inferred_type']}, samples={p['samples'][:3]})"
        for p in profiles
    )

    target_summary = "\n".join(
        f"- {col} ({dtype})" for col, dtype in target_cols.items()
    )

    sample_json = json.dumps(sample_records[:3], indent=2, default=str)

    return f"""You are a data-engineering specialist mapping source columns to a canonical ESG schema.

Source: **{source_name}**
Source columns:
{col_summary}

Sample records:
```json
{sample_json}
```

Target table: **{target_table}**
Target columns:
{target_summary}

For EACH source column, produce a mapping. If a source column does not map to any target column, set target_column to null.

Respond ONLY with valid JSON (no markdown fences) — an array of objects:
[
  {{
    "source_column": "<name>",
    "target_table": "{target_table}",
    "target_column": "<name or null>",
    "transformation_rule": "<description or empty string>",
    "mapping_confidence": 0.XX
  }}
]"""


# ════════════════════════════════════════════════════════════
#  Mapping persistence
# ════════════════════════════════════════════════════════════

def _next_mapping_id(existing):
    nums = []
    for m in existing:
        match = re.search(r"(\d+)$", m.get("mapping_id", ""))
        if match:
            nums.append(int(match.group(1)))
    return max(nums, default=0) + 1


def save_mappings(source_id, target_table, mappings, status="Review required"):
    data = _read_json(_MAPPINGS_FILE)
    entries = data.get("mappings", [])

    entries = [e for e in entries if e.get("source_id") != source_id]

    counter = _next_mapping_id(entries)
    for m in mappings:
        m["mapping_id"] = f"MAP_{counter:04d}"
        m["source_id"] = source_id
        m["mapping_status"] = status
        m["approved_by"] = None
        m["approved_at"] = None
        counter += 1
        entries.append(m)

    data["mappings"] = entries
    _write_json(_MAPPINGS_FILE, data)


def get_mappings(source_id):
    data = _read_json(_MAPPINGS_FILE)
    return [m for m in data.get("mappings", []) if m.get("source_id") == source_id]


def approve_mapping(mapping_id, approved_by):
    data = _read_json(_MAPPINGS_FILE)
    for m in data.get("mappings", []):
        if m["mapping_id"] == mapping_id:
            m["mapping_status"] = "Approved"
            m["approved_by"] = approved_by
            m["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(_MAPPINGS_FILE, data)


def approve_all_mappings(source_id, approved_by):
    data = _read_json(_MAPPINGS_FILE)
    for m in data.get("mappings", []):
        if m.get("source_id") == source_id:
            m["mapping_status"] = "Approved"
            m["approved_by"] = approved_by
            m["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(_MAPPINGS_FILE, data)


# ════════════════════════════════════════════════════════════
#  Scoring helpers
# ════════════════════════════════════════════════════════════

def calc_data_quality_score(df, profiles, fk_results=None):
    total = max(len(df), 1)
    total_cols = max(len(profiles), 1)

    total_cells = total * total_cols
    non_null_cells = sum(total - p["null_count"] for p in profiles)
    completeness = non_null_cells / total_cells

    valid_cols = sum(1 for p in profiles if p["null_pct"] < 100)
    validity = valid_cols / total_cols

    avg_uniqueness = sum(p["uniqueness_pct"] for p in profiles) / total_cols / 100

    ref_integrity = 1.0
    if fk_results:
        checks = len(fk_results)
        passed = sum(1 for r in fk_results if r.get("pass", True))
        ref_integrity = passed / max(checks, 1)

    timeliness = 1.0

    dq = (
        0.30 * completeness
        + 0.20 * validity
        + 0.20 * avg_uniqueness
        + 0.20 * ref_integrity
        + 0.10 * timeliness
    )
    return round(dq, 4)


def calc_schema_drift(old_columns, new_columns):
    old_set = set(old_columns)
    new_set = set(new_columns)
    added = new_set - old_set
    removed = old_set - new_set
    changes = len(added) + len(removed)
    pct = round(changes / max(len(old_set), 1) * 100, 1)
    return {
        "added_columns": sorted(added),
        "removed_columns": sorted(removed),
        "drift_pct": pct,
    }


def compare_schema_versions(source_id, new_profiles):
    existing = get_profile(source_id)
    if not existing:
        return None
    old_cols = [c["column"] for c in existing.get("columns", [])]
    new_cols = [c["column"] for c in new_profiles]
    return calc_schema_drift(old_cols, new_cols)


# ════════════════════════════════════════════════════════════
#  Referential integrity checks  (deterministic)
# ════════════════════════════════════════════════════════════

def run_referential_integrity_checks(df, fk_list):
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
    results = []
    for fk in fk_list:
        col = fk["column"]
        ref_parts = fk["references"].split(".")
        ref_table = ref_parts[0]
        ref_col = ref_parts[1] if len(ref_parts) > 1 else ref_parts[0]
        ref_path = os.path.join(UPLOAD_DIR, f"{ref_table}.csv")

        if not os.path.exists(ref_path):
            results.append({
                "column": col,
                "references": fk["references"],
                "pass": None,
                "message": f"Reference file {ref_table}.csv not found",
            })
            continue

        try:
            ref_df = pd.read_csv(ref_path)
            if ref_col not in ref_df.columns:
                results.append({
                    "column": col,
                    "references": fk["references"],
                    "pass": None,
                    "message": f"Column {ref_col} not found in {ref_table}",
                })
                continue

            source_vals = set(df[col].dropna().unique())
            ref_vals = set(ref_df[ref_col].dropna().unique())
            orphans = source_vals - ref_vals
            results.append({
                "column": col,
                "references": fk["references"],
                "pass": len(orphans) == 0,
                "orphan_count": len(orphans),
                "orphan_samples": sorted(str(v) for v in list(orphans)[:5]),
                "message": "OK" if not orphans else f"{len(orphans)} orphan value(s)",
            })
        except Exception as e:
            results.append({
                "column": col,
                "references": fk["references"],
                "pass": None,
                "message": str(e),
            })
    return results


# ════════════════════════════════════════════════════════════
#  Ingestion config generation
# ════════════════════════════════════════════════════════════

def generate_ingestion_configuration(source_id):
    source = get_source_by_id(source_id)
    profile = get_profile(source_id)
    mappings = get_mappings(source_id)
    if not source or not profile or not mappings:
        return None

    target_tables = sorted(set(m.get("target_table", "") for m in mappings if m.get("target_column")))
    mapped = [m for m in mappings if m.get("target_column")]
    unmapped = [m for m in mappings if not m.get("target_column")]

    return {
        "source_id": source_id,
        "source_name": source["source_name"],
        "source_type": source["source_type"],
        "target_tables": target_tables,
        "mapped_columns": len(mapped),
        "unmapped_columns": len(unmapped),
        "mappings": mapped,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ════════════════════════════════════════════════════════════
#  Validate mapping (deterministic checks)
# ════════════════════════════════════════════════════════════

def validate_mapping(mappings):
    warnings = []
    for m in mappings:
        target_table = m.get("target_table")
        target_col = m.get("target_column")
        if not target_col:
            warnings.append(f"Source column '{m['source_column']}' is unmapped")
            continue
        canonical = CANONICAL_TABLES.get(target_table, {}).get("columns", {})
        if target_col not in canonical:
            warnings.append(
                f"'{target_col}' is not in canonical table '{target_table}'"
            )
        conf = m.get("mapping_confidence", 0)
        if conf < 0.75:
            warnings.append(
                f"'{m['source_column']}' → '{target_col}' has low confidence ({conf})"
            )
    return warnings


# ════════════════════════════════════════════════════════════
#  LLM caller  (used by the view)
# ════════════════════════════════════════════════════════════

def call_llm(prompt):
    import requests as _req
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))

    api_url = os.getenv("CLAUDE_API_URL", "")
    api_key = os.getenv("CLAUDE_API_KEY", "")
    model = os.getenv("CLAUDE_MODEL", "vertex_ai.anthropic.claude-opus-4-6")

    if not api_url or not api_key:
        return None, "CLAUDE_API_URL or CLAUDE_API_KEY not set in .env"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
        "temperature": 0.1,
    }

    try:
        resp = _req.post(api_url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        body = resp.json()
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return content.strip(), None
    except Exception as e:
        return None, f"LLM call failed: {e}"


def parse_llm_json(raw_text):
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Auto-Registration Pipeline
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS = {
    "emission": "Environment",
    "carbon": "Environment",
    "ghg": "Environment",
    "energy": "Environment",
    "water": "Environment",
    "waste": "Environment",
    "biodiversity": "Environment",
    "pollution": "Environment",
    "climate": "Environment",
    "employee": "Social",
    "diversity": "Social",
    "safety": "Social",
    "health": "Social",
    "training": "Social",
    "labor": "Social",
    "community": "Social",
    "human_right": "Social",
    "workforce": "Social",
    "governance": "Governance",
    "board": "Governance",
    "audit": "Governance",
    "ethic": "Governance",
    "compliance": "Governance",
    "policy": "Governance",
    "risk": "Governance",
    "stakeholder": "Governance",
    "financial": "Financial",
    "revenue": "Financial",
    "asset": "Financial",
    "liability": "Financial",
    "esg": "ESG",
    "sustainability": "ESG",
    "regulation": "Governance",
}


def _infer_domain(filename):
    name_lower = filename.lower()
    for keyword, domain in _DOMAIN_KEYWORDS.items():
        if keyword in name_lower:
            return domain
    return "General"


def get_unregistered_files():
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    if not os.path.isdir(uploads_dir):
        return []
    registered = _read_json(_REGISTRY_FILE)
    registered_files = set()
    for src in registered.get("sources", []):
        sname = src.get("source_name", "")
        registered_files.add(sname.lower())
        loc = src.get("source_location", "")
        if loc:
            registered_files.add(os.path.basename(loc).lower())
    unregistered = []
    for f in os.listdir(uploads_dir):
        if f.lower().endswith((".csv", ".xlsx", ".xls", ".json", ".parquet")):
            name_no_ext = os.path.splitext(f)[0].lower()
            if f.lower() not in registered_files and name_no_ext not in registered_files:
                unregistered.append(os.path.join(uploads_dir, f))
    return sorted(unregistered)


def _fallback_target_table(source_name, profiles):
    name_lower = source_name.lower()
    best_match = None
    best_score = 0
    for table_key, table_def in CANONICAL_TABLES.items():
        score = 0
        table_lower = table_key.lower().replace("_", " ")
        for word in table_lower.split():
            if word in name_lower:
                score += 2
        if table_def.get("columns"):
            source_cols = {p["column"].lower() for p in profiles}
            canonical_cols = set(c.lower() for c in table_def["columns"].keys())
            overlap = len(source_cols & canonical_cols)
            score += overlap
        if score > best_score:
            best_score = score
            best_match = table_key
    if best_match and best_score >= 2:
        return best_match
    return None


def _fallback_column_mappings(profiles, target_table):
    if target_table not in CANONICAL_TABLES:
        return []
    canonical_cols = CANONICAL_TABLES[target_table].get("columns", {})
    canonical_lower = {k.lower(): k for k in canonical_cols.keys()}
    mappings = []
    for p in profiles:
        src_col = p["column"]
        src_lower = src_col.lower().strip()
        matched_key = None
        if src_lower in canonical_lower:
            matched_key = canonical_lower[src_lower]
        else:
            src_normalized = src_lower.replace(" ", "_").replace("-", "_")
            for canon_lower, canon_original in canonical_lower.items():
                canon_normalized = canon_lower.replace(" ", "_").replace("-", "_")
                if src_normalized == canon_normalized:
                    matched_key = canon_original
                    break
        if matched_key:
            mappings.append({
                "source_column": src_col,
                "target_column": matched_key,
                "transformation_rule": "direct_map",
                "mapping_confidence": 0.85,
            })
        else:
            mappings.append({
                "source_column": src_col,
                "target_column": None,
                "transformation_rule": "unmapped",
                "mapping_confidence": 0.0,
            })
    return mappings


def auto_register_source(filepath, source_owner="System"):
    import pandas as _pd

    result = {
        "status": "pending",
        "steps_completed": [],
        "errors": [],
        "source_id": None,
        "source_name": None,
        "target_table": None,
        "quality_score": None,
        "mappings": [],
    }

    filename = os.path.basename(filepath)
    source_name = os.path.splitext(filename)[0]
    result["source_name"] = source_name
    domain = _infer_domain(filename)

    # Load the file into a DataFrame
    try:
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext == "csv":
            df = _pd.read_csv(filepath)
        elif ext in ("xlsx", "xls"):
            df = _pd.read_excel(filepath)
        elif ext == "json":
            df = _pd.read_json(filepath)
        else:
            result["errors"].append(f"Unsupported file type: {ext}")
            result["status"] = "failed"
            return result
    except Exception as e:
        result["errors"].append(f"Failed to read file: {e}")
        result["status"] = "failed"
        return result

    # Step 1 — Register
    try:
        src = register_source(
            source_name=source_name,
            source_type="CSV File",
            source_location=filepath,
            business_domain=domain,
            refresh_frequency="One-time",
            source_owner=source_owner,
        )
        result["source_id"] = src.get("source_id")
        result["steps_completed"].append("register")
    except Exception as e:
        result["errors"].append(f"Register failed: {e}")
        result["status"] = "failed"
        return result

    # Step 2 — Profile
    try:
        profiles = profile_source_schema(df)
        save_profile(result["source_id"], profiles, len(df))
        result["steps_completed"].append("profile")
    except Exception as e:
        result["errors"].append(f"Profiling failed: {e}")
        result["status"] = "failed"
        return result

    # Step 3 — Target table (LLM with fallback)
    target_table = None
    sample_records = df.head(5).to_dict(orient="records")
    try:
        prompt_text = build_target_table_prompt(source_name, profiles, sample_records)
        raw, err = call_llm(prompt_text)
        if raw and not err:
            parsed = parse_llm_json(raw)
            if parsed and isinstance(parsed, dict):
                target_table = parsed.get("recommended_table") or parsed.get("table")
    except Exception:
        pass
    if not target_table:
        target_table = _fallback_target_table(source_name, profiles)
    if target_table:
        result["target_table"] = target_table
        result["steps_completed"].append("target_table")
    else:
        result["errors"].append("Could not determine target table")
        result["status"] = "failed"
        return result

    # Step 4 — Column mapping (LLM with fallback)
    mappings = []
    try:
        prompt_text = build_column_mapping_prompt(source_name, profiles, target_table, sample_records)
        raw, err = call_llm(prompt_text)
        if raw and not err:
            parsed = parse_llm_json(raw)
            if parsed and isinstance(parsed, list):
                mappings = parsed
    except Exception:
        pass
    if not mappings:
        mappings = _fallback_column_mappings(profiles, target_table)
    result["mappings"] = mappings
    result["steps_completed"].append("column_mapping")

    # Step 5 — Validate
    try:
        save_mappings(result["source_id"], target_table, mappings)
        mapping_warnings = validate_mapping(mappings)
        fk_candidates = infer_foreign_keys(profiles)
        fk_results = run_referential_integrity_checks(df, fk_candidates)
        quality = calc_data_quality_score(df, profiles, fk_results)
        result["quality_score"] = round(quality, 2) if isinstance(quality, (int, float)) else 0
        result["steps_completed"].append("validate")
    except Exception as e:
        result["errors"].append(f"Validation failed: {e}")

    # Step 6 — Approve
    try:
        approve_all_mappings(result["source_id"], source_owner)
        update_source(result["source_id"], {
            "last_successful_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        result["steps_completed"].append("approve")
        result["status"] = "completed"
    except Exception as e:
        result["errors"].append(f"Approval failed: {e}")
        result["status"] = "partial"

    return result
