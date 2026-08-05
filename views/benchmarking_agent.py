"""
ESG Benchmarking Agent — Streamlit view.

Compares a target company's ESG metrics against industry peers with:
  Tab 1  Benchmark Analysis — single-metric deep dive
  Tab 2  Benchmark Summary  — all-metric overview for a company
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from utils.benchmarking_agent import (
    get_available_companies,
    get_available_metrics,
    get_available_years,
    run_benchmark,
    run_benchmark_summary,
    get_historical_benchmark,
    compare_against_target,
    classify_performance,
    get_performance_color,
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


def _metric_card(label, value, color="#111827", accent=None):
    accent_css = f"border-left:4px solid {accent};" if accent else ""
    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px; {accent_css}">'
        f'<div style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
        f'letter-spacing:0.08em; margin-bottom:4px;">{label}</div>'
        f'<div style="font-size:1.5rem; font-weight:800; color:{color};">{value}</div></div>',
        unsafe_allow_html=True,
    )


def _status_pill(text, variant="info"):
    colors = {
        "success": ("#ECFDF5", "#059669"),
        "warning": ("#FFFBEB", "#D97706"),
        "error":   ("#FEF2F2", "#DC2626"),
        "info":    ("#EFF6FF", "#2563EB"),
        "leading": ("#ECFDF5", "#059669"),
        "above":   ("#EFF6FF", "#2563EB"),
        "below":   ("#FFFBEB", "#D97706"),
        "lagging": ("#FEF2F2", "#DC2626"),
    }
    bg, fg = colors.get(variant, colors["info"])
    return (
        f'<span style="background:{bg}; color:{fg}; font-size:0.75rem; font-weight:600; '
        f'padding:4px 12px; border-radius:20px; letter-spacing:0.02em; '
        f'white-space:nowrap; display:inline-block;">{text}</span>'
    )


def _performance_variant(perf):
    return {
        "Leading": "leading",
        "Above Median": "above",
        "Below Median": "below",
        "Lagging": "lagging",
    }.get(perf, "info")


# ════════════════════════════════════════════════════════════
#  Render entry point
# ════════════════════════════════════════════════════════════

def render():
    st.markdown(
        '<div style="margin-bottom:6px;">'
        '<h2 style="margin:0; font-size:1.55rem; font-weight:700; color:#111827;">'
        '📈 ESG Benchmarking Agent</h2>'
        '<p style="color:#6B7280; font-size:0.88rem; margin:6px 0 16px 0; line-height:1.6;">'
        'Compare your company\'s ESG performance against industry peers — '
        'peer group selection, percentile ranking, and performance classification.</p></div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["📊  Benchmark Analysis", "📋  Benchmark Summary"])

    with tabs[0]:
        _render_analysis_tab()
    with tabs[1]:
        _render_summary_tab()


# ════════════════════════════════════════════════════════════
#  Tab 1 — Benchmark Analysis
# ════════════════════════════════════════════════════════════

def _render_analysis_tab():
    companies = get_available_companies()
    metrics = get_available_metrics()

    if not companies:
        st.info("No company data available. Please upload ESG metric data first.")
        return

    # --- Selectors ---
    _section("Select Parameters", "Choose a company, metric, and year to benchmark")

    c1, c2, c3 = st.columns(3)
    with c1:
        comp_options = {f"{c['company_name']} ({c['company_id']})": c for c in companies}
        comp_label = st.selectbox("Company", list(comp_options.keys()), key="bm_company")
        selected_company = comp_options[comp_label]

    with c2:
        metric_options = {f"{m['metric_name']} ({m['metric_code']})": m for m in metrics}
        metric_label = st.selectbox("ESG Metric", list(metric_options.keys()), key="bm_metric")
        selected_metric = metric_options[metric_label]

    with c3:
        years = get_available_years(selected_company["company_id"], selected_metric["metric_code"])
        if years:
            selected_year = st.selectbox("Reporting Year", years, key="bm_year")
        else:
            st.warning("No years available for this combination.")
            return

    run_clicked = st.button("🔍  Run Benchmark", key="bm_run", type="primary", use_container_width=True)

    if run_clicked:
        with st.spinner("Running benchmark analysis..."):
            result = run_benchmark(
                selected_company["company_id"],
                selected_metric["metric_code"],
                selected_year,
            )
        if result:
            st.session_state["bm_result"] = result
            st.session_state["bm_company_name"] = selected_company["company_name"]
        else:
            st.error("No data found for this combination. Try a different metric or year.")
            return

    result = st.session_state.get("bm_result")
    if not result:
        st.markdown(
            '<div style="text-align:center; padding:48px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; background:#FAFAFA; margin:20px 0;">'
            '<div style="font-size:2.2rem; margin-bottom:10px;">📈</div>'
            '<div style="font-size:1rem; font-weight:600; color:#374151; margin-bottom:6px;">'
            'Select parameters and click Run Benchmark</div>'
            '<div style="color:#9CA3AF; font-size:0.88rem; max-width:500px; margin:0 auto; line-height:1.55;">'
            'Choose a company, ESG metric, and reporting year above, then click '
            '<b>Run Benchmark</b> to see how the company performs relative to its peers.</div></div>',
            unsafe_allow_html=True,
        )
        return

    if result.get("peer_count", 0) == 0:
        st.warning("No comparable peers found for this combination.")
        return

    company_name = st.session_state.get("bm_company_name", "")
    _render_performance_cards(result)
    _render_peer_group_info(result)
    _render_distribution_chart(result, company_name)
    _render_historical_trend(result, company_name)
    _render_target_progress(result)
    _render_statistics_table(result)
    _render_peer_detail_table(result)


# ── Performance Overview Cards ──

def _render_performance_cards(result):
    _section("Performance Overview")

    perf = result["performance"]
    perf_color = get_performance_color(perf)
    pctl = result["percentile"]
    dist = result["distance_from_median"]
    dist_pct = result["distance_pct"]
    direction = result.get("direction", "higher_is_better")

    if direction == "lower_is_better":
        arrow = "↓" if dist < 0 else "↑"
        dist_good = dist < 0
    else:
        arrow = "↑" if dist > 0 else "↓"
        dist_good = dist > 0
    dist_color = "#059669" if dist_good else "#DC2626"

    pctl_color = perf_color

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Percentile Rank", f"{pctl:.0f}th", pctl_color, accent=pctl_color)
    with c2:
        st.markdown(
            f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px; '
            f'border-left:4px solid {perf_color};">'
            f'<div style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
            f'letter-spacing:0.08em; margin-bottom:4px;">PERFORMANCE CLASS</div>'
            f'<div style="margin-top:4px;">{_status_pill(perf, _performance_variant(perf))}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        _metric_card(
            "Distance from Median",
            f"{arrow} {abs(dist):,.2f} ({abs(dist_pct):.1f}%)",
            dist_color,
            accent=dist_color,
        )
    with c4:
        tier_label = result.get("peer_tier_label", "")
        _metric_card(
            "Peer Count",
            f"{result['peer_count']} peers",
            "#111827",
            accent="#FF5A00",
        )


# ── Peer Group Info Box ──

def _render_peer_group_info(result):
    tier = result.get("peer_tier", 0)
    tier_label = result.get("peer_tier_label", "")
    description = result.get("peer_group", "")
    limitation = result.get("limitation")
    suitability = result.get("suitability", "")
    peer_count = result.get("peer_count", 0)

    tier_descriptions = {
        1: "Best match — same industry, same country, same year",
        2: "Regional match — same industry, same geographic region, same year",
        3: "Global match — same industry worldwide, same year",
        4: "Expanded match — includes adjacent industries",
    }
    tier_detail = tier_descriptions.get(tier, "")

    border_color = "#86efac" if not limitation else "#FCD34D"
    bg_color = "#f0fdf4" if not limitation else "#FFFBEB"

    info_html = (
        f'<div style="border:1px solid {border_color}; background:{bg_color}; '
        f'border-radius:12px; padding:16px; margin:12px 0;">'
        f'<div style="display:flex; align-items:center; gap:10px; margin-bottom:8px;">'
        f'<span style="font-size:0.68rem; font-weight:700; color:#6B7280; text-transform:uppercase; '
        f'letter-spacing:0.08em;">PEER GROUP</span>'
        f'<span style="background:#FF5A00; color:white; font-size:0.68rem; font-weight:700; '
        f'padding:2px 10px; border-radius:12px;">Tier {tier}</span>'
        f'</div>'
        f'<div style="font-size:1rem; font-weight:700; color:#111827; margin-bottom:4px;">'
        f'{description}</div>'
        f'<div style="font-size:0.84rem; color:#6B7280; margin-bottom:4px;">{tier_detail}</div>'
        f'<div style="font-size:0.82rem; color:#374151;">'
        f'<b>{peer_count}</b> peers — {suitability}</div>'
    )
    if limitation:
        info_html += (
            f'<div style="margin-top:8px; padding:8px 12px; background:#FEF3C7; border-radius:8px; '
            f'font-size:0.82rem; color:#92400E;">⚠️ {limitation}</div>'
        )
    info_html += '</div>'
    st.markdown(info_html, unsafe_allow_html=True)


# ── Peer Distribution Chart ──

def _render_distribution_chart(result, company_name):
    _section("Peer Distribution", "How the target company compares to each peer")

    peers = result.get("peer_details", [])
    if not peers:
        return

    target_value = result["target_value"]
    median = result["peer_median"]
    q1 = result["q1"]
    q3 = result["q3"]
    unit = result.get("unit", "")

    all_entries = list(peers) + [{
        "company_name": company_name,
        "value": target_value,
        "is_target": True,
    }]
    all_entries.sort(key=lambda x: x["value"])

    names = []
    values = []
    colors = []
    for entry in all_entries:
        names.append(entry["company_name"])
        values.append(entry["value"])
        colors.append("#FF5A00" if entry.get("is_target") else "#CBD5E1")

    fig = go.Figure()

    fig.add_shape(
        type="rect", x0=q1, x1=q3, y0=-0.5, y1=len(names) - 0.5,
        fillcolor="rgba(37,99,235,0.08)", line=dict(width=0),
        layer="below",
    )

    fig.add_trace(go.Bar(
        y=names, x=values, orientation="h",
        marker_color=colors,
        marker_line_width=0,
        text=[f"{v:,.2f}" for v in values],
        textposition="outside",
        textfont_size=11,
    ))

    fig.add_vline(x=median, line_dash="dash", line_color="#6B7280", line_width=2,
                  annotation_text=f"Median: {median:,.2f}",
                  annotation_position="top right",
                  annotation_font_size=11)

    fig.update_layout(
        height=max(350, len(names) * 32 + 80),
        margin=dict(l=10, r=60, t=30, b=40),
        xaxis_title=unit,
        yaxis=dict(autorange="reversed"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(size=12),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=True, gridcolor="#F3F4F6")

    st.plotly_chart(fig, use_container_width=True)

    st.markdown(
        '<div style="display:flex; gap:16px; justify-content:center; font-size:0.78rem; color:#6B7280;">'
        '<span>🟧 Target company</span>'
        '<span>⬜ Peer company</span>'
        '<span>--- Peer median</span>'
        '<span style="color:#2563EB;">█</span> Q1–Q3 range'
        '</div>',
        unsafe_allow_html=True,
    )


# ── Historical Trend Chart ──

def _render_historical_trend(result, company_name):
    _section("Historical Trend", "Performance over time vs. peer median")

    company_id = None
    metric_code = result.get("metric_code")
    companies = get_available_companies()
    for c in companies:
        if c["company_name"] == company_name:
            company_id = c["company_id"]
            break

    if not company_id:
        return

    historical = get_historical_benchmark(company_id, metric_code)
    if len(historical) < 2:
        st.caption("Not enough historical data for trend chart (need 2+ years).")
        return

    years = [h["year"] for h in historical]
    target_vals = [h["target_value"] for h in historical]
    medians = [h["peer_median"] for h in historical]
    q1s = [h["q1"] for h in historical]
    q3s = [h["q3"] for h in historical]
    unit = result.get("unit", "")

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=years, y=q3s, mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=q1s, mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(37,99,235,0.08)",
        showlegend=True, name="Q1–Q3 Range",
        hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=years, y=medians, mode="lines+markers",
        line=dict(color="#6B7280", width=2, dash="dash"),
        marker=dict(size=6, color="#6B7280"),
        name="Peer Median",
    ))

    fig.add_trace(go.Scatter(
        x=years, y=target_vals, mode="lines+markers",
        line=dict(color="#FF5A00", width=3),
        marker=dict(size=8, color="#FF5A00"),
        name=company_name,
    ))

    fig.update_layout(
        height=350,
        margin=dict(l=10, r=10, t=30, b=40),
        xaxis_title="Year",
        yaxis_title=unit,
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        font=dict(size=12),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#F3F4F6", dtick=1)
    fig.update_yaxes(showgrid=True, gridcolor="#F3F4F6")

    st.plotly_chart(fig, use_container_width=True)


# ── Target Progress ──

def _render_target_progress(result):
    company_id = None
    companies = get_available_companies()
    company_name = st.session_state.get("bm_company_name", "")
    for c in companies:
        if c["company_name"] == company_name:
            company_id = c["company_id"]
            break
    if not company_id:
        return

    target_info = compare_against_target(
        company_id, result["metric_code"], result["year"]
    )
    if not target_info:
        return

    _section("Target Progress", f"{target_info['target_name']}")

    status = target_info["status"]
    status_variant = {"On track": "success", "At risk": "warning", "Off track": "error"}.get(status, "info")
    progress = min(target_info["progress_pct"], 100)

    progress_color = {"On track": "#059669", "At risk": "#D97706", "Off track": "#DC2626"}.get(status, "#6B7280")

    st.markdown(
        f'<div style="border:1px solid #E5E7EB; border-radius:12px; padding:16px; margin:8px 0;">'
        f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">'
        f'<span style="font-size:0.88rem; font-weight:600; color:#111827;">'
        f'{target_info["target_type"]} — Target Year: {target_info["target_year"]}</span>'
        f'{_status_pill(status, status_variant)}'
        f'</div>'
        f'<div style="background:#F3F4F6; border-radius:8px; height:12px; overflow:hidden; margin-bottom:8px;">'
        f'<div style="background:{progress_color}; height:100%; width:{progress:.1f}%; '
        f'border-radius:8px; transition:width 0.3s;"></div></div>'
        f'<div style="display:flex; justify-content:space-between; font-size:0.78rem; color:#6B7280;">'
        f'<span>Base: {target_info["base_value"]:,.2f} ({target_info["base_year"]})</span>'
        f'<span style="font-weight:700; color:{progress_color};">{target_info["progress_pct"]:.1f}% complete</span>'
        f'<span>Target: {target_info["target_value"]:,.2f} ({target_info["target_year"]})</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        _metric_card("Base Value", f"{target_info['base_value']:,.2f}")
    with c2:
        _metric_card("Current Value", f"{target_info['current_value']:,.2f}", "#FF5A00")
    with c3:
        _metric_card("Target Value", f"{target_info['target_value']:,.2f}", "#059669")


# ── Statistics Table ──

def _render_statistics_table(result):
    _section("Peer Statistics")

    stats_data = [
        {"Statistic": "Mean", "Value": f"{result['peer_mean']:,.2f}"},
        {"Statistic": "Median", "Value": f"{result['peer_median']:,.2f}"},
        {"Statistic": "Q1 (25th percentile)", "Value": f"{result['q1']:,.2f}"},
        {"Statistic": "Q3 (75th percentile)", "Value": f"{result['q3']:,.2f}"},
        {"Statistic": "Interquartile Range (IQR)", "Value": f"{result['iqr']:,.2f}"},
        {"Statistic": "Standard Deviation", "Value": f"{result.get('std_dev', 0):,.2f}"},
        {"Statistic": "Minimum", "Value": f"{result.get('peer_min', 0):,.2f}"},
        {"Statistic": "Maximum", "Value": f"{result.get('peer_max', 0):,.2f}"},
        {"Statistic": "Peer Count", "Value": str(result['peer_count'])},
    ]
    st.dataframe(pd.DataFrame(stats_data), use_container_width=True, hide_index=True)


# ── Detailed Peer Table ──

def _render_peer_detail_table(result):
    peers = result.get("peer_details", [])
    if not peers:
        return

    with st.expander("📋 View Individual Peer Values", expanded=False):
        unit = result.get("unit", "")
        rows = []
        for p in peers:
            rows.append({
                "Company": p["company_name"],
                "Country": p["country"],
                "Industry": p["industry"],
                f"Value ({unit})": p["value"],
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════
#  Tab 2 — Benchmark Summary
# ════════════════════════════════════════════════════════════

def _render_summary_tab():
    companies = get_available_companies()
    if not companies:
        st.info("No company data available.")
        return

    _section("Multi-Metric Benchmark Overview",
             "See how a company performs across all ESG metrics at a glance")

    c1, c2 = st.columns(2)
    with c1:
        comp_options = {f"{c['company_name']} ({c['company_id']})": c for c in companies}
        comp_label = st.selectbox("Company", list(comp_options.keys()), key="bm_sum_company")
        selected_company = comp_options[comp_label]
    with c2:
        years = get_available_years(selected_company["company_id"])
        if years:
            selected_year = st.selectbox("Year", years, key="bm_sum_year")
        else:
            st.warning("No data available.")
            return

    if st.button("📊  Generate Summary", key="bm_sum_run", type="primary", use_container_width=True):
        with st.spinner("Benchmarking across all metrics..."):
            results = run_benchmark_summary(selected_company["company_id"], selected_year)
        if results:
            st.session_state["bm_summary"] = results
            st.session_state["bm_sum_name"] = selected_company["company_name"]
        else:
            st.warning("No benchmark results could be generated.")
            return

    summary = st.session_state.get("bm_summary")
    if not summary:
        st.markdown(
            '<div style="text-align:center; padding:40px 20px; border:1px dashed #D1D5DB; '
            'border-radius:14px; background:#FAFAFA; margin:20px 0;">'
            '<div style="font-size:2rem; margin-bottom:8px;">📋</div>'
            '<div style="font-size:0.95rem; font-weight:600; color:#374151;">Select a company and year, '
            'then click Generate Summary</div></div>',
            unsafe_allow_html=True,
        )
        return

    # KPI overview
    leading = sum(1 for r in summary if r["performance"] == "Leading")
    above = sum(1 for r in summary if r["performance"] == "Above Median")
    below = sum(1 for r in summary if r["performance"] == "Below Median")
    lagging = sum(1 for r in summary if r["performance"] == "Lagging")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Leading", str(leading), "#059669", accent="#059669")
    with c2:
        _metric_card("Above Median", str(above), "#2563EB", accent="#2563EB")
    with c3:
        _metric_card("Below Median", str(below), "#D97706", accent="#D97706")
    with c4:
        _metric_card("Lagging", str(lagging), "#DC2626", accent="#DC2626")

    # Pillar breakdown
    _section("Performance by ESG Pillar")

    for pillar in ["Environmental", "Social", "Governance"]:
        pillar_results = [r for r in summary if r.get("esg_pillar") == pillar]
        if not pillar_results:
            continue

        pillar_icon = {"Environmental": "🌍", "Social": "👥", "Governance": "🏛️"}.get(pillar, "")
        st.markdown(
            f'<div style="font-size:0.95rem; font-weight:700; color:#111827; margin:16px 0 8px 0;">'
            f'{pillar_icon} {pillar}</div>',
            unsafe_allow_html=True,
        )

        for r in pillar_results:
            perf = r["performance"]
            perf_color = get_performance_color(perf)
            pctl = r["percentile"]
            dist_pct = r.get("distance_pct", 0)
            direction = r.get("direction", "higher_is_better")

            if direction == "lower_is_better":
                trend = "↓" if dist_pct < 0 else "↑"
            else:
                trend = "↑" if dist_pct > 0 else "↓"

            st.markdown(
                f'<div style="border:1px solid #E5E7EB; border-left:4px solid {perf_color}; '
                f'border-radius:10px; padding:12px 16px; margin-bottom:6px; '
                f'display:flex; align-items:center; gap:12px; flex-wrap:wrap;">'
                f'<div style="flex:1; min-width:200px;">'
                f'<div style="font-weight:600; font-size:0.88rem; color:#111827;">{r["metric_name"]}</div>'
                f'<div style="font-size:0.78rem; color:#6B7280;">{r["unit"]} · {r["peer_count"]} peers</div></div>'
                f'<div style="text-align:center; min-width:80px;">'
                f'<div style="font-size:0.68rem; color:#6B7280; text-transform:uppercase;">Value</div>'
                f'<div style="font-weight:700; color:#111827;">{r["target_value"]:,.2f}</div></div>'
                f'<div style="text-align:center; min-width:80px;">'
                f'<div style="font-size:0.68rem; color:#6B7280; text-transform:uppercase;">Median</div>'
                f'<div style="font-weight:600; color:#6B7280;">{r["peer_median"]:,.2f}</div></div>'
                f'<div style="text-align:center; min-width:70px;">'
                f'<div style="font-size:0.68rem; color:#6B7280; text-transform:uppercase;">Percentile</div>'
                f'<div style="font-weight:700; color:{perf_color};">{pctl:.0f}th</div></div>'
                f'<div style="min-width:100px; text-align:center;">'
                f'{_status_pill(perf, _performance_variant(perf))}</div>'
                f'<div style="text-align:center; min-width:60px;">'
                f'<div style="font-size:1rem; color:{perf_color};">{trend} {abs(dist_pct):.1f}%</div></div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Export
    _section("Export")
    export_rows = []
    for r in summary:
        export_rows.append({
            "Pillar": r.get("esg_pillar", ""),
            "Metric": r["metric_name"],
            "Code": r["metric_code"],
            "Value": r["target_value"],
            "Unit": r.get("unit", ""),
            "Peer Median": r["peer_median"],
            "Peer Mean": r["peer_mean"],
            "Q1": r["q1"],
            "Q3": r["q3"],
            "Percentile": r["percentile"],
            "Performance": r["performance"],
            "Peer Count": r["peer_count"],
            "Peer Group": r["peer_group"],
        })
    export_df = pd.DataFrame(export_rows)
    company_name = st.session_state.get("bm_sum_name", "company")
    csv_data = export_df.to_csv(index=False)
    st.download_button(
        "📥  Export to CSV",
        data=csv_data,
        file_name=f"benchmark_summary_{company_name.replace(' ', '_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
