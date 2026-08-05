"""
Home / Dashboard — landing page after login.

Shows an Action Center with pipeline execution and data source navigation,
a quick-start guide, and recent activity.
"""

import streamlit as st
from datetime import datetime
from utils.auth import get_current_user, is_admin
from utils.json_manager import get_audit_logs

from utils.metric_analysis_agent import (
    get_available_companies as get_metric_companies,
    get_available_metrics,
    get_available_years as get_metric_years,
    run_full_analysis,
)
from utils.compliance_agent import (
    get_available_companies as get_compliance_companies,
    get_available_years as get_compliance_years,
    load_regulation_master,
    run_full_compliance_assessment,
)
from utils.benchmarking_agent import (
    get_available_companies as get_bm_companies,
    get_available_metrics as get_bm_metrics,
    get_available_years as get_bm_years,
    run_benchmark,
    run_benchmark_summary,
)
from utils.risk_opportunity_agent import (
    get_available_deals,
    run_risk_opportunity_analysis,
)
from utils.review_governance_agent import run_review_governance
from utils.registration_agent import (
    get_registered_sources,
    get_unregistered_files,
    auto_register_source,
)


_PIPELINE_CSS = """
<style>
.action-btn-primary {
    border: none; border-radius: 14px; padding: 28px 24px; width: 100%; cursor: pointer;
    background: linear-gradient(135deg, #FF5A00, #FF7F32);
    box-shadow: 0 4px 16px rgba(255, 90, 0, 0.25);
    transition: all 0.2s ease;
    text-align: left;
}
.action-btn-primary:hover {
    box-shadow: 0 6px 24px rgba(255, 90, 0, 0.35);
    transform: translateY(-2px);
}
.action-btn-secondary {
    border: 2px solid #FF5A00; border-radius: 14px; padding: 28px 24px; width: 100%;
    cursor: pointer; background: white;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    transition: all 0.2s ease;
    text-align: left;
}
.action-btn-secondary:hover {
    background: #FFF7F0;
    box-shadow: 0 4px 16px rgba(255, 90, 0, 0.12);
    transform: translateY(-2px);
}
.agent-card {
    border: 1px solid #E5E7EB; border-radius: 12px; padding: 14px 16px;
    background: white; display: flex; align-items: center; gap: 12px;
    margin-bottom: 8px;
}
.agent-card.completed { border-color: #A7F3D0; background: #F0FDF4; }
.agent-card.running { border-color: #FDBA74; background: #FFF7ED; }
.agent-card.failed { border-color: #FCA5A5; background: #FEF2F2; }
.agent-card.skipped { border-color: #E5E7EB; background: #F9FAFB; }
@keyframes pulse-glow {
    0%, 100% { box-shadow: 0 4px 16px rgba(255, 90, 0, 0.25); }
    50% { box-shadow: 0 4px 24px rgba(255, 90, 0, 0.5); }
}
.pipeline-done-actions button[kind="primary"] {
    animation: pulse-glow 1.5s ease-in-out infinite;
}
</style>
"""

AGENTS = [
    {"key": "registration", "icon": "\U0001f916", "name": "Registration Agent"},
    {"key": "metric_analysis", "icon": "\U0001f4ca", "name": "Metric Analysis"},
    {"key": "compliance", "icon": "\U0001f4cb", "name": "Regulatory Tracker"},
    {"key": "benchmarking", "icon": "\U0001f4c8", "name": "Benchmarking"},
    {"key": "risk_opportunity", "icon": "⚡", "name": "Risk & Opportunity"},
    {"key": "review", "icon": "\U0001f50d", "name": "Review & Report"},
]

_STATUS_ICONS = {
    "waiting": "⏳",
    "running": "\U0001f504",
    "completed": "✅",
    "failed": "❌",
    "skipped": "⏭️",
}


def render():
    st.markdown(_PIPELINE_CSS, unsafe_allow_html=True)

    user = st.session_state.get("full_name", st.session_state.get("user", ""))

    hour = datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    st.markdown(
        f'<div style="margin-bottom:28px;">'
        f'<h2 style="margin:0; font-size:1.65rem; font-weight:700; color:#111827;">'
        f'{greeting}, {user}</h2>'
        f'<p style="color:#6B7280; font-size:0.92rem; margin:6px 0 0 0; line-height:1.6;">'
        f'Welcome to the ESG Data Platform. Here\'s an overview of your workspace.</p></div>',
        unsafe_allow_html=True,
    )

    # ── Action Center ──
    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            '<div class="action-btn-primary">'
            '<div style="font-size:1.5rem; margin-bottom:8px;">▶️</div>'
            '<div style="font-size:1.1rem; font-weight:700; color:white; margin-bottom:4px;">'
            'Run Full ESG Pipeline</div>'
            '<div style="font-size:0.82rem; color:rgba(255,255,255,0.85); line-height:1.5;">'
            'Execute all 6 ESG agents automatically to analyse your data end-to-end.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        pipeline_clicked = st.button(
            "▶  Start Pipeline",
            key="home_run_pipeline",
            type="primary",
            use_container_width=True,
        )

    with col2:
        st.markdown(
            '<div class="action-btn-secondary">'
            '<div style="font-size:1.5rem; margin-bottom:8px;">\U0001f4c2</div>'
            '<div style="font-size:1.1rem; font-weight:700; color:#111827; margin-bottom:4px;">'
            'Go to Data Sources</div>'
            '<div style="font-size:0.82rem; color:#6B7280; line-height:1.5;">'
            'Upload files, connect databases, APIs, or cloud storage before running the pipeline.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.button(
            "\U0001f4c2  Open Data Sources",
            key="home_goto_datasources",
            use_container_width=True,
            on_click=lambda: st.session_state.update({"page": "datasources"}),
        )

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    if pipeline_clicked:
        st.session_state["pipeline_running"] = True
        st.session_state["pipeline_statuses"] = {a["key"]: "waiting" for a in AGENTS}
        st.session_state["pipeline_errors"] = {}

    if st.session_state.get("pipeline_running"):
        _run_pipeline()
    elif st.session_state.get("pipeline_completed"):
        _render_pipeline_results()

    # ── Quick-start guide ──
    st.markdown(
        '<div style="margin-bottom:20px;">'
        '<h3 style="margin:0; font-size:1.2rem; font-weight:700; color:#111827;">Quick Start Guide</h3>'
        '<p style="color:#6B7280; font-size:0.85rem; margin:4px 0 0 0;">'
        'Follow these steps to get your ESG data pipeline running.</p></div>',
        unsafe_allow_html=True,
    )

    current_user = get_current_user()

    c1, c2, c3 = st.columns(3)

    with c1:
        from utils.json_manager import get_datasources
        sources = get_datasources(username=current_user)
        connected = [s for s in sources if s.get("status") == "Connected"]
        has_sources = len(connected) > 0
        _guide_card(
            step="1",
            title="Connect Data Sources",
            description="Upload CSV files or connect to cloud storage, APIs, and databases to bring your ESG data into the platform.",
            target_page="datasources",
            button_label="Go to Data Sources",
            done=has_sources,
        )

    with c2:
        reg_sources = get_registered_sources()
        has_registered = len(reg_sources) > 0
        _guide_card(
            step="2",
            title="Register & Map Sources",
            description="Use the AI Registration Agent to profile your data schema, map columns to the canonical ESG model, and validate quality.",
            target_page="registration_agent",
            button_label="Go to Registration Agent",
            done=has_registered,
        )

    with c3:
        has_metric = st.session_state.get("fa_result") is not None
        _guide_card(
            step="3",
            title="Analyse Metrics",
            description="Run the Metric Analysis Agent to calculate trends, intensities, target progress, and detect anomalies in your ESG data.",
            target_page="metric_analysis",
            button_label="Go to Metric Analysis",
            done=has_metric,
        )

    c4, c5, c6 = st.columns(3)

    with c4:
        has_compliance = st.session_state.get("rta_results") is not None
        _guide_card(
            step="4",
            title="Regulatory Tracker",
            description="Assess compliance against global ESG regulations, identify gaps, and track remediation across multiple frameworks.",
            target_page="compliance_agent",
            button_label="Go to Regulatory Tracker",
            done=has_compliance,
        )

    with c5:
        has_benchmark = st.session_state.get("bm_result") is not None
        _guide_card(
            step="5",
            title="ESG Benchmarking",
            description="Compare your company's ESG performance against industry peers, identify strengths, and highlight areas for improvement.",
            target_page="benchmarking",
            button_label="Go to Benchmarking",
            done=has_benchmark,
        )

    with c6:
        has_risk = st.session_state.get("ro_results") is not None
        _guide_card(
            step="6",
            title="Risk & Opportunity",
            description="Identify ESG risks and opportunities, quantify financial impacts, and generate due-diligence recommendations.",
            target_page="risk_opportunity",
            button_label="Go to Risk & Opportunity",
            done=has_risk,
        )

    c7, _, _ = st.columns(3)

    with c7:
        has_review = st.session_state.get("review_results") is not None
        _guide_card(
            step="7",
            title="Review & Report",
            description="Validate findings across all agents, resolve conflicts, and generate the final ESG due-diligence report.",
            target_page="review_governance",
            button_label="Go to Review & Report",
            done=has_review,
        )

    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)

    # ── Recent activity (Admin only) ──
    if is_admin():
        st.markdown(
            '<h3 style="margin:0 0 12px 0; font-size:1.2rem; font-weight:700; color:#111827;">Recent Activity</h3>',
            unsafe_allow_html=True,
        )

        logs = get_audit_logs()
        user_logs = [l for l in logs if l.get("username") == current_user]
        recent = user_logs[-8:] if user_logs else []
        recent.reverse()

        if recent:
            for log in recent:
                action = log.get("action", "")
                ts = log.get("timestamp", "")
                icon = _action_icon(action)
                st.markdown(
                    f'<div style="display:flex; align-items:center; gap:10px; padding:8px 14px; '
                    f'border-bottom:1px solid #F3F4F6;">'
                    f'<span style="font-size:1rem;">{icon}</span>'
                    f'<span style="flex:1; font-size:0.88rem; color:#374151;">{action}</span>'
                    f'<span style="font-size:0.78rem; color:#9CA3AF; white-space:nowrap;">{ts}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div style="text-align:center; padding:24px; color:#9CA3AF; font-size:0.88rem;">'
                'No recent activity yet. Start by connecting a data source.</div>',
                unsafe_allow_html=True,
            )


# ════════════════════════════════════════════════════════════
#  Pipeline execution
# ════════════════════════════════════════════════════════════

def _render_agent_card(agent, status, error_msg=None):
    css_class = status if status in ("completed", "running", "failed", "skipped") else ""
    icon = _STATUS_ICONS.get(status, "⏳")
    status_label = status.capitalize()
    detail = ""
    if error_msg:
        detail = (
            f'<div style="font-size:0.75rem; color:#DC2626; margin-top:2px;">'
            f'{error_msg}</div>'
        )
    st.markdown(
        f'<div class="agent-card {css_class}">'
        f'  <span style="font-size:1.3rem;">{agent["icon"]}</span>'
        f'  <div style="flex:1;">'
        f'    <div style="font-size:0.9rem; font-weight:600; color:#111827;">{agent["name"]}</div>'
        f'    {detail}'
        f'  </div>'
        f'  <div style="display:flex; align-items:center; gap:6px;">'
        f'    <span style="font-size:1rem;">{icon}</span>'
        f'    <span style="font-size:0.78rem; font-weight:600; color:#6B7280;">{status_label}</span>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _run_pipeline():
    statuses = st.session_state.get("pipeline_statuses", {})
    errors = st.session_state.get("pipeline_errors", {})

    st.markdown(
        '<div style="margin-bottom:16px;">'
        '<h3 style="margin:0; font-size:1.15rem; font-weight:700; color:#111827;">'
        'Pipeline Progress</h3>'
        '<p style="color:#6B7280; font-size:0.84rem; margin:4px 0 0 0;">'
        'Running all 6 ESG agents sequentially...</p></div>',
        unsafe_allow_html=True,
    )

    progress_container = st.container()
    status_placeholder = st.empty()

    def _update_cards():
        with progress_container:
            for ag in AGENTS:
                _render_agent_card(
                    ag,
                    statuses.get(ag["key"], "waiting"),
                    errors.get(ag["key"]),
                )

    # --- 1. Registration Agent ---
    _set_status(statuses, "registration", "running")
    with status_placeholder.container():
        with st.spinner("Running Registration Agent..."):
            try:
                unreg = get_unregistered_files()
                reg_count = 0
                for filepath in unreg:
                    result = auto_register_source(filepath)
                    if result.get("status") == "completed":
                        reg_count += 1
                _set_status(statuses, "registration", "completed")
            except Exception as e:
                _set_status(statuses, "registration", "failed")
                errors["registration"] = str(e)[:120]

    # --- 2. Metric Analysis ---
    _set_status(statuses, "metric_analysis", "running")
    with status_placeholder.container():
        with st.spinner("Running Metric Analysis..."):
            try:
                companies = get_metric_companies()
                if companies:
                    company = companies[0]
                    metrics = get_available_metrics(company)
                    if metrics:
                        metric = metrics[0]
                        years = get_metric_years(company, metric)
                        if years:
                            year = years[-1]
                            result = run_full_analysis(company, metric, int(year))
                            if "error" not in result:
                                st.session_state["fa_result"] = result
                                _set_status(statuses, "metric_analysis", "completed")
                            else:
                                _set_status(statuses, "metric_analysis", "failed")
                                errors["metric_analysis"] = result["error"][:120]
                        else:
                            _set_status(statuses, "metric_analysis", "skipped")
                            errors["metric_analysis"] = "No reporting years available"
                    else:
                        _set_status(statuses, "metric_analysis", "skipped")
                        errors["metric_analysis"] = "No metrics available"
                else:
                    _set_status(statuses, "metric_analysis", "skipped")
                    errors["metric_analysis"] = "No company data available"
            except Exception as e:
                _set_status(statuses, "metric_analysis", "failed")
                errors["metric_analysis"] = str(e)[:120]

    # --- 3. Compliance / Regulatory Tracker ---
    _set_status(statuses, "compliance", "running")
    with status_placeholder.container():
        with st.spinner("Running Regulatory Tracker..."):
            try:
                comp_companies = get_compliance_companies()
                comp_years = get_compliance_years()
                if comp_companies and comp_years:
                    comp_company = comp_companies[0]
                    comp_year = comp_years[-1]
                    regs = load_regulation_master()
                    all_results = []
                    if not regs.empty:
                        for _, reg_row in regs.iterrows():
                            reg_id = reg_row["regulation_id"]
                            res = run_full_compliance_assessment(
                                comp_company, reg_id, int(comp_year))
                            all_results.append(res)
                        st.session_state["rta_results"] = all_results
                        _set_status(statuses, "compliance", "completed")
                    else:
                        _set_status(statuses, "compliance", "skipped")
                        errors["compliance"] = "No regulations defined"
                else:
                    _set_status(statuses, "compliance", "skipped")
                    errors["compliance"] = "No company or year data available"
            except Exception as e:
                _set_status(statuses, "compliance", "failed")
                errors["compliance"] = str(e)[:120]

    # --- 4. Benchmarking ---
    _set_status(statuses, "benchmarking", "running")
    with status_placeholder.container():
        with st.spinner("Running Benchmarking..."):
            try:
                bm_companies = get_bm_companies()
                if bm_companies:
                    bm_company = bm_companies[0]
                    bm_metrics = get_bm_metrics()
                    if bm_metrics:
                        bm_years = get_bm_years(
                            bm_company["company_id"], bm_metrics[0]["metric_code"])
                        if bm_years:
                            bm_year = bm_years[-1]
                            bm_result = run_benchmark(
                                bm_company["company_id"],
                                bm_metrics[0]["metric_code"],
                                bm_year,
                            )
                            if bm_result:
                                st.session_state["bm_result"] = bm_result
                            summary = run_benchmark_summary(
                                bm_company["company_id"], bm_year)
                            if summary:
                                st.session_state["bm_summary"] = summary
                            _set_status(statuses, "benchmarking", "completed")
                        else:
                            _set_status(statuses, "benchmarking", "skipped")
                            errors["benchmarking"] = "No years available"
                    else:
                        _set_status(statuses, "benchmarking", "skipped")
                        errors["benchmarking"] = "No metrics available"
                else:
                    _set_status(statuses, "benchmarking", "skipped")
                    errors["benchmarking"] = "No company data available"
            except Exception as e:
                _set_status(statuses, "benchmarking", "failed")
                errors["benchmarking"] = str(e)[:120]

    # --- 5. Risk & Opportunity ---
    _set_status(statuses, "risk_opportunity", "running")
    with status_placeholder.container():
        with st.spinner("Running Risk & Opportunity analysis..."):
            try:
                deals = get_available_deals()
                if deals:
                    deal = deals[0]
                    result = run_risk_opportunity_analysis(
                        deal["deal_id"], deal["company_id"])
                    st.session_state["ro_results"] = result
                    _set_status(statuses, "risk_opportunity", "completed")
                else:
                    _set_status(statuses, "risk_opportunity", "skipped")
                    errors["risk_opportunity"] = "No deal data available"
            except Exception as e:
                _set_status(statuses, "risk_opportunity", "failed")
                errors["risk_opportunity"] = str(e)[:120]

    # --- 6. Review & Report ---
    _set_status(statuses, "review", "running")
    with status_placeholder.container():
        with st.spinner("Running Review & Report..."):
            try:
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

                if agent_outputs:
                    deals = get_available_deals()
                    deal = deals[0] if deals else {"deal_id": "", "company_id": ""}
                    usr = st.session_state.get("user", "system")
                    result = run_review_governance(
                        deal.get("deal_id", ""),
                        deal.get("company_id", ""),
                        usr,
                        agent_outputs,
                    )
                    st.session_state["review_results"] = result
                    _set_status(statuses, "review", "completed")
                else:
                    _set_status(statuses, "review", "skipped")
                    errors["review"] = "No agent outputs to review"
            except Exception as e:
                _set_status(statuses, "review", "failed")
                errors["review"] = str(e)[:120]

    st.session_state["pipeline_running"] = False
    st.session_state["pipeline_completed"] = True
    st.session_state["pipeline_statuses"] = statuses
    st.session_state["pipeline_errors"] = errors
    st.rerun()


def _render_pipeline_results():
    statuses = st.session_state.get("pipeline_statuses", {})
    errors = st.session_state.get("pipeline_errors", {})

    st.markdown(
        '<div style="margin-bottom:16px;">'
        '<h3 style="margin:0; font-size:1.15rem; font-weight:700; color:#111827;">'
        'Pipeline Results</h3></div>',
        unsafe_allow_html=True,
    )

    for ag in AGENTS:
        _render_agent_card(
            ag,
            statuses.get(ag["key"], "waiting"),
            errors.get(ag["key"]),
        )

    completed_count = sum(1 for s in statuses.values() if s == "completed")
    failed_count = sum(1 for s in statuses.values() if s == "failed")

    all_success = failed_count == 0

    if all_success:
        st.markdown(
            '<div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:14px; '
            'padding:20px 24px; margin:16px 0; text-align:center;">'
            '<div style="font-size:1.5rem; margin-bottom:6px;">✅</div>'
            '<div style="font-size:1.1rem; font-weight:700; color:#065F46; margin-bottom:4px;">'
            'ESG Pipeline Completed Successfully</div>'
            '<div style="font-size:0.85rem; color:#047857;">'
            'Your ESG analysis is complete. Click &ldquo;Review &amp; Report Agent&rdquo; '
            'to generate and download the final report.</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="background:#FFF7ED; border:1px solid #FDBA74; border-radius:14px; '
            f'padding:20px 24px; margin:16px 0; text-align:center;">'
            f'<div style="font-size:1.5rem; margin-bottom:6px;">⚠️</div>'
            f'<div style="font-size:1.1rem; font-weight:700; color:#92400E; margin-bottom:4px;">'
            f'Pipeline Completed with Issues</div>'
            f'<div style="font-size:0.85rem; color:#B45309;">'
            f'{completed_count} agents completed, {failed_count} failed. '
            f'Review the results below and re-run individual agents if needed.</div></div>',
            unsafe_allow_html=True,
        )

    if all_success:
        st.markdown('<div class="pipeline-done-actions">', unsafe_allow_html=True)
        btn_left, btn_right = st.columns(2)
        with btn_left:
            st.button(
                "\U0001f4c4  Review & Report Agent",
                key="home_goto_review",
                type="primary",
                use_container_width=True,
                on_click=lambda: st.session_state.update({"page": "review_governance"}),
            )
        with btn_right:
            if st.button("Reset Pipeline", key="home_reset_pipeline", use_container_width=True):
                for k in ("pipeline_running", "pipeline_completed",
                           "pipeline_statuses", "pipeline_errors"):
                    st.session_state.pop(k, None)
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        if st.button("Reset Pipeline", key="home_reset_pipeline"):
            for k in ("pipeline_running", "pipeline_completed",
                       "pipeline_statuses", "pipeline_errors"):
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")


def _set_status(statuses, key, status):
    statuses[key] = status
    st.session_state["pipeline_statuses"] = statuses


# ════════════════════════════════════════════════════════════
#  Helper components
# ════════════════════════════════════════════════════════════

def _guide_card(step, title, description, target_page, button_label, done=False):
    check = (
        '<div style="position:absolute; top:12px; right:14px; width:24px; height:24px; '
        'background:#ECFDF5; border-radius:50%; display:flex; align-items:center; '
        'justify-content:center; font-size:0.75rem; color:#059669; font-weight:700;">&#10003;</div>'
        if done else ""
    )
    border_color = "#86efac" if done else "#E5E7EB"

    st.markdown(
        f'<div style="border:1px solid {border_color}; border-radius:14px; padding:22px; '
        f'background:white; position:relative; min-height:180px;">'
        f'{check}'
        f'<div style="width:32px; height:32px; background:linear-gradient(135deg,#FF5A00,#FF7F32); '
        f'border-radius:8px; display:flex; align-items:center; justify-content:center; '
        f'font-size:0.85rem; color:white; font-weight:700; margin-bottom:12px;">{step}</div>'
        f'<div style="font-size:1rem; font-weight:700; color:#111827; margin-bottom:6px;">{title}</div>'
        f'<div style="font-size:0.82rem; color:#6B7280; line-height:1.55; margin-bottom:14px;">'
        f'{description}</div></div>',
        unsafe_allow_html=True,
    )

    st.button(
        button_label,
        key=f"guide_{target_page}",
        use_container_width=True,
        type="primary" if not done else "secondary",
        on_click=lambda p=target_page: st.session_state.update({"page": p}),
    )


def _action_icon(action):
    a = action.lower()
    if "login" in a:
        return "&#128274;"
    if "registered" in a or "register" in a:
        return "&#128203;"
    if "loaded" in a or "load" in a:
        return "&#128229;"
    if "connected" in a or "connect" in a:
        return "&#128279;"
    if "approved" in a:
        return "&#9989;"
    if "collection" in a:
        return "&#128194;"
    return "&#128196;"
