"""
Persistence layer for ESG data categories and ingestion history.

Categories: esg_data, company_data, company_profits, company_expenses
Each dataset stored as: {dataset_id, name, source_type, category, schema, records, row_count, loaded_at, loaded_by}
Ingestion log tracks every load attempt with status.
"""

import json
import os
import hashlib
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")
os.makedirs(DB_DIR, exist_ok=True)

CATEGORIES = ["esg_data", "company_data", "company_profits", "company_expenses"]

_DATA_FILE = os.path.join(DB_DIR, "category_data.json")
_HISTORY_FILE = os.path.join(DB_DIR, "ingestion_history.json")


def _read(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _dataset_id(name, source_type, category):
    raw = f"{name}|{source_type}|{category}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


# ── Schema detection ──

def detect_schema(df):
    schema = []
    type_map = {
        "int64": "integer", "int32": "integer",
        "float64": "float", "float32": "float",
        "bool": "boolean",
        "datetime64[ns]": "datetime",
        "object": "string",
    }
    for col in df.columns:
        dtype = str(df[col].dtype)
        null_count = int(df[col].isnull().sum())
        sample_values = df[col].dropna().head(3).tolist()
        schema.append({
            "column": col,
            "dtype": type_map.get(dtype, dtype),
            "null_count": null_count,
            "null_pct": round(null_count / max(len(df), 1) * 100, 1),
            "sample": [str(v) for v in sample_values],
        })
    return schema


# ── Duplicate check ──

def is_duplicate(name, source_type, category):
    data = _read(_DATA_FILE)
    did = _dataset_id(name, source_type, category)
    datasets = data.get("datasets", [])
    return any(d.get("dataset_id") == did for d in datasets)


# ── Load data into category ──

def load_data(name, source_type, category, df, username):
    did = _dataset_id(name, source_type, category)

    if is_duplicate(name, source_type, category):
        return False, "Dataset already loaded in this category."

    schema = detect_schema(df)
    records = df.to_dict(orient="records")

    entry = {
        "dataset_id": did,
        "name": name,
        "source_type": source_type,
        "category": category,
        "schema": schema,
        "row_count": len(records),
        "col_count": len(schema),
        "loaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "loaded_by": username,
        "records": records,
    }

    data = _read(_DATA_FILE)
    datasets = data.get("datasets", [])
    datasets.append(entry)
    data["datasets"] = datasets
    _write(_DATA_FILE, data)

    add_ingestion_log(name, source_type, category, len(records), "Success", username)

    return True, f"Loaded {len(records)} rows into {category}."


# ── Get datasets ──

def get_datasets(category=None, username=None):
    data = _read(_DATA_FILE)
    datasets = data.get("datasets", [])
    if category:
        datasets = [d for d in datasets if d.get("category") == category]
    if username:
        datasets = [d for d in datasets if d.get("loaded_by") == username]
    result = []
    for d in datasets:
        info = {k: v for k, v in d.items() if k != "records"}
        result.append(info)
    return result


def get_dataset_records(dataset_id):
    data = _read(_DATA_FILE)
    for d in data.get("datasets", []):
        if d.get("dataset_id") == dataset_id:
            return d.get("records", [])
    return []


def remove_dataset(dataset_id):
    data = _read(_DATA_FILE)
    data["datasets"] = [d for d in data.get("datasets", []) if d.get("dataset_id") != dataset_id]
    _write(_DATA_FILE, data)


# ── Ingestion history ──

def add_ingestion_log(name, source_type, category, row_count, status, username, error_msg=None):
    data = _read(_HISTORY_FILE)
    logs = data.get("logs", [])
    logs.append({
        "source_name": name,
        "source_type": source_type,
        "category": category,
        "row_count": row_count,
        "status": status,
        "loaded_by": username,
        "loaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": error_msg,
    })
    data["logs"] = logs
    _write(_HISTORY_FILE, data)


def get_ingestion_history(limit=50):
    data = _read(_HISTORY_FILE)
    logs = data.get("logs", [])
    return logs[-limit:][::-1]


# ── Validate data ──

def validate_data(df):
    issues = []
    if df.empty:
        issues.append("Dataset is empty (0 rows).")
    if len(df.columns) == 0:
        issues.append("No columns detected.")
    dup_cols = df.columns[df.columns.duplicated()].tolist()
    if dup_cols:
        issues.append(f"Duplicate column names: {dup_cols}")
    all_null_cols = [c for c in df.columns if df[c].isnull().all()]
    if all_null_cols:
        issues.append(f"Fully empty columns: {all_null_cols}")
    return issues
