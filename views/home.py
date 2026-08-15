"""
Home / Dashboard — landing page after login.

Shows a professional ESG pipeline monitor with stats cards, action center,
quick-start guide, and recent activity.
"""

import streamlit as st
from datetime import datetime, timedelta
from utils.auth import get_current_user, is_admin
from utils.json_manager import get_audit_logs, get_datasources

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
    get_unregistered_files,
    auto_register_source,
)


# ════════════════════════════════════════════════════════════
#  CSS
# ════════════════════════════════════════════════════════════

_DASHBOARD_CSS = """
<style>
/* ── Animations ── */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes progressStripe {
    0% { background-position: 0 0; }
    100% { background-position: 40px 0; }
}
@keyframes runPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(255, 90, 0, 0.15); }
    50% { box-shadow: 0 0 0 8px rgba(255, 90, 0, 0); }
}
@keyframes pulse-glow {
    0%, 100% { box-shadow: 0 4px 16px rgba(255, 90, 0, 0.25); }
    50% { box-shadow: 0 4px 24px rgba(255, 90, 0, 0.5); }
}
@keyframes spinLoader {
    to { transform: rotate(360deg); }
}

/* ── Stats Cards ── */
.stats-row {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
    margin-bottom: 24px;
}
.stat-card {
    background: white; border: 1px solid #E5E7EB; border-radius: 16px;
    padding: 22px 24px; position: relative; overflow: hidden;
    animation: fadeInUp 0.45s ease-out both;
    transition: box-shadow 0.2s ease;
}
.stat-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.06); }
.stat-card:nth-child(1) { animation-delay: 0.04s; }
.stat-card:nth-child(2) { animation-delay: 0.08s; }
.stat-card:nth-child(3) { animation-delay: 0.12s; }
.stat-icon {
    width: 44px; height: 44px; border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 14px;
}
.stat-icon.orange { background: #FFF7ED; }
.stat-icon.green { background: #ECFDF5; }
.stat-icon.blue { background: #EFF6FF; }
.stat-label {
    font-size: 0.78rem; font-weight: 600; color: #6B7280;
    text-transform: uppercase; letter-spacing: 0.05em;
    margin-bottom: 6px;
}
.stat-value {
    font-size: 1.85rem; font-weight: 800; color: #111827; line-height: 1;
}
.stat-value.text-sm { font-size: 1.1rem; font-weight: 700; }

/* ── Action Cards ── */
.action-cards-row {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 20px;
    margin-bottom: 10px;
}
.action-card-primary {
    background: linear-gradient(135deg, #FF5A00 0%, #FF7F32 100%);
    border-radius: 20px; padding: 32px 28px;
    position: relative; overflow: hidden;
    box-shadow: 0 4px 24px rgba(255, 90, 0, 0.25);
    transition: all 0.3s cubic-bezier(0.23,1,0.32,1);
    animation: fadeInUp 0.5s ease-out 0.16s both;
    min-height: 185px;
}
.action-card-primary:hover {
    box-shadow: 0 8px 32px rgba(255, 90, 0, 0.35);
    transform: translateY(-3px);
}
.action-card-primary .card-play-sm {
    width: 40px; height: 40px; border-radius: 12px;
    background: rgba(255,255,255,0.18); display: flex;
    align-items: center; justify-content: center; margin-bottom: 16px;
}
.action-card-primary .card-title {
    font-size: 1.2rem; font-weight: 700; color: white; margin-bottom: 6px;
}
.action-card-primary .card-desc {
    font-size: 0.84rem; color: rgba(255,255,255,0.85); line-height: 1.55;
}
.action-card-primary .bg-circle-1 {
    position: absolute; right: -20px; bottom: -20px;
    width: 160px; height: 160px; border-radius: 50%;
    background: rgba(255,255,255,0.07);
}
.action-card-primary .bg-circle-2 {
    position: absolute; right: 50px; bottom: 40px;
    width: 90px; height: 90px; border-radius: 50%;
    background: rgba(255,255,255,0.05);
}
.action-card-secondary {
    background: white; border: 1.5px solid #E5E7EB;
    border-radius: 20px; padding: 32px 28px;
    position: relative; overflow: hidden;
    transition: all 0.3s cubic-bezier(0.23,1,0.32,1);
    animation: fadeInUp 0.5s ease-out 0.2s both;
    min-height: 185px;
}
.action-card-secondary:hover {
    border-color: #FF5A00; background: #FFFAF7;
    box-shadow: 0 4px 20px rgba(255, 90, 0, 0.10);
    transform: translateY(-3px);
}
.action-card-secondary .card-icon {
    width: 40px; height: 40px; border-radius: 12px;
    background: #FFF7ED; display: flex;
    align-items: center; justify-content: center; margin-bottom: 16px;
}
.action-card-secondary .card-title {
    font-size: 1.2rem; font-weight: 700; color: #111827; margin-bottom: 6px;
}
.action-card-secondary .card-desc {
    font-size: 0.84rem; color: #6B7280; line-height: 1.55;
}
.action-card-secondary .bg-icon {
    position: absolute; right: -10px; bottom: -10px;
    width: 140px; height: 140px; border-radius: 50%;
    background: rgba(255, 90, 0, 0.025);
}

/* ── Pipeline Monitor ── */
.pipeline-monitor {
    background: white; border: 1px solid #E5E7EB; border-radius: 20px;
    padding: 28px; margin-bottom: 20px;
    animation: fadeInUp 0.45s ease-out both;
}
.pipeline-header {
    display: flex; align-items: flex-start; justify-content: space-between;
    margin-bottom: 16px;
}
.pipeline-header-title {
    font-size: 1.1rem; font-weight: 700; color: #111827;
}
.pipeline-header-sub {
    font-size: 0.82rem; color: #6B7280; margin-top: 3px;
}
.pipeline-pct {
    font-size: 1.6rem; font-weight: 800; color: #FF5A00; line-height: 1;
}
.pipeline-bar-bg {
    width: 100%; height: 8px; border-radius: 4px;
    background: #F3F4F6; overflow: hidden; margin-bottom: 24px;
}
.pipeline-bar-fill {
    height: 100%; border-radius: 4px;
    background: linear-gradient(90deg, #FF5A00, #FF7F32);
    transition: width 0.5s cubic-bezier(0.23,1,0.32,1);
}
.pipeline-bar-fill.striped {
    background-image: linear-gradient(
        -45deg,
        rgba(255,255,255,0.2) 25%, transparent 25%,
        transparent 50%, rgba(255,255,255,0.2) 50%,
        rgba(255,255,255,0.2) 75%, transparent 75%
    );
    background-size: 40px 40px;
    animation: progressStripe 0.8s linear infinite;
}
.pipeline-steps {
    display: flex; flex-direction: column; gap: 6px;
    max-height: 340px; overflow-y: auto; scroll-behavior: smooth;
    padding-right: 4px;
}
.pipeline-steps::-webkit-scrollbar { width: 5px; }
.pipeline-steps::-webkit-scrollbar-track { background: #F3F4F6; border-radius: 4px; }
.pipeline-steps::-webkit-scrollbar-thumb { background: #D1D5DB; border-radius: 4px; }
.pipeline-steps::-webkit-scrollbar-thumb:hover { background: #9CA3AF; }
.p-step {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 18px; border-radius: 12px;
    border: 1px solid #E5E7EB; background: #FAFAFA;
    transition: all 0.25s ease;
}
.p-step.running {
    border-color: #FDBA74; background: #FFFAF5;
    animation: runPulse 2s ease-in-out infinite;
}
.p-step.completed { border-color: #86EFAC; background: #F0FDF4; }
.p-step.failed { border-color: #FCA5A5; background: #FEF2F2; }
.p-step.skipped { border-color: #E5E7EB; background: #F9FAFB; opacity: 0.7; }
.step-num {
    width: 34px; height: 34px; min-width: 34px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.82rem;
}
.step-num.waiting { background: #F3F4F6; color: #9CA3AF; border: 2px solid #E5E7EB; }
.step-num.running {
    background: linear-gradient(135deg, #FF5A00, #FF7F32);
    color: white; border: none;
}
.step-num.completed { background: #ECFDF5; color: #059669; border: 2px solid #86EFAC; }
.step-num.failed { background: #FEF2F2; color: #DC2626; border: 2px solid #FCA5A5; }
.step-num.skipped { background: #F3F4F6; color: #9CA3AF; border: 2px solid #E5E7EB; }
.step-info { flex: 1; min-width: 0; }
.step-name { font-size: 0.9rem; font-weight: 600; color: #111827; }
.step-err { font-size: 0.75rem; color: #DC2626; margin-top: 2px; }
.step-right { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.step-dur {
    font-size: 0.75rem; color: #9CA3AF;
    font-variant-numeric: tabular-nums; min-width: 44px; text-align: right;
}
.step-pill {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 10px; border-radius: 20px;
    font-size: 0.7rem; font-weight: 600;
}
.step-pill.waiting { background: #F3F4F6; color: #9CA3AF; }
.step-pill.running { background: #FFF7ED; color: #EA580C; }
.step-pill.completed { background: #ECFDF5; color: #059669; }
.step-pill.failed { background: #FEF2F2; color: #DC2626; }
.step-pill.skipped { background: #F3F4F6; color: #9CA3AF; }
.step-spinner {
    width: 14px; height: 14px; border: 2px solid rgba(255,90,0,0.2);
    border-top-color: #FF5A00; border-radius: 50%;
    animation: spinLoader 0.7s linear infinite;
    display: inline-block;
}

/* Pipeline summary banner */
.pipeline-summary {
    border-radius: 16px; padding: 22px 26px; margin-bottom: 20px;
    display: flex; align-items: center; gap: 16px;
    animation: fadeInUp 0.4s ease-out both;
}
.pipeline-summary.success {
    background: linear-gradient(135deg, #ECFDF5, #D1FAE5);
    border: 1px solid #86EFAC;
}
.pipeline-summary.warning {
    background: linear-gradient(135deg, #FFFBEB, #FEF3C7);
    border: 1px solid #FCD34D;
}
.pipeline-summary-icon {
    width: 48px; height: 48px; min-width: 48px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.4rem;
}
.pipeline-summary.success .pipeline-summary-icon { background: #D1FAE5; }
.pipeline-summary.warning .pipeline-summary-icon { background: #FEF3C7; }
.pipeline-summary-title { font-size: 1.05rem; font-weight: 700; }
.pipeline-summary.success .pipeline-summary-title { color: #065F46; }
.pipeline-summary.warning .pipeline-summary-title { color: #92400E; }
.pipeline-summary-detail { font-size: 0.84rem; margin-top: 2px; }
.pipeline-summary.success .pipeline-summary-detail { color: #047857; }
.pipeline-summary.warning .pipeline-summary-detail { color: #B45309; }

.pipeline-done-actions button[kind="primary"] {
    animation: pulse-glow 1.5s ease-in-out infinite;
}

/* ── Activity Rows ── */
.activity-row {
    display: flex; align-items: center; gap: 12px;
    padding: 11px 16px; margin-bottom: 5px;
    border-radius: 10px; background: white;
    border: 1px solid #F3F4F6;
    border-left: 3px solid #E5E7EB;
    transition: background 0.15s ease;
}
.activity-row:hover { background: #FAFAFA; }
.activity-row.login { border-left-color: #D1D5DB; }
.activity-row.data { border-left-color: #60A5FA; }
.activity-row.register { border-left-color: #34D399; }
.activity-row.pipeline { border-left-color: #FF7F32; }
.activity-icon {
    width: 32px; height: 32px; min-width: 32px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.9rem; background: #F3F4F6;
}
.activity-text { flex: 1; font-size: 0.86rem; color: #374151; }
.activity-time { font-size: 0.76rem; color: #9CA3AF; white-space: nowrap; }

/* ── Pipeline Status Badge ── */
.pipeline-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 5px 14px; border-radius: 20px;
    font-size: 0.75rem; font-weight: 600;
    white-space: nowrap; flex-shrink: 0;
}
.pipeline-badge.ready { background: #ECFDF5; color: #059669; }
.pipeline-badge.running { background: #FFF7ED; color: #EA580C; }
.pipeline-badge.completed { background: #ECFDF5; color: #059669; }
.pipeline-badge-dot {
    width: 7px; height: 7px; border-radius: 50%;
}
.pipeline-badge.ready .pipeline-badge-dot { background: #22C55E; }
.pipeline-badge.running .pipeline-badge-dot {
    background: #F97316;
    animation: badgePulse 1.5s ease-in-out infinite;
}
.pipeline-badge.completed .pipeline-badge-dot { background: #22C55E; }
@keyframes badgePulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}

/* ── Responsive ── */
@media (max-width: 900px) {
    .stats-row { grid-template-columns: repeat(2, 1fr); }
    .action-cards-row { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
    .stats-row { grid-template-columns: 1fr; }
    .stat-value { font-size: 1.5rem !important; }
    .action-card-primary, .action-card-secondary {
        padding: 24px 20px; min-height: 140px;
    }
    .p-step { padding: 10px 12px; gap: 10px; }
    .step-dur { display: none; }
    .pipeline-monitor { padding: 20px; }
}
</style>
"""


# ════════════════════════════════════════════════════════════
#  Constants
# ════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════
#  Main render
# ════════════════════════════════════════════════════════════

def render():
    st.markdown(_DASHBOARD_CSS, unsafe_allow_html=True)

    user = st.session_state.get("full_name", st.session_state.get("user", ""))
    current_user = get_current_user()

    hour = datetime.now().hour
    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    # ── Pipeline badge ──
    pipeline_running = st.session_state.get("pipeline_running", False)
    pipeline_completed = st.session_state.get("pipeline_completed", False)
    if pipeline_running:
        badge_cls, badge_label = "running", "Pipeline Running"
    elif pipeline_completed:
        badge_cls, badge_label = "completed", "Pipeline Complete"
    else:
        badge_cls, badge_label = "ready", "Pipeline Status: Ready"

    # ── Greeting ──
    st.markdown(
        f'<div style="margin-bottom:24px; animation: fadeInUp 0.4s ease-out both; display:flex; align-items:flex-start; justify-content:space-between;">'
        f'<div>'
        f'<h2 style="margin:0; font-size:1.55rem; font-weight:700; color:#111827;">'
        f'{greeting}, {user}</h2>'
        f'<p style="color:#6B7280; font-size:0.9rem; margin:5px 0 0 0; line-height:1.6;">'
        f'Welcome to the ESG Data Platform. Here\'s an overview of your workspace.</p>'
        f'</div>'
        f'<div class="pipeline-badge {badge_cls}">'
        f'<span class="pipeline-badge-dot"></span>'
        f'{badge_label}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Stats cards ──
    sources = get_datasources(username=current_user)
    connected_count = len([s for s in sources if s.get("status") == "Connected"])
    agent_count = len(AGENTS)
    recent_analysis = _get_recent_analysis_time()

    recent_cls = "" if len(recent_analysis) <= 12 else " text-sm"

    st.markdown(f'''
    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-icon orange">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                     stroke="#EA580C" stroke-width="1.75" stroke-linecap="round"
                     stroke-linejoin="round">
                    <ellipse cx="12" cy="5" rx="9" ry="3"/>
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
                    <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
                </svg>
            </div>
            <div class="stat-label">Data Sources Connected</div>
            <div class="stat-value">{connected_count}</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon green">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                     stroke="#059669" stroke-width="1.75" stroke-linecap="round"
                     stroke-linejoin="round">
                    <circle cx="12" cy="12" r="3"/>
                    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
                </svg>
            </div>
            <div class="stat-label">ESG Agents Available</div>
            <div class="stat-value">{agent_count}</div>
        </div>
        <div class="stat-card">
            <div class="stat-icon blue">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                     stroke="#2563EB" stroke-width="1.75" stroke-linecap="round"
                     stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>
            </div>
            <div class="stat-label">Recent Analysis</div>
            <div class="stat-value{recent_cls}">{recent_analysis}</div>
        </div>
    </div>
    ''', unsafe_allow_html=True)

    # ── Action cards (HTML decoration + Streamlit buttons) ──
    st.markdown(f'''
    <div class="action-cards-row">
        <div class="action-card-primary">
            <div class="card-play-sm">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="white" stroke="none">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
            </div>
            <div class="card-title">Run Full ESG Pipeline</div>
            <div class="card-desc">Execute all 6 ESG agents automatically to analyse
            your data end-to-end.</div>
            <div class="bg-circle-1"></div>
            <div class="bg-circle-2"></div>
        </div>
        <div class="action-card-secondary">
            <div class="card-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
                     stroke="#FF5A00" stroke-width="1.75" stroke-linecap="round"
                     stroke-linejoin="round">
                    <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>
                </svg>
            </div>
            <div class="card-title">Go to Data Sources</div>
            <div class="card-desc">Upload files, connect databases, APIs, or cloud
            storage before running the pipeline.</div>
            <div class="bg-icon"></div>
        </div>
    </div>
    ''', unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        pipeline_clicked = st.button(
            "▶  Start Pipeline",
            key="home_run_pipeline",
            type="primary",
            use_container_width=True,
        )
    with col2:
        st.button(
            "\U0001f4c2  Open Data Sources",
            key="home_goto_datasources",
            use_container_width=True,
            on_click=lambda: st.session_state.update({"page": "datasources"}),
        )

    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    if pipeline_clicked:
        st.session_state["pipeline_running"] = True
        st.session_state["pipeline_statuses"] = {a["key"]: "waiting" for a in AGENTS}
        st.session_state["pipeline_errors"] = {}
        st.session_state["pipeline_agent_times"] = {}
        st.session_state["pipeline_start_time"] = datetime.now()

    if st.session_state.get("pipeline_running"):
        _run_pipeline()
    elif st.session_state.get("pipeline_completed"):
        _render_pipeline_results()

    # ── Recent activity (Admin only) ──
    if is_admin():
        st.markdown(
            '<h3 style="margin:0 0 12px 0; font-size:1.15rem; font-weight:700; color:#111827;">'
            'Recent Activity</h3>',
            unsafe_allow_html=True,
        )

        logs = get_audit_logs()
        user_logs = [l for l in logs if l.get("username") == current_user]
        recent = user_logs[-6:] if user_logs else []
        recent.reverse()

        if recent:
            for log in recent:
                action = log.get("action", "")
                ts = log.get("timestamp", "")
                icon = _action_icon(action)
                row_cls = _action_row_class(action)
                relative_ts = _relative_time_str(ts)
                st.markdown(
                    f'<div class="activity-row {row_cls}">'
                    f'<div class="activity-icon">{icon}</div>'
                    f'<div class="activity-text">{action}</div>'
                    f'<div class="activity-time">{relative_ts}</div>'
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
#  Pipeline monitor renderer
# ════════════════════════════════════════════════════════════

_PIPELINE_MONITOR_CSS = """
@keyframes progressStripe {
    0% { background-position: 0 0; }
    100% { background-position: 40px 0; }
}
@keyframes runPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(255, 90, 0, 0.15); }
    50% { box-shadow: 0 0 0 8px rgba(255, 90, 0, 0); }
}
@keyframes spinLoader {
    to { transform: rotate(360deg); }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Source Sans Pro', -apple-system, BlinkMacSystemFont, sans-serif; background: transparent; }
.pipeline-monitor {
    background: white; border: 1px solid #E5E7EB; border-radius: 20px;
    padding: 28px;
}
.pipeline-header {
    display: flex; align-items: flex-start; justify-content: space-between;
    margin-bottom: 16px;
}
.pipeline-header-title { font-size: 1.1rem; font-weight: 700; color: #111827; }
.pipeline-header-sub { font-size: 0.82rem; color: #6B7280; margin-top: 3px; }
.pipeline-pct { font-size: 1.6rem; font-weight: 800; color: #FF5A00; line-height: 1; }
.pipeline-bar-bg {
    width: 100%; height: 8px; border-radius: 4px;
    background: #F3F4F6; overflow: hidden; margin-bottom: 24px;
}
.pipeline-bar-fill {
    height: 100%; border-radius: 4px;
    background: linear-gradient(90deg, #FF5A00, #FF7F32);
    transition: width 0.5s cubic-bezier(0.23,1,0.32,1);
}
.pipeline-bar-fill.striped {
    background-image: linear-gradient(
        -45deg,
        rgba(255,255,255,0.2) 25%, transparent 25%,
        transparent 50%, rgba(255,255,255,0.2) 50%,
        rgba(255,255,255,0.2) 75%, transparent 75%
    );
    background-size: 40px 40px;
    animation: progressStripe 0.8s linear infinite;
}
.pipeline-steps {
    display: flex; flex-direction: column; gap: 6px;
    max-height: 340px; overflow-y: auto; scroll-behavior: smooth;
    padding-right: 4px;
}
.pipeline-steps::-webkit-scrollbar { width: 5px; }
.pipeline-steps::-webkit-scrollbar-track { background: #F3F4F6; border-radius: 4px; }
.pipeline-steps::-webkit-scrollbar-thumb { background: #D1D5DB; border-radius: 4px; }
.pipeline-steps::-webkit-scrollbar-thumb:hover { background: #9CA3AF; }
.p-step {
    display: flex; align-items: center; gap: 14px;
    padding: 14px 18px; border-radius: 12px;
    border: 1px solid #E5E7EB; background: #FAFAFA;
    transition: all 0.25s ease;
}
.p-step.running { border-color: #FDBA74; background: #FFFAF5; animation: runPulse 2s ease-in-out infinite; }
.p-step.completed { border-color: #86EFAC; background: #F0FDF4; }
.p-step.failed { border-color: #FCA5A5; background: #FEF2F2; }
.p-step.skipped { border-color: #E5E7EB; background: #F9FAFB; opacity: 0.7; }
.step-num {
    width: 34px; height: 34px; min-width: 34px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 0.82rem;
}
.step-num.waiting { background: #F3F4F6; color: #9CA3AF; border: 2px solid #E5E7EB; }
.step-num.running { background: linear-gradient(135deg, #FF5A00, #FF7F32); color: white; border: none; }
.step-num.completed { background: #ECFDF5; color: #059669; border: 2px solid #86EFAC; }
.step-num.failed { background: #FEF2F2; color: #DC2626; border: 2px solid #FCA5A5; }
.step-num.skipped { background: #F3F4F6; color: #9CA3AF; border: 2px solid #E5E7EB; }
.step-info { flex: 1; min-width: 0; }
.step-name { font-size: 0.9rem; font-weight: 600; color: #111827; }
.step-err { font-size: 0.75rem; color: #DC2626; margin-top: 2px; }
.step-right { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.step-dur {
    font-size: 0.75rem; color: #9CA3AF;
    font-variant-numeric: tabular-nums; min-width: 44px; text-align: right;
}
.step-pill {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 10px; border-radius: 20px;
    font-size: 0.7rem; font-weight: 600;
}
.step-pill.waiting { background: #F3F4F6; color: #9CA3AF; }
.step-pill.running { background: #FFF7ED; color: #EA580C; }
.step-pill.completed { background: #ECFDF5; color: #059669; }
.step-pill.failed { background: #FEF2F2; color: #DC2626; }
.step-pill.skipped { background: #F3F4F6; color: #9CA3AF; }
.step-spinner {
    width: 14px; height: 14px; border: 2px solid rgba(255,90,0,0.2);
    border-top-color: #FF5A00; border-radius: 50%;
    animation: spinLoader 0.7s linear infinite;
    display: inline-block;
}
"""


def _build_pipeline_monitor_html(statuses, errors, agent_times, is_running=True):
    completed = sum(1 for s in statuses.values() if s in ("completed", "failed", "skipped"))
    has_running = any(s == "running" for s in statuses.values())
    total = len(AGENTS)
    pct = int((completed + (0.5 if has_running else 0)) / total * 100)
    bar_cls = "striped" if has_running else ""

    subtitle = "Running all 6 ESG agents sequentially..." if is_running else "Pipeline execution complete."

    steps_html = ""
    for i, agent in enumerate(AGENTS):
        status = statuses.get(agent["key"], "waiting")
        error = errors.get(agent["key"])
        times = agent_times.get(agent["key"], {})
        dur_s = times.get("duration_s")

        dur_str = ""
        if dur_s is not None:
            dur_str = f"{dur_s:.1f}s" if dur_s < 60 else f"{dur_s / 60:.1f}m"

        badge_content = _step_badge_html(i + 1, status)
        pill = f'<span class="step-pill {status}">{status.capitalize()}</span>'
        err_html = f'<div class="step-err">{error}</div>' if error else ""

        spinner = ""
        if status == "running":
            spinner = '<span class="step-spinner"></span>'

        steps_html += f'''
        <div class="p-step {status}">
            {badge_content}
            <div class="step-info">
                <div class="step-name">{agent["name"]}</div>
                {err_html}
            </div>
            <div class="step-right">
                {spinner}
                <span class="step-dur">{dur_str}</span>
                {pill}
            </div>
        </div>'''

    return f'''<html><head><style>{_PIPELINE_MONITOR_CSS}</style></head>
<body>
<div class="pipeline-monitor">
    <div class="pipeline-header">
        <div>
            <div class="pipeline-header-title">Pipeline Execution</div>
            <div class="pipeline-header-sub">{subtitle}</div>
        </div>
        <div class="pipeline-pct">{pct}%</div>
    </div>
    <div class="pipeline-bar-bg">
        <div class="pipeline-bar-fill {bar_cls}" style="width:{pct}%"></div>
    </div>
    <div class="pipeline-steps">{steps_html}</div>
</div>
</body></html>'''


def _step_badge_html(num, status):
    if status == "completed":
        return '<div class="step-num completed">&#10003;</div>'
    if status == "failed":
        return '<div class="step-num failed">&#10007;</div>'
    return f'<div class="step-num {status}">{num}</div>'


# ════════════════════════════════════════════════════════════
#  Pipeline execution
# ════════════════════════════════════════════════════════════

def _run_pipeline():
    statuses = st.session_state.get("pipeline_statuses", {})
    errors = st.session_state.get("pipeline_errors", {})
    agent_times = st.session_state.get("pipeline_agent_times", {})

    import streamlit.components.v1 as _stc
    _pipeline_height = 470

    monitor = st.empty()

    def _update_monitor():
        with monitor.container():
            _stc.html(
                _build_pipeline_monitor_html(statuses, errors, agent_times, is_running=True),
                height=_pipeline_height, scrolling=False,
            )

    _update_monitor()

    # --- 1. Registration Agent ---
    _begin_agent(statuses, agent_times, "registration")
    _update_monitor()
    try:
        unreg = get_unregistered_files()
        for filepath in unreg:
            auto_register_source(filepath)
        _set_status(statuses, "registration", "completed")
    except Exception as e:
        _set_status(statuses, "registration", "failed")
        errors["registration"] = str(e)[:120]
    _end_agent(agent_times, "registration")
    _update_monitor()

    # --- 2. Metric Analysis ---
    _begin_agent(statuses, agent_times, "metric_analysis")
    _update_monitor()
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
    _end_agent(agent_times, "metric_analysis")
    _update_monitor()

    # --- 3. Compliance / Regulatory Tracker ---
    _begin_agent(statuses, agent_times, "compliance")
    _update_monitor()
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
    _end_agent(agent_times, "compliance")
    _update_monitor()

    # --- 4. Benchmarking ---
    _begin_agent(statuses, agent_times, "benchmarking")
    _update_monitor()
    try:
        bm_companies = get_bm_companies()
        if bm_companies:
            bm_company = bm_companies[0]
            bm_metrics_list = get_bm_metrics(bm_company["company_id"])
            if bm_metrics_list:
                bm_years = get_bm_years(
                    bm_company["company_id"], bm_metrics_list[0]["metric_code"])
                if bm_years:
                    bm_year = bm_years[-1]
                    bm_result = run_benchmark(
                        bm_company["company_id"],
                        bm_metrics_list[0]["metric_code"],
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
    _end_agent(agent_times, "benchmarking")
    _update_monitor()

    # --- 5. Risk & Opportunity ---
    _begin_agent(statuses, agent_times, "risk_opportunity")
    _update_monitor()
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
    _end_agent(agent_times, "risk_opportunity")
    _update_monitor()

    # --- 6. Review & Report ---
    _begin_agent(statuses, agent_times, "review")
    _update_monitor()
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
    _end_agent(agent_times, "review")
    _update_monitor()

    st.session_state["pipeline_running"] = False
    st.session_state["pipeline_completed"] = True
    st.session_state["pipeline_statuses"] = statuses
    st.session_state["pipeline_errors"] = errors
    st.session_state["pipeline_agent_times"] = agent_times
    st.session_state["pipeline_end_time"] = datetime.now()
    st.rerun()


def _render_pipeline_results():
    statuses = st.session_state.get("pipeline_statuses", {})
    errors = st.session_state.get("pipeline_errors", {})
    agent_times = st.session_state.get("pipeline_agent_times", {})

    completed_count = sum(1 for s in statuses.values() if s == "completed")
    failed_count = sum(1 for s in statuses.values() if s == "failed")
    skipped_count = sum(1 for s in statuses.values() if s == "skipped")

    start_t = st.session_state.get("pipeline_start_time")
    end_t = st.session_state.get("pipeline_end_time")
    total_dur = ""
    if start_t and end_t:
        secs = (end_t - start_t).total_seconds()
        total_dur = f"{secs:.1f}s" if secs < 60 else f"{secs / 60:.1f} min"

    all_success = failed_count == 0

    if all_success:
        st.markdown(
            f'<div class="pipeline-summary success">'
            f'<div class="pipeline-summary-icon">✅</div>'
            f'<div>'
            f'<div class="pipeline-summary-title">ESG Pipeline Completed Successfully</div>'
            f'<div class="pipeline-summary-detail">'
            f'{completed_count} agents completed, {skipped_count} skipped.'
            f'{" Total duration: " + total_dur + "." if total_dur else ""}'
            f' Click &ldquo;View Report&rdquo; to generate and download the final report.</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="pipeline-summary warning">'
            f'<div class="pipeline-summary-icon">⚠️</div>'
            f'<div>'
            f'<div class="pipeline-summary-title">Pipeline Completed with Issues</div>'
            f'<div class="pipeline-summary-detail">'
            f'{completed_count} completed, {failed_count} failed, {skipped_count} skipped.'
            f'{" Total duration: " + total_dur + "." if total_dur else ""}'
            f' Review the results below and re-run individual agents if needed.</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    import streamlit.components.v1 as _stc
    _pipeline_height = 470
    _stc.html(
        _build_pipeline_monitor_html(statuses, errors, agent_times, is_running=False),
        height=_pipeline_height, scrolling=False,
    )

    if all_success:
        st.markdown('<div class="pipeline-done-actions">', unsafe_allow_html=True)
        btn_left, btn_right = st.columns(2)
        with btn_left:
            st.button(
                "\U0001f4c4  View Report",
                key="home_goto_review",
                type="primary",
                use_container_width=True,
                on_click=lambda: st.session_state.update({"page": "review_governance"}),
            )
        with btn_right:
            if st.button("Reset Pipeline", key="home_reset_pipeline", use_container_width=True):
                _reset_pipeline()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        if st.button("Reset Pipeline", key="home_reset_pipeline"):
            _reset_pipeline()
            st.rerun()

    st.markdown("---")


# ════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════

def _set_status(statuses, key, status):
    statuses[key] = status
    st.session_state["pipeline_statuses"] = statuses


def _begin_agent(statuses, agent_times, key):
    statuses[key] = "running"
    st.session_state["pipeline_statuses"] = statuses
    agent_times[key] = {"start": datetime.now(), "end": None, "duration_s": None}


def _end_agent(agent_times, key):
    t = agent_times.get(key, {})
    if t.get("start"):
        t["end"] = datetime.now()
        t["duration_s"] = (t["end"] - t["start"]).total_seconds()
    st.session_state["pipeline_agent_times"] = agent_times


def _reset_pipeline():
    for k in ("pipeline_running", "pipeline_completed", "pipeline_statuses",
              "pipeline_errors", "pipeline_agent_times", "pipeline_start_time",
              "pipeline_end_time"):
        st.session_state.pop(k, None)


def _get_recent_analysis_time():
    end_t = st.session_state.get("pipeline_end_time")
    if end_t:
        return _relative_time_str(end_t)

    try:
        logs = get_audit_logs(_caller_is_system=True)
        if logs:
            for log in reversed(logs):
                action = log.get("action", "").lower()
                if "login" not in action:
                    ts = log.get("timestamp", "")
                    return _relative_time_str(ts)
    except Exception:
        pass

    return "Not yet"


def _relative_time_str(ts):
    if not ts:
        return ""
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                ts = datetime.strptime(ts, fmt)
                break
            except ValueError:
                continue
        else:
            return ts
    if not isinstance(ts, datetime):
        return str(ts)

    diff = datetime.now() - ts
    secs = diff.total_seconds()
    if secs < 0:
        return "Just now"
    if secs < 60:
        return "Just now"
    if secs < 3600:
        m = int(secs // 60)
        return f"{m} min ago"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = int(secs // 86400)
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return ts.strftime("%b %d")


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


def _action_row_class(action):
    a = action.lower()
    if "login" in a:
        return "login"
    if "connected" in a or "connect" in a or "loaded" in a or "load" in a:
        return "data"
    if "registered" in a or "register" in a:
        return "register"
    if "pipeline" in a or "collection" in a:
        return "pipeline"
    return ""
