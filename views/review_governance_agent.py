import io
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from utils.auth import is_admin
from utils.review_governance_agent import (
    get_available_deals,
    run_review_governance,
    log_review_action,
)


# ── Shared helpers (same as other agent views) ──────────────────────────────

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
    accent_css = (
        f"border-left:4px solid {accent or color};"
        if accent or color != "#111827"
        else ""
    )
    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px; {accent_css}'
        f'background:white;">'
        f'<div style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
        f'letter-spacing:0.08em; margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:1.6rem; font-weight:800; color:{color};">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _status_pill(text, variant="info"):
    colors = {
        "success": ("#ECFDF5", "#059669"),
        "warning": ("#FFFBEB", "#D97706"),
        "error": ("#FEF2F2", "#DC2626"),
        "info": ("#EFF6FF", "#2563EB"),
        "neutral": ("#F3F4F6", "#6B7280"),
        "critical": ("#FEF2F2", "#991B1B"),
    }
    bg, fg = colors.get(variant, colors["info"])
    return (
        f'<span style="display:inline-block; background:{bg}; color:{fg}; '
        f'font-size:0.72rem; font-weight:600; padding:3px 10px; border-radius:6px;">'
        f'{text}</span>'
    )


def _priority_dot(priority):
    dot_colors = {
        "Critical": "#991B1B",
        "High": "#DC2626",
        "Medium": "#D97706",
        "Low": "#059669",
    }
    c = dot_colors.get(priority, "#6B7280")
    return f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{c};margin-right:6px;"></span>'


def _readiness_variant(status):
    if "Ready" in status:
        return "success"
    if "qualification" in status:
        return "warning"
    return "error"


# ── Tab renderers ───────────────────────────────────────────────────────────

def _render_executive_dashboard():
    res = st.session_state["review_results"]
    summary = res.get("executive_summary", {})
    scores = res.get("review_scores", {})
    components = scores.get("component_scores", {})

    _section("Overall Quality Assessment")

    score_pct = round(summary.get("overall_quality_score", 0) * 100, 1)

    if score_pct >= 85:
        gauge_color = "#059669"
    elif score_pct >= 70:
        gauge_color = "#D97706"
    else:
        gauge_color = "#DC2626"

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score_pct,
        number={"suffix": "%", "font": {"size": 42, "color": "#111827"}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#E5E7EB"},
            "bar": {"color": gauge_color, "thickness": 0.3},
            "bgcolor": "#F9FAFB",
            "steps": [
                {"range": [0, 70], "color": "#FEF2F2"},
                {"range": [70, 85], "color": "#FFFBEB"},
                {"range": [85, 100], "color": "#ECFDF5"},
            ],
            "threshold": {
                "line": {"color": "#111827", "width": 2},
                "thickness": 0.8,
                "value": score_pct,
            },
        },
    ))
    fig.update_layout(
        height=260,
        margin=dict(l=30, r=30, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    readiness = scores.get("readiness_status", "")
    st.markdown(
        f'<div style="text-align:center; margin:-10px 0 16px 0;">'
        f'{_status_pill(readiness, _readiness_variant(readiness))}</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card(
            "Findings Reviewed",
            str(summary.get("total_findings", 0)),
            accent="#3B82F6",
        )
    with c2:
        total = scores.get("total_findings_scored", 0)
        passing = sum(
            1 for pf in scores.get("per_finding_scores", [])
            if pf.get("score", 0) >= 0.70
        )
        rate = f"{round(passing / total * 100) if total else 0}%"
        _metric_card("Pass Rate", rate, color="#059669", accent="#059669")
    with c3:
        conflicts = summary.get("conflicts_count", 0)
        cc = "#D97706" if conflicts > 0 else "#059669"
        _metric_card("Conflicts", str(conflicts), color=cc, accent=cc)
    with c4:
        pending = summary.get("human_review_items", 0)
        pc = "#DC2626" if pending > 0 else "#059669"
        _metric_card("Pending Review", str(pending), color=pc, accent=pc)

    _section("Quality Score Breakdown")

    labels = [
        "Evidence\nCompleteness",
        "Calculation\nReproducibility",
        "Source\nReliability",
        "Cross-Agent\nConsistency",
        "Reviewer\nVerification",
    ]
    keys = [
        "evidence_completeness",
        "calculation_reproducibility",
        "source_reliability",
        "cross_agent_consistency",
        "reviewer_verification",
    ]
    values = [round(components.get(k, 0) * 100, 1) for k in keys]
    values_closed = values + [values[0]]
    labels_closed = labels + [labels[0]]

    radar = go.Figure()
    radar.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=labels_closed,
        fill="toself",
        fillcolor="rgba(255,90,0,0.15)",
        line=dict(color="#FF5A00", width=2),
        marker=dict(size=6, color="#FF5A00"),
        name="Quality Score",
    ))
    radar.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True, range=[0, 100],
                tickfont=dict(size=10, color="#6B7280"),
                gridcolor="#E5E7EB",
            ),
            angularaxis=dict(
                tickfont=dict(size=11, color="#374151"),
                gridcolor="#E5E7EB",
            ),
            bgcolor="white",
        ),
        showlegend=False,
        height=380,
        margin=dict(l=60, r=60, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(radar, use_container_width=True)

    agents_used = res.get("agents_used", [])
    all_agents = ["Metric Analysis", "Compliance", "Benchmarking", "Risk & Opportunity"]
    missing = [a for a in all_agents if a not in agents_used]

    if agents_used:
        pills_html = " ".join(
            _status_pill(a, "success") for a in agents_used
        )
        if missing:
            pills_html += "  " + " ".join(
                _status_pill(f"{a} (not run)", "neutral") for a in missing
            )
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:14px 18px; '
            f'background:white; margin-top:8px;">'
            f'<div style="font-size:0.72rem; font-weight:700; color:#6B7280; '
            f'text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px;">'
            f'Agent Coverage</div>'
            f'<div>{pills_html}</div></div>',
            unsafe_allow_html=True,
        )


def _render_access_governance():
    res = st.session_state["review_results"]
    access = res.get("access_governance", {})

    _section("Access Control Status")

    status = access.get("access_status", "unknown")
    variant_map = {"allowed": "success", "denied": "error", "unknown": "neutral"}
    variant = variant_map.get(status, "neutral")

    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:20px; '
        f'background:white; margin-bottom:16px;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center;">'
        f'  <div>'
        f'    <div style="font-size:0.72rem; font-weight:700; color:#6B7280; '
        f'         text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px;">'
        f'         Access Status</div>'
        f'    <div style="font-size:1.4rem; font-weight:800; color:#111827; margin-bottom:4px;">'
        f'         {status.title()}</div>'
        f'    {_status_pill(status.upper(), variant)}'
        f'  </div>'
        f'  <div style="text-align:right;">'
        f'    <div style="font-size:0.72rem; color:#6B7280; margin-bottom:4px;">Permission Level</div>'
        f'    <div style="font-size:1.1rem; font-weight:700; color:#111827;">'
        f'         {(access.get("permission_level") or "N/A").title()}</div>'
        f'    <div style="font-size:0.72rem; color:#6B7280; margin-top:4px;">Role</div>'
        f'    <div style="font-size:0.95rem; font-weight:600; color:#374151;">'
        f'         {access.get("user_role") or "Unknown"}</div>'
        f'  </div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    warnings = access.get("warnings", [])
    if warnings:
        for w in warnings:
            st.markdown(
                f'<div style="background:#FFFBEB; border:1px solid #FDE68A; border-radius:8px; '
                f'padding:10px 14px; margin-bottom:6px; font-size:0.83rem; color:#92400E;">'
                f'⚠ {w}</div>',
                unsafe_allow_html=True,
            )

    _section("Deal Permissions", "All access records for this deal")

    records = access.get("access_records", [])
    if records:
        rows = []
        for r in records:
            rows.append({
                "User ID": r.get("user_id", ""),
                "Permission": r.get("permission_level", "").title(),
                "Granted": r.get("granted_date", ""),
                "Revoked": r.get("revoked_date", "") or "—",
                "Status": r.get("status", ""),
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No access records found for this deal.")

    _section("Data Change History", "Field-level changes tracked in data_value_history")

    import os
    dvh_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "uploads", "data_value_history.csv",
    )
    try:
        dvh = pd.read_csv(dvh_path)
    except Exception:
        dvh = pd.DataFrame()

    deal_id = res.get("deal_id", "")
    if not dvh.empty and deal_id:
        prefix = deal_id.replace("DEAL", "D")
        filtered = dvh[dvh["history_id"].str.startswith(prefix, na=False)]
        if not filtered.empty:
            for _, row in filtered.iterrows():
                with st.expander(
                    f"{row.get('field_name', '')} — {row.get('entity_type', '')} "
                    f"({row.get('entity_id', '')})"
                ):
                    lc, rc = st.columns(2)
                    with lc:
                        st.markdown(f"**Old Value:** `{row.get('old_value', '')}`")
                        st.markdown(f"**New Value:** `{row.get('new_value', '')}`")
                    with rc:
                        st.markdown(f"**Changed By:** {row.get('changed_by', '')}")
                        st.markdown(f"**Date:** {row.get('change_date', '')}")
                    st.markdown(f"**Reason:** {row.get('change_reason', '')}")
        else:
            st.info("No data changes recorded for this deal.")
    else:
        st.info("No data change history available.")

    if is_admin():
        _section("Recent Audit Activity")
        try:
            db_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "database",
            )
            with open(os.path.join(db_dir, "audit_logs.json"), "r", encoding="utf-8") as f:
                audit_data = json.load(f)
            logs = audit_data.get("logs", [])
            if logs:
                recent = logs[-15:]
                recent.reverse()
                audit_rows = [
                    {
                        "User": l.get("user", ""),
                        "Action": l.get("action", ""),
                        "Timestamp": l.get("timestamp", ""),
                    }
                    for l in recent
                ]
                st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No audit log entries found.")
        except Exception:
            st.info("Could not load audit logs.")


def _render_evidence_validation():
    res = st.session_state["review_results"]
    issues = res.get("evidence_validation", [])

    _section("Evidence Validation Results")

    if not issues:
        st.markdown(
            '<div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:12px; '
            'padding:14px 20px; margin:16px 0;">'
            '<span style="color:#059669; font-weight:600;">All findings have adequate evidence.</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    critical = sum(1 for i in issues if i["severity"] == "Critical")
    high = sum(1 for i in issues if i["severity"] == "High")
    medium_low = sum(1 for i in issues if i["severity"] in ("Medium", "Low"))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Total Issues", str(len(issues)), accent="#DC2626")
    with c2:
        cc = "#991B1B" if critical > 0 else "#059669"
        _metric_card("Critical", str(critical), color=cc, accent=cc)
    with c3:
        hc = "#DC2626" if high > 0 else "#059669"
        _metric_card("High", str(high), color=hc, accent=hc)
    with c4:
        _metric_card("Medium / Low", str(medium_low), accent="#3B82F6")

    by_agent = {}
    for issue in issues:
        agent = issue.get("agent_source", "Unknown")
        by_agent.setdefault(agent, []).append(issue)

    for agent, agent_issues in by_agent.items():
        with st.expander(f"{agent} — {len(agent_issues)} issue(s)"):
            for issue in agent_issues:
                sev = issue.get("severity", "Medium")
                border_map = {
                    "Critical": "#991B1B",
                    "High": "#DC2626",
                    "Medium": "#D97706",
                    "Low": "#059669",
                }
                bg_map = {
                    "Critical": "#FEF2F2",
                    "High": "#FFF7ED",
                    "Medium": "#FFFBEB",
                    "Low": "#F0FDF4",
                }
                border_c = border_map.get(sev, "#6B7280")
                bg_c = bg_map.get(sev, "#FFFFFF")
                sev_variant = {
                    "Critical": "critical",
                    "High": "error",
                    "Medium": "warning",
                    "Low": "success",
                }.get(sev, "neutral")

                st.markdown(
                    f'<div style="border:1px solid #E5E7EB; border-left:5px solid {border_c}; '
                    f'border-radius:12px; padding:14px 18px; margin-bottom:10px; background:{bg_c};">'
                    f'  <div style="display:flex; justify-content:space-between; align-items:flex-start;">'
                    f'    <div>'
                    f'      <div style="font-size:0.9rem; font-weight:700; color:#111827; margin-bottom:4px;">'
                    f'        {issue.get("finding_ref", "")}</div>'
                    f'      <div style="font-size:0.82rem; color:#374151; line-height:1.5;">'
                    f'        {issue.get("description", "")}</div>'
                    f'    </div>'
                    f'    <div style="text-align:right; min-width:120px;">'
                    f'      {_status_pill(sev, sev_variant)}'
                    f'      <div style="font-size:0.7rem; color:#6B7280; margin-top:4px;">'
                    f'        {issue.get("issue_type", "")}</div>'
                    f'    </div>'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


def _render_conflict_resolution():
    res = st.session_state["review_results"]
    conflicts = res.get("conflicts", [])

    _section("Cross-Agent Conflict Detection")

    if not conflicts:
        st.markdown(
            '<div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:12px; '
            'padding:14px 20px; margin:16px 0;">'
            '<span style="color:#059669; font-weight:600;">'
            'No cross-agent contradictions detected.</span></div>',
            unsafe_allow_html=True,
        )
        return

    type_counts = {}
    for c in conflicts:
        t = c.get("conflict_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    cols = st.columns(min(len(type_counts), 4))
    type_labels = {
        "trend_vs_risk": "Trend vs Risk",
        "target_vs_risk": "Target vs Risk",
        "compliance_vs_benchmark": "Compliance vs Benchmark",
    }
    for i, (ctype, count) in enumerate(type_counts.items()):
        with cols[i % len(cols)]:
            _metric_card(
                type_labels.get(ctype, ctype),
                str(count),
                color="#D97706",
                accent="#D97706",
            )

    for conflict in conflicts:
        st.markdown(
            f'<div style="border:1px solid #FDE68A; border-radius:12px; padding:18px 20px; '
            f'margin-bottom:14px; background:#FFFBEB;">'
            f'  <div style="margin-bottom:10px;">'
            f'    {_status_pill(type_labels.get(conflict["conflict_type"], conflict["conflict_type"]), "warning")}'
            f'    {_status_pill(conflict.get("esg_pillar", ""), "neutral") if conflict.get("esg_pillar") else ""}'
            f'  </div>'
            f'  <div style="font-size:0.88rem; color:#374151; line-height:1.6; margin-bottom:12px;">'
            f'    {conflict.get("description", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        left, right = st.columns(2)
        with left:
            st.markdown(
                f'<div style="border:1px solid #E5E7EB; border-radius:10px; padding:14px; '
                f'background:white;">'
                f'  <div style="font-size:0.7rem; font-weight:700; color:#6B7280; '
                f'       text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px;">'
                f'       {conflict.get("agent_a", "")}</div>'
                f'  <div style="font-size:0.9rem; font-weight:600; color:#111827;">'
                f'       {conflict.get("agent_a_assessment", "")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with right:
            st.markdown(
                f'<div style="border:1px solid #E5E7EB; border-radius:10px; padding:14px; '
                f'background:white;">'
                f'  <div style="font-size:0.7rem; font-weight:700; color:#6B7280; '
                f'       text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px;">'
                f'       {conflict.get("agent_b", "")}</div>'
                f'  <div style="font-size:0.9rem; font-weight:600; color:#111827;">'
                f'       {conflict.get("agent_b_assessment", "")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:10px; padding:12px 16px; '
            f'margin-top:6px; margin-bottom:16px; background:#F9FAFB;">'
            f'  <div style="font-size:0.72rem; font-weight:700; color:#FF5A00; margin-bottom:4px;">'
            f'       Resolution Guidance</div>'
            f'  <div style="font-size:0.82rem; color:#374151; line-height:1.6;">'
            f'       {conflict.get("resolution_needed", "")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_review_queue():
    res = st.session_state["review_results"]
    queue = res.get("review_queue", [])

    _section("Human Review Queue")

    if not queue:
        st.markdown(
            '<div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:12px; '
            'padding:14px 20px; margin:16px 0;">'
            '<span style="color:#059669; font-weight:600;">'
            'All items have been reviewed. No pending actions.</span></div>',
            unsafe_allow_html=True,
        )
        return

    pending = [q for q in queue if q.get("status") == "pending"]
    approved = [q for q in queue if q.get("status") == "approved"]
    flagged = [q for q in queue if q.get("status") == "flagged"]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Total Items", str(len(queue)), accent="#3B82F6")
    with c2:
        pc = "#DC2626" if len(pending) > 0 else "#059669"
        _metric_card("Pending", str(len(pending)), color=pc, accent=pc)
    with c3:
        _metric_card("Approved", str(len(approved)), color="#059669", accent="#059669")
    with c4:
        fc = "#D97706" if len(flagged) > 0 else "#6B7280"
        _metric_card("Flagged", str(len(flagged)), color=fc, accent=fc)

    for idx, item in enumerate(queue):
        priority = item.get("priority", "Medium")
        status = item.get("status", "pending")

        border_map = {"Critical": "#991B1B", "High": "#DC2626", "Medium": "#D97706"}
        bg_map = {"Critical": "#FEF2F2", "High": "#FFF7ED", "Medium": "#FFFBEB"}
        border_c = border_map.get(priority, "#6B7280")
        bg_c = bg_map.get(priority, "#FFFFFF")

        if status == "approved":
            bg_c = "#ECFDF5"
            border_c = "#059669"
        elif status == "flagged":
            bg_c = "#FEF2F2"
            border_c = "#DC2626"

        status_variant = {
            "pending": "warning",
            "approved": "success",
            "flagged": "error",
        }.get(status, "neutral")

        priority_variant = {
            "Critical": "critical",
            "High": "error",
            "Medium": "warning",
        }.get(priority, "neutral")

        reasons_html = ""
        for reason in item.get("trigger_reasons", []):
            reasons_html += (
                f'<li style="font-size:0.8rem; color:#374151; line-height:1.6;">{reason}</li>'
            )

        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-left:5px solid {border_c}; '
            f'border-radius:12px; padding:16px 20px; margin-bottom:10px; background:{bg_c};">'
            f'  <div style="display:flex; justify-content:space-between; align-items:flex-start;">'
            f'    <div style="flex:1;">'
            f'      <div style="font-size:0.95rem; font-weight:700; color:#111827; margin-bottom:4px;">'
            f'        {item.get("title", "")}</div>'
            f'      <div style="font-size:0.78rem; color:#6B7280; margin-bottom:8px;">'
            f'        {item.get("finding_ref", "")} · {item.get("agent_source", "")}</div>'
            f'      <div style="margin-bottom:4px;">'
            f'        {_status_pill(priority, priority_variant)} '
            f'        {_status_pill(status.title(), status_variant)}'
            f'      </div>'
            f'      <ul style="margin:8px 0 0 0; padding-left:18px;">{reasons_html}</ul>'
            f'    </div>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if status == "pending":
            btn_left, btn_right, _ = st.columns([1, 1, 4])
            with btn_left:
                if st.button(
                    "Approve",
                    key=f"approve_{item.get('review_item_id', idx)}",
                    type="primary",
                ):
                    item["status"] = "approved"
                    user = st.session_state.get("user", "system")
                    log_review_action(
                        user, "Approved review item",
                        deal_id=res.get("deal_id", ""),
                        details=f"Approved: {item.get('finding_ref', '')}",
                    )
                    st.rerun()
            with btn_right:
                if st.button(
                    "Flag",
                    key=f"flag_{item.get('review_item_id', idx)}",
                ):
                    item["status"] = "flagged"
                    user = st.session_state.get("user", "system")
                    log_review_action(
                        user, "Flagged review item",
                        deal_id=res.get("deal_id", ""),
                        details=f"Flagged: {item.get('finding_ref', '')}",
                    )
                    st.rerun()


def _render_final_report():
    res = st.session_state["review_results"]
    summary = res.get("executive_summary", {})
    sections = res.get("sections", {})

    _section("Due-Diligence Report")

    readiness = summary.get("readiness_status", "")
    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:18px 22px; '
        f'background:white; margin-bottom:16px;">'
        f'  <div style="display:flex; justify-content:space-between; align-items:center;">'
        f'    <div>'
        f'      <div style="font-size:1.1rem; font-weight:800; color:#111827;">'
        f'        {res.get("company_name", "")} — {res.get("deal_name", "")}</div>'
        f'      <div style="font-size:0.78rem; color:#6B7280; margin-top:4px;">'
        f'        Report ID: {res.get("report_id", "")} · Generated: {res.get("generated_at", "")}</div>'
        f'    </div>'
        f'    <div>{_status_pill(readiness, _readiness_variant(readiness))}</div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Executive Summary", expanded=True):
        st.markdown(summary.get("narrative", ""))
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.metric("Total Findings", summary.get("total_findings", 0))
        with sc2:
            st.metric("Critical Findings", summary.get("critical_findings", 0))
        with sc3:
            st.metric("Evidence Issues", summary.get("evidence_issues_count", 0))

    red_flags = sections.get("material_red_flags", [])
    with st.expander(f"Material Red Flags ({len(red_flags)})"):
        if red_flags:
            for rf in red_flags:
                fin = rf.get("financial_impact", 0)
                fin_str = f"${fin:,.0f}" if fin else "Not quantified"
                st.markdown(
                    f'<div style="border:1px solid #E5E7EB; border-left:5px solid #991B1B; '
                    f'border-radius:12px; padding:14px 18px; margin-bottom:8px; background:#FEF2F2;">'
                    f'  <div style="font-size:0.9rem; font-weight:700; color:#111827;">'
                    f'    {rf.get("finding_id", "")} — {rf.get("title", "")}</div>'
                    f'  <div style="font-size:0.82rem; color:#374151; margin:4px 0;">'
                    f'    {rf.get("description", "")}</div>'
                    f'  <div style="font-size:0.78rem; color:#991B1B; font-weight:600;">'
                    f'    Financial Impact: {fin_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.success("No material red flags identified.")

    gaps = sections.get("compliance_gaps", [])
    with st.expander(f"Compliance Gaps ({len(gaps)})"):
        if gaps:
            rows = []
            for g in gaps:
                rows.append({
                    "Regulation": g.get("regulation", ""),
                    "Requirement": g.get("requirement_id", ""),
                    "Name": g.get("requirement_name", "")[:60],
                    "Status": g.get("status", ""),
                    "Severity": g.get("severity", ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.success("No compliance gaps found.")

    benchmarks = sections.get("benchmark_performance", [])
    with st.expander(f"Benchmark Performance ({len(benchmarks)})"):
        if benchmarks:
            rows = []
            for b in benchmarks:
                rows.append({
                    "Metric": b.get("metric_code", ""),
                    "Performance": b.get("performance", ""),
                    "Percentile": b.get("percentile", ""),
                    "Peers": b.get("peer_count", ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No benchmark data available.")

    trends = sections.get("esg_trends", [])
    with st.expander(f"ESG Metric Trends ({len(trends)})"):
        if trends:
            rows = []
            for t in trends:
                rows.append({
                    "Metric": t.get("metric_code", ""),
                    "Trend": t.get("trend", ""),
                    "Target Progress": t.get("target_progress", ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No metric trend data available.")

    risks = sections.get("risk_register", [])
    with st.expander(f"Risk Register ({len(risks)})"):
        if risks:
            for r in risks:
                fin = r.get("financial_impact", 0)
                fin_str = f"${fin:,.0f}" if fin else "—"
                prio = r.get("priority", "Medium")
                border_map = {
                    "Critical": "#991B1B", "High": "#DC2626",
                    "Medium": "#D97706", "Low": "#059669",
                }
                st.markdown(
                    f'<div style="border:1px solid #E5E7EB; border-left:5px solid {border_map.get(prio, "#6B7280")}; '
                    f'border-radius:12px; padding:12px 16px; margin-bottom:8px; background:white;">'
                    f'  <div style="display:flex; justify-content:space-between;">'
                    f'    <div>'
                    f'      <div style="font-size:0.88rem; font-weight:700; color:#111827;">'
                    f'        {r.get("finding_id", "")} — {r.get("title", "")}</div>'
                    f'      <div style="font-size:0.78rem; color:#6B7280; margin-top:2px;">'
                    f'        {r.get("esg_pillar", "")}</div>'
                    f'    </div>'
                    f'    <div style="text-align:right;">'
                    f'      {_status_pill(prio, "critical" if prio == "Critical" else "error" if prio == "High" else "warning")}'
                    f'      <div style="font-size:0.82rem; font-weight:700; color:#111827; margin-top:4px;">'
                    f'        {fin_str}</div>'
                    f'    </div>'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No risk findings available.")

    opps = sections.get("opportunities", [])
    with st.expander(f"Value-Creation Opportunities ({len(opps)})"):
        if opps:
            for o in opps:
                st.markdown(
                    f'<div style="border:1px solid #E5E7EB; border-left:5px solid #059669; '
                    f'border-radius:12px; padding:12px 16px; margin-bottom:8px; background:#F0FDF4;">'
                    f'  <div style="font-size:0.88rem; font-weight:700; color:#111827;">'
                    f'    {o.get("finding_id", "")} — {o.get("title", "")}</div>'
                    f'  <div style="font-size:0.78rem; color:#6B7280; margin-top:2px;">'
                    f'    {o.get("esg_pillar", "")}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No opportunities identified.")

    recs = sections.get("recommendations", [])
    with st.expander(f"Recommendations ({len(recs)})"):
        if recs:
            for rec in recs:
                st.markdown(
                    f'<div style="border:1px solid #E5E7EB; border-radius:10px; padding:12px 16px; '
                    f'margin-bottom:8px; background:white;">'
                    f'  <div style="font-size:0.85rem; font-weight:700; color:#111827; margin-bottom:4px;">'
                    f'    {rec.get("finding_id", "")} — {rec.get("category", "")}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No recommendations generated.")

    with st.expander("Methodology & Disclaimer"):
        st.markdown(f"**Methodology**\n\n{res.get('methodology', '')}")
        st.markdown(f"**Disclaimer**\n\n{res.get('disclaimer', '')}")

    st.markdown("---")
    _section("Export Report")

    dl1, dl2, dl3 = st.columns(3)

    with dl1:
        report_json = json.dumps(res, indent=2, default=str)
        st.download_button(
            "Download JSON",
            data=report_json,
            file_name=f"dd_report_{res.get('deal_id', 'report')}.json",
            mime="application/json",
            key="rg_dl_json",
        )

    with dl2:
        csv_rows = []
        for section_key in ("risk_register", "compliance_gaps", "opportunities"):
            for item in sections.get(section_key, []):
                row = {"section": section_key}
                row.update({
                    k: v for k, v in item.items()
                    if not isinstance(v, (list, dict))
                })
                csv_rows.append(row)
        if csv_rows:
            csv_buf = io.StringIO()
            pd.DataFrame(csv_rows).to_csv(csv_buf, index=False)
            st.download_button(
                "Download CSV",
                data=csv_buf.getvalue(),
                file_name=f"dd_report_{res.get('deal_id', 'report')}.csv",
                mime="text/csv",
                key="rg_dl_csv",
            )
        else:
            st.button("Download CSV", disabled=True, key="rg_dl_csv_disabled")

    with dl3:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            summary_df = pd.DataFrame([{
                "Company": res.get("company_name", ""),
                "Deal": res.get("deal_name", ""),
                "Quality Score": f"{summary.get('overall_quality_score', 0) * 100:.1f}%",
                "Readiness": summary.get("readiness_status", ""),
                "Total Findings": summary.get("total_findings", 0),
                "Critical": summary.get("critical_findings", 0),
                "Evidence Issues": summary.get("evidence_issues_count", 0),
                "Conflicts": summary.get("conflicts_count", 0),
                "Pending Review": summary.get("human_review_items", 0),
            }])
            summary_df.to_excel(writer, sheet_name="Executive Summary", index=False)

            xl_risks = sections.get("risk_register", [])
            if xl_risks:
                pd.DataFrame(xl_risks).to_excel(
                    writer, sheet_name="Risk Register", index=False
                )
            xl_gaps = sections.get("compliance_gaps", [])
            if xl_gaps:
                pd.DataFrame(xl_gaps).to_excel(
                    writer, sheet_name="Compliance Gaps", index=False
                )
            xl_issues = res.get("evidence_validation", [])
            if xl_issues:
                pd.DataFrame(xl_issues).to_excel(
                    writer, sheet_name="Evidence Issues", index=False
                )
            xl_conflicts = res.get("conflicts", [])
            if xl_conflicts:
                pd.DataFrame(xl_conflicts).to_excel(
                    writer, sheet_name="Conflicts", index=False
                )
            xl_queue = res.get("review_queue", [])
            if xl_queue:
                pd.DataFrame(xl_queue).to_excel(
                    writer, sheet_name="Review Queue", index=False
                )

        st.download_button(
            "Download Excel",
            data=buf.getvalue(),
            file_name=f"dd_report_{res.get('deal_id', 'report')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="rg_dl_xlsx",
        )


# ── Main render ─────────────────────────────────────────────────────────────

def render():
    st.markdown(
        '<div style="margin-bottom:6px;">'
        '<h2 style="margin:0 0 4px 0; font-size:1.55rem; font-weight:800; color:#111827;">'
        '🔍 Review &amp; Report Agent</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:0; line-height:1.5;">'
        'Quality assurance, governance validation, and final due-diligence '
        'report generation across all agent outputs.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander("How does the Review & Report Agent work?"):
        st.markdown("""
**This agent validates and consolidates outputs from all specialist agents.**

| Step | What it does |
|------|-------------|
| **1. Access Control** | Verifies user permissions for the selected deal |
| **2. Evidence Validation** | Checks every finding has supporting evidence |
| **3. Conflict Detection** | Identifies contradictions between agents |
| **4. Quality Scoring** | Scores findings on a 5-component formula |
| **5. Review Routing** | Flags items that need human review |
| **6. Report Generation** | Compiles a traceable due-diligence report |

**Quality Score Formula:**
- Evidence Completeness (30%) — Do findings have evidence?
- Calculation Reproducibility (25%) — Can financial estimates be reproduced?
- Source Reliability (20%) — Are sources verified and audited?
- Cross-Agent Consistency (15%) — Do agents agree?
- Reviewer Verification (10%) — Have data changes been reviewed?

**Readiness Thresholds:**
- **≥ 85%** — Ready for report
- **70–84%** — Include with qualification
- **< 70%** — Human review required
""")

    st.markdown("---")

    deal_options = get_available_deals()
    if not deal_options:
        st.markdown(
            '<div style="border:1px dashed #D1D5DB; border-radius:14px; background:#FAFAFA; '
            'text-align:center; padding:48px 24px;">'
            '<div style="font-size:2.2rem; margin-bottom:8px;">📂</div>'
            '<div style="font-size:1.05rem; font-weight:700; color:#111827; margin-bottom:6px;">'
            'No deals available</div>'
            '<p style="color:#6B7280; font-size:0.85rem; max-width:400px; margin:0 auto;">'
            'Upload deal data via the Data Sources page to get started.</p></div>',
            unsafe_allow_html=True,
        )
        return

    deal_labels = {
        f"{d['deal_name']} ({d['company_name']})": d for d in deal_options
    }
    selected_label = st.selectbox(
        "Select Deal",
        options=list(deal_labels.keys()),
        key="rg_deal_select",
    )

    agent_status = {}
    agent_keys = {
        "Metric Analysis": "fa_result",
        "Compliance": "rta_results",
        "Benchmarking": "bm_result",
        "Risk & Opportunity": "ro_results",
    }
    for name, key in agent_keys.items():
        agent_status[name] = st.session_state.get(key) is not None

    available = [n for n, v in agent_status.items() if v]
    missing = [n for n, v in agent_status.items() if not v]

    pills = " ".join(_status_pill(a, "success") for a in available) if available else ""
    pills += (" " + " ".join(
        _status_pill(f"{a} (not run)", "neutral") for a in missing
    )) if missing else ""

    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:12px 16px; '
        f'background:white; margin:8px 0 16px 0;">'
        f'<div style="font-size:0.72rem; font-weight:700; color:#6B7280; '
        f'text-transform:uppercase; letter-spacing:0.08em; margin-bottom:6px;">'
        f'Agent Outputs Available</div>'
        f'<div>{pills}</div></div>',
        unsafe_allow_html=True,
    )

    if not available:
        st.warning(
            "No agent outputs available. Run at least one specialist agent "
            "(Metric Analysis, Compliance, Benchmarking, or Risk & Opportunity) "
            "before generating a review."
        )

    run_clicked = st.button(
        "🔍 Run Review & Generate Report",
        key="rg_run_btn",
        type="primary",
        use_container_width=True,
        disabled=not available,
    )

    if run_clicked and selected_label:
        deal = deal_labels[selected_label]
        user = st.session_state.get("user", "system")

        agent_outputs = {}
        if st.session_state.get("fa_result"):
            agent_outputs["metric_analysis"] = st.session_state["fa_result"]
        if st.session_state.get("rta_results"):
            agent_outputs["compliance"] = st.session_state["rta_results"]
        if st.session_state.get("bm_result"):
            agent_outputs["benchmarking"] = st.session_state["bm_result"]
        if st.session_state.get("bm_summary"):
            agent_outputs["benchmarking_summary"] = st.session_state["bm_summary"]
        if st.session_state.get("ro_results"):
            agent_outputs["risk_opportunity"] = st.session_state["ro_results"]

        with st.spinner("Running review, validation, and report generation..."):
            result = run_review_governance(
                deal["deal_id"],
                deal["company_id"],
                user,
                agent_outputs,
            )
            st.session_state["review_results"] = result

        log_review_action(
            user, "Review & Report Generated",
            deal_id=deal["deal_id"],
            details=f"Quality score: {result.get('review_scores', {}).get('overall_score', 0):.2f}",
        )

        st.markdown(
            '<div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:12px; '
            'padding:14px 20px; margin:16px 0;">'
            '<span style="color:#059669; font-weight:600;">'
            'Review complete! Explore the tabs below.</span></div>',
            unsafe_allow_html=True,
        )

    if st.session_state.get("review_results"):
        tabs = st.tabs([
            "Executive Dashboard",
            "Access & Governance",
            "Evidence Validation",
            "Conflict Resolution",
            "Review Queue",
            "Final Report",
        ])
        with tabs[0]:
            _render_executive_dashboard()
        with tabs[1]:
            _render_access_governance()
        with tabs[2]:
            _render_evidence_validation()
        with tabs[3]:
            _render_conflict_resolution()
        with tabs[4]:
            _render_review_queue()
        with tabs[5]:
            _render_final_report()
