"""
Regulatory Tracker Agent -- Streamlit view.

Monitors global ESG frameworks with automated compliance analysis,
radar-chart visualisation, gap analysis, framework-update tracking,
and AI-generated compliance narratives.
"""

import io
import streamlit as st
import pandas as pd
import json
import plotly.graph_objects as go
from datetime import datetime, timedelta

from utils.compliance_agent import (
    run_full_compliance_assessment,
    run_multi_regulation_assessment,
    get_available_companies,
    get_available_years,
    get_company_name,
    load_regulation_master,
    get_regulation_abbreviation,
    get_all_regulation_abbreviations,
    extract_gap_analysis,
    compute_compliance_summary,
    extract_radar_chart_data,
    generate_compliance_narrative,
    generate_executive_narrative_llm,
    load_framework_updates,
    apply_framework_update,
    dismiss_framework_update,
    refresh_framework_updates_check,
    log_compliance_action,
    create_notification,
    get_notifications,
    mark_notification_read,
    mark_all_notifications_read,
    generate_compliance_notifications,
    REGULATION_ABBREVIATIONS,
)
from utils.auth import is_admin
from utils.json_manager import read_json


# ════════════════════════════════════════════════════════════
#  Shared helpers
# ════════════════════════════════════════════════════════════

def _section(title, subtitle=None):
    st.markdown(
        f'<h3 style="font-size:1.15rem; font-weight:700; color:#111827; margin:18px 0 6px 0;">'
        f'{title}</h3>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(
            f'<p style="color:#6B7280; font-size:0.84rem; margin-top:-4px; line-height:1.5;">'
            f'{subtitle}</p>',
            unsafe_allow_html=True,
        )


def _metric_card(label, value, color="#111827", accent=None):
    accent_css = f"border-left:4px solid {accent or color};" if accent or color != "#111827" else ""
    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px; {accent_css}">'
        f'<div style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
        f'letter-spacing:0.08em; margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:1.6rem; font-weight:800; color:{color};">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _status_pill(text, variant="info"):
    colors = {
        "success": ("#ECFDF5", "#059669"), "warning": ("#FFFBEB", "#D97706"),
        "error": ("#FEF2F2", "#DC2626"), "info": ("#EFF6FF", "#2563EB"),
        "neutral": ("#F3F4F6", "#6B7280"), "critical": ("#FEF2F2", "#991B1B"),
    }
    bg, fg = colors.get(variant, colors["info"])
    return (
        f'<span style="display:inline-block; background:{bg}; color:{fg}; '
        f'font-size:0.72rem; font-weight:600; padding:3px 10px; border-radius:6px;">'
        f'{text}</span>'
    )


def _priority_dot(priority):
    emojis = {"Critical": "\U0001f534", "High": "\U0001f7e0", "Medium": "\U0001f7e1", "Low": "\U0001f7e2"}
    return f'{emojis.get(priority, "⚪")} {priority}'


def _render_remediation_section(title, items):
    st.markdown(
        f'<div style="margin-bottom:12px;">'
        f'<div style="font-weight:700; font-size:0.85rem; color:#FF5A00; margin-bottom:4px;">{title}</div>'
        f'<ul style="margin:0; padding-left:18px; font-size:0.83rem; color:#374151; line-height:1.7;">'
        + "".join(f"<li>{item}</li>" for item in items)
        + '</ul></div>',
        unsafe_allow_html=True,
    )


def _find_requirement_result(all_results, requirement_id):
    for reg in all_results:
        for req in reg.get("results", []):
            if req.get("requirement_id") == requirement_id:
                return req
    return None


# ════════════════════════════════════════════════════════════
#  Main render
# ════════════════════════════════════════════════════════════

def render():
    _render_header()
    st.markdown("---")

    selected_frameworks = _render_framework_selector()
    if not selected_frameworks:
        st.info("Select at least one framework above to begin.")
        return

    companies = get_available_companies()
    years = get_available_years()

    if not companies or not years:
        st.markdown(
            '<div style="text-align:center; padding:48px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; margin:12px 0; background:#FAFAFA;">'
            '<div style="font-size:2.2rem; margin-bottom:10px;">&#128203;</div>'
            '<div style="font-size:1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
            'No deal or company data available</div>'
            '<div style="color:#9CA3AF; font-size:0.88rem; max-width:420px; margin:0 auto; line-height:1.55;">'
            'Head to <b>Data Sources</b> to upload your files, '
            'then use the <b>Registration Agent</b> to map them.</div></div>',
            unsafe_allow_html=True,
        )
        return

    if st.button("\U0001f4ca Run Compliance Analysis", type="primary", key="rta_run"):
        company = companies[0]
        year = years[-1]
        user = st.session_state.get("user", "system")

        with st.spinner("Running compliance analysis across selected frameworks..."):
            all_results = []
            regs = load_regulation_master()
            for _, reg_row in regs.iterrows():
                reg_id = reg_row["regulation_id"]
                abbr = get_regulation_abbreviation(reg_id)
                if abbr in selected_frameworks:
                    result = run_full_compliance_assessment(company, reg_id, int(year))
                    all_results.append(result)

            st.session_state["rta_results"] = all_results
            st.session_state["rta_company"] = company
            st.session_state["rta_year"] = year

        log_compliance_action(user, "Compliance Analysis Run", details=f"Analyzed {len(all_results)} frameworks")
        generate_compliance_notifications(all_results, user)

    if st.session_state.get("rta_results"):
        st.markdown(
            '<div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:12px; '
            'padding:14px 20px; margin:16px 0;">'
            '<span style="color:#059669; font-weight:600;">✓ Compliance analysis complete!</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown("---")
        _render_summary_stats(st.session_state["rta_results"])
        st.markdown("---")

        tab_names = [
            "Compliance Radar",
            "Gap Analysis",
            "Global Framework Updates",
            "AI Narrative",
        ]
        if is_admin():
            tab_names.append("Audit Trail")

        tabs = st.tabs(tab_names)

        with tabs[0]:
            _render_compliance_radar(st.session_state["rta_results"])
        with tabs[1]:
            _render_gap_analysis(st.session_state["rta_results"])
        with tabs[2]:
            _render_framework_updates()
        with tabs[3]:
            _render_ai_narrative(
                st.session_state["rta_results"],
                st.session_state.get("rta_company", ""),
                st.session_state.get("rta_year", ""),
            )
        if is_admin():
            with tabs[4]:
                _render_audit_trail()


# ════════════════════════════════════════════════════════════
#  Header with notification bell
# ════════════════════════════════════════════════════════════

def _render_header():
    source_data = read_json("source_registry.json")
    sources = source_data.get("sources", [])
    if not sources:
        ds_data = read_json("datasources.json")
        sources = ds_data.get("connections", [])
    source_count = len(sources)

    user = st.session_state.get("user", "system")
    unread = get_notifications(user=user, unread_only=True)
    unread_count = len(unread)

    badge_html = ""
    if unread_count > 0:
        badge_html = (
            f'<span style="background:#DC2626; color:white; font-size:0.65rem; font-weight:700; '
            f'border-radius:50%; width:20px; height:20px; display:inline-flex; align-items:center; '
            f'justify-content:center; margin-left:8px; vertical-align:top;">{unread_count}</span>'
        )

    st.markdown(
        f'<div style="margin-bottom:8px;">'
        f'<div style="display:flex; align-items:center; gap:14px; margin-bottom:6px;">'
        f'<div style="width:46px; height:46px; background:linear-gradient(135deg,#FF5A00,#FF7F32); '
        f'border-radius:12px; display:flex; align-items:center; justify-content:center; '
        f'font-size:1.4rem; color:white; box-shadow:0 3px 10px rgba(255,90,0,0.25);">\U0001f4cb</div>'
        f'<div>'
        f'<h2 style="margin:0; font-size:1.65rem; font-weight:700; color:#111827; line-height:1.2;">'
        f'Regulatory Tracker Agent{badge_html}</h2>'
        f'</div></div>'
        f'<p style="color:#6B7280; font-size:0.88rem; font-style:italic; margin:8px 0 0 0; line-height:1.6;">'
        f'Monitors global ESG frameworks &mdash; auto-updates within 24 hours of any mandate shift</p>'
        f'<p style="color:#9CA3AF; font-size:0.82rem; margin:6px 0 0 0;">'
        f'\U0001f4dd <b>{source_count}</b> real source(s) registered &mdash; '
        f'head to the <b>Data Collector</b> page to ingest them for the first time.</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if unread_count > 0:
        with st.expander(f"\U0001f514 Notifications ({unread_count} unread)", expanded=False):
            category_icons = {
                "critical_gap": "\U0001f534", "compliance_drop": "\U0001f4c9",
                "regulatory_change": "\U0001f4e2", "deadline": "⏰", "info": "\U0001f514",
            }
            for n in unread[:10]:
                icon = category_icons.get(n.get("category", "info"), "\U0001f514")
                st.markdown(
                    f'<div style="border-bottom:1px solid #F3F4F6; padding:8px 0;">'
                    f'<div style="font-weight:600; font-size:0.85rem; color:#111827;">{icon} {n["title"]}</div>'
                    f'<div style="font-size:0.78rem; color:#6B7280; margin-top:2px;">{n["message"]}</div>'
                    f'<div style="font-size:0.7rem; color:#9CA3AF; margin-top:2px;">{n["timestamp"]}</div></div>',
                    unsafe_allow_html=True,
                )
            if st.button("Mark all as read", key="rta_mark_all_read"):
                mark_all_notifications_read(user)
                st.rerun()


# ════════════════════════════════════════════════════════════
#  Framework selector
# ════════════════════════════════════════════════════════════

def _render_framework_selector():
    all_abbrs = get_all_regulation_abbreviations()
    options = [info["abbr"] for info in all_abbrs.values()]
    if not options:
        return []
    st.markdown(
        '<p style="font-size:0.82rem; font-weight:600; color:#374151; margin-bottom:4px;">'
        'Frameworks to analyze</p>',
        unsafe_allow_html=True,
    )
    return st.multiselect(
        "Frameworks to analyze", options=options, default=options,
        key="rta_frameworks", label_visibility="collapsed",
    )


# ════════════════════════════════════════════════════════════
#  Summary stats
# ════════════════════════════════════════════════════════════

def _render_summary_stats(all_results):
    stats = compute_compliance_summary(all_results)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        score = stats["overall_compliance"]
        color = "#059669" if score >= 80 else "#D97706" if score >= 60 else "#DC2626"
        _metric_card("OVERALL COMPLIANCE", f"{score:.1f}%", color=color, accent=color)
    with c2:
        _metric_card("FRAMEWORKS ANALYZED", str(stats["frameworks_analyzed"]), accent="#3B82F6")
    with c3:
        gc = "#DC2626" if stats["total_gaps"] > 0 else "#059669"
        _metric_card("TOTAL GAPS", str(stats["total_gaps"]), color=gc, accent=gc)
    with c4:
        pc = "#D97706" if stats["pending_updates"] > 0 else "#059669"
        _metric_card("PENDING UPDATES", str(stats["pending_updates"]), color=pc, accent=pc)


# ════════════════════════════════════════════════════════════
#  Tab 1 — Compliance Radar
# ════════════════════════════════════════════════════════════

def _render_compliance_radar(all_results):
    _section("Framework Compliance Score")

    chart_data = extract_radar_chart_data(all_results)
    if not chart_data:
        st.info("No data for compliance visualization.")
        return

    categories = [d["framework"] for d in chart_data]
    values = [d["compliance_pct"] for d in chart_data]

    marker_colors = []
    for v in values:
        if v >= 95:
            marker_colors.append("#059669")
        elif v >= 80:
            marker_colors.append("#D97706")
        else:
            marker_colors.append("#DC2626")

    if len(categories) >= 3:
        categories_closed = categories + [categories[0]]
        values_closed = values + [values[0]]
        colors_closed = marker_colors + [marker_colors[0]]

        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill='toself',
            fillcolor='rgba(255, 90, 0, 0.08)',
            line=dict(color='#FF5A00', width=2.5),
            marker=dict(size=10, color=colors_closed, line=dict(width=2, color='white')),
            name='Compliance %',
            hovertemplate='%{theta}: %{r:.1f}%<extra></extra>',
        ))

        fig.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], tickvals=[20, 40, 60, 80, 100],
                                tickfont=dict(size=10, color="#9CA3AF"),
                                gridcolor="#E5E7EB"),
                angularaxis=dict(tickfont=dict(size=13, color="#374151"), gridcolor="#E5E7EB"),
                bgcolor='rgba(0,0,0,0)',
            ),
            showlegend=False,
            height=450,
            margin=dict(t=40, b=40, l=60, r=60),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=categories, y=values,
            marker_color=marker_colors,
            text=[f"{v:.0f}%" for v in values],
            textposition='outside',
            textfont=dict(size=13, color="#374151"),
        ))
        fig.update_layout(
            yaxis=dict(range=[0, 110], title="Compliance %"),
            xaxis=dict(title=""),
            height=350,
            margin=dict(t=30, b=40),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
        )
        st.plotly_chart(fig, use_container_width=True)

    _section("Framework Compliance Table")

    table_data = []
    for d in chart_data:
        table_data.append({
            "Framework": d["framework"],
            "Full Name": d["full_name"],
            "Mandatory": d["mandatory"],
            "Compliance": d["compliance_pct"],
            "Covered": d["covered"],
            "Partial": d["partial"],
            "Missing": d["missing"],
            "Total": d["total"],
        })

    df = pd.DataFrame(table_data)

    filter_col, _, export_csv_col, export_xlsx_col = st.columns([3, 2, 1.5, 1.5])
    with filter_col:
        filter_text = st.text_input("Filter frameworks", key="rta_fw_filter", placeholder="Type to filter...")
    if filter_text:
        df = df[df.apply(lambda r: filter_text.lower() in r.to_string().lower(), axis=1)]

    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "Compliance": st.column_config.ProgressColumn("Compliance", min_value=0, max_value=100, format="%.1f%%"),
        },
    )

    with export_csv_col:
        st.download_button(
            "\U0001f4e5 Export CSV", df.to_csv(index=False),
            "compliance_frameworks.csv", "text/csv", key="rta_export_csv",
        )
    with export_xlsx_col:
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        st.download_button(
            "\U0001f4e5 Export Excel", buf.getvalue(),
            "compliance_frameworks.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="rta_export_xlsx",
        )


# ════════════════════════════════════════════════════════════
#  Tab 2 — Gap Analysis
# ════════════════════════════════════════════════════════════

_IMPROVEMENT_MAP = {
    "no data mapping available": "Upload and map relevant data source",
    "no metric data found": "Collect and upload the required metric data",
    "no supporting document found": "Prepare and upload the required disclosure document",
    "reporting period mismatch": "Update data to cover the current reporting period",
    "no assurance obtained": "Obtain independent third-party assurance for this metric",
    "insufficient evidence": "Gather additional evidence and supporting documentation",
    "data quality below threshold": "Review and improve data quality controls",
    "pending regulatory update requires review": "Review the regulatory update and update compliance documentation",
}


def _derive_improvement(reason):
    """Generate an improvement suggestion from the gap reason text (UI layer only)."""
    if not reason:
        return "Review and address the identified gap"
    reason_lower = reason.lower().strip()
    for key, suggestion in _IMPROVEMENT_MAP.items():
        if key in reason_lower:
            return suggestion
    if "no " in reason_lower and "data" in reason_lower:
        return "Identify and upload the required data source"
    if "no " in reason_lower and "document" in reason_lower:
        return "Prepare and upload the required document"
    if "missing" in reason_lower:
        return "Collect and provide the missing information"
    if "assurance" in reason_lower:
        return "Obtain independent assurance or verification"
    return "Review gap details and implement corrective action"


def _render_gap_analysis(all_results):
    st.markdown(
        '<p style="color:#6B7280; font-size:0.85rem; margin-bottom:16px;">'
        'Identified compliance gaps with suggested improvements.</p>',
        unsafe_allow_html=True,
    )

    gap_data = extract_gap_analysis(all_results)
    total_gaps = sum(gd["gap_count"] for gd in gap_data)

    if total_gaps == 0:
        st.success("No compliance gaps identified across all analyzed frameworks.")
        return

    for gd in gap_data:
        if gd["gap_count"] == 0:
            continue

        _section(f"{gd['abbreviation']} Gaps ({gd['gap_count']})")

        header = (
            '<table style="width:100%; border-collapse:collapse; font-size:0.82rem; margin-bottom:4px;">'
            '<thead><tr style="border-bottom:2px solid #E5E7EB;">'
            '<th style="text-align:left; padding:10px 8px; color:#6B7280; font-weight:600; width:10%;">ID</th>'
            '<th style="text-align:left; padding:10px 8px; color:#6B7280; font-weight:600; width:22%;">Requirement</th>'
            '<th style="text-align:left; padding:10px 8px; color:#6B7280; font-weight:600; width:8%;">Status</th>'
            '<th style="text-align:left; padding:10px 8px; color:#6B7280; font-weight:600; width:9%;">Priority</th>'
            '<th style="text-align:left; padding:10px 8px; color:#6B7280; font-weight:600; width:23%;">Reason</th>'
            '<th style="text-align:left; padding:10px 8px; color:#6B7280; font-weight:600; width:28%;">Improvement</th>'
            '</tr></thead><tbody>'
        )
        rows_html = ""
        for g in gd["gaps"]:
            reason = g.get("reason", "No data mapping available")
            recommendation = g.get("recommendation", "")
            improvement = recommendation if recommendation else _derive_improvement(reason)

            rows_html += (
                f'<tr style="border-bottom:1px solid #F3F4F6;">'
                f'<td style="padding:10px 8px; color:#111827; font-weight:500;">{g["requirement_id"]}</td>'
                f'<td style="padding:10px 8px; color:#374151; line-height:1.4;">{g["requirement_name"]}</td>'
                f'<td style="padding:10px 8px;">{_status_pill(g["status"])}</td>'
                f'<td style="padding:10px 8px;">{_priority_dot(g["priority"])}</td>'
                f'<td style="padding:10px 8px; color:#6B7280; font-size:0.8rem; line-height:1.4;">{reason}</td>'
                f'<td style="padding:10px 8px; color:#374151; font-size:0.8rem; line-height:1.4;">{improvement}</td>'
                f'</tr>'
            )
        st.markdown(header + rows_html + '</tbody></table>', unsafe_allow_html=True)

        st.markdown("")


# ════════════════════════════════════════════════════════════
#  Tab 3 — Global Framework Updates
# ════════════════════════════════════════════════════════════

def _render_regulatory_feed():
    _section("Regulatory Change Feed", "Chronological timeline of detected regulatory changes")

    updates_data = load_framework_updates()
    updates = updates_data.get("updates", [])

    sorted_updates = sorted(updates, key=lambda u: u.get("published_date", ""), reverse=True)
    severity_colors = {"critical": "#DC2626", "high": "#F59E0B", "medium": "#3B82F6", "low": "#10B981"}

    for i, u in enumerate(sorted_updates[:12]):
        dot_color = severity_colors.get(u.get("severity", "medium"), "#3B82F6")
        status = u.get("status", "").replace("_", " ").title()
        status_var = "warning" if u.get("status") == "pending_review" else "success" if u.get("status") == "applied" else "neutral"
        pill = _status_pill(status, status_var)

        connecting_line = '<div style="width:2px; flex:1; background:#E5E7EB;"></div>' if i < min(len(sorted_updates), 12) - 1 else ""

        st.markdown(
            f'<div style="display:flex; gap:16px; margin-bottom:0; padding-left:8px;">'
            f'<div style="display:flex; flex-direction:column; align-items:center; min-width:20px;">'
            f'<div style="width:14px; height:14px; border-radius:50%; background:{dot_color}; '
            f'border:3px solid white; box-shadow:0 0 0 2px {dot_color}; z-index:1; flex-shrink:0;"></div>'
            f'{connecting_line}</div>'
            f'<div style="flex:1; border:1px solid #E5E7EB; border-radius:12px; padding:16px; margin-bottom:16px; background:white;">'
            f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">'
            f'<span style="font-weight:700; font-size:0.9rem; color:#111827;">{u.get("framework_abbr", "")}</span>'
            f'{pill}</div>'
            f'<div style="font-weight:600; font-size:0.88rem; color:#374151; margin-bottom:6px;">{u["title"]}</div>'
            f'<div style="font-size:0.82rem; color:#6B7280; line-height:1.6; margin-bottom:10px;">'
            f'{u["description"][:250]}{"..." if len(u.get("description", "")) > 250 else ""}</div>'
            f'<div style="display:flex; gap:16px; flex-wrap:wrap; font-size:0.75rem; color:#9CA3AF;">'
            f'<span>Published: {u.get("published_date", "N/A")}</span>'
            f'<span>Severity: <b style="color:{dot_color};">{u.get("severity", "").capitalize()}</b></span>'
            f'<span>Source: {u.get("source_url", "N/A")}</span>'
            f'</div></div></div>',
            unsafe_allow_html=True,
        )


def _render_framework_updates():
    _render_regulatory_feed()

    st.markdown("---")

    _section(
        "Framework Update Management",
        "Review, apply, or dismiss pending regulatory updates. "
        "Applied updates feed into gap analysis; dismissed updates are archived.",
    )

    updates_data = load_framework_updates()
    updates = updates_data.get("updates", [])
    last_checked = updates_data.get("last_checked")
    audit_log = updates_data.get("audit_log", [])

    pending = [u for u in updates if u["status"] == "pending_review"]
    applied = [u for u in updates if u["status"] == "applied"]
    dismissed = [u for u in updates if u["status"] == "dismissed"]

    if last_checked:
        try:
            checked_dt = datetime.fromisoformat(last_checked)
            delta = datetime.now() - checked_dt
            if delta.total_seconds() < 60:
                last_display = "just now"
            elif delta.total_seconds() < 3600:
                last_display = f"{int(delta.total_seconds() // 60)}m ago"
            elif delta.total_seconds() < 86400:
                last_display = f"{int(delta.total_seconds() // 3600)}h ago"
            else:
                last_display = f"{int(delta.days)}d ago"
        except (ValueError, TypeError):
            last_display = "never"
    else:
        last_display = "never"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("LAST CHECKED", last_display)
    with c2:
        _metric_card("PENDING REVIEW", str(len(pending)),
                      color="#D97706" if pending else "#059669",
                      accent="#D97706" if pending else "#059669")
    with c3:
        _metric_card("APPLIED", str(len(applied)), color="#059669", accent="#059669")
    with c4:
        _metric_card("DISMISSED", str(len(dismissed)), color="#6B7280", accent="#6B7280")

    st.markdown("")

    col_btn, col_info = st.columns([2, 4])
    with col_btn:
        if st.button("\U0001f310 Check for global updates now", type="primary", key="rta_check_updates"):
            refresh_framework_updates_check()
            st.rerun()
    with col_info:
        if last_checked:
            st.markdown(
                f'<div style="padding-top:8px; font-size:0.78rem; color:#9CA3AF;">'
                f'Last successful refresh: {last_checked}</div>',
                unsafe_allow_html=True,
            )

    st.markdown("")
    _section("Pending Review")

    if not pending:
        st.markdown(
            '<p style="color:#6B7280; font-size:0.85rem;">'
            'No pending updates. Click <b>Check for global updates now</b> to refresh.</p>',
            unsafe_allow_html=True,
        )
    else:
        for u in pending:
            severity_colors = {"critical": "#DC2626", "high": "#F59E0B", "medium": "#3B82F6", "low": "#10B981"}
            dot_color = severity_colors.get(u.get("severity", "medium"), "#3B82F6")

            with st.expander(f"{u.get('framework_abbr', '')} — {u['title']}", expanded=False):
                st.markdown(
                    f'<div style="font-size:0.85rem; color:#374151; line-height:1.7; margin-bottom:12px;">'
                    f'{u["description"]}</div>'
                    f'<div style="font-size:0.75rem; color:#9CA3AF;">'
                    f'Published: {u.get("published_date", "")} &nbsp;|&nbsp; '
                    f'Severity: <span style="color:{dot_color}; font-weight:600;">'
                    f'{u.get("severity", "").capitalize()}</span> &nbsp;|&nbsp; '
                    f'Source: {u.get("source_url", "")}</div>',
                    unsafe_allow_html=True,
                )

                btn1, btn2, _ = st.columns([1, 1, 4])
                with btn1:
                    if st.button("✓ Apply", key=f"apply_{u['update_id']}", type="primary"):
                        user = st.session_state.get("user", "system")
                        apply_framework_update(u["update_id"], user)
                        st.rerun()
                with btn2:
                    if st.button("✗ Dismiss", key=f"dismiss_{u['update_id']}"):
                        user = st.session_state.get("user", "system")
                        dismiss_framework_update(u["update_id"], user)
                        st.rerun()

    if applied:
        with st.expander(f"Applied updates ({len(applied)})", expanded=False):
            for u in applied:
                st.markdown(
                    f'<div style="border-left:3px solid #059669; padding:10px 16px; margin-bottom:8px; '
                    f'background:#F9FAFB; border-radius:0 8px 8px 0;">'
                    f'<div style="font-weight:600; font-size:0.85rem; color:#374151;">'
                    f'■ {u.get("framework_abbr", "")} — {u["title"]}</div>'
                    f'<div style="font-size:0.72rem; color:#9CA3AF; margin-top:2px;">'
                    f'Applied by {u.get("reviewed_by", "system")} on {u.get("reviewed_at", "")}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    if audit_log and is_admin():
        with st.expander(f"\U0001f50d Audit log ({len(audit_log)} events)", expanded=False):
            log_rows = []
            for entry in reversed(audit_log[-20:]):
                log_rows.append({
                    "Timestamp": entry.get("timestamp", ""),
                    "Action": entry.get("action", "").capitalize(),
                    "Update ID": entry.get("update_id", ""),
                    "User": entry.get("user", ""),
                })
            st.dataframe(pd.DataFrame(log_rows), use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════
#  Tab 4 — AI Narrative
# ════════════════════════════════════════════════════════════

def _render_ai_narrative(all_results, company_id, year):
    _section("AI Compliance Narrative", "Executive-level compliance assessment report")

    company_name = get_company_name(company_id) if company_id else "Unknown Company"

    use_ai = st.toggle("Use AI-Enhanced Narrative", value=False, key="rta_ai_toggle")

    if use_ai:
        if "rta_ai_narrative" not in st.session_state:
            with st.spinner("Generating AI-enhanced narrative..."):
                response, error = generate_executive_narrative_llm(all_results, company_name, year)
                if response:
                    st.session_state["rta_ai_narrative"] = response
                else:
                    st.warning(f"AI narrative unavailable: {error}. Falling back to template.")
                    st.session_state["rta_ai_narrative"] = generate_compliance_narrative(all_results, company_name, year)
        narrative = st.session_state["rta_ai_narrative"]
    else:
        narrative = generate_compliance_narrative(all_results, company_name, year)

    st.markdown(
        '<div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:14px; '
        'padding:28px; line-height:1.8; font-size:0.9rem; color:#374151;">',
        unsafe_allow_html=True,
    )
    st.markdown(narrative)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("")

    col1, col2, _ = st.columns([1.5, 1.5, 3])
    with col1:
        st.download_button(
            "\U0001f4c4 Download Narrative (TXT)",
            data=narrative,
            file_name=f"compliance_narrative_{company_id}_{year}.txt",
            mime="text/plain",
            key="rta_download_narrative",
        )
    with col2:
        export_data = {
            "company_id": company_id,
            "company_name": company_name,
            "reporting_year": year,
            "summary": compute_compliance_summary(all_results),
            "radar_data": extract_radar_chart_data(all_results),
            "gap_analysis": [
                {k: v for k, v in gd.items() if k != "fix_suggestions"}
                for gd in extract_gap_analysis(all_results)
            ],
        }
        st.download_button(
            "\U0001f4ca Download Full Report (JSON)",
            data=json.dumps(export_data, indent=2, default=str),
            file_name=f"compliance_report_{company_id}_{year}.json",
            mime="application/json",
            key="rta_download_json",
        )


# ════════════════════════════════════════════════════════════
#  Tab 5 — Audit Trail
# ════════════════════════════════════════════════════════════

def _render_audit_trail():
    _section("Compliance Audit Trail", "Complete history of all compliance actions and regulatory changes")

    compliance_data = read_json("compliance_audit_trail.json")
    fw_data = read_json("framework_updates.json")

    entries = list(compliance_data.get("entries", []))

    for log_entry in fw_data.get("audit_log", []):
        entries.append({
            "timestamp": log_entry.get("timestamp", ""),
            "user": log_entry.get("user", "system"),
            "action": f"Framework Update {log_entry.get('action', '').capitalize()}",
            "framework": "",
            "details": f"Update ID: {log_entry.get('update_id', '')}",
            "status": log_entry.get("action", ""),
        })

    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    if not entries:
        st.info("No audit trail entries yet. Run a compliance analysis or apply framework updates to generate entries.")
        return

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        actions = sorted(set(e.get("action", "") for e in entries if e.get("action")))
        action_filter = st.selectbox("Filter by Action", ["All"] + actions, key="audit_action_filter")
    with col2:
        frameworks = sorted(set(e.get("framework", "") for e in entries if e.get("framework")))
        framework_filter = st.selectbox("Filter by Framework", ["All"] + frameworks, key="audit_fw_filter")
    with col3:
        users = sorted(set(e.get("user", "") for e in entries if e.get("user")))
        user_filter = st.selectbox("Filter by User", ["All"] + users, key="audit_user_filter")

    filtered = entries
    if action_filter != "All":
        filtered = [e for e in filtered if e.get("action") == action_filter]
    if framework_filter != "All":
        filtered = [e for e in filtered if e.get("framework") == framework_filter]
    if user_filter != "All":
        filtered = [e for e in filtered if e.get("user") == user_filter]

    if filtered:
        df = pd.DataFrame(filtered)
        display_cols = [c for c in ["timestamp", "user", "action", "framework", "status", "details"] if c in df.columns]
        df = df[display_cols]
        df.columns = [c.replace("_", " ").title() for c in display_cols]
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown(f'<p style="font-size:0.75rem; color:#9CA3AF;">{len(filtered)} entries</p>', unsafe_allow_html=True)
    else:
        st.info("No audit entries match the selected filters.")


