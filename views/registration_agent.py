"""
Data Registration, Schema Mapping & Validation Agent — Streamlit view.

Walks the user through:
  Step 1  Source registration
  Step 2  Schema profiling
  Step 3  Target table identification   (LLM-assisted)
  Step 4  Source-to-target mapping       (LLM-assisted)
  Step 5  Validation & approval
  Step 6  Summary / ingestion config
"""

import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime

from utils.auth import get_current_user
from utils.json_manager import add_audit_log
from utils.registration_agent import (
    register_source, get_registered_sources, get_source_by_id, update_source,
    profile_source_schema, save_profile, get_profile,
    infer_primary_keys, infer_foreign_keys,
    build_target_table_prompt, build_column_mapping_prompt,
    save_mappings, get_mappings, approve_all_mappings,
    validate_mapping, compare_schema_versions,
    run_referential_integrity_checks,
    calc_data_quality_score, generate_ingestion_configuration,
    call_llm, parse_llm_json,
    CANONICAL_TABLES,
    auto_register_source, get_unregistered_files,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


# ════════════════════════════════════════════════════════════
#  Render entry point
# ════════════════════════════════════════════════════════════

def render():
    top_tabs = st.tabs([
        "🤖  Registration Agent",
        "⚡  Auto Registration",
        "📋  Source Registry",
    ])

    with top_tabs[0]:
        _agent_page()
    with top_tabs[1]:
        _auto_register_page()
    with top_tabs[2]:
        _registry_page()


# ════════════════════════════════════════════════════════════
#  SHARED HELPERS
# ════════════════════════════════════════════════════════════

def _section(title, subtitle=None):
    st.markdown(
        f'<div style="margin:24px 0 8px 0;">'
        f'<h3 style="margin:0; font-size:1.15rem; font-weight:700; color:#111827;">{title}</h3>'
        + (f'<p style="color:#6B7280; font-size:0.84rem; margin:4px 0 0 0;">{subtitle}</p>' if subtitle else "")
        + '</div>',
        unsafe_allow_html=True,
    )


def _step_badge(number, label, current_step):
    if number < current_step:
        bg = "#059669"
        fg = "#FFFFFF"
        content = "&#10003;"
        label_color = "#059669"
        label_weight = "500"
    elif number == current_step:
        bg = "linear-gradient(135deg,#FF5A00,#FF7F32)"
        fg = "#FFFFFF"
        content = str(number)
        label_color = "#111827"
        label_weight = "700"
    else:
        bg = "#E5E7EB"
        fg = "#6B7280"
        content = str(number)
        label_color = "#9CA3AF"
        label_weight = "400"

    return (
        f'<div style="display:inline-flex; align-items:center; gap:6px; flex-shrink:0;">'
        f'<div style="width:28px; height:28px; background:{bg}; border-radius:50%; '
        f'display:flex; align-items:center; justify-content:center; '
        f'font-size:0.75rem; font-weight:700; color:{fg}; flex-shrink:0; min-width:28px;">{content}</div>'
        f'<span style="font-size:0.78rem; font-weight:{label_weight}; '
        f'color:{label_color}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{label}</span></div>'
    )


def _step_connector(completed=False):
    color = "#059669" if completed else "#E5E7EB"
    return (
        f'<div style="flex:1; height:2px; background:{color}; '
        f'margin:0 4px; min-width:12px; max-width:40px; align-self:center;"></div>'
    )


def _metric_card(label, value, color="#111827"):
    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px;">'
        f'<div style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
        f'letter-spacing:0.08em; margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:1.4rem; font-weight:700; color:{color};">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _status_pill(text, variant="info"):
    colors = {
        "success": ("#ECFDF5", "#059669"),
        "warning": ("#FFFBEB", "#D97706"),
        "error": ("#FEF2F2", "#DC2626"),
        "info": ("#EFF6FF", "#2563EB"),
    }
    bg, fg = colors.get(variant, colors["info"])
    return (
        f'<span style="background:{bg}; color:{fg}; font-size:0.72rem; font-weight:600; '
        f'padding:3px 10px; border-radius:20px; letter-spacing:0.02em; '
        f'white-space:nowrap; display:inline-block; flex-shrink:0;">{text}</span>'
    )


def _confidence_bar(value):
    pct = int(round(value * 100))
    if pct >= 85:
        bar_color = "#059669"
    elif pct >= 70:
        bar_color = "#D97706"
    else:
        bar_color = "#DC2626"
    return (
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<div style="flex:1;max-width:100px;height:6px;background:#E5E7EB;border-radius:3px;">'
        f'<div style="width:{pct}%;height:100%;background:{bar_color};border-radius:3px;"></div></div>'
        f'<span style="font-size:0.82rem;font-weight:600;color:{bar_color};">{pct}%</span></div>'
    )


_TABLE_CSS = (
    'width:100%;border-collapse:collapse;'
)
_TH_CSS = (
    'padding:10px 14px;text-align:left;font-size:0.75rem;font-weight:600;'
    'color:#6B7280;text-transform:uppercase;letter-spacing:0.04em;'
    'background:#F9FAFB;border-bottom:2px solid #E5E7EB;'
    'position:sticky;top:0;z-index:1;'
)
_TD_CSS = 'padding:10px 14px;font-size:0.84rem;color:#374151;border-bottom:1px solid #F3F4F6;'


def _html_table(card_title, headers, rows, subtitle=None):
    thead = "".join(f'<th style="{_TH_CSS}">{h}</th>' for h in headers)
    tbody_rows = []
    for i, row in enumerate(rows):
        bg = "background:#FAFAFA;" if i % 2 == 1 else ""
        cells = "".join(f'<td style="{_TD_CSS}{bg}">{c}</td>' for c in row)
        tbody_rows.append(
            f'<tr style="{bg}transition:background 0.15s;" '
            f'onmouseover="this.style.background=\'#FFF7ED\'" '
            f'onmouseout="this.style.background=\'{("#FAFAFA" if i % 2 == 1 else "")}\'">'
            f'{cells}</tr>'
        )
    tbody = "".join(tbody_rows)
    sub = (f'<p style="color:#6B7280;font-size:0.82rem;margin:4px 0 0;">{subtitle}</p>'
           if subtitle else "")
    return (
        f'<div style="border:1px solid #E5E7EB;border-radius:12px;overflow:hidden;margin:12px 0;">'
        f'<div style="padding:16px 18px 12px;border-bottom:1px solid #F3F4F6;">'
        f'<h4 style="margin:0;font-size:1rem;font-weight:700;color:#111827;">{card_title}</h4>'
        f'{sub}</div>'
        f'<div style="overflow-x:auto;max-height:420px;overflow-y:auto;">'
        f'<table style="{_TABLE_CSS}"><thead><tr>{thead}</tr></thead>'
        f'<tbody>{tbody}</tbody></table></div></div>'
    )


# ════════════════════════════════════════════════════════════
#  AGENT PAGE — step-by-step flow
# ════════════════════════════════════════════════════════════

def _agent_page():
    st.markdown(
        '<div style="margin-bottom:6px;">'
        '<h2 style="margin:0; font-size:1.55rem; font-weight:700; color:#111827;">'
        'Data Registration Agent</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:6px 0 12px 0; line-height:1.6;">'
        'Onboard a new data source into the ESG platform in 6 guided steps.</p></div>',
        unsafe_allow_html=True,
    )

    with st.expander("How does the Registration Agent work?", expanded=False):
        st.markdown(
            "1. **Register** — Upload your file and set metadata (type, domain, owner)\n"
            "2. **Profile** — Auto-analyse column types, nulls, keys, and uniqueness\n"
            "3. **Target Table** — AI identifies the best-matching canonical ESG table\n"
            "4. **Column Mapping** — AI maps source columns to canonical columns with confidence scores\n"
            "5. **Validate** — Run quality checks: completeness, referential integrity, uniqueness\n"
            "6. **Summary** — Review the output JSON and ingestion configuration\n\n"
            "You can go back to any previous step using the **Back** button."
        )

    current_step = st.session_state.get("ra_step", 1)

    step_labels = ["Register", "Profile", "Target Table", "Mapping", "Validate", "Summary"]
    parts = []
    for i, label in enumerate(step_labels, 1):
        parts.append(_step_badge(i, label, current_step))
        if i < len(step_labels):
            parts.append(_step_connector(completed=(i < current_step)))
    steps_html = "".join(parts)

    st.markdown(
        f'<div style="display:flex; align-items:center; '
        f'margin-bottom:24px; padding:12px 16px; background:white; '
        f'border-radius:14px; border:1px solid #E5E7EB; '
        f'box-shadow:0 1px 3px rgba(0,0,0,0.04); overflow-x:auto; '
        f'gap:0; flex-wrap:nowrap;">{steps_html}</div>',
        unsafe_allow_html=True,
    )

    if current_step == 1:
        _step_1_register()
    elif current_step == 2:
        _step_2_profile()
    elif current_step == 3:
        _step_3_target_table()
    elif current_step == 4:
        _step_4_column_mapping()
    elif current_step == 5:
        _step_5_validate()
    elif current_step == 6:
        _step_6_summary()


# ────────────────────────────────────────────────────
#  Step 1 — Source Registration
# ────────────────────────────────────────────────────

def _step_1_register():
    _section("Step 1: Source Registration", "Register a new data source for onboarding.")

    source_type = st.selectbox(
        "Source Type",
        ["CSV File", "REST API", "SQL Database", "Google Sheets", "BigQuery", "GCS",
         "AWS S3", "Azure Blob", "Delta Lake", "Other"],
        key="ra_source_type",
        help="Select the type of data source. For most users, start with CSV File to upload a local file.",
    )

    if source_type == "CSV File":
        uploaded = st.file_uploader(
            "Upload CSV File", type=["csv", "xlsx", "xls", "json"],
            key="ra_upload",
            help="Upload the file to register and profile.",
        )
        if uploaded:
            st.caption(f"{uploaded.name} — {uploaded.size / (1024*1024):.2f} MB")
    else:
        uploaded = None

    c1, c2 = st.columns(2)
    with c1:
        source_name = st.text_input("Source Name", key="ra_src_name",
                                    placeholder="e.g. esg_metric_data.csv",
                                    value=uploaded.name if uploaded else "")
    with c2:
        business_domain = st.selectbox(
            "Business Domain",
            ["ESG Metrics", "Company Data", "Regulatory", "Supply Chain",
             "Financial", "Risk & Opportunity", "Compliance", "Other"],
            key="ra_biz_domain",
            help="Categorise this source so downstream agents can filter by domain",
        )

    c3, c4 = st.columns(2)
    with c3:
        refresh_freq = st.selectbox(
            "Refresh Frequency",
            ["One-time", "Daily", "Weekly", "Monthly", "Quarterly", "Annually"],
            key="ra_refresh",
        )
    with c4:
        source_owner = st.text_input("Source Owner", key="ra_owner",
                                     value=get_current_user() or "",
                                     placeholder="username or team")

    conn_ref = ""
    if source_type != "CSV File":
        conn_ref = st.text_input(
            "Connection Reference / Endpoint",
            key="ra_conn_ref",
            placeholder="e.g. https://api.example.com or project.dataset.table",
        )

    watermark = st.text_input("Watermark Column (optional)", key="ra_watermark",
                              placeholder="e.g. updated_at")

    if st.button("Register Source", key="ra_register_btn", type="primary"):
        if not source_name:
            st.error("Source Name is required.")
            return

        if source_type == "CSV File":
            if not uploaded:
                st.error("Please upload a file.")
                return
            file_path = os.path.join(UPLOAD_DIR, uploaded.name)
            uploaded.seek(0)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            location = file_path
        else:
            location = conn_ref or "N/A"

        record = register_source(
            source_name=source_name,
            source_type=source_type,
            source_location=location,
            business_domain=business_domain,
            connection_reference=conn_ref,
            refresh_frequency=refresh_freq,
            watermark_column=watermark,
            source_owner=source_owner,
        )

        add_audit_log(get_current_user(), f"Source Registered: {record['source_id']} — {source_name}")

        st.session_state["ra_source_id"] = record["source_id"]
        st.session_state["ra_source_record"] = record
        if source_type == "CSV File" and uploaded:
            uploaded.seek(0)
            name_lower = uploaded.name.lower()
            if name_lower.endswith(".csv"):
                st.session_state["ra_df"] = pd.read_csv(uploaded)
            elif name_lower.endswith((".xlsx", ".xls")):
                st.session_state["ra_df"] = pd.read_excel(uploaded)
            elif name_lower.endswith(".json"):
                st.session_state["ra_df"] = pd.read_json(uploaded)

        st.session_state["ra_step"] = 2
        st.rerun()


# ────────────────────────────────────────────────────
#  Step 2 — Schema Profiling
# ────────────────────────────────────────────────────

def _step_2_profile():
    source_id = st.session_state.get("ra_source_id")
    source = st.session_state.get("ra_source_record", {})
    _section("Step 2: Schema Profiling",
             f"Profiling <b>{source.get('source_name', '')}</b> ({source_id})")

    df = st.session_state.get("ra_df")
    if df is None:
        st.warning("No data loaded. For non-CSV sources, data must be fetched first.")
        if st.button("← Back to Registration", key="ra_back1"):
            st.session_state["ra_step"] = 1
            st.rerun()
        return

    profiles = profile_source_schema(df)
    st.session_state["ra_profiles"] = profiles

    save_profile(source_id, profiles, len(df))

    drift = compare_schema_versions(source_id, profiles)
    if drift:
        st.info(f"Schema drift detected: {drift['drift_pct']}% — "
                f"Added: {drift['added_columns']}, Removed: {drift['removed_columns']}")

    pk_candidates = infer_primary_keys(df, profiles)
    fk_candidates = infer_foreign_keys(profiles)
    st.session_state["ra_pk"] = pk_candidates
    st.session_state["ra_fk"] = fk_candidates

    mc1, mc2, mc3, mc4 = st.columns(4)
    with mc1:
        _metric_card("Rows", f"{len(df):,}")
    with mc2:
        _metric_card("Columns", str(len(profiles)))
    with mc3:
        _metric_card("Primary Key(s)", ", ".join(pk_candidates) if pk_candidates else "None detected")
    with mc4:
        _metric_card("Foreign Key(s)", str(len(fk_candidates)))

    _section("Column Profiles")
    prof_df = pd.DataFrame(profiles)
    display_cols = ["column", "inferred_type", "null_pct", "distinct_count",
                    "uniqueness_pct", "duplicate_pct", "samples"]
    prof_df = prof_df[[c for c in display_cols if c in prof_df.columns]]
    prof_df.columns = ["Column", "Type", "Null %", "Distinct", "Unique %", "Dup %", "Samples"]
    st.dataframe(prof_df, use_container_width=True, hide_index=True)

    if fk_candidates:
        _section("Detected Foreign Keys")
        for fk in fk_candidates:
            st.markdown(f"- **{fk['column']}** → `{fk['references']}`")

    st.markdown("---")
    if st.button("Proceed to Target Table Identification →", key="ra_to_step3", type="primary"):
        st.session_state["ra_step"] = 3
        st.rerun()

    if st.button("← Back", key="ra_back2"):
        st.session_state["ra_step"] = 1
        st.rerun()


# ────────────────────────────────────────────────────
#  Step 3 — Target Table Identification (LLM)
# ────────────────────────────────────────────────────

def _step_3_target_table():
    source = st.session_state.get("ra_source_record", {})
    profiles = st.session_state.get("ra_profiles", [])
    df = st.session_state.get("ra_df")

    _section("Step 3: Identify Target Table",
             "The AI agent analyses column names, sample data and canonical schema "
             "to recommend the best-matching target table.")

    if "ra_target_result" not in st.session_state:
        with st.spinner("AI agent identifying the target table..."):
            sample_records = df.head(5).to_dict(orient="records") if df is not None else []
            prompt = build_target_table_prompt(source.get("source_name", ""), profiles, sample_records)

            raw, err = call_llm(prompt)
            if err:
                st.error(f"LLM call failed: {err}")
                st.text_area("Prompt sent", prompt, height=200)
                if st.button("← Back", key="ra_back3a"):
                    st.session_state["ra_step"] = 2
                    st.rerun()
                return

            parsed = parse_llm_json(raw)
            if not parsed:
                st.error("Could not parse AI response.")
                st.text_area("Raw response", raw, height=200)
                if st.button("Retry", key="ra_retry3"):
                    st.rerun()
                if st.button("← Back", key="ra_back3b"):
                    st.session_state["ra_step"] = 2
                    st.rerun()
                return

            st.session_state["ra_target_result"] = parsed

    result = st.session_state["ra_target_result"]
    rec_table = result.get("recommended_table", "")
    confidence = result.get("confidence", 0)
    reason = result.get("reason", "")

    st.markdown(
        f'<div style="border:1px solid #86efac; background:#f0fdf4; border-radius:12px; '
        f'padding:20px; margin:12px 0;">'
        f'<div style="font-size:0.75rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
        f'margin-bottom:6px;">AI RECOMMENDATION</div>'
        f'<div style="font-size:1.3rem; font-weight:700; color:#111827; margin-bottom:4px;">'
        f'{rec_table}</div>'
        f'<div style="color:#6B7280; font-size:0.88rem; margin-bottom:8px;">{reason}</div>'
        f'<div>{_status_pill(f"Confidence: {confidence:.0%}", "success" if confidence >= 0.85 else "warning")}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    canonical_list = list(CANONICAL_TABLES.keys())
    default_idx = canonical_list.index(rec_table) if rec_table in canonical_list else 0
    selected_table = st.selectbox(
        "Confirm or override target table",
        canonical_list,
        index=default_idx,
        key="ra_target_select",
    )

    st.session_state["ra_target_table"] = selected_table

    table_info = CANONICAL_TABLES.get(selected_table, {})
    if table_info:
        st.markdown(f"**{selected_table}** — {table_info.get('description', '')}")
        st.markdown("Canonical columns: " + ", ".join(f"`{c}`" for c in table_info.get("columns", {}).keys()))

    st.markdown("---")
    if st.button("Proceed to Column Mapping →", key="ra_to_step4", type="primary"):
        st.session_state["ra_step"] = 4
        st.rerun()

    if st.button("← Back", key="ra_back3c"):
        st.session_state.pop("ra_target_result", None)
        st.session_state["ra_step"] = 2
        st.rerun()


# ────────────────────────────────────────────────────
#  Step 4 — Column Mapping (LLM)
# ────────────────────────────────────────────────────

def _step_4_column_mapping():
    source = st.session_state.get("ra_source_record", {})
    profiles = st.session_state.get("ra_profiles", [])
    df = st.session_state.get("ra_df")
    target_table = st.session_state.get("ra_target_table", "")
    source_id = st.session_state.get("ra_source_id")

    _section("Step 4: Source-to-Target Column Mapping",
             f"Mapping columns from <b>{source.get('source_name', '')}</b> → <b>{target_table}</b>")

    if "ra_mapping_result" not in st.session_state:
        with st.spinner("AI agent generating column mappings..."):
            sample_records = df.head(5).to_dict(orient="records") if df is not None else []
            prompt = build_column_mapping_prompt(
                source.get("source_name", ""), profiles, target_table, sample_records
            )

            raw, err = call_llm(prompt)
            if err:
                st.error(f"LLM call failed: {err}")
                if st.button("← Back", key="ra_back4a"):
                    st.session_state["ra_step"] = 3
                    st.rerun()
                return

            parsed = parse_llm_json(raw)
            if not parsed or not isinstance(parsed, list):
                st.error("Could not parse AI mapping response.")
                st.text_area("Raw response", raw, height=200)
                if st.button("Retry", key="ra_retry4"):
                    st.rerun()
                if st.button("← Back", key="ra_back4b"):
                    st.session_state["ra_step"] = 3
                    st.rerun()
                return

            st.session_state["ra_mapping_result"] = parsed

    mappings = st.session_state["ra_mapping_result"]

    mapped = [m for m in mappings if m.get("target_column")]
    unmapped = [m for m in mappings if not m.get("target_column")]

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        _metric_card("Mapped", str(len(mapped)), "#059669")
    with mc2:
        _metric_card("Unmapped", str(len(unmapped)), "#DC2626" if unmapped else "#059669")
    with mc3:
        avg_conf = sum(m.get("mapping_confidence", 0) for m in mapped) / max(len(mapped), 1)
        _metric_card("Avg Confidence", f"{avg_conf:.0%}")

    _section("Column Mapping Table")

    map_rows = []
    for m in mappings:
        conf = m.get("mapping_confidence", 0)
        if conf >= 0.90:
            status = "Auto-approve"
            variant = "success"
        elif conf >= 0.75:
            status = "Review"
            variant = "warning"
        else:
            status = "Manual"
            variant = "error"

        map_rows.append({
            "Source Column": m.get("source_column", ""),
            "Target Table": m.get("target_table", target_table),
            "Target Column": m.get("target_column") or "—",
            "Transformation": m.get("transformation_rule", ""),
            "Confidence": f"{conf:.0%}",
            "Status": status,
        })

    map_df = pd.DataFrame(map_rows)
    st.dataframe(map_df, use_container_width=True, hide_index=True)

    if unmapped:
        st.warning(f"{len(unmapped)} column(s) could not be mapped: "
                   f"{', '.join(m['source_column'] for m in unmapped)}")

    save_mappings(source_id, target_table, mappings, "Review required")

    st.markdown("---")
    if st.button("Proceed to Validation →", key="ra_to_step5", type="primary"):
        st.session_state["ra_step"] = 5
        st.rerun()

    if st.button("← Back", key="ra_back4c"):
        st.session_state.pop("ra_mapping_result", None)
        st.session_state["ra_step"] = 3
        st.rerun()


# ────────────────────────────────────────────────────
#  Step 5 — Validation & Approval
# ────────────────────────────────────────────────────

def _step_5_validate():
    source_id = st.session_state.get("ra_source_id")
    source = st.session_state.get("ra_source_record", {})
    profiles = st.session_state.get("ra_profiles", [])
    df = st.session_state.get("ra_df")
    mappings = st.session_state.get("ra_mapping_result", [])
    fk_candidates = st.session_state.get("ra_fk", [])

    _section("Step 5: Validation & Approval",
             "Automated quality checks and referential integrity analysis.")

    mapping_warnings = validate_mapping(mappings)
    fk_results = run_referential_integrity_checks(df, fk_candidates) if df is not None else []
    dq_score = calc_data_quality_score(df, profiles, fk_results) if df is not None else 0

    st.session_state["ra_dq_score"] = dq_score
    st.session_state["ra_fk_results"] = fk_results
    st.session_state["ra_map_warnings"] = mapping_warnings

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        color = "#059669" if dq_score >= 0.85 else ("#D97706" if dq_score >= 0.70 else "#DC2626")
        _metric_card("Data Quality Score", f"{dq_score:.0%}", color)
    with mc2:
        fk_pass = sum(1 for r in fk_results if r.get("pass") is True)
        _metric_card("FK Checks Passed", f"{fk_pass}/{len(fk_results)}" if fk_results else "N/A")
    with mc3:
        _metric_card("Mapping Warnings", str(len(mapping_warnings)),
                     "#DC2626" if mapping_warnings else "#059669")

    if mapping_warnings:
        _section("Mapping Warnings")
        for w in mapping_warnings:
            st.warning(w)

    if fk_results:
        _section("Referential Integrity Checks")
        for r in fk_results:
            icon = "✅" if r.get("pass") is True else ("⚠️" if r.get("pass") is None else "❌")
            st.markdown(f"{icon} **{r['column']}** → `{r['references']}` — {r['message']}")
            if r.get("orphan_samples"):
                st.caption(f"  Sample orphans: {', '.join(r['orphan_samples'])}")

    _section("Data Quality Breakdown")
    total = max(len(df), 1) if df is not None else 1
    total_cols = max(len(profiles), 1)
    total_cells = total * total_cols
    non_null_cells = sum(total - p["null_count"] for p in profiles)
    completeness = non_null_cells / total_cells
    valid_cols = sum(1 for p in profiles if p["null_pct"] < 100)
    validity = valid_cols / total_cols
    avg_unique = sum(p["uniqueness_pct"] for p in profiles) / total_cols / 100

    dq_rows = [
        {"Dimension": "Completeness (30%)", "Score": f"{completeness:.1%}",
         "Detail": f"{non_null_cells:,}/{total_cells:,} cells filled"},
        {"Dimension": "Validity (20%)", "Score": f"{validity:.1%}",
         "Detail": f"{valid_cols}/{total_cols} columns have data"},
        {"Dimension": "Uniqueness (20%)", "Score": f"{avg_unique:.1%}",
         "Detail": "Average column uniqueness"},
        {"Dimension": "Referential Integrity (20%)",
         "Score": f"{sum(1 for r in fk_results if r.get('pass') is True) / max(len(fk_results), 1):.1%}" if fk_results else "N/A",
         "Detail": f"{len(fk_results)} FK check(s)"},
        {"Dimension": "Timeliness (10%)", "Score": "100.0%",
         "Detail": "Freshly uploaded"},
    ]
    st.dataframe(pd.DataFrame(dq_rows), use_container_width=True, hide_index=True)

    st.markdown("---")

    approve_col, back_col = st.columns([3, 1])
    with approve_col:
        if st.button("✅  Approve Mappings & Proceed", key="ra_approve", type="primary",
                      use_container_width=True):
            user = get_current_user()
            approve_all_mappings(source_id, user)
            update_source(source_id, {"last_successful_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            add_audit_log(user, f"Mappings Approved for {source_id}")
            st.session_state["ra_step"] = 6
            st.rerun()

    with back_col:
        if st.button("← Back", key="ra_back5"):
            st.session_state["ra_step"] = 4
            st.rerun()


# ────────────────────────────────────────────────────
#  Step 6 — Summary
# ────────────────────────────────────────────────────

def _step_6_summary():
    source_id = st.session_state.get("ra_source_id")
    source = st.session_state.get("ra_source_record", {})
    profiles = st.session_state.get("ra_profiles", [])
    target_table = st.session_state.get("ra_target_table", "")
    mappings = st.session_state.get("ra_mapping_result", [])
    dq_score = st.session_state.get("ra_dq_score", 0)
    map_warnings = st.session_state.get("ra_map_warnings", [])
    df = st.session_state.get("ra_df")

    _section("Step 6: Registration Complete",
             f"Source <b>{source.get('source_name', '')}</b> has been fully onboarded.")

    st.markdown(
        f'<div style="border:2px solid #86efac; background:#f0fdf4; border-radius:14px; '
        f'padding:24px; margin:12px 0; text-align:center;">'
        f'<div style="font-size:2.5rem; margin-bottom:8px;">✅</div>'
        f'<div style="font-size:1.2rem; font-weight:700; color:#111827; margin-bottom:4px;">'
        f'Source Registered & Mappings Approved</div>'
        f'<div style="color:#6B7280; font-size:0.88rem;">Ready for downstream agents</div></div>',
        unsafe_allow_html=True,
    )

    mapped = [m for m in mappings if m.get("target_column")]
    unmapped = [m for m in mappings if not m.get("target_column")]
    avg_conf = sum(m.get("mapping_confidence", 0) for m in mapped) / max(len(mapped), 1)

    mc1, mc2, mc3, mc4, mc5 = st.columns(5)
    with mc1:
        _metric_card("Source ID", source_id)
    with mc2:
        _metric_card("Target Table", target_table)
    with mc3:
        _metric_card("Mapped Cols", str(len(mapped)))
    with mc4:
        _metric_card("Unmapped Cols", str(len(unmapped)))
    with mc5:
        _metric_card("DQ Score", f"{dq_score:.0%}")

    # ── Registration Summary table ──────────────────────
    summary_rows = [
        ["Source ID", f'<code style="font-size:0.82rem;background:#F3F4F6;padding:2px 8px;'
                      f'border-radius:6px;">{source_id}</code>'],
        ["Source Name", source.get("source_name", "")],
        ["Target Table", f'<code style="font-size:0.82rem;background:#F3F4F6;padding:2px 8px;'
                         f'border-radius:6px;">{target_table}</code>'],
        ["Mapping Status", _status_pill("Approved", "success")],
        ["Mapping Confidence", _confidence_bar(avg_conf)],
        ["Data Quality Score", _confidence_bar(dq_score)],
        ["Mapped Columns", f'<span style="font-weight:600;color:#059669;">{len(mapped)}</span>'],
        ["Unmapped Columns",
         f'<span style="font-weight:600;color:{"#DC2626" if unmapped else "#059669"};">'
         f'{len(unmapped)}</span>'],
    ]
    st.markdown(
        _html_table("Registration Summary",
                     ["Property", "Value"],
                     summary_rows,
                     subtitle="Mapping and quality overview for this source"),
        unsafe_allow_html=True,
    )

    if map_warnings:
        warn_items = "".join(
            f'<div style="display:flex;align-items:flex-start;gap:8px;padding:8px 14px;'
            f'border-bottom:1px solid #FDE68A;font-size:0.82rem;color:#92400E;">'
            f'<span style="flex-shrink:0;margin-top:1px;">&#9888;</span>'
            f'<span>{w}</span></div>'
            for w in map_warnings[:10]
        )
        st.markdown(
            f'<div style="border:1px solid #FDE68A;border-radius:12px;overflow:hidden;'
            f'margin:0 0 12px;background:#FFFBEB;">'
            f'<div style="padding:12px 18px 8px;border-bottom:1px solid #FDE68A;">'
            f'<h4 style="margin:0;font-size:0.92rem;font-weight:700;color:#92400E;">'
            f'Warnings ({len(map_warnings)})</h4></div>'
            f'{warn_items}</div>',
            unsafe_allow_html=True,
        )

    # ── Ingestion Configuration tables ────────────────
    config = generate_ingestion_configuration(source_id)
    if config:
        overview_rows = [
            ["Source ID", f'<code style="font-size:0.82rem;background:#F3F4F6;'
                          f'padding:2px 8px;border-radius:6px;">{config.get("source_id", "")}</code>'],
            ["Source Name", config.get("source_name", "")],
            ["Source Type", config.get("source_type", "")],
            ["Target Tables", ", ".join(
                f'<code style="font-size:0.82rem;background:#F3F4F6;padding:2px 8px;'
                f'border-radius:6px;">{t}</code>'
                for t in config.get("target_tables", []))],
            ["Mapped / Unmapped",
             f'<span style="font-weight:600;color:#059669;">{config.get("mapped_columns", 0)}</span>'
             f' / <span style="font-weight:600;color:#DC2626;">{config.get("unmapped_columns", 0)}</span>'],
            ["Generated At", config.get("generated_at", "")],
        ]
        st.markdown(
            _html_table("Ingestion Configuration",
                         ["Property", "Value"],
                         overview_rows,
                         subtitle="Source and ingestion metadata"),
            unsafe_allow_html=True,
        )

        cfg_mappings = config.get("mappings", [])
        if cfg_mappings:
            mapping_rows = []
            for i, m in enumerate(cfg_mappings, 1):
                conf = m.get("mapping_confidence", 0)
                status = m.get("mapping_status", "")
                variant = "success" if status == "Approved" else "warning"
                mapping_rows.append([
                    str(i),
                    f'<code style="font-size:0.8rem;">{m.get("source_column", "")}</code>',
                    f'<code style="font-size:0.8rem;">{m.get("target_table", "")}</code>',
                    f'<code style="font-size:0.8rem;">{m.get("target_column", "")}</code>',
                    f'<span style="font-size:0.8rem;color:#6B7280;">'
                    f'{m.get("transformation_rule", "")[:60]}</span>',
                    _confidence_bar(conf),
                    _status_pill(status, variant),
                    m.get("approved_by") or "—",
                ])
            st.markdown(
                _html_table("Column Mappings",
                             ["#", "Source Column", "Target Table", "Target Column",
                              "Transformation", "Confidence", "Status", "Approved By"],
                             mapping_rows,
                             subtitle=f"{len(cfg_mappings)} column mapping(s)"),
                unsafe_allow_html=True,
            )
    else:
        st.info("No ingestion configuration generated (incomplete data).")

    # ── Export / Copy buttons ─────────────────────────
    output_dict = {
        "source_id": source_id,
        "source_name": source.get("source_name", ""),
        "recommended_target_table": target_table,
        "mapping_status": "Approved",
        "mapping_confidence": round(avg_conf, 2),
        "data_quality_score": round(dq_score, 2),
        "mapped_columns": len(mapped),
        "unmapped_columns": len(unmapped),
        "warnings": map_warnings[:10],
    }

    exp_rows = []
    if config:
        for m in config.get("mappings", []):
            exp_rows.append({
                "Source Column": m.get("source_column", ""),
                "Target Table": m.get("target_table", ""),
                "Target Column": m.get("target_column", ""),
                "Transformation": m.get("transformation_rule", ""),
                "Confidence": m.get("mapping_confidence", 0),
                "Status": m.get("mapping_status", ""),
                "Approved By": m.get("approved_by", ""),
            })

    st.markdown("---")
    bc1, bc2, bc3 = st.columns([1, 1, 2])
    with bc1:
        csv_data = pd.DataFrame(exp_rows).to_csv(index=False) if exp_rows else "No data"
        st.download_button(
            "Export Table (CSV)",
            data=csv_data,
            file_name=f"{source_id}_mappings.csv",
            mime="text/csv",
            key="ra_export_csv",
            use_container_width=True,
        )
    with bc2:
        full_config = {**output_dict, "ingestion_configuration": config} if config else output_dict
        st.download_button(
            "Copy Configuration (JSON)",
            data=json.dumps(full_config, indent=2, default=str),
            file_name=f"{source_id}_config.json",
            mime="application/json",
            key="ra_export_json",
            use_container_width=True,
        )

    st.markdown("")
    if st.button("Register Another Source", key="ra_restart", type="primary"):
        for k in list(st.session_state.keys()):
            if k.startswith("ra_"):
                del st.session_state[k]
        st.session_state["ra_step"] = 1
        st.rerun()


# ════════════════════════════════════════════════════════════
#  AUTO REGISTRATION PAGE — batch-register all unregistered files
# ════════════════════════════════════════════════════════════

def _auto_register_page():
    st.markdown(
        '<div style="margin-bottom:6px;">'
        '<h2 style="margin:0; font-size:1.55rem; font-weight:700; color:#111827;">'
        '⚡ Auto Registration</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:6px 0 12px 0; line-height:1.6;">'
        'Automatically register, profile, map and validate all unregistered files in the uploads folder — '
        'no manual steps required.</p></div>',
        unsafe_allow_html=True,
    )

    with st.expander("How does Auto Registration work?", expanded=False):
        st.markdown(
            "1. **Scan** — Finds all CSV/Excel/JSON files in `uploads/` not yet registered\n"
            "2. **Register** — Creates a source record with auto-detected domain\n"
            "3. **Profile** — Analyses column types, nulls, keys, uniqueness\n"
            "4. **Target Table** — AI identifies best-matching canonical ESG table (with pattern-based fallback)\n"
            "5. **Column Mapping** — AI maps columns to canonical schema (with name-matching fallback)\n"
            "6. **Validate & Approve** — Runs quality checks and auto-approves mappings\n\n"
            "All 6 steps run automatically for each file. Results are shown below."
        )

    unregistered = get_unregistered_files()

    mc1, mc2 = st.columns(2)
    with mc1:
        _metric_card("Unregistered Files", str(len(unregistered)), "#D97706" if unregistered else "#059669")
    with mc2:
        already = len(get_registered_sources())
        _metric_card("Already Registered", str(already), "#059669")

    if unregistered:
        _section("Files Ready for Auto-Registration")
        file_names = [os.path.basename(f) for f in unregistered]
        for fn in file_names:
            st.markdown(
                f'<div style="display:inline-flex; align-items:center; gap:8px; '
                f'padding:6px 14px; margin:4px 4px 4px 0; background:#FFF7ED; '
                f'border:1px solid #FDBA74; border-radius:20px; font-size:0.82rem; '
                f'font-weight:500; color:#9A3412;">'
                f'📄 {fn}</div>',
                unsafe_allow_html=True,
            )

        st.markdown("")
        user = get_current_user() or "System"

        if st.button("🚀  Auto-Register All Files", key="ra_auto_btn", type="primary",
                      use_container_width=True):
            results = []
            progress_bar = st.progress(0, text="Starting auto-registration...")
            total = len(unregistered)
            status_container = st.container()

            for idx, filepath in enumerate(unregistered):
                fname = os.path.basename(filepath)
                progress_bar.progress(
                    (idx) / total,
                    text=f"Processing {fname} ({idx + 1}/{total})..."
                )
                res = auto_register_source(filepath, source_owner=user)
                res["file_name"] = fname
                results.append(res)
                add_audit_log(user, f"Auto-Registered: {res.get('source_id', 'N/A')} — {fname}")

            progress_bar.progress(1.0, text="Auto-registration complete!")
            st.session_state["ra_auto_results"] = results
            st.rerun()

    else:
        st.markdown(
            '<div style="text-align:center; padding:40px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; background:#F0FDF4; margin:16px 0;">'
            '<div style="font-size:2.2rem; margin-bottom:10px;">✅</div>'
            '<div style="font-size:1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
            'All files are registered</div>'
            '<div style="color:#6B7280; font-size:0.88rem; max-width:400px; margin:0 auto; line-height:1.55;">'
            'Every data file in the uploads folder has already been registered. '
            'Upload new files to the <code>uploads/</code> folder and return here to auto-register them.</div></div>',
            unsafe_allow_html=True,
        )

    # Show previous auto-registration results
    auto_results = st.session_state.get("ra_auto_results", [])
    if auto_results:
        _section("Auto-Registration Results")

        completed = [r for r in auto_results if r.get("status") == "completed"]
        partial = [r for r in auto_results if r.get("status") == "partial"]
        failed = [r for r in auto_results if r.get("status") == "failed"]

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            _metric_card("Completed", str(len(completed)), "#059669")
        with mc2:
            _metric_card("Partial", str(len(partial)), "#D97706")
        with mc3:
            _metric_card("Failed", str(len(failed)), "#DC2626")

        for res in auto_results:
            fname = res.get("file_name", "Unknown")
            status = res.get("status", "unknown")
            sid = res.get("source_id", "N/A")
            target = res.get("target_table", "N/A")
            quality = res.get("quality_score", 0)
            steps = res.get("steps_completed", [])
            errors = res.get("errors", [])
            mappings = res.get("mappings", [])

            if status == "completed":
                border_color = "#86efac"
                bg_color = "#f0fdf4"
                status_html = _status_pill("Completed", "success")
            elif status == "partial":
                border_color = "#FCD34D"
                bg_color = "#FFFBEB"
                status_html = _status_pill("Partial", "warning")
            else:
                border_color = "#FCA5A5"
                bg_color = "#FEF2F2"
                status_html = _status_pill("Failed", "error")

            mapped_count = sum(1 for m in mappings if m.get("target_column"))
            unmapped_count = sum(1 for m in mappings if not m.get("target_column"))

            step_icons = []
            all_steps = ["register", "profile", "target_table", "column_mapping", "validate", "approve"]
            step_labels_map = {
                "register": "Register", "profile": "Profile", "target_table": "Target",
                "column_mapping": "Mapping", "validate": "Validate", "approve": "Approve"
            }
            for s in all_steps:
                if s in steps:
                    step_icons.append(
                        f'<span style="background:#ECFDF5; color:#059669; font-size:0.68rem; '
                        f'font-weight:600; padding:2px 8px; border-radius:12px; margin:2px;">'
                        f'✓ {step_labels_map[s]}</span>'
                    )
                else:
                    step_icons.append(
                        f'<span style="background:#F3F4F6; color:#9CA3AF; font-size:0.68rem; '
                        f'font-weight:600; padding:2px 8px; border-radius:12px; margin:2px;">'
                        f'○ {step_labels_map[s]}</span>'
                    )
            steps_html = " ".join(step_icons)

            quality_str = f"{quality:.0%}" if isinstance(quality, float) else str(quality)

            st.markdown(
                f'<div style="border:1px solid {border_color}; background:{bg_color}; '
                f'border-radius:12px; padding:16px; margin-bottom:10px;">'
                f'<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px;">'
                f'<span style="font-weight:700; font-size:0.95rem; color:#111827;">📄 {fname}</span>'
                f'{status_html}'
                f'<span style="font-size:0.78rem; color:#6B7280;">ID: {sid}</span>'
                f'</div>'
                f'<div style="display:flex; gap:20px; font-size:0.82rem; color:#374151; '
                f'margin-bottom:8px; flex-wrap:wrap;">'
                f'<span>Target: <b>{target}</b></span>'
                f'<span>Mapped: <b>{mapped_count}</b></span>'
                f'<span>Unmapped: <b>{unmapped_count}</b></span>'
                f'<span>Quality: <b>{quality_str}</b></span>'
                f'</div>'
                f'<div style="display:flex; flex-wrap:wrap; gap:2px;">{steps_html}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if errors:
                with st.expander(f"Errors for {fname}", expanded=False):
                    for err in errors:
                        st.error(err)

        if st.button("🗑️  Clear Results", key="ra_clear_results"):
            st.session_state.pop("ra_auto_results", None)
            st.rerun()


# ════════════════════════════════════════════════════════════
#  SOURCE REGISTRY PAGE — browse all registered sources
# ════════════════════════════════════════════════════════════

def _registry_page():
    st.markdown(
        '<div style="margin-bottom:20px;">'
        '<h2 style="margin:0 0 6px 0; font-size:1.55rem; font-weight:700; color:#111827; '
        'display:flex; align-items:center; gap:10px;">'
        '<span style="flex-shrink:0;">&#128203;</span>'
        '<span>Source Registry</span></h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:0; line-height:1.6;">'
        'All data sources registered through the Registration Agent.</p></div>',
        unsafe_allow_html=True,
    )

    sources = get_registered_sources()
    if not sources:
        st.markdown(
            '<div style="text-align:center; padding:48px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; background:#FAFAFA;">'
            '<div style="font-size:2.2rem; margin-bottom:10px;">&#128203;</div>'
            '<div style="font-size:1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
            'No sources registered yet</div>'
            '<div style="color:#9CA3AF; font-size:0.88rem; max-width:400px; margin:0 auto; line-height:1.55;">'
            'Switch to the <b>Registration Agent</b> tab above to onboard your first data source. '
            'The agent will guide you through registration, profiling, mapping, and validation.</div></div>',
            unsafe_allow_html=True,
        )
        return

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        _metric_card("Total Sources", str(len(sources)))
    with mc2:
        active = sum(1 for s in sources if s.get("active_flag"))
        _metric_card("Active", str(active), "#059669")
    with mc3:
        domains = set(s.get("business_domain", "") for s in sources)
        _metric_card("Domains", str(len(domains)))

    st.markdown("---")

    for idx, src in enumerate(sources):
        sid = src.get("source_id", "")
        name = src.get("source_name", "")
        stype = src.get("source_type", "")
        domain = src.get("business_domain", "")
        active = src.get("active_flag", False)
        created = src.get("created_at", "")
        last_run = src.get("last_successful_run", "Never")

        profile = get_profile(sid)
        mappings = get_mappings(sid)
        has_profile = profile is not None
        has_mappings = len(mappings) > 0

        active_pill = _status_pill("Active", "success") if active else _status_pill("Inactive", "error")
        profile_pill = _status_pill("Profiled", "success") if has_profile else _status_pill("Not profiled", "info")
        mapping_pill = _status_pill("Mapped", "success") if has_mappings else _status_pill("Unmapped", "warning")

        row_info = ""
        if profile:
            row_info = (f'<span style="color:#6B7280; font-size:0.8rem; margin-left:8px;">'
                        f'Rows: <b>{profile.get("row_count", 0):,}</b> · '
                        f'Cols: <b>{profile.get("column_count", 0)}</b></span>')

        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:14px 18px; '
            f'background:#FAFAFA; margin-bottom:10px;">'
            f'<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; row-gap:6px;">'
            f'<span style="font-weight:700; font-size:0.95rem; color:#111827; flex-shrink:0;">{sid}</span>'
            f'<span style="font-weight:500; font-size:0.88rem; color:#374151; flex-shrink:0;">{name}</span>'
            f'<span style="display:inline-flex; gap:6px; flex-wrap:wrap; align-items:center;">'
            f'{active_pill} {profile_pill} {mapping_pill}</span>'
            f'{row_info}'
            f'</div>'
            f'<div style="margin-top:6px; font-size:0.78rem; color:#9CA3AF; word-break:break-word;">'
            f'{stype} · {domain} · Created: {created} · Last run: {last_run or "Never"}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        if has_mappings:
            with st.expander(f"View mappings for {sid}", expanded=False):
                map_rows = []
                for m in mappings:
                    map_rows.append({
                        "Mapping ID": m.get("mapping_id", ""),
                        "Source Column": m.get("source_column", ""),
                        "Target Table": m.get("target_table", ""),
                        "Target Column": m.get("target_column") or "—",
                        "Confidence": f"{m.get('mapping_confidence', 0):.0%}",
                        "Status": m.get("mapping_status", ""),
                        "Approved By": m.get("approved_by") or "—",
                    })
                st.dataframe(pd.DataFrame(map_rows), use_container_width=True, hide_index=True)
