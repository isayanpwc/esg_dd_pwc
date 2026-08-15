"""
ESG Risk & Opportunity Agent -- Streamlit view.

Displays synthesised risk/opportunity findings with:
  Tab 1  Executive Dashboard  -- KPIs, risk matrix, exposure breakdown
  Tab 2  Risk Register        -- detailed table with severity coding
  Tab 3  Opportunities        -- cards with value and payback
  Tab 4  Deal Recommendations -- grouped by category with diligence checklist
  Tab 5  Evidence Trail       -- links to source data
"""

import html as _html
import io
import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.risk_opportunity_agent import (
    get_available_deals,
    run_risk_opportunity_analysis,
    get_risk_matrix_data,
    PRIORITY_COLORS,
    RECOMMENDATION_CATEGORIES,
)


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
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px; {accent_css}'
        f'background:white;">'
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
        "strong": ("#ECFDF5", "#059669"), "moderate": ("#FFFBEB", "#D97706"),
        "weak": ("#FEF2F2", "#DC2626"),
    }
    bg, fg = colors.get(variant, colors["info"])
    return (
        f'<span style="display:inline-block; background:{bg}; color:{fg}; '
        f'font-size:0.72rem; font-weight:600; padding:3px 10px; border-radius:6px;">'
        f'{text}</span>'
    )


def _priority_dot(priority):
    emojis = {"Critical": "\U0001f534", "High": "\U0001f7e0",
              "Medium": "\U0001f7e1", "Low": "\U0001f7e2"}
    return f'{emojis.get(priority, "⚪")} {priority}'


def _priority_variant(priority):
    return {"Critical": "critical", "High": "error",
            "Medium": "warning", "Low": "success"}.get(priority, "info")


def _pillar_variant(pillar):
    return {"Environmental": "success", "Social": "info",
            "Governance": "warning"}.get(pillar, "neutral")


def _format_currency(value, currency="USD"):
    if value is None or value == 0:
        return "N/A"
    if abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.1f}B {currency}"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M {currency}"
    if abs(value) >= 1_000:
        return f"${value / 1_000:,.1f}K {currency}"
    return f"${value:,.0f} {currency}"


def _format_original_currency(value, currency):
    if value is None or value == 0:
        return "N/A"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:,.1f}B {currency}"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:,.1f}M {currency}"
    if abs(value) >= 1_000:
        return f"{value / 1_000:,.1f}K {currency}"
    return f"{value:,.0f} {currency}"


def _get_severity_label(risk):
    score = risk.get("calculated_risk_score", 0)
    if score >= 20:
        return "Critical"
    if score >= 15:
        return "High"
    if score >= 10:
        return "Major"
    if score >= 5:
        return "Medium"
    return "Low"


_FRAMEWORK_KEYWORDS = {
    "CSRD": "CSRD", "ESRS": "ESRS", "BRSR": "BRSR", "GRI": "GRI",
    "SASB": "SASB", "GDPR": "GDPR", "SEBI": "SEBI", "ISO": "ISO",
    "TCFD": "TCFD", "CDP": "CDP", "UNGC": "UNGC", "SDG": "SDG",
}


def _detect_frameworks(risk):
    text = " ".join([
        risk.get("title", ""), risk.get("description", ""),
        risk.get("category", ""),
    ]).upper()
    found = [label for kw, label in _FRAMEWORK_KEYWORDS.items() if kw in text]
    return found if found else [risk.get("category", "N/A")]


def _build_cell_tooltip(cell_findings, impact_label, likelihood_label):
    pillar_short = {"Environmental": "E", "Social": "S", "Governance": "G"}
    lines = [
        f"Impact: {impact_label}  |  Likelihood: {likelihood_label}",
        f"Count: {len(cell_findings)}",
    ]
    for r in cell_findings[:3]:
        rid = r.get("finding_id", "")
        pillar = r.get("esg_pillar", "")
        tag = pillar_short.get(pillar, "?")
        lines.append(f"  {rid} — {tag} — {r.get('title', '')[:40]}")
    if len(cell_findings) > 3:
        lines.append(f"  … +{len(cell_findings) - 3} more")
    lines.append("Click to view details")
    return "\n".join(lines)


_CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF "}


def _format_exposure(value, currency):
    if value is None or value == 0:
        return "Not Available"
    sym = _CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{sym}{value:,.0f}"


def _remediation_steps(recommendation):
    if not recommendation:
        return ["Review risk and define remediation steps"]
    parts = [s.strip() for s in recommendation.replace(";", "\n").split("\n") if s.strip()]
    if len(parts) == 1 and len(parts[0]) > 60:
        parts = [s.strip() for s in parts[0].split(",") if s.strip()]
    if len(parts) <= 1:
        parts = [recommendation.strip()]
    return parts[:5]


def _render_risk_drilldown(cell_risks, impact_label, likelihood_label,
                           company_name, deal_name):
    pillar_colors = {
        "Environmental": ("#ECFDF5", "#059669"),
        "Social": ("#EFF6FF", "#2563EB"),
        "Governance": ("#FFFBEB", "#D97706"),
    }
    pillar_short = {"Environmental": "E", "Social": "S", "Governance": "G"}
    severity_colors = {
        "Critical": ("#FEF2F2", "#DC2626"),
        "High": ("#FFF7ED", "#EA580C"),
        "Major": ("#FFFBEB", "#D97706"),
        "Medium": ("#FFFBEB", "#CA8A04"),
        "Low": ("#F0FDF4", "#16A34A"),
    }
    status_colors = {
        "Open": ("#F3F4F6", "#374151"),
        "In Progress": ("#EFF6FF", "#2563EB"),
        "Mitigated": ("#ECFDF5", "#059669"),
    }

    st.session_state.setdefault("rm_drilldown_idx", 0)
    idx = st.session_state.get("rm_drilldown_idx", 0)
    if idx >= len(cell_risks):
        idx = 0
        st.session_state["rm_drilldown_idx"] = 0

    if len(cell_risks) > 1:
        nav_cols = st.columns([1, 6, 1])
        with nav_cols[0]:
            if st.button("◀", key="rm_dd_prev", use_container_width=True):
                st.session_state["rm_drilldown_idx"] = (idx - 1) % len(cell_risks)
                st.rerun()
        with nav_cols[1]:
            st.markdown(
                f'<div style="text-align:center; font-size:0.82rem; font-weight:600; '
                f'color:#6B7280; padding:8px 0;">'
                f'Risk {idx + 1} of {len(cell_risks)}</div>',
                unsafe_allow_html=True,
            )
        with nav_cols[2]:
            if st.button("▶", key="rm_dd_next", use_container_width=True):
                st.session_state["rm_drilldown_idx"] = (idx + 1) % len(cell_risks)
                st.rerun()

    risk = cell_risks[idx]
    pillar = risk.get("esg_pillar", "N/A")
    p_bg, p_fg = pillar_colors.get(pillar, ("#F3F4F6", "#6B7280"))
    p_tag = pillar_short.get(pillar, "?")
    severity = _get_severity_label(risk)
    s_bg, s_fg = severity_colors.get(severity, ("#F3F4F6", "#6B7280"))
    status = risk.get("status", "Open")
    st_bg, st_fg = status_colors.get(status, ("#F3F4F6", "#374151"))
    fi = risk.get("financial_impact", 0)
    fi_cur = risk.get("financial_impact_currency", "USD")
    exposure_text = _format_exposure(fi, fi_cur)
    likelihood = risk.get("likelihood_score", 0)
    impact = risk.get("impact_score", 0)
    score = risk.get("calculated_risk_score", 0)
    frameworks = ", ".join(_detect_frameworks(risk))
    description = risk.get("description", "Not Available")
    category = risk.get("category", "N/A")
    finding_id = risk.get("finding_id", "N/A")
    score_color = s_fg

    badge_html = (
        f'<span style="display:inline-block; background:{p_bg}; color:{p_fg}; '
        f'font-size:0.72rem; font-weight:700; padding:4px 12px; border-radius:20px; '
        f'margin-right:6px;">✔ {pillar.upper()} ({p_tag})</span>'
        f'<span style="display:inline-block; background:{s_bg}; color:{s_fg}; '
        f'font-size:0.72rem; font-weight:700; padding:4px 12px; border-radius:20px; '
        f'margin-right:6px;">⚠ {severity.upper()}</span>'
        f'<span style="display:inline-block; background:{st_bg}; color:{st_fg}; '
        f'font-size:0.72rem; font-weight:700; padding:4px 12px; border-radius:20px;">'
        f'{status.upper()}</span>'
    )

    exposure_block = (
        f'<div style="background:#EFF6FF; border-radius:10px; padding:16px 20px; '
        f'margin:16px 0;">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#2563EB; '
        f'text-transform:uppercase; letter-spacing:0.08em; margin-bottom:2px;">'
        f'Financial Exposure</div>'
        f'<div style="font-size:1.6rem; font-weight:800; color:#111827;">'
        f'{exposure_text}</div></div>'
    )

    grid_html = (
        f'<div style="display:grid; grid-template-columns:1fr 1fr; gap:1px; '
        f'border:1px solid #E5E7EB; border-radius:10px; overflow:hidden; margin:14px 0;">'
        f'<div style="padding:14px 16px; background:#FAFAFA;">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
        f'text-transform:uppercase; letter-spacing:0.06em;">Likelihood</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:#111827;">{likelihood}</div></div>'
        f'<div style="padding:14px 16px; background:#FAFAFA;">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
        f'text-transform:uppercase; letter-spacing:0.06em;">Impact</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:#111827;">{impact}</div></div>'
        f'<div style="padding:14px 16px; background:#FAFAFA;">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
        f'text-transform:uppercase; letter-spacing:0.06em;">Score (LxI)</div>'
        f'<div style="font-size:1.15rem; font-weight:800; color:{score_color};">{score}</div></div>'
        f'<div style="padding:14px 16px; background:#FAFAFA;">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
        f'text-transform:uppercase; letter-spacing:0.06em;">Framework</div>'
        f'<div style="font-size:1.0rem; font-weight:700; color:#111827;">{frameworks}</div></div>'
        f'<div style="padding:14px 16px; background:#FAFAFA; grid-column:1/-1;">'
        f'<div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
        f'text-transform:uppercase; letter-spacing:0.06em;">Entity</div>'
        f'<div style="font-size:1.0rem; font-weight:700; color:#111827;">'
        f'{company_name or "Not Available"}</div></div>'
        f'</div>'
    )

    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:16px; '
        f'background:white; padding:24px; margin-top:16px; '
        f'box-shadow:0 4px 24px rgba(0,0,0,0.08);">'
        f'<div style="margin-bottom:14px;">{badge_html}</div>'
        f'{exposure_block}'
        f'<div style="margin-bottom:6px;">'
        f'<div style="font-size:0.92rem; font-weight:700; color:#111827;">Description</div>'
        f'<div style="font-size:0.84rem; color:#374151; line-height:1.6; margin-top:4px;">'
        f'{description}</div></div>'
        f'{grid_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

    steps = _remediation_steps(risk.get("recommendation", ""))
    st.markdown(
        '<div style="margin-top:18px;">'
        '<div style="font-size:0.92rem; font-weight:700; color:#111827; '
        'margin-bottom:10px;">✔ Remediation Plan</div></div>',
        unsafe_allow_html=True,
    )
    for si, step in enumerate(steps):
        st.checkbox(step, key=f"rm_dd_step_{idx}_{si}", value=False)

    st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
    st.button(
        "Assign Owner",
        key="rm_dd_assign",
        type="primary",
        use_container_width=True,
    )


# ════════════════════════════════════════════════════════════
#  Render entry point
# ════════════════════════════════════════════════════════════

def render():
    st.markdown(
        '<div style="margin-bottom:6px;">'
        '<h2 style="margin:0 0 4px 0; font-size:1.55rem; font-weight:800; color:#111827;">'
        '⚡ Risk &amp; Opportunity Agent</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:0; line-height:1.5;">'
        'Synthesise ESG risk signals and value-creation opportunities across '
        'controversy, compliance, benchmarking, and supplier data.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander("How does the Risk & Opportunity Agent work?"):
        st.markdown("""
**7-step analysis pipeline:**
1. **Collect risk signals** from controversies, legal penalties, certifications, supplier assessments, and ESG targets
2. **Consolidate overlapping signals** into unified findings with multiple evidence sources
3. **Calculate likelihood x impact scores** using a transparent 1-5 scale
4. **Assess evidence quality** and flag items requiring human review
5. **Quantify financial impact** where a defensible basis exists
6. **Identify value-creation opportunities** from ESG improvements
7. **Generate deal recommendations** categorised by type (diligence, protection, remediation, value creation)
        """)

    _render_deal_selector()

    if st.session_state.get("ro_results"):
        tabs = st.tabs([
            "\U0001f4ca Executive Dashboard",
            "\U0001f6e1️ Risk Register",
            "\U0001f4a1 Opportunities",
            "\U0001f4cb Deal Recommendations",
            "\U0001f50d Evidence Trail",
        ])
        with tabs[0]:
            _render_executive_dashboard()
        with tabs[1]:
            _render_risk_register()
        with tabs[2]:
            _render_opportunities()
        with tabs[3]:
            _render_recommendations()
        with tabs[4]:
            _render_evidence_trail()


# ════════════════════════════════════════════════════════════
#  Deal selector
# ════════════════════════════════════════════════════════════

def _render_deal_selector():
    deals = get_available_deals()

    if not deals:
        st.markdown(
            '<div style="border:1px dashed #D1D5DB; border-radius:14px; background:#FAFAFA; '
            'text-align:center; padding:48px 24px;">'
            '<div style="font-size:2.2rem; margin-bottom:8px;">\U0001f4c2</div>'
            '<div style="font-size:1.05rem; font-weight:700; color:#111827; margin-bottom:6px;">'
            'No deals available</div>'
            '<p style="color:#6B7280; font-size:0.85rem; max-width:400px; margin:0 auto;">'
            'Upload deal data via the Data Sources page to get started.</p></div>',
            unsafe_allow_html=True,
        )
        return

    deal_options = {
        f"{d['deal_name']} ({d['deal_id']})": d for d in deals
    }

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_label = st.selectbox(
            "Select deal for analysis",
            options=list(deal_options.keys()),
            key="ro_deal_select",
        )
    with col2:
        st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
        run_clicked = st.button(
            "⚡ Run Analysis",
            key="ro_run_btn",
            type="primary",
            use_container_width=True,
        )

    if run_clicked and selected_label:
        deal = deal_options[selected_label]
        with st.spinner("Running risk & opportunity analysis…"):
            result = run_risk_opportunity_analysis(
                deal["deal_id"], deal["company_id"])
            st.session_state["ro_results"] = result

    if not st.session_state.get("ro_results"):
        st.markdown(
            '<div style="border:1px dashed #D1D5DB; border-radius:14px; background:#FAFAFA; '
            'text-align:center; padding:48px 24px; margin-top:16px;">'
            '<div style="font-size:2.2rem; margin-bottom:8px;">\U0001f50d</div>'
            '<div style="font-size:1.05rem; font-weight:700; color:#111827; margin-bottom:6px;">'
            'Select a deal and run analysis</div>'
            '<p style="color:#6B7280; font-size:0.85rem; max-width:420px; margin:0 auto;">'
            'Choose a deal from the dropdown above and click '
            '<b style="color:#FF5A00;">Run Analysis</b> to generate the risk and '
            'opportunity assessment.</p></div>',
            unsafe_allow_html=True,
        )


# ════════════════════════════════════════════════════════════
#  Tab 1 — Executive Dashboard
# ════════════════════════════════════════════════════════════

def _render_executive_dashboard():
    res = st.session_state["ro_results"]
    summary = res["summary"]
    findings = res["findings"]

    _section("Executive Summary",
             f"{res['deal_name']} — {res['company_name']}")

    # --- KPI cards ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Total Risks", summary["total_risks"],
                     color="#DC2626", accent="#DC2626")
    with c2:
        _metric_card("Critical", summary["critical_count"],
                     color="#991B1B", accent="#991B1B")
    with c3:
        _metric_card("Opportunities", summary["total_opportunities"],
                     color="#059669", accent="#059669")
    with c4:
        _metric_card("Total Exposure",
                     _format_currency(summary["total_financial_exposure"]),
                     color="#111827", accent="#FF5A00")

    st.markdown("---")

    # --- Risk matrix (Plotly heatmap) ---
    _section("Risk Matrix", "Likelihood vs Impact (risk findings only)")

    rich_matrix = [[[] for _ in range(5)] for _ in range(5)]
    for f in findings:
        if f.get("finding_type") != "Risk":
            continue
        li = max(0, min(4, int(f.get("likelihood_score", 1)) - 1))
        im = max(0, min(4, int(f.get("impact_score", 1)) - 1))
        rich_matrix[li][im].append(f)

    impact_labels = ["Negligible", "Minor", "Moderate", "Major", "Severe"]
    likelihood_labels = ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"]

    st.session_state.setdefault("rm_selected", None)

    pillar_short = {"Environmental": "E", "Social": "S", "Governance": "G"}
    severity_badge = {
        "Critical": ("#DC2626", "#FEF2F2"),
        "High": ("#EA580C", "#FFF7ED"),
        "Major": ("#D97706", "#FFFBEB"),
        "Medium": ("#CA8A04", "#FFFBEB"),
        "Low": ("#16A34A", "#F0FDF4"),
    }
    nan = float("nan")

    z_matrix = []
    tooltip_data = {}
    annotations = []

    for li in range(5):
        row_z = []
        for im in range(5):
            cell = rich_matrix[li][im]
            cnt = len(cell)
            if cnt == 0:
                row_z.append(nan)
            else:
                row_z.append(cnt)
                risks_for_tt = []
                for r in cell:
                    rid = r.get("finding_id", "N/A")
                    title = r.get("title", "N/A")
                    pillar = r.get("esg_pillar", "")
                    tag = pillar_short.get(pillar, "?")
                    sev = _get_severity_label(r)
                    exp = _format_exposure(
                        r.get("financial_impact"),
                        r.get("financial_impact_currency", ""),
                    )
                    fw = ", ".join(_detect_frameworks(r)[:3])
                    rec = r.get("recommendation", "") or "N/A"
                    _e = _html.escape
                    risks_for_tt.append({
                        "id": _e(rid), "title": _e(title),
                        "pillar": _e(pillar), "tag": _e(tag),
                        "severity": _e(sev), "exposure": _e(exp),
                        "framework": _e(fw), "remediation": _e(rec),
                    })
                tooltip_data[
                    f"{impact_labels[im]}|{likelihood_labels[li]}"
                ] = {"count": cnt, "risks": risks_for_tt}
                annotations.append(dict(
                    x=impact_labels[im],
                    y=likelihood_labels[li],
                    text=f"<b>{cnt}</b>",
                    showarrow=False,
                    font=dict(size=22, color="#1a1a1a"),
                ))
        z_matrix.append(row_z)

    fig = go.Figure(data=go.Heatmap(
        z=z_matrix,
        x=impact_labels,
        y=likelihood_labels,
        hoverinfo="none",
        colorscale=[
            [0.0, "#FDEBD0"],
            [0.5, "#F5CBA7"],
            [1.0, "#F1948A"],
        ],
        zmin=1,
        zmax=5,
        showscale=False,
        xgap=3,
        ygap=3,
        connectgaps=False,
    ))

    fig.update_layout(
        annotations=annotations,
        xaxis=dict(
            title=dict(text="Impact", font=dict(size=14, color="#374151")),
            tickfont=dict(size=12, color="#6B7280"),
            side="bottom",
            dtick=1,
            showgrid=False,
        ),
        yaxis=dict(
            title=dict(text="Likelihood", font=dict(size=14, color="#374151")),
            tickfont=dict(size=12, color="#6B7280"),
            dtick=1,
            categoryorder="array",
            categoryarray=likelihood_labels,
            showgrid=False,
        ),
        plot_bgcolor="#E8F5E9",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=10, b=20),
        height=450,
    )

    event = st.plotly_chart(
        fig, use_container_width=True,
        on_select="rerun",
        selection_mode="points",
        key="rm_heatmap",
    )

    # --- Custom scrollable tooltip (replaces Plotly's native SVG hover) ---
    _tt_json = json.dumps(tooltip_data).replace("</", r"<\/")
    _tooltip_html = (
        "<html><head><script>"
        "(function(){"
        "var TD=" + _tt_json + ";"
        "var top_doc=window.parent.document;"
        "var tt=top_doc.getElementById('rm-custom-tooltip');"
        "if(!tt){"
        "  tt=top_doc.createElement('div');"
        "  tt.id='rm-custom-tooltip';"
        "  top_doc.body.appendChild(tt);"
        "  var st=top_doc.createElement('style');"
        "  st.textContent='"
        "#rm-custom-tooltip{"
        "  position:fixed;z-index:999999;background:#fff;"
        "  border:1px solid #CBD5E1;border-radius:6px;"
        "  padding:10px 14px;font-family:Arial,sans-serif;"
        "  font-size:13px;color:#1E293B;text-align:left;"
        "  max-height:60vh;max-width:420px;min-width:300px;"
        "  overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,.15);"
        "  pointer-events:auto;display:none;line-height:1.5;"
        "  word-wrap:break-word;overflow-wrap:break-word;"
        "}"
        "#rm-custom-tooltip::-webkit-scrollbar{width:6px}"
        "#rm-custom-tooltip::-webkit-scrollbar-track{"
        "  background:#F1F5F9;border-radius:3px}"
        "#rm-custom-tooltip::-webkit-scrollbar-thumb{"
        "  background:#94A3B8;border-radius:3px}"
        "#rm-custom-tooltip .rm-tt-sep{"
        "  border:0;border-top:1px solid #E2E8F0;margin:6px 0}"
        "';"
        "  top_doc.head.appendChild(st);"
        "}"
        "var ht;"
        "function bld(d,x,y){"
        "  var h=\"<b>\"+x+\"</b> \\u00d7 <b>\"+y+\"</b>  \\u00b7  \"+"
        "    d.count+\" risk\"+(d.count>1?\"s\":\"\")+\"<br>\"+"
        "    '<hr class=\\\"rm-tt-sep\\\">';"
        "  d.risks.forEach(function(r,i){"
        "    if(i>0)h+='<hr class=\\\"rm-tt-sep\\\">';"
        "    h+=\"<b>\"+r.id+\"</b><br>\";"
        "    h+=\"  \\u2022 Risk: \"+r.title+\"<br>\";"
        "    h+=\"  \\u2022 Pillar: \"+r.pillar+\" (\"+r.tag+\")<br>\";"
        "    h+=\"  \\u2022 Severity: \"+r.severity+\"<br>\";"
        "    h+=\"  \\u2022 Exposure: \"+r.exposure+\"<br>\";"
        "    h+=\"  \\u2022 Framework: \"+r.framework+\"<br>\";"
        "    h+=\"  \\u2022 Remediation: \"+r.remediation+\"<br>\";"
        "  });"
        "  h+='<br><i style=\\\"color:#64748B\\\">Click to view full details</i>';"
        "  return h;"
        "}"
        "function showTT(html,mx,my){"
        "  tt.innerHTML=html;tt.style.display='block';"
        "  var tw=tt.offsetWidth,th=tt.offsetHeight;"
        "  var vw=top_doc.documentElement.clientWidth;"
        "  var vh=top_doc.documentElement.clientHeight;"
        "  var l=mx+15,t=my+15;"
        "  if(l+tw>vw-10)l=mx-tw-15;"
        "  if(l<5)l=5;"
        "  if(t+th>vh-10)t=vh-th-10;"
        "  if(t<5)t=5;"
        "  tt.style.left=l+'px';tt.style.top=t+'px';"
        "}"
        "function hideTT(){tt.style.display='none';}"
        "tt.addEventListener('mouseenter',function(){clearTimeout(ht);});"
        "tt.addEventListener('mouseleave',function(){"
        "  ht=setTimeout(hideTT,200);});"
        "var tries=0;"
        "function attach(){"
        "  if(tries++>60)return;"
        "  var pd=null,chart_ifr=null;"
        "  var all_docs=[top_doc];"
        "  var ifs=top_doc.querySelectorAll('iframe');"
        "  for(var i=0;i<ifs.length;i++){"
        "    try{all_docs.push(ifs[i].contentDocument||"
        "      ifs[i].contentWindow.document);}catch(e){}"
        "  }"
        "  for(var di=0;di<all_docs.length;di++){"
        "    var d=all_docs[di];"
        "    var ifs2=d.querySelectorAll('iframe');"
        "    for(var j=0;j<ifs2.length;j++){"
        "      try{"
        "        var cd=ifs2[j].contentDocument||ifs2[j].contentWindow.document;"
        "        pd=cd.querySelector('.js-plotly-plot');"
        "        if(pd&&pd._fullLayout){chart_ifr=ifs2[j];break;}"
        "        else pd=null;"
        "      }catch(e){pd=null;}"
        "    }"
        "    if(pd)break;"
        "    pd=d.querySelector('.js-plotly-plot');"
        "    if(pd&&pd._fullLayout){if(d!==top_doc){"
        "      for(var fi=0;fi<ifs.length;fi++){"
        "        try{if((ifs[fi].contentDocument||"
        "          ifs[fi].contentWindow.document)===d)"
        "          {chart_ifr=ifs[fi];break;}}catch(e){}"
        "      }"
        "    }break;}"
        "    pd=null;"
        "  }"
        "  if(!pd||!pd._fullLayout){setTimeout(attach,250);return;}"
        "  var sdoc=chart_ifr?(chart_ifr.contentDocument||"
        "    chart_ifr.contentWindow.document):top_doc;"
        "  var sty=sdoc.createElement('style');"
        "  sty.textContent='.hoverlayer .hovertext{display:none!important}';"
        "  sdoc.head.appendChild(sty);"
        "  pd.on('plotly_hover',function(ev){"
        "    clearTimeout(ht);"
        "    var pt=ev.points[0];"
        "    var key=pt.x+'|'+pt.y,cd=TD[key];"
        "    if(cd){"
        "      var mx=ev.event.clientX,my=ev.event.clientY;"
        "      if(chart_ifr){"
        "        var r=chart_ifr.getBoundingClientRect();"
        "        mx+=r.left;my+=r.top;"
        "      }"
        "      showTT(bld(cd,pt.x,pt.y),mx,my);"
        "    }"
        "  });"
        "  pd.on('plotly_unhover',function(){"
        "    ht=setTimeout(hideTT,300);"
        "  });"
        "}"
        "attach();"
        "})();"
        "</script></head><body></body></html>"
    )
    import streamlit.components.v1 as _stc
    _stc.html(_tooltip_html, height=0, scrolling=False)

    if event and hasattr(event, "selection") and event.selection.points:
        pt = event.selection.points[0]
        clicked_x = pt.get("x") if isinstance(pt, dict) else getattr(pt, "x", None)
        clicked_y = pt.get("y") if isinstance(pt, dict) else getattr(pt, "y", None)
        if clicked_x in impact_labels and clicked_y in likelihood_labels:
            im_idx = impact_labels.index(clicked_x)
            li_idx = likelihood_labels.index(clicked_y)
            if rich_matrix[li_idx][im_idx]:
                st.session_state["rm_selected"] = (li_idx, im_idx)
                st.session_state["rm_drilldown_idx"] = 0

    sel = st.session_state.get("rm_selected")
    if sel is not None:
        li_sel, im_sel = sel
        cell_risks = rich_matrix[li_sel][im_sel]
        if cell_risks:
            cards_html = []
            for r in cell_risks:
                rid = r.get("finding_id", "N/A")
                title = r.get("title", "N/A")
                pillar = r.get("esg_pillar", "")
                tag = pillar_short.get(pillar, "?")
                severity = _get_severity_label(r)
                sev_color, sev_bg = severity_badge.get(severity, ("#6B7280", "#F9FAFB"))
                exposure = _format_exposure(
                    r.get("financial_impact"),
                    r.get("financial_impact_currency", ""),
                )
                fw_str = ", ".join(_detect_frameworks(r)[:4])
                rec = r.get("recommendation", "") or "Review risk and define remediation steps"
                cards_html.append(f"""
                <div style="background:#FFFFFF; border:1px solid #E5E7EB; border-radius:10px;
                            padding:16px 20px; margin-bottom:10px;">
                  <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
                    <span style="font-weight:700; font-size:0.95rem; color:#1E293B;">{rid}</span>
                    <span style="background:{sev_bg}; color:{sev_color}; font-size:0.75rem;
                                 font-weight:700; padding:2px 10px; border-radius:20px;
                                 border:1px solid {sev_color}20;">{severity}</span>
                    <span style="background:#F0F9FF; color:#0369A1; font-size:0.75rem;
                                 font-weight:600; padding:2px 10px; border-radius:20px;">
                      {tag} — {pillar}</span>
                  </div>
                  <div style="font-size:0.88rem; color:#334155; font-weight:600;
                              margin-bottom:10px;">{title}</div>
                  <table style="width:100%; font-size:0.82rem; color:#475569;
                                border-collapse:collapse;">
                    <tr>
                      <td style="padding:4px 0; width:40%;"><b>Impact:</b> {impact_labels[im_sel]}</td>
                      <td style="padding:4px 0;"><b>Likelihood:</b> {likelihood_labels[li_sel]}</td>
                    </tr>
                    <tr>
                      <td style="padding:4px 0;"><b>Exposure:</b> {exposure}</td>
                      <td style="padding:4px 0;"><b>Framework:</b> {fw_str}</td>
                    </tr>
                    <tr>
                      <td colspan="2" style="padding:6px 0 2px 0;">
                        <b>Remediation:</b> {rec}
                      </td>
                    </tr>
                  </table>
                </div>
                """)

            panel_html = f"""
            <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px;
                        padding:16px 18px; margin-top:8px; max-height:420px;
                        overflow-y:auto;">
              <div style="display:flex; align-items:center; justify-content:space-between;
                          margin-bottom:12px;">
                <span style="font-weight:700; font-size:0.95rem; color:#1E293B;">
                  {len(cell_risks)} Risk{'s' if len(cell_risks) > 1 else ''} —
                  {impact_labels[im_sel]} Impact × {likelihood_labels[li_sel]} Likelihood
                </span>
              </div>
              {"".join(cards_html)}
            </div>
            """
            st.markdown(panel_html, unsafe_allow_html=True)

            close_col1, close_col2 = st.columns([8, 1])
            with close_col2:
                if st.button("✕ Close", key="rm_dd_close"):
                    st.session_state["rm_selected"] = None
                    st.session_state["rm_drilldown_idx"] = 0
                    st.rerun()
            _render_risk_drilldown(
                cell_risks, impact_labels[im_sel], likelihood_labels[li_sel],
                res.get("company_name", ""), res.get("deal_name", ""),
            )
        else:
            st.session_state["rm_selected"] = None

    st.markdown("---")

    # --- Financial exposure by pillar + Priority distribution ---
    col_left, col_right = st.columns([3, 2])

    with col_left:
        _section("Financial Exposure by ESG Pillar")
        pillar_data = summary.get("by_pillar", {})
        if pillar_data:
            pillar_colors = {
                "Environmental": "#059669",
                "Social": "#2563EB",
                "Governance": "#D97706",
            }
            _p_short = {"Environmental": "E", "Social": "S",
                        "Governance": "G"}
            total_exp = summary.get("total_financial_exposure", 0) or 1
            _e = _html.escape

            _cat_impacts = {
                "Data privacy": "Regulatory penalties, Compliance violations",
                "Regulatory penalty": "Financial penalties, Regulatory sanctions",
                "Certifications": "Market access restrictions, Contract risk",
                "Supply chain": "Supply disruption, Third-party liability",
                "Human rights": "Legal liability, Investor divestment risk",
                "Scope 3 disclosure": "Regulatory non-compliance, Carbon pricing exposure",
                "Target progress": "Missed commitments, Greenwashing allegations",
            }

            ep_tooltip_data = {}
            for p_name in pillar_data:
                p_risks = [f for f in findings
                           if f.get("finding_type") == "Risk"
                           and f.get("esg_pillar") == p_name]
                all_fw = set()
                all_impacts = set()
                for r in p_risks:
                    for fw in _detect_frameworks(r)[:3]:
                        all_fw.add(fw)
                    cat = r.get("category", "")
                    if cat in _cat_impacts:
                        all_impacts.add(_cat_impacts[cat])
                pct = (pillar_data[p_name] / total_exp * 100
                       ) if total_exp else 0
                impacts_str = "; ".join(sorted(all_impacts)) \
                    if all_impacts else "Compliance violations, Reputation damage"
                fw_str = ", ".join(sorted(all_fw)) \
                    if all_fw else "BRSR, GRI"
                ep_tooltip_data[p_name] = {
                    "segment": _p_short.get(p_name, "?"),
                    "count": len(p_risks),
                    "exposure": _format_currency(pillar_data[p_name]),
                    "contribution": f"{pct:.1f}%",
                    "impact": _e(impacts_str),
                    "framework": _e(fw_str),
                }

            pillars = list(pillar_data.keys())
            values = [pillar_data[p] for p in pillars]
            colors = [pillar_colors.get(p, "#6B7280") for p in pillars]

            fig_bar = go.Figure(go.Bar(
                y=pillars,
                x=values,
                orientation="h",
                marker_color=colors,
                text=[_format_currency(v) for v in values],
                textposition="auto",
                textfont=dict(size=11, color="white"),
                hoverinfo="none",
            ))
            fig_bar.update_layout(
                height=220,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="white",
                xaxis=dict(showgrid=True, gridcolor="#F3F4F6",
                           tickformat="$,.0f"),
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_bar, use_container_width=True,
                            key="ep_bar_chart")

            _ep_tt_json = json.dumps(ep_tooltip_data).replace("</", r"<\/")
            _ep_tooltip_html = (
                "<html><head><script>"
                "(function(){"
                "var TD=" + _ep_tt_json + ";"
                "var top_doc=window.parent.document;"
                "var tt=top_doc.getElementById('ep-custom-tooltip');"
                "if(!tt){"
                "  tt=top_doc.createElement('div');"
                "  tt.id='ep-custom-tooltip';"
                "  top_doc.body.appendChild(tt);"
                "  var st=top_doc.createElement('style');"
                "  st.textContent='"
                "#ep-custom-tooltip{"
                "  position:fixed;z-index:999999;background:#fff;"
                "  border:1px solid #CBD5E1;border-radius:6px;"
                "  padding:10px 14px;font-family:Arial,sans-serif;"
                "  font-size:13px;color:#1E293B;text-align:left;"
                "  max-height:60vh;max-width:420px;min-width:300px;"
                "  overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,.15);"
                "  pointer-events:auto;display:none;line-height:1.5;"
                "  word-wrap:break-word;overflow-wrap:break-word;"
                "}"
                "#ep-custom-tooltip::-webkit-scrollbar{width:6px}"
                "#ep-custom-tooltip::-webkit-scrollbar-track{"
                "  background:#F1F5F9;border-radius:3px}"
                "#ep-custom-tooltip::-webkit-scrollbar-thumb{"
                "  background:#94A3B8;border-radius:3px}"
                "#ep-custom-tooltip .ep-tt-sep{"
                "  border:0;border-top:1px solid #E2E8F0;margin:6px 0}"
                "';"
                "  top_doc.head.appendChild(st);"
                "}"
                "var ht;"
                "function bld(pillar,d){"
                "  var h='<b>'+pillar+' ('+d.segment+')</b><br>'+"
                "    '<hr class=\\\"ep-tt-sep\\\">';"
                "  h+='\\u2022 <b>Total Exposure:</b> '+d.exposure+'<br>';"
                "  h+='\\u2022 <b>Contribution:</b> '+d.contribution+"
                "    ' of Total Exposure<br>';"
                "  h+='\\u2022 <b>Number of Risks:</b> '+d.count+'<br>';"
                "  h+='\\u2022 <b>Potential Business Impact:</b> '+"
                "    d.impact+'<br>';"
                "  h+='\\u2022 <b>Affected Frameworks:</b> '+"
                "    d.framework+'<br>';"
                "  return h;"
                "}"
                "function showTT(html,mx,my){"
                "  tt.innerHTML=html;tt.style.display='block';"
                "  var tw=tt.offsetWidth,th=tt.offsetHeight;"
                "  var vw=top_doc.documentElement.clientWidth;"
                "  var vh=top_doc.documentElement.clientHeight;"
                "  var l=mx+15,t=my+15;"
                "  if(l+tw>vw-10)l=mx-tw-15;"
                "  if(l<5)l=5;"
                "  if(t+th>vh-10)t=vh-th-10;"
                "  if(t<5)t=5;"
                "  tt.style.left=l+'px';tt.style.top=t+'px';"
                "}"
                "function hideTT(){tt.style.display='none';}"
                "tt.addEventListener('mouseenter',function(){"
                "  clearTimeout(ht);});"
                "tt.addEventListener('mouseleave',function(){"
                "  ht=setTimeout(hideTT,200);});"
                "var tries=0;"
                "function attach(){"
                "  if(tries++>60)return;"
                "  var pd=null,chart_ifr=null;"
                "  var all_docs=[top_doc];"
                "  var ifs=top_doc.querySelectorAll('iframe');"
                "  for(var i=0;i<ifs.length;i++){"
                "    try{all_docs.push(ifs[i].contentDocument||"
                "      ifs[i].contentWindow.document);}catch(e){}"
                "  }"
                "  for(var di=0;di<all_docs.length;di++){"
                "    var d=all_docs[di];"
                "    var plots=d.querySelectorAll('.js-plotly-plot');"
                "    for(var pi=0;pi<plots.length;pi++){"
                "      var p=plots[pi];"
                "      if(p&&p._fullLayout&&p._fullLayout.xaxis"
                "        &&p._fullLayout.xaxis.tickformat==='$,.0f'"
                "        &&!p.dataset.epBound){"
                "        pd=p;break;"
                "      }"
                "    }"
                "    if(pd)break;"
                "    var ifs2=d.querySelectorAll('iframe');"
                "    for(var j=0;j<ifs2.length;j++){"
                "      try{"
                "        var cd=ifs2[j].contentDocument||"
                "          ifs2[j].contentWindow.document;"
                "        var plots2=cd.querySelectorAll('.js-plotly-plot');"
                "        for(var pk=0;pk<plots2.length;pk++){"
                "          var p2=plots2[pk];"
                "          if(p2&&p2._fullLayout&&p2._fullLayout.xaxis"
                "            &&p2._fullLayout.xaxis.tickformat==='$,.0f'"
                "            &&!p2.dataset.epBound){"
                "            pd=p2;chart_ifr=ifs2[j];break;"
                "          }"
                "        }"
                "        if(pd)break;"
                "      }catch(e){}"
                "    }"
                "    if(pd)break;"
                "  }"
                "  if(!pd||!pd._fullLayout){"
                "    setTimeout(attach,250);return;}"
                "  pd.dataset.epBound='1';"
                "  pd.on('plotly_hover',function(ev){"
                "    clearTimeout(ht);"
                "    var pt=ev.points[0];"
                "    var key=pt.y,cd=TD[key];"
                "    if(cd){"
                "      var mx=ev.event.clientX,my=ev.event.clientY;"
                "      if(chart_ifr){"
                "        var r=chart_ifr.getBoundingClientRect();"
                "        mx+=r.left;my+=r.top;"
                "      }"
                "      showTT(bld(key,cd),mx,my);"
                "    }"
                "  });"
                "  pd.on('plotly_unhover',function(){"
                "    ht=setTimeout(hideTT,300);"
                "  });"
                "}"
                "attach();"
                "})();"
                "</script></head><body></body></html>"
            )
            import streamlit.components.v1 as _stc_ep
            _stc_ep.html(_ep_tooltip_html, height=0, scrolling=False)
        else:
            st.info("No financial exposure data to display.")

    with col_right:
        _section("Priority Distribution")
        pc = summary.get("priority_counts", {})
        labels = []
        vals = []
        colors_list = []
        priority_color_map = {
            "Critical": "#991B1B", "High": "#DC2626",
            "Medium": "#D97706", "Low": "#059669",
        }
        for p in ["Critical", "High", "Medium", "Low"]:
            count = pc.get(p, 0)
            if count > 0:
                labels.append(p)
                vals.append(count)
                colors_list.append(priority_color_map.get(p, "#6B7280"))

        if vals:
            total_risks = summary.get("total_risks", 1) or 1
            _p_short_pd = {"Environmental": "E", "Social": "S",
                           "Governance": "G"}
            pd_tooltip_data = {}
            for pri in labels:
                pri_risks = [f for f in findings
                             if f.get("finding_type") == "Risk"
                             and f.get("priority") == pri]
                pri_exp = sum(
                    f.get("financial_usd", 0) or 0 for f in pri_risks)
                pillars_set = set()
                fw_set = set()
                for r in pri_risks:
                    pil = r.get("esg_pillar", "")
                    if pil:
                        pillars_set.add(
                            f"{pil} ({_p_short_pd.get(pil, '?')})")
                    for fw in _detect_frameworks(r)[:3]:
                        fw_set.add(fw)
                pct_share = len(pri_risks) / total_risks * 100
                pd_tooltip_data[pri] = {
                    "count": len(pri_risks),
                    "share": f"{pct_share:.1f}%",
                    "exposure": _format_currency(pri_exp),
                    "pillars": _html.escape(
                        ", ".join(sorted(pillars_set))
                        if pillars_set else "N/A"),
                    "framework": _html.escape(
                        ", ".join(sorted(fw_set))
                        if fw_set else "BRSR, GRI"),
                }

            fig_donut = go.Figure(go.Pie(
                labels=labels,
                values=vals,
                hole=0.55,
                marker=dict(colors=colors_list),
                textinfo="label+value",
                textfont=dict(size=11),
                hoverinfo="none",
            ))
            fig_donut.update_layout(
                height=220,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                annotations=[dict(
                    text=f"<b>{summary['total_risks']}</b>",
                    x=0.5, y=0.5, font_size=22, showarrow=False,
                    font_color="#111827",
                )],
            )
            st.plotly_chart(fig_donut, use_container_width=True,
                            key="pd_donut_chart")

            _pd_tt_json = json.dumps(pd_tooltip_data).replace(
                "</", r"<\/")
            _pd_tooltip_html = (
                "<html><head><script>"
                "(function(){"
                "var TD=" + _pd_tt_json + ";"
                "var top_doc=window.parent.document;"
                "var tt=top_doc.getElementById('pd-custom-tooltip');"
                "if(!tt){"
                "  tt=top_doc.createElement('div');"
                "  tt.id='pd-custom-tooltip';"
                "  top_doc.body.appendChild(tt);"
                "  var st=top_doc.createElement('style');"
                "  st.textContent='"
                "#pd-custom-tooltip{"
                "  position:fixed;z-index:999999;background:#fff;"
                "  border:1px solid #CBD5E1;border-radius:6px;"
                "  padding:10px 14px;font-family:Arial,sans-serif;"
                "  font-size:13px;color:#1E293B;text-align:left;"
                "  max-height:60vh;max-width:420px;min-width:280px;"
                "  overflow-y:auto;box-shadow:0 4px 12px rgba(0,0,0,.15);"
                "  pointer-events:auto;display:none;line-height:1.5;"
                "  word-wrap:break-word;overflow-wrap:break-word;"
                "}"
                "#pd-custom-tooltip::-webkit-scrollbar{width:6px}"
                "#pd-custom-tooltip::-webkit-scrollbar-track{"
                "  background:#F1F5F9;border-radius:3px}"
                "#pd-custom-tooltip::-webkit-scrollbar-thumb{"
                "  background:#94A3B8;border-radius:3px}"
                "#pd-custom-tooltip .pd-tt-sep{"
                "  border:0;border-top:1px solid #E2E8F0;margin:6px 0}"
                "';"
                "  top_doc.head.appendChild(st);"
                "}"
                "var ht;"
                "function bld(label,d){"
                "  var h='<b>'+label+' Priority</b><br>'+"
                "    '<hr class=\\\"pd-tt-sep\\\">';"
                "  h+='\\u2022 <b>Number of Risks:</b> '+d.count+'<br>';"
                "  h+='\\u2022 <b>Share:</b> '+d.share+"
                "    ' of Total Risks<br>';"
                "  h+='\\u2022 <b>Total Exposure:</b> '+d.exposure+'<br>';"
                "  h+='\\u2022 <b>Affected Pillars:</b> '+"
                "    d.pillars+'<br>';"
                "  h+='\\u2022 <b>Affected Frameworks:</b> '+"
                "    d.framework+'<br>';"
                "  return h;"
                "}"
                "function showTT(html,mx,my){"
                "  tt.innerHTML=html;tt.style.display='block';"
                "  var tw=tt.offsetWidth,th=tt.offsetHeight;"
                "  var vw=top_doc.documentElement.clientWidth;"
                "  var vh=top_doc.documentElement.clientHeight;"
                "  var l=mx+15,t=my+15;"
                "  if(l+tw>vw-10)l=mx-tw-15;"
                "  if(l<5)l=5;"
                "  if(t+th>vh-10)t=vh-th-10;"
                "  if(t<5)t=5;"
                "  tt.style.left=l+'px';tt.style.top=t+'px';"
                "}"
                "function hideTT(){tt.style.display='none';}"
                "tt.addEventListener('mouseenter',function(){"
                "  clearTimeout(ht);});"
                "tt.addEventListener('mouseleave',function(){"
                "  ht=setTimeout(hideTT,200);});"
                "var tries=0;"
                "function attach(){"
                "  if(tries++>60)return;"
                "  var pd=null,chart_ifr=null;"
                "  var all_docs=[top_doc];"
                "  var ifs=top_doc.querySelectorAll('iframe');"
                "  for(var i=0;i<ifs.length;i++){"
                "    try{all_docs.push(ifs[i].contentDocument||"
                "      ifs[i].contentWindow.document);}catch(e){}"
                "  }"
                "  for(var di=0;di<all_docs.length;di++){"
                "    var d=all_docs[di];"
                "    var plots=d.querySelectorAll('.js-plotly-plot');"
                "    for(var pi=0;pi<plots.length;pi++){"
                "      var p=plots[pi];"
                "      if(p&&p._fullLayout&&p._fullData"
                "        &&p._fullData[0]&&p._fullData[0].type==='pie'"
                "        &&!p.dataset.pdBound){"
                "        pd=p;break;"
                "      }"
                "    }"
                "    if(pd)break;"
                "    var ifs2=d.querySelectorAll('iframe');"
                "    for(var j=0;j<ifs2.length;j++){"
                "      try{"
                "        var cd=ifs2[j].contentDocument||"
                "          ifs2[j].contentWindow.document;"
                "        var plots2=cd.querySelectorAll("
                "          '.js-plotly-plot');"
                "        for(var pk=0;pk<plots2.length;pk++){"
                "          var p2=plots2[pk];"
                "          if(p2&&p2._fullLayout&&p2._fullData"
                "            &&p2._fullData[0]"
                "            &&p2._fullData[0].type==='pie'"
                "            &&!p2.dataset.pdBound){"
                "            pd=p2;chart_ifr=ifs2[j];break;"
                "          }"
                "        }"
                "        if(pd)break;"
                "      }catch(e){}"
                "    }"
                "    if(pd)break;"
                "  }"
                "  if(!pd||!pd._fullLayout){"
                "    setTimeout(attach,250);return;}"
                "  pd.dataset.pdBound='1';"
                "  pd.on('plotly_hover',function(ev){"
                "    clearTimeout(ht);"
                "    var pt=ev.points[0];"
                "    var key=pt.label,cd=TD[key];"
                "    if(cd){"
                "      var mx=ev.event.clientX,my=ev.event.clientY;"
                "      if(chart_ifr){"
                "        var r=chart_ifr.getBoundingClientRect();"
                "        mx+=r.left;my+=r.top;"
                "      }"
                "      showTT(bld(key,cd),mx,my);"
                "    }"
                "  });"
                "  pd.on('plotly_unhover',function(){"
                "    ht=setTimeout(hideTT,300);"
                "  });"
                "}"
                "attach();"
                "})();"
                "</script></head><body></body></html>"
            )
            import streamlit.components.v1 as _stc_pd
            _stc_pd.html(_pd_tooltip_html, height=0, scrolling=False)
        else:
            st.info("No risk findings to display.")


# ════════════════════════════════════════════════════════════
#  Tab 2 — Risk Register
# ════════════════════════════════════════════════════════════

def _render_risk_register():
    res = st.session_state["ro_results"]
    risks = [f for f in res["findings"] if f.get("finding_type") == "Risk"]

    _section("Risk Register",
             f"{len(risks)} risk findings identified")

    # --- Filters ---
    col1, col2 = st.columns(2)
    with col1:
        pillars = sorted(set(r.get("esg_pillar", "") for r in risks))
        selected_pillars = st.multiselect(
            "Filter by ESG Pillar", pillars, default=pillars, key="ro_pillar_filter")
    with col2:
        priorities = ["Critical", "High", "Medium", "Low"]
        selected_priorities = st.multiselect(
            "Filter by Priority", priorities, default=priorities,
            key="ro_priority_filter")

    filtered = [
        r for r in risks
        if r.get("esg_pillar") in selected_pillars
        and r.get("priority") in selected_priorities
    ]

    if not filtered:
        st.markdown(
            '<div style="border:1px dashed #D1D5DB; border-radius:14px; background:#FAFAFA; '
            'text-align:center; padding:40px 24px;">'
            '<div style="font-size:1.8rem; margin-bottom:6px;">\U0001f50e</div>'
            '<div style="font-size:0.95rem; font-weight:600; color:#374151;">'
            'No risks match the selected filters</div></div>',
            unsafe_allow_html=True,
        )
        return

    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    filtered.sort(key=lambda r: priority_order.get(r.get("priority", "Low"), 4))

    for r in filtered:
        priority = r.get("priority", "Medium")
        border_color = PRIORITY_COLORS.get(priority, "#6B7280")
        bg_map = {"Critical": "#FEF2F2", "High": "#FFF7ED",
                  "Medium": "#FFFBEB", "Low": "#F0FDF4"}
        bg_color = bg_map.get(priority, "#FFFFFF")
        fi_display = _format_original_currency(
            r.get("financial_impact", 0), r.get("financial_impact_currency", "USD"))
        evidence = r.get("evidence", {})
        confidence = evidence.get("evidence_confidence", "N/A")
        confidence_variant = confidence.lower() if confidence in (
            "Strong", "Moderate", "Weak") else "neutral"
        review_flag = evidence.get("review_required", False)
        calc_score = r.get("calculated_risk_score", 0)
        likelihood = r.get("likelihood_score", 0)
        impact = r.get("impact_score", 0)

        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-left:5px solid {border_color}; '
            f'border-radius:12px; padding:18px 20px; margin-bottom:12px; background:{bg_color};">'
            f'<div style="display:flex; justify-content:space-between; align-items:flex-start; '
            f'flex-wrap:wrap; gap:8px;">'
            f'  <div style="flex:1; min-width:200px;">'
            f'    <div style="font-size:1rem; font-weight:700; color:#111827; margin-bottom:4px;">'
            f'      {r.get("title", "")}</div>'
            f'    <div style="font-size:0.82rem; color:#374151; line-height:1.5; margin-bottom:8px;">'
            f'      {r.get("description", "")}</div>'
            f'    <div style="display:flex; flex-wrap:wrap; gap:6px; align-items:center;">'
            f'      {_status_pill(r.get("esg_pillar", ""), _pillar_variant(r.get("esg_pillar", "")))}'
            f'      {_status_pill(r.get("category", ""), "neutral")}'
            f'      {_status_pill(f"Evidence: {confidence}", confidence_variant)}'
            f'      {"" if not review_flag else _status_pill("Review required", "error")}'
            f'    </div>'
            f'  </div>'
            f'  <div style="text-align:right; min-width:150px;">'
            f'    <div style="font-size:0.68rem; font-weight:700; color:#6B7280; '
            f'text-transform:uppercase; letter-spacing:0.06em;">Risk Score</div>'
            f'    <div style="font-size:1.4rem; font-weight:800; color:{border_color};">'
            f'      {calc_score}</div>'
            f'    <div style="font-size:0.72rem; color:#6B7280;">'
            f'      L{likelihood} × I{impact}</div>'
            f'    <div style="font-size:0.72rem; color:#6B7280; margin-top:2px;">'
            f'      {_priority_dot(priority)}</div>'
            f'    <div style="font-size:0.85rem; font-weight:700; color:#111827; margin-top:6px;">'
            f'      {fi_display}</div>'
            f'  </div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        with st.expander(f"Details — {r.get('finding_id', r.get('title', ''))}"):
            det_c1, det_c2 = st.columns(2)
            with det_c1:
                st.markdown(f"**Recommendation:** {r.get('recommendation', 'N/A')}")
                st.markdown(f"**Category:** {r.get('recommendation_category', 'N/A')}")
                st.markdown(f"**Status:** {r.get('status', 'Open')}")
            with det_c2:
                fin = r.get("financial", {})
                st.markdown(f"**Financial Method:** {fin.get('calculation_method', 'N/A')}")
                st.markdown(f"**Assumptions:** {fin.get('assumptions', 'N/A')}")
                st.markdown(f"**Confidence:** {fin.get('confidence_level', 'N/A')}")

            sources = r.get("evidence_sources", [])
            if sources:
                st.markdown("**Evidence sources:**")
                for s in sources:
                    st.markdown(
                        f"- `{s.get('source_table', '')}` → "
                        f"`{s.get('source_id', '')}` "
                        f"({s.get('signal_type', '')}) "
                        f"{'✓ Verified' if s.get('verified') == 'Yes' else '⚠ Unverified'}"
                    )

    # --- Export ---
    st.markdown("---")
    export_rows = []
    for r in filtered:
        export_rows.append({
            "Finding ID": r.get("finding_id", ""),
            "Title": r.get("title", ""),
            "ESG Pillar": r.get("esg_pillar", ""),
            "Category": r.get("category", ""),
            "Priority": r.get("priority", ""),
            "Likelihood": r.get("likelihood_score", ""),
            "Impact": r.get("impact_score", ""),
            "Risk Score": r.get("calculated_risk_score", ""),
            "Financial Impact": r.get("financial_impact", ""),
            "Currency": r.get("financial_impact_currency", ""),
            "Recommendation": r.get("recommendation", ""),
            "Status": r.get("status", ""),
            "Evidence Confidence": r.get("evidence", {}).get("evidence_confidence", ""),
            "Review Required": r.get("evidence", {}).get("review_required", ""),
        })
    if export_rows:
        df_export = pd.DataFrame(export_rows)
        csv_buf = io.StringIO()
        df_export.to_csv(csv_buf, index=False)
        st.download_button(
            "⬇️ Download Risk Register (CSV)",
            csv_buf.getvalue(),
            file_name="risk_register.csv",
            mime="text/csv",
            key="ro_export_csv",
        )


# ════════════════════════════════════════════════════════════
#  Tab 3 — Opportunities
# ════════════════════════════════════════════════════════════

def _render_opportunities():
    res = st.session_state["ro_results"]
    opps = [f for f in res["findings"] if f.get("finding_type") == "Opportunity"]

    _section("Value-Creation Opportunities",
             f"{len(opps)} opportunities identified")

    if not opps:
        st.markdown(
            '<div style="border:1px dashed #D1D5DB; border-radius:14px; background:#FAFAFA; '
            'text-align:center; padding:40px 24px;">'
            '<div style="font-size:1.8rem; margin-bottom:6px;">\U0001f4a1</div>'
            '<div style="font-size:0.95rem; font-weight:600; color:#374151;">'
            'No opportunities identified for this deal</div></div>',
            unsafe_allow_html=True,
        )
        return

    total_opp_value = sum(o.get("financial_usd", 0) or 0 for o in opps)
    st.markdown(
        f'<div style="border:1px solid #D1FAE5; border-radius:14px; padding:18px 24px; '
        f'background:linear-gradient(135deg, #ECFDF5, #F0FDF4); margin-bottom:20px;">'
        f'<div style="display:flex; align-items:center; gap:16px;">'
        f'  <div style="font-size:1.8rem;">\U0001f4b0</div>'
        f'  <div>'
        f'    <div style="font-size:0.72rem; font-weight:700; color:#059669; '
        f'text-transform:uppercase; letter-spacing:0.08em;">Total Opportunity Value</div>'
        f'    <div style="font-size:1.5rem; font-weight:800; color:#059669;">'
        f'      {_format_currency(total_opp_value)}</div>'
        f'  </div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(2)
    for i, opp in enumerate(opps):
        with cols[i % 2]:
            fi = opp.get("financial_impact", 0)
            fi_cur = opp.get("financial_impact_currency", "USD")
            fi_display = _format_original_currency(fi, fi_cur) if fi > 0 else "N/A"
            payback = opp.get("payback_period_months")
            payback_text = f"{payback} months" if payback else "N/A"
            effort = opp.get("implementation_effort", "Medium")
            effort_variant = {"Low": "success", "Medium": "warning",
                              "High": "error"}.get(effort, "info")

            st.markdown(
                f'<div style="border:1px solid #D1FAE5; border-left:5px solid #059669; '
                f'border-radius:12px; padding:18px 20px; margin-bottom:14px; background:white;">'
                f'  <div style="font-size:1rem; font-weight:700; color:#111827; '
                f'margin-bottom:6px;">{opp.get("title", "")}</div>'
                f'  <div style="font-size:0.82rem; color:#374151; line-height:1.5; '
                f'margin-bottom:10px;">{opp.get("description", "")}</div>'
                f'  <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px;">'
                f'    {_status_pill(opp.get("esg_pillar", ""), _pillar_variant(opp.get("esg_pillar", "")))}'
                f'    {_status_pill(opp.get("category", ""), "neutral")}'
                f'    {_status_pill(f"Effort: {effort}", effort_variant)}'
                f'  </div>'
                f'  <div style="display:flex; gap:20px; flex-wrap:wrap;">'
                f'    <div>'
                f'      <div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
                f'text-transform:uppercase; letter-spacing:0.06em;">Est. Value</div>'
                f'      <div style="font-size:1.1rem; font-weight:800; color:#059669;">'
                f'{fi_display}</div>'
                f'    </div>'
                f'    <div>'
                f'      <div style="font-size:0.65rem; font-weight:700; color:#6B7280; '
                f'text-transform:uppercase; letter-spacing:0.06em;">Payback</div>'
                f'      <div style="font-size:1.1rem; font-weight:700; color:#374151;">'
                f'{payback_text}</div>'
                f'    </div>'
                f'  </div>'
                f'  <div style="margin-top:10px; font-size:0.82rem; color:#374151; '
                f'border-top:1px solid #E5E7EB; padding-top:10px;">'
                f'    <b style="color:#FF5A00;">Recommendation:</b> '
                f'{opp.get("recommendation", "N/A")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ════════════════════════════════════════════════════════════
#  Tab 4 — Deal Recommendations
# ════════════════════════════════════════════════════════════

def _render_recommendations():
    res = st.session_state["ro_results"]
    findings = res["findings"]

    _section("Deal Recommendations",
             "Findings grouped by recommendation category")

    by_category = {}
    for f in findings:
        cat = f.get("recommendation_category", "Additional diligence")
        by_category.setdefault(cat, []).append(f)

    category_icons = {
        "Additional diligence": "\U0001f50d",
        "Valuation consideration": "\U0001f4b2",
        "Contractual protection": "\U0001f6e1️",
        "Condition precedent": "⚖️",
        "Remediation requirement": "\U0001f527",
        "Post-merger integration": "\U0001f4c8",
        "Value creation": "\U0001f4a1",
    }

    for cat in RECOMMENDATION_CATEGORIES:
        items = by_category.get(cat, [])
        if not items:
            continue

        icon = category_icons.get(cat, "•")
        st.markdown(
            f'<div style="margin-top:16px; margin-bottom:8px;">'
            f'<span style="font-size:1.05rem; font-weight:700; color:#111827;">'
            f'{icon} {cat}</span>'
            f'<span style="font-size:0.78rem; color:#6B7280; margin-left:8px;">'
            f'({len(items)} finding{"s" if len(items) != 1 else ""})</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        for f in items:
            priority = f.get("priority", "Medium")
            finding_type = f.get("finding_type", "Risk")
            type_pill = (_status_pill("Risk", _priority_variant(priority))
                         if finding_type == "Risk"
                         else _status_pill("Opportunity", "success"))
            st.markdown(
                f'<div style="border:1px solid #E5E7EB; border-radius:10px; padding:12px 16px; '
                f'margin-bottom:8px; background:white;">'
                f'  <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">'
                f'    {type_pill}'
                f'    <span style="font-size:0.9rem; font-weight:600; color:#111827;">'
                f'      {f.get("title", "")}</span>'
                f'  </div>'
                f'  <div style="font-size:0.82rem; color:#374151; margin-top:6px;">'
                f'    {f.get("recommendation", "")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ════════════════════════════════════════════════════════════
#  Tab 5 — Evidence Trail
# ════════════════════════════════════════════════════════════

def _render_evidence_trail():
    res = st.session_state["ro_results"]
    findings = res["findings"]

    _section("Evidence Trail",
             "Trace each finding back to its source data")

    st.markdown(
        f'<div style="font-size:0.84rem; color:#6B7280; margin-bottom:16px;">'
        f'Signals collected from source data: '
        f'<b style="color:#111827;">{res.get("signals_collected", 0)}</b> '
        f'| Analysis timestamp: '
        f'<b style="color:#111827;">{res.get("timestamp", "N/A")}</b></div>',
        unsafe_allow_html=True,
    )

    risks = [f for f in findings if f.get("finding_type") == "Risk"]
    opps = [f for f in findings if f.get("finding_type") == "Opportunity"]

    for f in risks + opps:
        finding_id = f.get("finding_id", f.get("title", ""))
        finding_type = f.get("finding_type", "Risk")
        sources = f.get("evidence_sources", [])
        evidence = f.get("evidence", {})
        confidence = evidence.get("evidence_confidence", "N/A")
        confidence_variant = confidence.lower() if confidence in (
            "Strong", "Moderate", "Weak") else "neutral"
        review_req = evidence.get("review_required", False)

        header_parts = [
            f"{_priority_dot(f.get('priority', 'Medium'))} " if finding_type == "Risk" else "\U0001f4a1 ",
            f"**{finding_id}**",
            f" — {f.get('title', '')}",
        ]

        with st.expander("".join(header_parts)):
            st.markdown(
                f'{_status_pill(finding_type, "error" if finding_type == "Risk" else "success")} '
                f'{_status_pill(f.get("esg_pillar", ""), _pillar_variant(f.get("esg_pillar", "")))} '
                f'{_status_pill(f"Evidence: {confidence}", confidence_variant)} '
                f'{"" if not review_req else _status_pill("⚠ Review required", "error")}',
                unsafe_allow_html=True,
            )

            if sources:
                st.markdown("")
                st.markdown("**Evidence sources:**")
                for s in sources:
                    raw = s.get("raw_data", {})
                    raw_detail = ", ".join(
                        f"`{k}`: {v}" for k, v in raw.items() if v
                    ) if raw else "N/A"
                    verified_badge = (
                        '<span style="color:#059669; font-weight:600;">✓ Verified</span>'
                        if s.get("verified") == "Yes"
                        else '<span style="color:#D97706; font-weight:600;">⚠ Unverified</span>'
                    )

                    st.markdown(
                        f'<div style="border:1px solid #E5E7EB; border-radius:8px; '
                        f'padding:10px 14px; margin-bottom:6px; background:#FAFAFA;">'
                        f'  <div style="display:flex; justify-content:space-between; '
                        f'align-items:center; margin-bottom:4px;">'
                        f'    <span style="font-size:0.82rem; font-weight:600; color:#111827;">'
                        f'      {s.get("source_table", "")} → {s.get("source_id", "")}'
                        f'    </span>'
                        f'    {verified_badge}'
                        f'  </div>'
                        f'  <div style="font-size:0.78rem; color:#6B7280;">'
                        f'    Signal: {s.get("signal_type", "N/A")}</div>'
                        f'  <div style="font-size:0.75rem; color:#9CA3AF; margin-top:2px;">'
                        f'    {raw_detail}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                doc_id = f.get("evidence_document_id", "")
                controv_id = f.get("evidence_controversy_id", "")
                if doc_id or controv_id:
                    st.markdown(
                        f'<div style="font-size:0.82rem; color:#374151; margin-top:6px;">'
                        f'{"<b>Document:</b> " + doc_id + "<br>" if doc_id else ""}'
                        f'{"<b>Controversy:</b> " + controv_id if controv_id else ""}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div style="font-size:0.82rem; color:#9CA3AF; font-style:italic;">'
                        'No detailed evidence sources linked</div>',
                        unsafe_allow_html=True,
                    )

            st.markdown(
                f'<div style="margin-top:8px; font-size:0.78rem; color:#6B7280;">'
                f'Evidence count: <b>{evidence.get("evidence_count", 0)}</b> | '
                f'Verified: <b>{evidence.get("verified_count", 0)}</b> | '
                f'Confidence score: <b>{evidence.get("confidence_score", "N/A")}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )
