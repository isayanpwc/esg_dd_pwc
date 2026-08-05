import streamlit as st
import pandas as pd
import os
from datetime import datetime
from utils.auth import get_current_user
from utils.json_manager import save_datasource, get_datasources, remove_datasource, add_audit_log
from utils.data_store import (
    CATEGORIES, detect_schema, validate_data, is_duplicate,
    load_data, get_datasets, get_ingestion_history, add_ingestion_log,
    remove_dataset, get_dataset_records,
)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

_CAT_LABELS = {
    "esg_data": "ESG Data",
    "company_data": "Company Data",
    "company_profits": "Company Profits",
    "company_expenses": "Company Expenses",
}


def render():
    top_tabs = st.tabs([
        "ƒ  Connect Data Sources",
        "●  Run Collection",
    ])

    with top_tabs[0]:
        _connect_data_sources_page()
    with top_tabs[1]:
        _run_collection_page()


# ═══════════════════════════════════════════════════════════
#  CONNECT DATA SOURCES PAGE
# ═══════════════════════════════════════════════════════════

def _connect_data_sources_page():
    st.markdown(
        '<div style="margin-bottom:6px;">'
        '<h2 style="margin:0; font-size:1.55rem; font-weight:700; color:#111827;">Connect Your ESG Data</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:6px 0 8px 0; line-height:1.6;">'
        'Upload files, connect to cloud storage, or fetch from APIs. '
        'The system auto-detects the ESG schema and maps columns.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="background:#FFF7F2; border:1px solid #FFE4D0; border-radius:12px; '
        'padding:14px 18px; margin-bottom:18px; display:flex; align-items:flex-start; gap:10px;">'
        '<span style="font-size:1.1rem; flex-shrink:0;">&#128161;</span>'
        '<div style="font-size:0.84rem; color:#92400E; line-height:1.55;">'
        '<b>How it works:</b> '
        '1. Enter a name for your data source below. '
        '2. Choose a connector tab (start with <b>File Upload</b> for CSV/Excel). '
        '3. Click <b>Test & Preview</b> to validate. '
        '4. Click <b>Save & Connect</b> to load the data into the platform.</div></div>',
        unsafe_allow_html=True,
    )

    ds_name = st.text_input(
        "Data Source Name",
        key="ds_global_name",
        placeholder="e.g. My Emissions Data",
        help="Give this data source a descriptive name so you can find it later",
    )

    connector_tabs = st.tabs([
        "📁 File Upload",
        "📊 Google Sheets",
        "🌐 REST API",
        "☁️ AWS S3",
        "◆ BigQuery",
        "◇ GCS",
        "● Azure Blob",
        "▲ Delta Lake",
        "❄️ Snowflake",
    ])

    with connector_tabs[0]:
        _file_upload_connector(ds_name)
    with connector_tabs[1]:
        _google_sheets_connector(ds_name)
    with connector_tabs[2]:
        _rest_api_connector(ds_name)
    with connector_tabs[3]:
        _aws_connector(ds_name)
    with connector_tabs[4]:
        _bigquery_connector(ds_name)
    with connector_tabs[5]:
        _gcs_connector(ds_name)
    with connector_tabs[6]:
        _azure_connector(ds_name)
    with connector_tabs[7]:
        _delta_lake_connector(ds_name)
    with connector_tabs[8]:
        _snowflake_connector(ds_name)



# ═══════════════════════════════════════════════════════════
#  SHARED HELPERS
# ═══════════════════════════════════════════════════════════

def _connector_desc(text):
    st.markdown(
        f'<p style="color:#6B7280; font-size:0.88rem; margin:4px 0 18px 0; line-height:1.55;">{text}</p>',
        unsafe_allow_html=True,
    )


def _show_schema(df):
    schema = detect_schema(df)
    st.markdown("**Schema Detection**")
    schema_df = pd.DataFrame(schema)
    schema_df.columns = ["Column", "Type", "Nulls", "Null %", "Samples"]
    st.dataframe(schema_df, use_container_width=True, hide_index=True)
    return schema


def _show_preview(df, label="Data Preview"):
    st.markdown(f"**{label}** — {len(df):,} rows × {len(df.columns)} columns")
    st.dataframe(df.head(50), use_container_width=True, hide_index=True)


def _show_validation(df):
    issues = validate_data(df)
    if issues:
        for issue in issues:
            st.warning(issue)
        return False
    st.success("Data validation passed.")
    return True


def _connection_status_badge(success, message=None):
    if success:
        st.markdown(
            '<div style="background:#f0fdf4; border:1px solid #86efac; border-radius:10px; '
            'padding:10px 16px; margin:8px 0;">'
            '<span style="color:#16a34a; font-weight:600;">● Connected</span>'
            f'{"  —  " + message if message else ""}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#fef2f2; border:1px solid #fca5a5; border-radius:10px; '
            'padding:10px 16px; margin:8px 0;">'
            f'<span style="color:#dc2626; font-weight:600;">● Failed</span>'
            f'{"  —  " + message if message else ""}</div>',
            unsafe_allow_html=True,
        )


def _do_load(name, source_type, category, df):
    user = get_current_user()
    if is_duplicate(name, source_type, category):
        st.error(f"Dataset '{name}' already loaded in {_CAT_LABELS.get(category, category)}. Remove it first to reload.")
        return False

    ok, msg = load_data(name, source_type, category, df, user)
    if ok:
        add_audit_log(user, f"Data Loaded: {name} -> {category} ({len(df)} rows)")
        st.success(msg)
        return True
    else:
        add_ingestion_log(name, source_type, category, 0, "Failed", user, msg)
        st.error(msg)
        return False


def _save_and_connect(ds_name, source_type, config, df, state_prefix):
    user = get_current_user()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    save_datasource({
        "user": user,
        "datasource_name": ds_name,
        "type": source_type,
        "config": config,
        "status": "Connected",
        "created_at": created_at,
    })

    ok = _do_load(ds_name, source_type, "esg_data", df)
    if ok:
        st.session_state[f"{state_prefix}_connected"] = True
        st.session_state[f"{state_prefix}_connected_name"] = ds_name
        st.session_state[f"{state_prefix}_connected_at"] = created_at
        _connection_status_badge(True, f"{ds_name} saved and loaded successfully")
        add_audit_log(user, f"Data Source Connected: {ds_name} ({source_type})")
    return ok


def _read_uploaded_file(uploaded):
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded)
    elif name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    elif name.endswith(".json"):
        return pd.read_json(uploaded)
    return None


def _coming_soon(label):
    st.markdown(
        f'<div style="text-align:center; padding:48px 20px;">'
        f'<div style="font-size:2.5rem; margin-bottom:12px;">🔒</div>'
        f'<div style="font-size:1.1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
        f'{label} Connector</div>'
        f'<div style="color:#9CA3AF; font-size:0.88rem;">Coming soon. '
        f'This connector is under development.</div></div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════
#  FILE UPLOAD CONNECTOR
# ═══════════════════════════════════════════════════════════

def _file_upload_connector(ds_name):
    _connector_desc("Upload CSV, Excel, or JSON files. Supported formats: .csv, .xlsx, .xls, .json (max 200 MB per file).")

    uploaded = st.file_uploader(
        "Choose a file",
        type=["csv", "xlsx", "xls", "json"],
        key="fu_file",
        help="200MB per file - CSV, XLSX, XLS, JSON",
        label_visibility="collapsed",
    )

    if uploaded:
        size_mb = uploaded.size / (1024 * 1024)
        if size_mb > 200:
            st.error("File exceeds 200 MB limit.")
            return

        st.caption(f"{uploaded.name} — {size_mb:.2f} MB")

    if st.button("Test & Preview", key="fu_test", use_container_width=False):
        if not uploaded:
            st.error("Please upload a file first.")
            return

        try:
            size_mb = uploaded.size / (1024 * 1024)
            df = _read_uploaded_file(uploaded)
            if df is None:
                st.error("Could not read file. Unsupported format.")
                return

            st.session_state["fu_preview_df"] = df
            st.session_state["fu_preview_name"] = uploaded.name
            st.session_state["fu_preview_size"] = size_mb
            st.session_state.pop("fu_connected", None)
        except Exception as e:
            st.error(f"Error reading file: {e}")
            return

    if "fu_preview_df" in st.session_state and "fu_connected" not in st.session_state:
        df = st.session_state["fu_preview_df"]
        st.markdown("---")
        _show_schema(df)
        _show_preview(df)
        valid = _show_validation(df)

        st.markdown("---")
        name = ds_name or st.session_state.get("fu_preview_name", "Uploaded File")

        if st.button("Save & Connect", key="fu_save", type="primary"):
            if not valid:
                st.warning("Data has validation issues. Saving anyway...")

            file_path = os.path.join(UPLOAD_DIR, st.session_state["fu_preview_name"])
            if uploaded:
                uploaded.seek(0)
                with open(file_path, "wb") as f:
                    f.write(uploaded.getbuffer())

            config = {
                "filename": st.session_state["fu_preview_name"],
                "size_mb": round(st.session_state.get("fu_preview_size", 0), 2),
                "path": file_path,
            }
            _save_and_connect(name, "File Upload", config, df, "fu")

    if st.session_state.get("fu_connected"):
        _show_inline_connected_status(
            st.session_state.get("fu_connected_name", ""),
            "File Upload",
            "fu",
        )


# ═══════════════════════════════════════════════════════════
#  GOOGLE SHEETS CONNECTOR
# ═══════════════════════════════════════════════════════════

def _google_sheets_connector(ds_name):
    _connector_desc(
        "Connect to a Google Spreadsheet using a service account key. "
        "Paste the sheet URL or ID and optionally pick a worksheet and cell range."
    )

    sheet_url = st.text_input(
        "Sheet URL or ID", key="gs_url",
        placeholder="https://docs.google.com/spreadsheets/d/1aBcDe.../edit  or  1aBcDe...",
    )

    service_key = st.file_uploader(
        "Service Account Key (JSON)", type=["json"], key="gs_key",
        help="Upload the JSON key file for your Google service account. "
             "Leave empty to use application-default credentials.",
    )

    c1, c2 = st.columns(2)
    with c1:
        sheet_name = st.text_input(
            "Worksheet Name (optional)", key="gs_sheet",
            placeholder="Sheet1",
        )
    with c2:
        cell_range = st.text_input(
            "Cell Range (optional)", key="gs_range",
            placeholder="A1:Z1000",
        )

    if st.button("Test & Preview", key="gs_test"):
        if not sheet_url:
            st.error("Sheet URL or ID is required.")
            return

        from utils.connectors import google_sheets_read
        df, err = google_sheets_read(
            sheet_url,
            sheet_name=sheet_name or None,
            cell_range=cell_range or None,
            service_key_file=service_key,
        )
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(
                ds_name or "Google Sheets", "Google Sheets", "esg_data",
                0, "Failed", get_current_user(), err,
            )
            return

        _connection_status_badge(True, "Google Sheets connected")
        st.session_state["gs_df"] = df
        st.session_state.pop("gs_connected", None)

        _show_schema(df)
        _show_preview(df)
        _show_validation(df)

    if "gs_df" in st.session_state and "gs_connected" not in st.session_state:
        st.markdown("---")
        name = ds_name or "Google Sheet"

        if st.button("Save & Connect", key="gs_save", type="primary"):
            config = {
                "sheet_url": sheet_url,
                "sheet_name": sheet_name or "",
                "cell_range": cell_range or "",
            }
            _save_and_connect(name, "Google Sheets", config, st.session_state["gs_df"], "gs")

    if st.session_state.get("gs_connected"):
        _show_inline_connected_status(
            st.session_state.get("gs_connected_name", ""),
            "Google Sheets",
            "gs",
        )


# ═══════════════════════════════════════════════════════════
#  REST API CONNECTOR
# ═══════════════════════════════════════════════════════════

def _rest_api_connector(ds_name):
    _connector_desc(
        "Fetch data from a REST API endpoint. The response must be JSON. "
        "Use the JSON path to drill into nested responses (e.g. <code>data.results</code>)."
    )

    api_url = st.text_input(
        "Endpoint URL", key="ra_url",
        placeholder="https://api.example.com/v1/esg-data",
    )

    method = st.selectbox("HTTP Method", ["GET", "POST"], key="ra_method")

    headers_json = st.text_area(
        "Headers (JSON, optional)", key="ra_headers",
        placeholder='{"Authorization": "Bearer <token>", "Content-Type": "application/json"}',
        height=80,
    )

    if method == "POST":
        body_json = st.text_area(
            "Request Body (JSON)", key="ra_body",
            placeholder='{"filters": {"year": 2024}}',
            height=80,
        )
    else:
        body_json = None

    json_path = st.text_input(
        "JSON Path (optional)", key="ra_jpath",
        placeholder="data.results",
        help="Dot-notation path to the array inside the response, e.g. data.items",
    )

    if st.button("Test & Preview", key="ra_test"):
        if not api_url:
            st.error("Endpoint URL is required.")
            return

        from utils.connectors import rest_api_fetch
        df, err = rest_api_fetch(
            api_url,
            method=method,
            headers_json=headers_json or None,
            body_json=body_json or None,
            json_path=json_path or None,
        )
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(
                ds_name or "REST API", "REST API", "esg_data",
                0, "Failed", get_current_user(), err,
            )
            return

        _connection_status_badge(True, f"API responded — {len(df)} record(s)")
        st.session_state["ra_df"] = df
        st.session_state.pop("ra_connected", None)

        _show_schema(df)
        _show_preview(df)
        _show_validation(df)

    if "ra_df" in st.session_state and "ra_connected" not in st.session_state:
        st.markdown("---")
        name = ds_name or "REST API Data"

        if st.button("Save & Connect", key="ra_save", type="primary"):
            config = {
                "url": api_url,
                "method": method,
                "json_path": json_path or "",
            }
            _save_and_connect(name, "REST API", config, st.session_state["ra_df"], "ra")

    if st.session_state.get("ra_connected"):
        _show_inline_connected_status(
            st.session_state.get("ra_connected_name", ""),
            "REST API",
            "ra",
        )


# ═══════════════════════════════════════════════════════════
#  AWS S3 CONNECTOR
# ═══════════════════════════════════════════════════════════

def _aws_connector(ds_name):
    _connector_desc(
        "Connect to an AWS S3 bucket to discover and load data files into the ESG pipeline."
    )

    c1, c2 = st.columns(2)
    with c1:
        access_key = st.text_input("Access Key ID", key="aws_ak", placeholder="AKIA...")
    with c2:
        secret_key = st.text_input("Secret Access Key", type="password", key="aws_sk")
    region = st.text_input("Region", key="aws_region", placeholder="us-east-1", value="us-east-1")

    bucket_name = st.text_input("Bucket Name (optional)", key="aws_bucket_input", placeholder="my-esg-bucket")
    prefix = st.text_input("File Prefix (optional)", key="aws_prefix", placeholder="data/esg/")

    if st.button("Test & Preview", key="aws_test"):
        if not access_key or not secret_key:
            st.error("Access Key and Secret Key are required.")
            return

        from utils.connectors import aws_connect, aws_list_buckets
        session, err = aws_connect(access_key, secret_key, region)
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(ds_name or "AWS", "AWS S3", "esg_data", 0, "Failed", get_current_user(), err)
            return

        _connection_status_badge(True, "AWS credentials verified")
        st.session_state["aws_session"] = session
        buckets = aws_list_buckets(session)
        st.session_state["aws_buckets"] = buckets
        st.info(f"Found {len(buckets)} bucket(s): {', '.join(buckets[:10])}")
        st.session_state.pop("aws_connected", None)

    if "aws_session" in st.session_state and "aws_buckets" in st.session_state and "aws_connected" not in st.session_state:
        session = st.session_state["aws_session"]
        buckets = st.session_state["aws_buckets"]

        if not buckets:
            st.warning("No buckets found.")
            return

        bucket = st.selectbox("Select Bucket", buckets, key="aws_bucket")

        if st.button("List Files", key="aws_list"):
            from utils.connectors import aws_list_objects
            objects = aws_list_objects(session, bucket, prefix)
            st.session_state["aws_objects"] = objects
            if objects:
                st.success(f"Found {len(objects)} supported file(s).")
            else:
                st.warning("No supported files found (csv, json, xlsx, parquet).")

        if "aws_objects" in st.session_state and st.session_state["aws_objects"]:
            obj_key = st.selectbox("Select File", st.session_state["aws_objects"], key="aws_obj")

            if st.button("Read & Preview", key="aws_read"):
                try:
                    from utils.connectors import aws_read_object
                    df = aws_read_object(session, bucket, obj_key)
                    st.session_state["aws_df"] = df
                    _show_schema(df)
                    _show_preview(df)
                    _show_validation(df)
                except Exception as e:
                    st.error(f"Failed to read file: {e}")

            if "aws_df" in st.session_state:
                st.markdown("---")
                name = ds_name or obj_key.split("/")[-1]

                if st.button("Save & Connect", key="aws_save", type="primary"):
                    config = {"bucket": bucket, "key": obj_key, "region": region}
                    _save_and_connect(name, "AWS S3", config, st.session_state["aws_df"], "aws")

    if st.session_state.get("aws_connected"):
        _show_inline_connected_status(
            st.session_state.get("aws_connected_name", ""),
            "AWS S3",
            "aws",
        )


# ═══════════════════════════════════════════════════════════
#  BIGQUERY CONNECTOR
# ═══════════════════════════════════════════════════════════

def _bigquery_connector(ds_name):
    _connector_desc(
        "Run a SQL query against Google BigQuery. Results are streamed into the ESG pipeline."
    )

    project_id = st.text_input(
        "GCP Project ID", key="bq_project",
        placeholder="my-gcp-project-123",
    )

    service_key = st.file_uploader(
        "Service Account Key (JSON)", type=["json"], key="bq_key",
        help="Upload the JSON key file for your Google service account. "
             "Leave empty to use application-default credentials.",
    )

    location = st.text_input(
        "Location (optional)", key="bq_location",
        placeholder="US",
        help="BigQuery dataset location, e.g. US, EU, us-central1",
    )

    query = st.text_area(
        "SQL Query", key="bq_query",
        placeholder="SELECT * FROM `project.dataset.table` LIMIT 10000",
        height=120,
    )

    if st.button("Test & Preview", key="bq_test"):
        if not project_id:
            st.error("GCP Project ID is required.")
            return
        if not query or not query.strip():
            st.error("SQL Query is required.")
            return

        from utils.connectors import bigquery_query
        df, err = bigquery_query(
            project_id, query,
            service_key_file=service_key,
            location=location or None,
        )
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(
                ds_name or "BigQuery", "BigQuery", "esg_data",
                0, "Failed", get_current_user(), err,
            )
            return

        _connection_status_badge(True, f"Query returned {len(df):,} row(s)")
        st.session_state["bq_df"] = df
        st.session_state.pop("bq_connected", None)

        _show_schema(df)
        _show_preview(df)
        _show_validation(df)

    if "bq_df" in st.session_state and "bq_connected" not in st.session_state:
        st.markdown("---")
        name = ds_name or "BigQuery Query"

        if st.button("Save & Connect", key="bq_save", type="primary"):
            config = {
                "project_id": project_id,
                "query": query,
                "location": location or "",
            }
            _save_and_connect(name, "BigQuery", config, st.session_state["bq_df"], "bq")

    if st.session_state.get("bq_connected"):
        _show_inline_connected_status(
            st.session_state.get("bq_connected_name", ""),
            "BigQuery",
            "bq",
        )


# ═══════════════════════════════════════════════════════════
#  GCS CONNECTOR
# ═══════════════════════════════════════════════════════════

def _gcs_connector(ds_name):
    _connector_desc(
        "Connect to a Google Cloud Storage bucket to discover and load data files into the ESG pipeline."
    )

    service_key = st.file_uploader(
        "Service Account Key (JSON)", type=["json"], key="gcs_key",
        help="Upload the JSON key file for your Google service account. "
             "Leave empty to use application-default credentials.",
    )

    bucket_name = st.text_input(
        "Bucket Name", key="gcs_bucket_input",
        placeholder="my-esg-data-bucket",
    )
    prefix = st.text_input(
        "File Prefix (optional)", key="gcs_prefix",
        placeholder="reports/2024/",
    )

    if st.button("Test & Preview", key="gcs_test"):
        if not bucket_name:
            st.error("Bucket Name is required.")
            return

        from utils.connectors import gcs_connect, gcs_list_objects
        client, err = gcs_connect(service_key_file=service_key)
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(
                ds_name or "GCS", "GCS", "esg_data",
                0, "Failed", get_current_user(), err,
            )
            return

        _connection_status_badge(True, "GCS credentials verified")
        st.session_state["gcs_client"] = client
        st.session_state["gcs_bucket"] = bucket_name

        try:
            objects = gcs_list_objects(client, bucket_name, prefix)
            st.session_state["gcs_objects"] = objects
            if objects:
                st.success(f"Found {len(objects)} supported file(s).")
            else:
                st.warning("No supported files found (csv, json, xlsx, parquet).")
        except Exception as e:
            st.error(f"Failed to list objects: {e}")
            return

        st.session_state.pop("gcs_connected", None)

    if "gcs_client" in st.session_state and "gcs_objects" in st.session_state and "gcs_connected" not in st.session_state:
        client = st.session_state["gcs_client"]
        objects = st.session_state["gcs_objects"]
        bucket = st.session_state.get("gcs_bucket", bucket_name)

        if not objects:
            st.warning("No files available to read.")
            return

        obj_key = st.selectbox("Select File", objects, key="gcs_obj")

        if st.button("Read & Preview", key="gcs_read"):
            try:
                from utils.connectors import gcs_read_object
                df = gcs_read_object(client, bucket, obj_key)
                st.session_state["gcs_df"] = df
                _show_schema(df)
                _show_preview(df)
                _show_validation(df)
            except Exception as e:
                st.error(f"Failed to read file: {e}")

        if "gcs_df" in st.session_state:
            st.markdown("---")
            name = ds_name or obj_key.split("/")[-1]

            if st.button("Save & Connect", key="gcs_save", type="primary"):
                config = {"bucket": bucket, "key": obj_key}
                _save_and_connect(name, "GCS", config, st.session_state["gcs_df"], "gcs")

    if st.session_state.get("gcs_connected"):
        _show_inline_connected_status(
            st.session_state.get("gcs_connected_name", ""),
            "GCS",
            "gcs",
        )


# ═══════════════════════════════════════════════════════════
#  AZURE BLOB CONNECTOR
# ═══════════════════════════════════════════════════════════

def _azure_connector(ds_name):
    _connector_desc(
        "Connect to Azure Blob Storage to browse containers and load data files."
    )

    conn_string = st.text_input(
        "Connection String", type="password", key="az_conn",
        placeholder="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=...",
    )

    if st.button("Test & Preview", key="az_test"):
        if not conn_string:
            st.error("Connection String is required.")
            return

        from utils.connectors import azure_connect, azure_list_containers
        client, err = azure_connect(conn_string)
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(ds_name or "Azure", "Azure", "esg_data", 0, "Failed", get_current_user(), err)
            return

        _connection_status_badge(True, "Azure Storage connected")
        st.session_state["az_client"] = client
        containers = azure_list_containers(client)
        st.session_state["az_containers"] = containers
        st.info(f"Found {len(containers)} container(s): {', '.join(containers[:10])}")
        st.session_state.pop("az_connected", None)

    if "az_client" in st.session_state and "az_containers" in st.session_state and "az_connected" not in st.session_state:
        client = st.session_state["az_client"]
        containers = st.session_state["az_containers"]

        if not containers:
            st.warning("No containers found.")
            return

        container = st.selectbox("Select Container", containers, key="az_container")
        blob_prefix = st.text_input("Blob Prefix (optional)", key="az_prefix", placeholder="reports/2024/")

        if st.button("List Files", key="az_list"):
            from utils.connectors import azure_list_blobs
            blobs = azure_list_blobs(client, container, blob_prefix)
            st.session_state["az_blobs"] = blobs
            if blobs:
                st.success(f"Found {len(blobs)} supported file(s).")
            else:
                st.warning("No supported files found.")

        if "az_blobs" in st.session_state and st.session_state["az_blobs"]:
            blob = st.selectbox("Select File", st.session_state["az_blobs"], key="az_blob")

            if st.button("Read & Preview", key="az_read"):
                try:
                    from utils.connectors import azure_read_blob
                    df = azure_read_blob(client, container, blob)
                    st.session_state["az_df"] = df
                    _show_schema(df)
                    _show_preview(df)
                    _show_validation(df)
                except Exception as e:
                    st.error(f"Failed to read blob: {e}")

            if "az_df" in st.session_state:
                st.markdown("---")
                name = ds_name or blob.split("/")[-1]

                if st.button("Save & Connect", key="az_save", type="primary"):
                    config = {"container": container, "blob": blob}
                    _save_and_connect(name, "Azure Blob", config, st.session_state["az_df"], "az")

    if st.session_state.get("az_connected"):
        _show_inline_connected_status(
            st.session_state.get("az_connected_name", ""),
            "Azure Blob",
            "az",
        )


# ═══════════════════════════════════════════════════════════
#  DELTA LAKE CONNECTOR
# ═══════════════════════════════════════════════════════════

def _delta_lake_connector(ds_name):
    _connector_desc(
        "Read Delta tables from S3, ADLS, GCS, or a local path — the schema is auto-detected."
    )

    delta_path = st.text_input(
        "Delta Table Path", key="dl_path",
        placeholder="s3://bucket/delta-table/ or /path/to/delta/",
    )

    st.markdown(
        '<p style="font-weight:500; font-size:0.875rem; color:#374151; margin:12px 0 4px 0;">'
        'Storage Credentials <span style="color:#9CA3AF; font-weight:400;">(optional — for cloud paths)</span></p>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        storage_key = st.text_input("Access Key / Account Name", key="dl_key", placeholder="For S3 or ADLS")
    with c2:
        storage_secret = st.text_input("Secret Key / Account Key", type="password", key="dl_secret")

    if st.button("Test & Preview", key="dl_test"):
        if not delta_path:
            st.error("Delta Table Path is required.")
            return

        storage_options = None
        if storage_key and storage_secret:
            if "s3://" in delta_path:
                storage_options = {"AWS_ACCESS_KEY_ID": storage_key, "AWS_SECRET_ACCESS_KEY": storage_secret}
            else:
                storage_options = {"account_name": storage_key, "account_key": storage_secret}

        from utils.connectors import delta_connect, delta_read
        dt, err = delta_connect(delta_path, storage_options)
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(ds_name or "Delta Lake", "Delta Lake", "esg_data", 0, "Failed", get_current_user(), err)
            return

        _connection_status_badge(True, f"Delta table loaded from {delta_path}")

        try:
            df = delta_read(dt)
            st.session_state["dl_df"] = df
            _show_schema(df)
            _show_preview(df)
            _show_validation(df)
            st.session_state.pop("dl_connected", None)
        except Exception as e:
            st.error(f"Failed to read Delta table: {e}")

    if "dl_df" in st.session_state and "dl_connected" not in st.session_state:
        st.markdown("---")
        name = ds_name or delta_path.rstrip("/").split("/")[-1] if delta_path else "Delta Table"

        if st.button("Save & Connect", key="dl_save", type="primary"):
            config = {"path": delta_path}
            _save_and_connect(name, "Delta Lake", config, st.session_state["dl_df"], "dl")

    if st.session_state.get("dl_connected"):
        _show_inline_connected_status(
            st.session_state.get("dl_connected_name", ""),
            "Delta Lake",
            "dl",
        )


# ═══════════════════════════════════════════════════════════
#  SNOWFLAKE CONNECTOR
# ═══════════════════════════════════════════════════════════

def _snowflake_connector(ds_name):
    _connector_desc(
        "Run a SQL query against a <b>Snowflake</b> warehouse. "
        "Results feed straight into the ESG pipeline — the schema is auto-detected from your query's columns."
    )

    account = st.text_input(
        "Account Identifier", key="sf_account",
        placeholder="xy12345.us-east-1  (or your org-account e.g. myorg-myaccount)",
    )

    c1, c2 = st.columns(2)
    with c1:
        sf_user = st.text_input("User", key="sf_user")
    with c2:
        sf_pass = st.text_input("Password", type="password", key="sf_pass")

    c3, c4 = st.columns(2)
    with c3:
        warehouse = st.text_input("Warehouse", key="sf_wh", placeholder="COMPUTE_WH")
    with c4:
        role = st.text_input("Role (optional)", key="sf_role", placeholder="SYSADMIN")

    c5, c6 = st.columns(2)
    with c5:
        database = st.text_input("Database", key="sf_db", placeholder="ESG_DB")
    with c6:
        schema = st.text_input("Schema", key="sf_schema", placeholder="PUBLIC", value="PUBLIC")

    query = st.text_area(
        "SQL Query", key="sf_query",
        placeholder="SELECT * FROM ESG_DB.PUBLIC.EMISSIONS_2024",
        height=100,
    )

    if st.button("Test & Preview", key="sf_test"):
        missing = []
        if not account: missing.append("Account Identifier")
        if not sf_user: missing.append("User")
        if not sf_pass: missing.append("Password")
        if not warehouse: missing.append("Warehouse")
        if not database: missing.append("Database")
        if missing:
            st.error(f"Missing required fields: {', '.join(missing)}")
            return

        from utils.connectors import snowflake_connect
        conn, err = snowflake_connect(account, sf_user, sf_pass, warehouse, database, schema, role)
        if err:
            _connection_status_badge(False, err)
            add_ingestion_log(ds_name or "Snowflake", "Snowflake", "esg_data", 0, "Failed", get_current_user(), err)
            return

        _connection_status_badge(True, f"Connected to {database}.{schema}")
        st.session_state["sf_conn"] = conn
        st.session_state["sf_db_name"] = database
        st.session_state["sf_schema_name"] = schema
        st.session_state.pop("sf_connected", None)

        if query and query.strip():
            try:
                from utils.connectors import snowflake_read_query
                df = snowflake_read_query(conn, query)
                st.session_state["sf_df"] = df
                _show_schema(df)
                _show_preview(df)
                _show_validation(df)
            except Exception as e:
                st.error(f"Query failed: {e}")
        else:
            from utils.connectors import snowflake_list_tables
            tables = snowflake_list_tables(conn, database, schema)
            st.session_state["sf_tables"] = tables
            st.info(f"Connection successful. Found {len(tables)} table(s) in {database}.{schema}")

    if "sf_conn" in st.session_state and "sf_connected" not in st.session_state:
        conn = st.session_state["sf_conn"]

        if "sf_tables" in st.session_state and "sf_df" not in st.session_state:
            tables = st.session_state["sf_tables"]
            if tables:
                table = st.selectbox("Select Table", tables, key="sf_table")
                if st.button("Read Table", key="sf_read_table"):
                    try:
                        from utils.connectors import snowflake_read_table
                        db_name = st.session_state["sf_db_name"]
                        schema_name = st.session_state["sf_schema_name"]
                        full_table = f"{db_name}.{schema_name}.{table}"
                        df = snowflake_read_table(conn, full_table)
                        st.session_state["sf_df"] = df
                        st.session_state["sf_src_name"] = table
                        _show_schema(df)
                        _show_preview(df)
                        _show_validation(df)
                    except Exception as e:
                        st.error(f"Failed to read table: {e}")
            else:
                st.warning("No tables found in this schema.")

        if "sf_df" in st.session_state:
            st.markdown("---")
            name = ds_name or st.session_state.get("sf_src_name", "Snowflake Query")

            if st.button("Save & Connect", key="sf_save", type="primary"):
                config = {
                    "account": account, "warehouse": warehouse,
                    "database": database, "schema": schema,
                    "query": query,
                }
                _save_and_connect(name, "Snowflake", config, st.session_state["sf_df"], "sf")

    if st.session_state.get("sf_connected"):
        _show_inline_connected_status(
            st.session_state.get("sf_connected_name", ""),
            "Snowflake",
            "sf",
        )


# ═══════════════════════════════════════════════════════════
#  CONNECTED INLINE STATUS + DISCONNECT
# ═══════════════════════════════════════════════════════════

def _show_inline_connected_status(name, source_type, state_prefix):
    st.markdown("---")
    st.markdown(
        f'<div style="background:#f0fdf4; border:1px solid #86efac; border-radius:12px; '
        f'padding:16px 20px; margin:8px 0;">'
        f'<span style="color:#16a34a; font-weight:700; font-size:1rem;">● Connected</span>'
        f'<span style="color:#374151; font-size:0.9rem; margin-left:12px;">{name}</span>'
        f'<span style="color:#9CA3AF; font-size:0.82rem; margin-left:8px;">({source_type})</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if st.button("Disconnect", key=f"{state_prefix}_disconnect", type="secondary"):
        user = get_current_user()
        connected_at = st.session_state.get(f"{state_prefix}_connected_at")
        if connected_at:
            remove_datasource(user, connected_at)
        add_audit_log(user, f"Data Source Disconnected: {name} ({source_type})")

        for k in list(st.session_state.keys()):
            if k.startswith(state_prefix + "_"):
                del st.session_state[k]
        st.rerun()


# ═══════════════════════════════════════════════════════════
#  RUN COLLECTION PAGE
# ═══════════════════════════════════════════════════════════

def _run_collection_page():
    st.markdown(
        '<h2 style="margin:0 0 6px 0; font-size:1.55rem; font-weight:700; color:#111827;">'
        'Run Data Collection</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:0 0 18px 0; line-height:1.6;">'
        'Bulk-load data from registered sources and uploaded files. '
        'Upload additional files below or click Run to refresh existing connections.</p>',
        unsafe_allow_html=True,
    )

    use_real = st.checkbox("Use registered real sources", value=True, key="rc_use_real")

    extra_files = st.file_uploader(
        "Upload additional files (CSV/JSON)",
        type=["csv", "json"],
        key="rc_extra_files",
        accept_multiple_files=True,
        help="200MB per file · CSV, JSON",
    )

    if st.button("Run Data Collection", key="rc_run", type="primary", use_container_width=True):
        user = get_current_user()

        if extra_files:
            for f in extra_files:
                size_mb = f.size / (1024 * 1024)
                if size_mb > 200:
                    st.warning(f"{f.name} exceeds 200 MB — skipped.")
                    continue
                try:
                    df = _read_uploaded_file(f)
                    if df is not None:
                        file_path = os.path.join(UPLOAD_DIR, f.name)
                        f.seek(0)
                        with open(file_path, "wb") as out:
                            out.write(f.getbuffer())

                        name = f.name.rsplit(".", 1)[0]
                        config = {"filename": f.name, "size_mb": round(size_mb, 2), "path": file_path}
                        save_datasource({
                            "user": user, "datasource_name": name,
                            "type": "File Upload", "config": config,
                            "status": "Connected",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })

                        if not is_duplicate(name, "File Upload", "esg_data"):
                            load_data(name, "File Upload", "esg_data", df, user)
                            add_ingestion_log(name, "File Upload", "esg_data", len(df), "Success", user)
                        add_audit_log(user, f"Collection: loaded {f.name} ({len(df)} rows)")
                except Exception as e:
                    add_ingestion_log(f.name, "File Upload", "esg_data", 0, "Failed", user, str(e))

        st.session_state["rc_complete"] = True

    if st.session_state.get("rc_complete"):
        st.success("Data collection complete!")

    st.markdown("---")

    _show_metrics_dashboard()

    st.markdown("---")

    _registered_data_section()


# ═══════════════════════════════════════════════════════════
#  REGISTERED DATA SECTION
# ═══════════════════════════════════════════════════════════

def _get_file_stats(file_path):
    try:
        name_lower = file_path.lower()
        if name_lower.endswith(".csv"):
            df = pd.read_csv(file_path)
        elif name_lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file_path)
        elif name_lower.endswith(".json"):
            df = pd.read_json(file_path)
        else:
            return None, None
        return len(df), len(df.columns)
    except Exception:
        return None, None


def _resolve_stats(ds_name, file_path, stats_key):
    if stats_key in st.session_state:
        return st.session_state[stats_key]

    rows, cols = None, None
    if file_path and os.path.exists(file_path):
        rows, cols = _get_file_stats(file_path)

    if rows is None:
        all_ds = get_datasets()
        matched = [d for d in all_ds if d.get("name") == ds_name]
        if matched:
            ds_info = matched[-1]
            rows = ds_info.get("row_count", 0)
            cols = ds_info.get("col_count", 0)

    if rows is not None:
        st.session_state[stats_key] = {"rows": rows, "cols": cols}
        return {"rows": rows, "cols": cols}
    return None


def _registered_data_section():
    st.markdown(
        '<div style="margin:24px 0 16px 0;">'
        '<h3 style="margin:0 0 6px 0; font-size:1.25rem; font-weight:700; color:#111827; '
        'display:flex; align-items:center; gap:10px;">'
        '<span style="flex-shrink:0;">&#128194;</span>'
        '<span>Registered Data</span></h3>'
        '<p style="color:#6B7280; font-size:0.85rem; margin:0; line-height:1.55;">'
        'All data sources connected through the Data Sources tab. '
        'Use Refresh to update row/column counts, or Disconnect to remove a source.</p></div>',
        unsafe_allow_html=True,
    )

    user = get_current_user()
    sources = get_datasources(username=user)
    connected = [s for s in sources if s.get("status") == "Connected"]

    if not connected:
        st.markdown(
            '<div style="text-align:center; padding:40px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; margin:8px 0; background:#FAFAFA;">'
            '<div style="font-size:2.2rem; margin-bottom:10px;">&#128194;</div>'
            '<div style="font-size:1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
            'No data sources connected yet</div>'
            '<div style="color:#9CA3AF; font-size:0.88rem; max-width:400px; margin:0 auto; line-height:1.55;">'
            'Switch to the <b>Connect Data Sources</b> tab above to upload CSV files, '
            'connect to cloud storage, or fetch from APIs.</div></div>',
            unsafe_allow_html=True,
        )
        return

    seen = set()
    unique_sources = []
    for s in connected:
        key = (s.get("datasource_name", ""), s.get("type", ""), s.get("created_at", ""))
        if key not in seen:
            seen.add(key)
            unique_sources.append(s)

    type_icons = {
        "File Upload": "📄", "AWS S3": "☁️", "Azure Blob": "●",
        "Snowflake": "❄️", "Delta Lake": "▲", "Google Sheets": "📊",
        "REST API": "🌐", "BigQuery": "◆", "GCS": "◇",
    }

    for idx, src in enumerate(unique_sources):
        ds_name = src.get("datasource_name", "Unknown")
        ds_type = src.get("type", "Unknown")
        created = src.get("created_at", "")
        config = src.get("config", {})
        file_path = config.get("path", "")
        icon = type_icons.get(ds_type, "📁")

        safe_id = f"{idx}_{created.replace(' ', '_').replace(':', '')}"
        stats_key = f"rd_stats_{safe_id}"

        stats = _resolve_stats(ds_name, file_path, stats_key)

        if stats:
            stats_text = (
                f'<span style="color:#6B7280; font-size:0.8rem; margin-left:8px;">'
                f'Rows: <b style="color:#111827;">{stats["rows"]:,}</b>'
                f' &nbsp;|&nbsp; '
                f'Columns: <b style="color:#111827;">{stats["cols"]}</b></span>'
            )
        else:
            stats_text = ""

        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:10px; padding:10px 16px; '
            f'background:#FAFAFA; display:flex; align-items:center; gap:10px; min-height:44px; '
            f'margin-bottom:8px; flex-wrap:wrap; row-gap:6px;">'
            f'<span style="font-size:1.2rem; flex-shrink:0;">{icon}</span>'
            f'<span style="font-weight:600; font-size:0.92rem; color:#111827; '
            f'overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{ds_name}</span>'
            f'<span style="background:#ECFDF5; color:#059669; font-size:0.72rem; font-weight:600; '
            f'padding:2px 8px; border-radius:20px; letter-spacing:0.02em; flex-shrink:0; '
            f'white-space:nowrap;">● Connected</span>'
            f'{stats_text}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")


# ═══════════════════════════════════════════════════════════
#  METRICS DASHBOARD
# ═══════════════════════════════════════════════════════════

def _show_metrics_dashboard():
    user = get_current_user()
    active_sources = get_datasources(username=user)
    connected = [s for s in active_sources if s.get("status") == "Connected"]

    seen_files = set()
    unique_connected = []
    for s in connected:
        key = (s.get("datasource_name", ""), s.get("type", ""), s.get("created_at", ""))
        if key not in seen_files:
            seen_files.add(key)
            unique_connected.append(s)

    total_datasets = 0
    total_records = 0
    total_cells = 0
    non_null_cells = 0
    col_fill_rates = []

    for src in unique_connected:
        config = src.get("config", {})
        file_path = config.get("path", "")
        ds_name = src.get("datasource_name", "")

        df = None
        if file_path and os.path.exists(file_path):
            try:
                name_lower = file_path.lower()
                if name_lower.endswith(".csv"):
                    df = pd.read_csv(file_path)
                elif name_lower.endswith((".xlsx", ".xls")):
                    df = pd.read_excel(file_path)
                elif name_lower.endswith(".json"):
                    df = pd.read_json(file_path)
            except Exception:
                pass

        if df is not None:
            rows = len(df)
            cols = len(df.columns)
            total_datasets += 1
            total_records += rows
            cells = rows * cols
            total_cells += cells
            non_null = int(df.notna().sum().sum())
            non_null_cells += non_null
            for c in df.columns:
                fill = (1 - df[c].isnull().sum() / max(rows, 1)) * 100
                col_fill_rates.append(fill)
        else:
            all_ds = get_datasets()
            matched = [d for d in all_ds if d.get("name") == ds_name]
            if matched:
                ds_info = matched[-1]
                rows = ds_info.get("row_count", 0)
                cols = ds_info.get("col_count", 0)
                total_datasets += 1
                total_records += rows
                cells = rows * cols
                total_cells += cells
                schema = ds_info.get("schema", [])
                for col_info in schema:
                    nc = col_info.get("null_count", 0)
                    non_null_cells += rows - nc
                    col_fill_rates.append(100 - col_info.get("null_pct", 0))

    completeness = round(non_null_cells / max(total_cells, 1) * 100, 1)
    avg_confidence = round(sum(col_fill_rates) / max(len(col_fill_rates), 1), 1)

    total_sources = len(unique_connected)
    active_count = total_sources

    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    with mc1:
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:18px 16px;">'
            f'<div style="font-size:0.7rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
            f'letter-spacing:0.08em; margin-bottom:6px;">DATASETS LOADED</div>'
            f'<div style="font-size:1.6rem; font-weight:700; color:#111827;">{total_datasets}</div></div>',
            unsafe_allow_html=True,
        )
    with mc2:
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:18px 16px;">'
            f'<div style="font-size:0.7rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
            f'letter-spacing:0.08em; margin-bottom:6px;">TOTAL RECORDS</div>'
            f'<div style="font-size:1.6rem; font-weight:700; color:#111827;">{total_records:,}</div></div>',
            unsafe_allow_html=True,
        )
    with mc3:
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:18px 16px;">'
            f'<div style="font-size:0.7rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
            f'letter-spacing:0.08em; margin-bottom:6px;">COMPLETENESS</div>'
            f'<div style="font-size:1.6rem; font-weight:700; color:#111827;">{completeness}%</div></div>',
            unsafe_allow_html=True,
        )
    with mc4:
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:18px 16px;">'
            f'<div style="font-size:0.7rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
            f'letter-spacing:0.08em; margin-bottom:6px;">AVG CONFIDENCE</div>'
            f'<div style="font-size:1.6rem; font-weight:700; color:#111827;">{avg_confidence}%</div></div>',
            unsafe_allow_html=True,
        )
    with mc5:
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:18px 16px;">'
            f'<div style="font-size:0.7rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
            f'letter-spacing:0.08em; margin-bottom:6px;">ACTIVE CONNECTORS</div>'
            f'<div style="font-size:1.6rem; font-weight:700; color:#111827;">{active_count}/{total_sources}</div></div>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════
#  ENTERPRISE CONNECTORS PAGE (Placeholder)
# ═══════════════════════════════════════════════════════════

def _enterprise_connectors_page():
    st.markdown(
        '<div style="text-align:center; padding:60px 20px;">'
        '<div style="font-size:3rem; margin-bottom:16px;">🏢</div>'
        '<h2 style="font-size:1.4rem; font-weight:700; color:#111827; margin-bottom:8px;">'
        'Enterprise Connectors</h2>'
        '<p style="color:#6B7280; font-size:0.92rem; max-width:480px; margin:0 auto; line-height:1.6;">'
        'Premium enterprise-grade connectors for SAP, Oracle, Salesforce, '
        'and other enterprise systems. Contact your administrator for access.</p>'
        '</div>',
        unsafe_allow_html=True,
    )
