"""
ESG Risk & Opportunity Agent -- Streamlit view.

Displays synthesised risk/opportunity findings with:
  Tab 1  Executive Dashboard  -- KPIs, risk matrix, exposure breakdown
  Tab 2  Risk Register        -- detailed table with severity coding
  Tab 3  Opportunities        -- cards with value and payback
  Tab 4  Deal Recommendations -- grouped by category with diligence checklist
  Tab 5  Evidence Trail       -- links to source data
"""

import io
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

    # --- Risk matrix heatmap ---
    _section("Risk Matrix", "Likelihood vs Impact (risk findings only)")

    matrix = get_risk_matrix_data(findings)
    z_vals = [[len(cell) for cell in row] for row in matrix]
    hover_texts = []
    for row in matrix:
        hover_row = []
        for cell in row:
            if cell:
                hover_row.append("<br>".join(str(c) for c in cell[:5]))
            else:
                hover_row.append("")
        hover_texts.append(hover_row)

    annotation_texts = []
    for row in z_vals:
        annotation_texts.append([str(v) if v > 0 else "" for v in row])

    impact_labels = ["Negligible", "Minor", "Moderate", "Major", "Severe"]
    likelihood_labels = ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"]

    fig = go.Figure(data=go.Heatmap(
        z=z_vals,
        x=impact_labels,
        y=likelihood_labels,
        colorscale=[
            [0.0, "#F0FDF4"],
            [0.25, "#FEF9C3"],
            [0.5, "#FED7AA"],
            [0.75, "#FECACA"],
            [1.0, "#FCA5A5"],
        ],
        showscale=False,
        hovertext=hover_texts,
        hovertemplate="<b>Impact:</b> %{x}<br><b>Likelihood:</b> %{y}<br>"
                      "<b>Count:</b> %{z}<br>%{hovertext}<extra></extra>",
    ))

    for i, row in enumerate(annotation_texts):
        for j, text in enumerate(row):
            if text:
                fig.add_annotation(
                    x=impact_labels[j], y=likelihood_labels[i],
                    text=f"<b>{text}</b>", showarrow=False,
                    font=dict(size=16, color="#111827"),
                )

    fig.update_layout(
        xaxis_title="Impact",
        yaxis_title="Likelihood",
        height=380,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="white",
        xaxis=dict(side="bottom", tickfont=dict(size=11)),
        yaxis=dict(tickfont=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)

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
            st.plotly_chart(fig_bar, use_container_width=True)
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
            fig_donut = go.Figure(go.Pie(
                labels=labels,
                values=vals,
                hole=0.55,
                marker=dict(colors=colors_list),
                textinfo="label+value",
                textfont=dict(size=11),
                hovertemplate="<b>%{label}</b>: %{value} findings<extra></extra>",
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
            st.plotly_chart(fig_donut, use_container_width=True)
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
