"""
Connection modules for external data sources.
Each connector: connect → list objects/tables → read data → return DataFrame.
Missing libraries produce clear error messages instead of crashes.
"""

import pandas as pd
import io
import json


# ═══════════════════════════════════════════════
#  AWS S3
# ═══════════════════════════════════════════════

def aws_connect(access_key, secret_key, region):
    try:
        import boto3
    except ImportError:
        return None, "boto3 is not installed. Run: pip install boto3"
    try:
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        s3 = session.client("s3")
        s3.list_buckets()
        return session, None
    except Exception as e:
        return None, f"AWS connection failed: {e}"


def aws_list_buckets(session):
    s3 = session.client("s3")
    resp = s3.list_buckets()
    return [b["Name"] for b in resp.get("Buckets", [])]


def aws_list_objects(session, bucket, prefix=""):
    s3 = session.client("s3")
    params = {"Bucket": bucket, "MaxKeys": 200}
    if prefix:
        params["Prefix"] = prefix
    resp = s3.list_objects_v2(**params)
    objects = resp.get("Contents", [])
    supported = (".csv", ".json", ".xlsx", ".xls", ".parquet")
    return [o["Key"] for o in objects if any(o["Key"].lower().endswith(ext) for ext in supported)]


def aws_read_object(session, bucket, key):
    s3 = session.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()
    lower = key.lower()

    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(body))
    elif lower.endswith(".json"):
        return pd.read_json(io.BytesIO(body))
    elif lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(body))
    elif lower.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(body))
    else:
        raise ValueError(f"Unsupported file type: {key}")


# ═══════════════════════════════════════════════
#  AZURE  (Blob Storage / Data Lake)
# ═══════════════════════════════════════════════

def azure_connect(connection_string):
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        return None, "azure-storage-blob is not installed. Run: pip install azure-storage-blob"
    try:
        client = BlobServiceClient.from_connection_string(connection_string)
        client.get_account_information()
        return client, None
    except Exception as e:
        return None, f"Azure connection failed: {e}"


def azure_list_containers(client):
    return [c.name for c in client.list_containers()]


def azure_list_blobs(client, container, prefix=""):
    container_client = client.get_container_client(container)
    blobs = container_client.list_blobs(name_starts_with=prefix if prefix else None)
    supported = (".csv", ".json", ".xlsx", ".xls", ".parquet")
    return [b.name for b in blobs if any(b.name.lower().endswith(ext) for ext in supported)]


def azure_read_blob(client, container, blob_name):
    container_client = client.get_container_client(container)
    blob_data = container_client.download_blob(blob_name).readall()
    lower = blob_name.lower()

    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(blob_data))
    elif lower.endswith(".json"):
        return pd.read_json(io.BytesIO(blob_data))
    elif lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(blob_data))
    elif lower.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(blob_data))
    else:
        raise ValueError(f"Unsupported file type: {blob_name}")


# ═══════════════════════════════════════════════
#  SNOWFLAKE
# ═══════════════════════════════════════════════

def snowflake_connect(account, user, password, warehouse, database, schema="PUBLIC", role=None):
    try:
        import snowflake.connector
    except ImportError:
        return None, "snowflake-connector-python is not installed. Run: pip install snowflake-connector-python"
    try:
        params = dict(
            account=account, user=user, password=password,
            warehouse=warehouse, database=database, schema=schema,
        )
        if role:
            params["role"] = role
        conn = snowflake.connector.connect(**params)
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_VERSION()")
        cur.close()
        return conn, None
    except Exception as e:
        return None, f"Snowflake connection failed: {e}"


def snowflake_list_tables(conn, database, schema="PUBLIC"):
    cur = conn.cursor()
    cur.execute(f"SHOW TABLES IN {database}.{schema}")
    rows = cur.fetchall()
    cur.close()
    return [r[1] for r in rows]


def snowflake_read_table(conn, table, limit=50000):
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} LIMIT {limit}")
    cols = [desc[0] for desc in cur.description]
    data = cur.fetchall()
    cur.close()
    return pd.DataFrame(data, columns=cols)


def snowflake_read_query(conn, query):
    cur = conn.cursor()
    cur.execute(query)
    cols = [desc[0] for desc in cur.description]
    data = cur.fetchall()
    cur.close()
    return pd.DataFrame(data, columns=cols)


# ═══════════════════════════════════════════════
#  DELTA LAKE
# ═══════════════════════════════════════════════

def delta_connect(path, storage_options=None):
    try:
        from deltalake import DeltaTable
    except ImportError:
        return None, "deltalake is not installed. Run: pip install deltalake"
    try:
        dt = DeltaTable(path, storage_options=storage_options)
        return dt, None
    except Exception as e:
        return None, f"Delta Lake connection failed: {e}"


def delta_read(dt):
    return dt.to_pandas()


def delta_schema(dt):
    return dt.schema().to_pyarrow()


# ═══════════════════════════════════════════════
#  GOOGLE SHEETS
# ═══════════════════════════════════════════════

def google_sheets_read(sheet_url, sheet_name=None, cell_range=None, service_key_file=None):
    try:
        import gspread
    except ImportError:
        return None, "gspread is not installed. Run: pip install gspread"

    try:
        sheet_id = sheet_url.strip()
        if "/spreadsheets/d/" in sheet_id:
            sheet_id = sheet_id.split("/spreadsheets/d/")[1].split("/")[0]

        if service_key_file is not None:
            key_data = json.loads(service_key_file.read())
            gc = gspread.service_account_from_dict(key_data)
        else:
            gc = gspread.service_account()

        spreadsheet = gc.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(sheet_name) if sheet_name else spreadsheet.sheet1

        if cell_range:
            data = worksheet.get(cell_range)
            if not data or len(data) < 2:
                return None, "No data found in the specified range."
            df = pd.DataFrame(data[1:], columns=data[0])
        else:
            records = worksheet.get_all_records()
            if not records:
                return None, "Sheet is empty."
            df = pd.DataFrame(records)

        return df, None
    except Exception as e:
        return None, f"Google Sheets read failed: {e}"


# ═══════════════════════════════════════════════
#  REST API
# ═══════════════════════════════════════════════

def rest_api_fetch(url, method="GET", headers_json=None, body_json=None, json_path=None):
    try:
        import requests
    except ImportError:
        return None, "requests is not installed. Run: pip install requests"

    try:
        headers = json.loads(headers_json) if headers_json else {}
        body = json.loads(body_json) if body_json else None

        if method == "POST":
            resp = requests.post(url, headers=headers, json=body, timeout=60)
        else:
            resp = requests.get(url, headers=headers, timeout=60)

        resp.raise_for_status()
        data = resp.json()

        if json_path:
            for key in json_path.split("."):
                if isinstance(data, dict):
                    data = data[key]
                elif isinstance(data, list) and key.isdigit():
                    data = data[int(key)]

        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            df = pd.DataFrame([data])
        else:
            return None, f"Unexpected response type: {type(data).__name__}"

        return df, None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in headers or body: {e}"
    except Exception as e:
        return None, f"REST API request failed: {e}"


# ═══════════════════════════════════════════════
#  BIGQUERY
# ═══════════════════════════════════════════════

def bigquery_query(project_id, query, service_key_file=None, location=None):
    try:
        from google.cloud import bigquery
    except ImportError:
        return None, "google-cloud-bigquery is not installed. Run: pip install google-cloud-bigquery"

    try:
        if service_key_file is not None:
            import tempfile, os
            key_data = service_key_file.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="wb")
            tmp.write(key_data)
            tmp.close()
            client = bigquery.Client.from_service_account_json(tmp.name, project=project_id)
            os.unlink(tmp.name)
        else:
            client = bigquery.Client(project=project_id)

        job_config = bigquery.QueryJobConfig()
        if location:
            job = client.query(query, job_config=job_config, location=location)
        else:
            job = client.query(query, job_config=job_config)

        df = job.to_dataframe()
        return df, None
    except Exception as e:
        return None, f"BigQuery query failed: {e}"


# ═══════════════════════════════════════════════
#  GCS (Google Cloud Storage)
# ═══════════════════════════════════════════════

def gcs_connect(service_key_file=None):
    try:
        from google.cloud import storage
    except ImportError:
        return None, "google-cloud-storage is not installed. Run: pip install google-cloud-storage"

    try:
        if service_key_file is not None:
            import tempfile, os
            key_data = service_key_file.read()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="wb")
            tmp.write(key_data)
            tmp.close()
            client = storage.Client.from_service_account_json(tmp.name)
            os.unlink(tmp.name)
        else:
            client = storage.Client()

        return client, None
    except Exception as e:
        return None, f"GCS connection failed: {e}"


def gcs_list_objects(client, bucket_name, prefix=""):
    bucket = client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=prefix if prefix else None, max_results=200)
    supported = (".csv", ".json", ".xlsx", ".xls", ".parquet")
    return [b.name for b in blobs if any(b.name.lower().endswith(ext) for ext in supported)]


def gcs_read_object(client, bucket_name, blob_name):
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    data = blob.download_as_bytes()
    lower = blob_name.lower()

    if lower.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data))
    elif lower.endswith(".json"):
        return pd.read_json(io.BytesIO(data))
    elif lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    elif lower.endswith(".parquet"):
        return pd.read_parquet(io.BytesIO(data))
    else:
        raise ValueError(f"Unsupported file type: {blob_name}")
