"""
ESG Metric Analysis Agent — Streamlit view.

Provides a six-step interactive analysis of standardised ESG metrics:
  Step 1  Select metrics (filters)
  Step 2  Validate metric quality
  Step 3  Calculate trends
  Step 4  Calculate intensity metrics
  Step 5  Calculate target progress
  Step 6  Detect anomalies

Plus a Full Analysis tab that orchestrates all steps for a chosen metric.
"""

import streamlit as st
import pandas as pd
import json

from utils.metric_analysis_agent import (
    get_metric_records,
    get_metric_definition,
    validate_metric_units,
    validate_metric_quality,
    calculate_metric_trend,
    calculate_intensity,
    calculate_target_progress,
    detect_metric_anomalies,
    find_missing_metrics,
    find_missing_historical_years,
    get_metric_evidence,
    run_full_analysis,
    get_available_companies,
    get_available_metrics,
    get_available_years,
    get_company_name,
    load_metric_master,
    _check_duplicates,
)


# ════════════════════════════════════════════════════════════
#  Shared helpers
# ════════════════════════════════════════════════════════════

def _section(title, subtitle=None):
    st.markdown(
        f'<div style="margin:24px 0 8px 0;">'
        f'<h3 style="margin:0; font-size:1.15rem; font-weight:700; color:#111827;">{title}</h3>'
        + (f'<p style="color:#6B7280; font-size:0.84rem; margin:4px 0 0 0;">{subtitle}</p>' if subtitle else "")
        + '</div>',
        unsafe_allow_html=True,
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
        f'padding:4px 10px; border-radius:6px; white-space:nowrap; '
        f'display:inline-block; flex-shrink:0;">{text}</span>'
    )


def _step_badge(number, label, active=False):
    bg = "linear-gradient(135deg,#FF5A00,#FF7F32)" if active else "#E5E7EB"
    fg = "#FFFFFF" if active else "#6B7280"
    return (
        f'<div style="display:inline-flex; align-items:center; gap:6px; margin-right:12px; flex-shrink:0;">'
        f'<div style="width:28px; height:28px; background:{bg}; border-radius:50%; '
        f'display:flex; align-items:center; justify-content:center; '
        f'font-size:0.78rem; font-weight:700; color:{fg}; flex-shrink:0; min-width:28px;">{number}</div>'
        f'<span style="font-size:0.82rem; font-weight:{"600" if active else "400"}; '
        f'color:{"#111827" if active else "#9CA3AF"}; white-space:nowrap;">{label}</span></div>'
    )


def _trend_arrow(val):
    if val is None:
        return "—"
    if val > 0:
        return f'<span style="color:#DC2626;">▲ +{val}%</span>'
    elif val < 0:
        return f'<span style="color:#059669;">▼ {val}%</span>'
    return '<span style="color:#6B7280;">— 0%</span>'


def _target_color(status):
    if "Ahead" in str(status):
        return "success"
    if "on track" in str(status).lower():
        return "info"
    return "error"


def _quality_badge(status):
    status_str = str(status).strip()
    if status_str == "Pass":
        return (
            '<span style="background:#ECFDF5; color:#059669; font-size:0.78rem; font-weight:600; '
            'padding:4px 12px; border-radius:6px; display:inline-block;">🟢 Qualified</span>'
        )
    if status_str == "Qualified":
        return (
            '<span style="background:#FFFBEB; color:#D97706; font-size:0.78rem; font-weight:600; '
            'padding:4px 12px; border-radius:6px; display:inline-block;">🟡 Warning</span>'
        )
    return (
        '<span style="background:#FEF2F2; color:#DC2626; font-size:0.78rem; font-weight:600; '
        'padding:4px 12px; border-radius:6px; display:inline-block;">🔴 Error</span>'
    )


_FIELD_LABELS = {
    "metric_code": "Metric Code",
    "metric_name": "Metric Name",
    "esg_pillar": "ESG Pillar",
    "year": "Reporting Year",
    "value": "Metric Value",
    "unit": "Unit",
    "quality_status": "Quality Status",
    "quality_flags": "Quality Flags",
    "yoy_change_pct": "YoY Change (%)",
    "cagr_pct": "CAGR (%)",
    "trend_period": "Trend Period",
    "target_progress_pct": "Target Progress (%)",
    "expected_progress_pct": "Expected Progress (%)",
    "target_status": "Target Status",
}

_HIDDEN_KEYS = {"anomalies", "intensity_metrics", "evidence", "unit_issues", "error"}


def _render_analysis_table(result):
    evidence = result.get("evidence", {})
    doc_id = evidence.get("document_id")
    page = evidence.get("page")

    if doc_id:
        source_parts = [f"<b>Document ID:</b> {doc_id}"]
        if page:
            source_parts.append(f"<b>Page:</b> {page}")
        st.markdown(
            '<div style="background:#F9FAFB; border:1px solid #E5E7EB; border-radius:10px; '
            'padding:12px 18px; margin-bottom:16px; font-size:0.88rem; color:#374151;">'
            + " &nbsp;|&nbsp; ".join(source_parts) + '</div>',
            unsafe_allow_html=True,
        )

    rows_html = []
    for key in result:
        if key in _HIDDEN_KEYS:
            continue

        val = result[key]

        if isinstance(val, list) and len(val) == 0:
            continue
        if val is None or val == "":
            continue

        label = _FIELD_LABELS.get(key, key.replace("_", " ").title())

        if key == "quality_status":
            val_html = _quality_badge(val)
        elif key == "quality_flags":
            if isinstance(val, list) and val:
                tags = " ".join(
                    f'<span style="background:#FEF3C7; color:#92400E; font-size:0.72rem; '
                    f'font-weight:500; padding:3px 8px; border-radius:4px; '
                    f'display:inline-block; margin:2px 4px 2px 0;">{flag}</span>'
                    for flag in val
                )
                val_html = tags
            else:
                continue
        elif key == "target_status":
            val_html = _status_pill(val, _target_color(val))
        elif key == "value":
            val_html = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
        elif key in ("yoy_change_pct", "cagr_pct"):
            val_html = f"{val:+.2f}%" if isinstance(val, (int, float)) else str(val)
        elif key in ("target_progress_pct", "expected_progress_pct"):
            val_html = f"{val:.1f}%" if isinstance(val, (int, float)) else str(val)
        else:
            val_html = str(val)

        rows_html.append(
            f'<tr>'
            f'<td style="padding:10px 16px; font-weight:600; color:#374151; '
            f'background:#F9FAFB; border-bottom:1px solid #E5E7EB; white-space:nowrap; '
            f'width:200px; font-size:0.88rem;">{label}</td>'
            f'<td style="padding:10px 16px; color:#111827; border-bottom:1px solid #E5E7EB; '
            f'font-size:0.88rem;">{val_html}</td>'
            f'</tr>'
        )

    table_html = (
        '<div style="border:1px solid #E5E7EB; border-radius:12px; overflow:hidden; '
        'margin-bottom:16px;">'
        '<table style="width:100%; border-collapse:collapse;">'
        '<thead><tr>'
        '<th style="padding:12px 16px; text-align:left; font-size:0.78rem; font-weight:700; '
        'color:#6B7280; text-transform:uppercase; letter-spacing:0.06em; '
        'background:#F3F4F6; border-bottom:2px solid #E5E7EB;">Attribute</th>'
        '<th style="padding:12px 16px; text-align:left; font-size:0.78rem; font-weight:700; '
        'color:#6B7280; text-transform:uppercase; letter-spacing:0.06em; '
        'background:#F3F4F6; border-bottom:2px solid #E5E7EB;">Value</th>'
        '</tr></thead>'
        '<tbody>' + "".join(rows_html) + '</tbody></table></div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════
#  Render entry point
# ════════════════════════════════════════════════════════════

def render():
    top_tabs = st.tabs([
        "📊  Full Analysis",
        "📋  Metric Browser",
    ])

    with top_tabs[0]:
        _full_analysis_page()
    with top_tabs[1]:
        _metric_browser_page()


# ════════════════════════════════════════════════════════════
#  FULL ANALYSIS TAB
# ════════════════════════════════════════════════════════════

def _full_analysis_page():
    st.markdown(
        '<div class="section-heading">Metric Analysis Agent</div>'
        '<p class="section-subtitle">Select a company, metric, and year to run the full analysis pipeline.</p>',
        unsafe_allow_html=True,
    )

    with st.expander("What does the analysis include?", expanded=False):
        st.markdown(
            "The full analysis pipeline runs six checks on your selected metric:\n\n"
            "- **Quality Validation** — flags missing sources, low confidence, and unaudited values\n"
            "- **YoY Trend** — calculates year-over-year change and CAGR\n"
            "- **Intensity Metrics** — normalises emissions/energy by revenue and headcount\n"
            "- **Target Progress** — compares actual vs expected linear progress\n"
            "- **Anomaly Detection** — identifies statistical outliers and threshold breaches\n"
            "- **Evidence Trace** — links the metric value back to its source document"
        )

    companies = get_available_companies()
    if not companies:
        st.markdown(
            '<div style="text-align:center; padding:48px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; margin:12px 0; background:#FAFAFA;">'
            '<div style="font-size:2.2rem; margin-bottom:10px;">&#128202;</div>'
            '<div style="font-size:1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
            'No metric data available</div>'
            '<div style="color:#9CA3AF; font-size:0.88rem; max-width:420px; margin:0 auto; line-height:1.55;">'
            'To use the Metric Analysis Agent, first load ESG metric data. '
            'Go to <b>Data Sources</b> to upload your <code>esg_metric_data.csv</code> file, '
            'then use the <b>Registration Agent</b> to map it.</div></div>',
            unsafe_allow_html=True,
        )
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        company = st.selectbox("Company", companies, key="fa_company",
                               format_func=lambda c: f"{c} — {get_company_name(c)}")
    with col2:
        metrics = get_available_metrics(company)
        master = load_metric_master()
        def _fmt_metric(mc):
            if not master.empty:
                row = master[master["metric_code"] == mc]
                if not row.empty:
                    return f"{mc} — {row.iloc[0]['metric_name']}"
            return mc
        metric = st.selectbox("Metric", metrics, key="fa_metric", format_func=_fmt_metric)
    with col3:
        years = get_available_years(company, metric)
        year = st.selectbox("Reporting Year", years, index=len(years) - 1 if years else 0, key="fa_year")

    if st.button("Run Analysis", type="primary", key="fa_run"):
        if not company or not metric or not year:
            st.error("Please select company, metric, and year.")
            return

        with st.spinner("Running full metric analysis..."):
            result = run_full_analysis(company, metric, int(year))

        if "error" in result:
            st.error(result["error"])
            return

        st.session_state["fa_result"] = result

    result = st.session_state.get("fa_result")
    if not result:
        return

    st.markdown("---")

    # ── View toggle ──
    view_mode = st.radio(
        "Display mode",
        ["View Formatted Table", "View Raw JSON"],
        horizontal=True,
        key="fa_view_mode",
        label_visibility="collapsed",
    )

    if view_mode == "View Raw JSON":
        st.json(result)
    else:
        _render_analysis_table(result)

        # ── Intensity metrics (separate section below table) ──
        intensities = result.get("intensity_metrics", [])
        if intensities:
            _section("Intensity Metrics")
            cols = st.columns(min(len(intensities), 3))
            for i, im in enumerate(intensities):
                with cols[i % len(cols)]:
                    _metric_card(im["name"], f"{im['value']:,.4f}")

        # ── Anomalies ──
        anomalies = result.get("anomalies", [])
        if anomalies:
            _section("Anomalies Detected", f"{len(anomalies)} anomaly(ies) found")
            anom_df = pd.DataFrame(anomalies)
            st.dataframe(anom_df, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════
#  STEP-BY-STEP TAB
# ════════════════════════════════════════════════════════════

def _step_by_step_page():
    st.markdown(
        '<div class="section-heading">Step-by-Step Analysis</div>'
        '<p class="section-subtitle">Walk through each analysis step individually</p>',
        unsafe_allow_html=True,
    )

    companies = get_available_companies()
    if not companies:
        st.warning("No metric data available.")
        return

    col1, col2 = st.columns(2)
    with col1:
        company = st.selectbox("Company", companies, key="sbs_company",
                               format_func=lambda c: f"{c} — {get_company_name(c)}")
    with col2:
        master = load_metric_master()
        pillar_options = ["All"] + sorted(master["esg_pillar"].unique().tolist()) if not master.empty else ["All"]
        pillar = st.selectbox("ESG Pillar", pillar_options, key="sbs_pillar")

    step_tabs = st.tabs([
        "1️⃣ Select",
        "2️⃣ Quality",
        "3️⃣ Trends",
        "4️⃣ Intensity",
        "5️⃣ Targets",
        "6️⃣ Anomalies",
    ])

    esg_pillar_filter = pillar if pillar != "All" else None

    # ── Step 1: Select ──
    with step_tabs[0]:
        _section("Step 1 — Select Applicable Metrics", "Filter metric records by company, pillar, year, and metric code")

        c1, c2, c3 = st.columns(3)
        with c1:
            metrics = get_available_metrics(company)
            metric_filter = st.selectbox("Metric Code", ["All"] + metrics, key="s1_metric")
        with c2:
            years = get_available_years(company)
            year_filter = st.selectbox("Reporting Year", ["All"] + [str(y) for y in years], key="s1_year")
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            run_step1 = st.button("Fetch Records", type="primary", key="s1_run")

        if run_step1:
            records = get_metric_records(
                company_id=company,
                metric_code=metric_filter if metric_filter != "All" else None,
                reporting_year=int(year_filter) if year_filter != "All" else None,
                esg_pillar=esg_pillar_filter,
            )
            st.session_state["s1_records"] = records

        records = st.session_state.get("s1_records")
        if records is not None and not records.empty:
            st.success(f"Found {len(records)} record(s)")
            st.dataframe(records, use_container_width=True, hide_index=True)
        elif records is not None:
            st.info("No records match the selected filters.")

    # ── Step 2: Quality ──
    with step_tabs[1]:
        _section("Step 2 — Validate Metric Quality", "Check for missing sources, low confidence, unaudited values, duplicates")

        if st.button("Run Quality Validation", type="primary", key="s2_run"):
            records = st.session_state.get("s1_records")
            if records is None or records.empty:
                records = get_metric_records(company_id=company, esg_pillar=esg_pillar_filter)

            quality = validate_metric_quality(records)
            unit_issues = validate_metric_units(records)
            duplicates = _check_duplicates(records)

            st.session_state["s2_quality"] = quality
            st.session_state["s2_units"] = unit_issues
            st.session_state["s2_dupes"] = duplicates

        quality = st.session_state.get("s2_quality")
        if quality:
            passed = sum(1 for q in quality if q["quality_status"] == "Pass")
            flagged = len(quality) - passed

            c1, c2, c3 = st.columns(3)
            with c1:
                _metric_card("Total Records", str(len(quality)))
            with c2:
                _metric_card("Passed", str(passed), color="#059669")
            with c3:
                _metric_card("Flagged", str(flagged), color="#DC2626" if flagged else "#059669")

            flagged_records = [q for q in quality if q["quality_status"] != "Pass"]
            if flagged_records:
                _section("Flagged Records")
                for q in flagged_records:
                    with st.expander(f"{q['metric_code']} ({q['reporting_year']}) — {len(q['quality_flags'])} flag(s)"):
                        for f in q["quality_flags"]:
                            st.markdown(f"- ⚠️ {f}")

            unit_issues = st.session_state.get("s2_units", [])
            if unit_issues:
                _section("Unit Incompatibilities")
                st.dataframe(pd.DataFrame(unit_issues), use_container_width=True, hide_index=True)

            dupes = st.session_state.get("s2_dupes", [])
            if dupes:
                _section("Duplicate Records")
                st.dataframe(pd.DataFrame(dupes), use_container_width=True, hide_index=True)

    # ── Step 3: Trends ──
    with step_tabs[2]:
        _section("Step 3 — Calculate Trends", "Year-over-year change, percentage change, and CAGR")

        metrics = get_available_metrics(company)
        metric_sel = st.selectbox("Metric", metrics, key="s3_metric",
                                  format_func=lambda mc: f"{mc} — {(get_metric_definition(mc) or {}).get('metric_name', mc)}")

        if st.button("Calculate Trend", type="primary", key="s3_run"):
            trend = calculate_metric_trend(company, metric_sel)
            st.session_state["s3_trend"] = trend

        trend = st.session_state.get("s3_trend")
        if trend:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                _metric_card("Period", trend["period"])
            with c2:
                _metric_card("Data Points", str(trend["data_points"]))
            with c3:
                yoy = trend.get("latest_yoy_change_pct")
                _metric_card("Latest YoY", f"{yoy:+.1f}%" if yoy is not None else "N/A")
            with c4:
                cagr = trend.get("cagr_pct")
                _metric_card("CAGR", f"{cagr:+.2f}%" if cagr is not None else "N/A")

            if trend.get("trend_detail"):
                _section("Year-over-Year Detail")
                detail_df = pd.DataFrame(trend["trend_detail"])
                st.dataframe(detail_df, use_container_width=True, hide_index=True)

                chart_data = pd.DataFrame({
                    "Year": [d["to_year"] for d in trend["trend_detail"]],
                    "Value": [d["current_value"] for d in trend["trend_detail"]],
                })
                chart_data = pd.concat([
                    pd.DataFrame({"Year": [trend["trend_detail"][0]["from_year"]],
                                  "Value": [trend["trend_detail"][0]["previous_value"]]}),
                    chart_data,
                ]).reset_index(drop=True)
                st.line_chart(chart_data.set_index("Year"), use_container_width=True)

    # ── Step 4: Intensity ──
    with step_tabs[3]:
        _section("Step 4 — Calculate Intensity Metrics", "Emissions and energy normalised by revenue and headcount")

        years = get_available_years(company)
        year_sel = st.selectbox("Reporting Year", years, index=len(years) - 1 if years else 0, key="s4_year")

        if st.button("Calculate Intensities", type="primary", key="s4_run"):
            intensity = calculate_intensity(company, int(year_sel))
            st.session_state["s4_intensity"] = intensity

        intensity = st.session_state.get("s4_intensity")
        if intensity and intensity.get("intensities"):
            c1, c2, c3 = st.columns(3)
            with c1:
                _metric_card("Revenue", f"{intensity['revenue']:,.0f} {intensity['currency']}")
            with c2:
                _metric_card("Employees", f"{intensity['employee_count']:,}")
            with c3:
                _metric_card("Year", str(intensity["reporting_year"]))

            _section("Intensity Results")
            for im in intensity["intensities"]:
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**{im['name']}**")
                with c2:
                    st.markdown(f"**{im['value']:,.4f}**")
        elif intensity is not None and not intensity.get("intensities"):
            st.info("No intensity metrics could be calculated (missing emissions or financial data).")

    # ── Step 5: Targets ──
    with step_tabs[4]:
        _section("Step 5 — Calculate Target Progress", "Actual vs expected linear progress for ESG targets")

        metrics = get_available_metrics(company)
        metric_sel = st.selectbox("Metric (or All)", ["All"] + metrics, key="s5_metric")
        years = get_available_years(company)
        year_sel = st.selectbox("Year", years, index=len(years) - 1 if years else 0, key="s5_year")

        if st.button("Calculate Progress", type="primary", key="s5_run"):
            progress = calculate_target_progress(
                company,
                metric_code=metric_sel if metric_sel != "All" else None,
                reporting_year=int(year_sel),
            )
            st.session_state["s5_progress"] = progress

        progress = st.session_state.get("s5_progress")
        if progress:
            for p in progress:
                status_var = _target_color(p["target_status"])
                with st.expander(
                    f"{p['metric_code']} — {p['target_name']}  |  {p['target_status']}"
                ):
                    c1, c2, c3, c4 = st.columns(4)
                    with c1:
                        _metric_card("Actual Progress", f"{p['actual_progress_pct']:.1f}%")
                    with c2:
                        _metric_card("Expected Progress", f"{p['expected_progress_pct']:.1f}%")
                    with c3:
                        _metric_card("Variance", f"{p['variance_pp']:+.1f} pp",
                                     color="#059669" if p["variance_pp"] >= 0 else "#DC2626")
                    with c4:
                        st.markdown(
                            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px;">'
                            f'<div style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
                            f'letter-spacing:0.08em; margin-bottom:4px;">STATUS</div>'
                            f'<div>{_status_pill(p["target_status"], status_var)}</div></div>',
                            unsafe_allow_html=True,
                        )

                    st.markdown(
                        f"**Base:** {p['base_value']:,.2f} ({p['base_year']}) → "
                        f"**Target:** {p['target_value']:,.2f} ({p['target_year']}) &nbsp; | &nbsp; "
                        f"**Current:** {p['current_value']:,.2f} ({p['current_year']})"
                    )

                    pct_val = min(p["actual_progress_pct"], 100)
                    bar_color = "#059669" if p["variance_pp"] >= 0 else "#DC2626"
                    st.markdown(
                        f'<div style="background:#F3F4F6; border-radius:8px; height:12px; margin-top:8px; position:relative;">'
                        f'<div style="background:{bar_color}; border-radius:8px; height:12px; width:{pct_val}%;"></div>'
                        f'<div style="position:absolute; top:-2px; left:{min(p["expected_progress_pct"], 100)}%; '
                        f'width:2px; height:16px; background:#6B7280;"></div></div>',
                        unsafe_allow_html=True,
                    )
        elif progress is not None:
            st.info("No ESG targets found for this company/metric.")

    # ── Step 6: Anomalies ──
    with step_tabs[5]:
        _section("Step 6 — Detect Anomalies", "Rule-based thresholds and statistical outlier detection")

        metrics = get_available_metrics(company)
        metric_sel = st.selectbox("Metric (or All)", ["All"] + metrics, key="s6_metric")

        if st.button("Detect Anomalies", type="primary", key="s6_run"):
            anomalies = detect_metric_anomalies(
                company,
                metric_code=metric_sel if metric_sel != "All" else None,
            )
            st.session_state["s6_anomalies"] = anomalies

        anomalies = st.session_state.get("s6_anomalies")
        if anomalies:
            high = sum(1 for a in anomalies if a.get("severity") == "High")
            med = len(anomalies) - high

            c1, c2, c3 = st.columns(3)
            with c1:
                _metric_card("Total Anomalies", str(len(anomalies)))
            with c2:
                _metric_card("High Severity", str(high), color="#DC2626")
            with c3:
                _metric_card("Medium Severity", str(med), color="#D97706")

            st.dataframe(pd.DataFrame(anomalies), use_container_width=True, hide_index=True)
        elif anomalies is not None:
            st.success("No anomalies detected.")


# ════════════════════════════════════════════════════════════
#  METRIC BROWSER TAB
# ════════════════════════════════════════════════════════════

def _metric_browser_page():
    st.markdown(
        '<div class="section-heading">Metric Browser</div>'
        '<p class="section-subtitle">Browse the ESG metric catalogue, find reporting gaps, and trace values back to source documents.</p>',
        unsafe_allow_html=True,
    )

    sub_tabs = st.tabs(["📖 Metric Catalogue", "🔎 Coverage Gaps", "📄 Evidence Trace"])

    # ── Catalogue ──
    with sub_tabs[0]:
        master = load_metric_master()
        if master.empty:
            st.info("No metric master catalogue found.")
        else:
            pillar = st.selectbox("Filter by Pillar", ["All"] + sorted(master["esg_pillar"].unique().tolist()),
                                  key="mb_pillar")
            display = master if pillar == "All" else master[master["esg_pillar"] == pillar]
            st.dataframe(display, use_container_width=True, hide_index=True)

    # ── Coverage Gaps ──
    with sub_tabs[1]:
        companies = get_available_companies()
        if not companies:
            st.warning("No data available.")
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            company = st.selectbox("Company", companies, key="mb_company",
                                   format_func=lambda c: f"{c} — {get_company_name(c)}")
        with c2:
            years = get_available_years(company)
            year = st.selectbox("Year", years, index=len(years) - 1 if years else 0, key="mb_year")
        with c3:
            master = load_metric_master()
            pillar_opts = ["All"] + sorted(master["esg_pillar"].unique().tolist()) if not master.empty else ["All"]
            pillar = st.selectbox("Pillar", pillar_opts, key="mb_gap_pillar")

        if st.button("Find Missing Metrics", type="primary", key="mb_run"):
            missing = find_missing_metrics(company, int(year), esg_pillar=pillar if pillar != "All" else None)
            st.session_state["mb_missing"] = missing

        missing = st.session_state.get("mb_missing")
        if missing:
            st.warning(f"{len(missing)} metric(s) not reported for {company} in {year}")
            st.dataframe(pd.DataFrame(missing), use_container_width=True, hide_index=True)
        elif missing is not None:
            st.success("All expected metrics are reported.")

    # ── Evidence Trace ──
    with sub_tabs[2]:
        companies = get_available_companies()
        if not companies:
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            company = st.selectbox("Company", companies, key="ev_company",
                                   format_func=lambda c: f"{c} — {get_company_name(c)}")
        with c2:
            metrics = get_available_metrics(company)
            metric = st.selectbox("Metric", metrics, key="ev_metric")
        with c3:
            years = get_available_years(company, metric)
            year = st.selectbox("Year", years, index=len(years) - 1 if years else 0, key="ev_year")

        if st.button("Trace Evidence", type="primary", key="ev_run"):
            evidence = get_metric_evidence(company_id=company, metric_code=metric, reporting_year=int(year))
            st.session_state["ev_result"] = evidence

        evidence = st.session_state.get("ev_result")
        if evidence:
            _section("Metric Value")
            c1, c2, c3 = st.columns(3)
            with c1:
                _metric_card("Value", f"{evidence['value']} {evidence['unit']}")
            with c2:
                _metric_card("Confidence", f"{evidence.get('confidence_score', 'N/A')}")
            with c3:
                _metric_card("Extraction", evidence.get("extraction_method", "N/A"))

            _section("Source Document")
            doc = evidence.get("document")
            if doc:
                st.markdown(
                    f"**Document ID:** {evidence['document_id']}  \n"
                    f"**Name:** {doc.get('document_name', 'N/A')}  \n"
                    f"**Type:** {doc.get('document_type', 'N/A')}  \n"
                    f"**Page:** {evidence.get('source_page', 'N/A')}  \n"
                    f"**Audited:** {doc.get('audited_flag', 'N/A')}  \n"
                    f"**Auditor:** {doc.get('auditor_name', 'N/A')}"
                )
            else:
                st.markdown(
                    f"**Document ID:** {evidence.get('document_id', 'N/A')}  \n"
                    f"**Page:** {evidence.get('source_page', 'N/A')}"
                )
