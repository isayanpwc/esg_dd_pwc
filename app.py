import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.auth import is_logged_in, logout_user
from views import login, home, datasources, registration_agent, metric_analysis_agent, compliance_agent, benchmarking_agent, risk_opportunity_agent, review_governance_agent

st.set_page_config(
    page_title="ESG Data Platform",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ══════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════

_BASE_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

*, *::before, *::after {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
/* Preserve Material Symbols icon font — the * selector above overrides the icon
   font, causing ligature text like "upload" to render as a visible duplicate word */
[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] * {
    font-family: 'Material Symbols Rounded' !important;
}
.stApp {
    background: linear-gradient(165deg, #FFF8F2 0%, #FFFBF8 40%, #FEFEFE 100%) !important;
}

.stApp > div[data-testid="stAppViewContainer"],
.stApp > div[data-testid="stAppViewContainer"] > div,
div[data-testid="stMain"],
div[data-testid="stMainBlockContainer"],
.stMain, section.main,
section.main > div,
section.main > div > div,
.block-container {
    background: transparent !important;
}

div[data-testid="stHeader"] { visibility: hidden; height: 0; }
#MainMenu, header, footer { visibility: hidden; }
div[data-testid="stAppDeployButton"] { display: none; }

/* ── Tabs ── */
div[data-testid="stTabs"] [role="tablist"] {
    gap: 0; border-bottom: 2px solid #E5E7EB; background: transparent;
}
div[data-testid="stTabs"] [role="tab"],
div[data-testid="stTab"] {
    padding: 12px 28px; font-weight: 500; font-size: 0.92rem;
    color: #6B7280; background: transparent; border: none;
    transition: all 0.2s ease;
}
div[data-testid="stTabs"] [aria-selected="true"],
div[data-testid="stTab"][aria-selected="true"] {
    color: #111827 !important; font-weight: 600 !important;
    border-bottom: 3px solid #FF5A00 !important;
}
div[data-testid="stTabs"] [role="tab"]:hover,
div[data-testid="stTab"]:hover { color: #374151 !important; }

/* ── Primary buttons (main area) ── */
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #FF5A00, #FF7F32) !important;
    border: none !important; color: #FFFFFF !important;
    font-weight: 600 !important; border-radius: 12px !important;
    padding: 0.65rem 1.5rem !important; font-size: 0.95rem !important;
    letter-spacing: 0.3px !important;
    transition: all 0.25s cubic-bezier(0.23,1,0.32,1) !important;
    box-shadow: 0 2px 8px rgba(255,90,0,0.20) !important;
}
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #E65000, #FF6A14) !important;
    box-shadow: 0 6px 20px rgba(255,90,0,0.30) !important;
    transform: translateY(-1px) !important;
}
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"]:active {
    transform: translateY(0) !important;
    box-shadow: 0 1px 4px rgba(255,90,0,0.20) !important;
}

/* ── Secondary buttons (main area) ── */
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-secondary"] {
    border: 1px solid #D1D5DB !important; border-radius: 12px !important;
    font-weight: 500 !important; background: #FFFFFF !important;
    color: #374151 !important; padding: 0.55rem 1.2rem !important;
    font-size: 0.92rem !important; transition: all 0.25s ease !important;
}
div[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-secondary"]:hover {
    border-color: #FF5A00 !important; color: #FF5A00 !important;
    background: #FFF7F2 !important;
}

/* ── Inputs ── */
div[data-testid="stTextInputRootElement"] {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important; transition: all 0.25s ease !important;
}
div[data-testid="stTextInputRootElement"]:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12), 0 1px 3px rgba(0,0,0,0.04) !important;
}
div[data-testid="stTextInputRootElement"]:hover:not(:focus-within) {
    border-color: #D1D5DB !important;
}
div[data-testid="stTextInput"] input {
    border: none !important; background: transparent !important;
    padding: 12px 16px !important; font-size: 0.95rem !important;
    font-weight: 400 !important; color: #111827 !important;
    outline: none !important; box-shadow: none !important;
}
div[data-testid="stTextInput"] input::placeholder { color: #9CA3AF !important; }

div[data-testid="stTextAreaRootElement"] {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important; transition: all 0.25s ease !important;
}
div[data-testid="stTextAreaRootElement"]:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12), 0 1px 3px rgba(0,0,0,0.04) !important;
}

div[data-testid="stTextInput"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stTextArea"] label,
div[data-testid="stCheckbox"] label {
    font-weight: 500 !important; color: #374151 !important;
    font-size: 0.875rem !important; letter-spacing: 0.01em !important;
}

/* ── Selectbox ── */
div[data-testid="stSelectbox"] > div > div {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important; transition: all 0.25s ease !important;
}
div[data-testid="stSelectbox"] > div > div:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12) !important;
}
div[data-testid="stSelectboxVirtualDropdown"] {
    border-radius: 12px !important; border: 1px solid #E5E7EB !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.10) !important;
}

/* ── Checkbox ── */
div[data-testid="stCheckbox"] label span {
    font-size: 0.85rem; color: #4B5563 !important;
}

/* ── Form card ── */
.form-card {
    background: white; border: 1px solid #E5E7EB;
    border-radius: 16px; padding: 32px; margin-top: 12px;
}

/* ── Section heading ── */
.section-heading {
    font-size: 1.75rem; font-weight: 700; color: #111827;
    margin-bottom: 2px; line-height: 1.25; letter-spacing: -0.02em;
}
.section-heading::after {
    content: ''; display: block; width: 40px; height: 3px;
    background: linear-gradient(90deg, #FF5A00, #FF7F32);
    margin-top: 10px; border-radius: 2px;
}
.section-subtitle {
    color: #6B7280; font-size: 0.9rem; font-weight: 400;
    margin-top: 6px; margin-bottom: 0; line-height: 1.6;
}

/* ── Connector sub-tabs (nested inside top-level) ── */
div[data-testid="stTabs"] div[data-testid="stTabs"] [role="tablist"] {
    gap: 4px; border-bottom: none; background: #FFF7F2;
    border-radius: 12px; padding: 4px; margin-bottom: 16px;
}
div[data-testid="stTabs"] div[data-testid="stTabs"] [role="tab"],
div[data-testid="stTabs"] div[data-testid="stTabs"] div[data-testid="stTab"] {
    padding: 8px 16px; font-weight: 500; font-size: 0.82rem;
    color: #6B7280; background: transparent; border: none;
    border-radius: 8px; transition: all 0.2s ease;
    border-bottom: none !important;
}
div[data-testid="stTabs"] div[data-testid="stTabs"] [aria-selected="true"],
div[data-testid="stTabs"] div[data-testid="stTabs"] div[data-testid="stTab"][aria-selected="true"] {
    color: #111827 !important; font-weight: 600 !important;
    background: #FFFFFF !important;
    border-bottom: none !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08) !important;
}
div[data-testid="stTabs"] div[data-testid="stTabs"] [role="tab"]:hover,
div[data-testid="stTabs"] div[data-testid="stTabs"] div[data-testid="stTab"]:hover {
    color: #374151 !important; background: rgba(255,255,255,0.6) !important;
}

/* ── Error / Alert ── */
div[data-testid="stAlert"] { border-radius: 10px !important; }

/* ── Expander — fix icon/text overlap ── */
div[data-testid="stExpander"] {
    border: 1px solid #E5E7EB !important;
    border-radius: 12px !important;
    overflow: hidden !important;
    margin-bottom: 12px !important;
}
div[data-testid="stExpander"] details > summary {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    padding: 12px 16px !important;
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: #374151 !important;
    cursor: pointer !important;
    white-space: normal !important;
    word-break: break-word !important;
    overflow: visible !important;
    position: relative !important;
    list-style: none !important;
}
div[data-testid="stExpander"] details > summary::-webkit-details-marker {
    display: none !important;
}
div[data-testid="stExpander"] details > summary > span {
    flex: 1 1 auto !important;
    min-width: 0 !important;
}
div[data-testid="stExpander"] summary svg,
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] svg {
    flex-shrink: 0 !important;
    width: 16px !important;
    height: 16px !important;
    min-width: 16px !important;
}
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-shrink: 0 !important;
    width: 20px !important;
    height: 20px !important;
    overflow: hidden !important;
    font-size: 0 !important;
    line-height: 0 !important;
}
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] svg {
    font-size: initial !important;
}
div[data-testid="stExpander"] [data-testid="stExpanderDetails"] {
    padding: 0 16px 16px 16px !important;
}

/* ── Hide Streamlit internal accessibility text that leaks visually ── */
div[data-testid="stExpander"] summary span[data-testid],
div[data-testid="stExpander"] summary .css-0,
div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] span {
    font-size: 0 !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    position: absolute !important;
    clip: rect(0, 0, 0, 0) !important;
    white-space: nowrap !important;
    border: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
}

/* ── File uploader — styling ── */
div[data-testid="stFileUploader"] > div > div {
    border-radius: 12px !important;
    border: 1px solid #E5E7EB !important;
    background: #FFFAF7 !important;
}
div[data-testid="stFileUploader"] button {
    border-radius: 10px !important;
    flex-shrink: 0 !important;
}

/* ── Generic flex/icon-text overlap prevention ── */
div[data-testid="stMarkdownContainer"] > div[style*="display:flex"],
div[data-testid="stMarkdownContainer"] > div[style*="display: flex"] {
    overflow: visible !important;
}
div[data-testid="stMarkdownContainer"] > div[style*="display:flex"] > *,
div[data-testid="stMarkdownContainer"] > div[style*="display: flex"] > * {
    position: relative !important;
}

/* ── Tab labels — prevent overlap on narrow screens ── */
div[data-testid="stTabs"] [role="tab"] {
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    min-width: 0 !important;
}

/* ── Selectbox / multi-select — prevent label overlap ── */
div[data-testid="stSelectbox"] label,
div[data-testid="stMultiSelect"] label {
    display: block !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}

/* ── Focus a11y ── */
*:focus-visible { outline: 2px solid #FF5A00 !important; outline-offset: 2px !important; }
</style>
"""

_HIDE_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] { display: none !important; width: 0 !important; min-width: 0 !important; }
button[data-testid="stSidebarCollapseButton"] { display: none !important; }
div[data-testid="stSidebarCollapsedControl"] { display: none !important; visibility: hidden !important; width: 0 !important; height: 0 !important; overflow: hidden !important; }
div[data-testid="stAppViewContainer"] { margin-left: 0 !important; }
[data-testid="stSidebarNav"] { display: none !important; }
</style>
"""

_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] {
    display: flex !important;
    background: linear-gradient(180deg, #FFF5EE 0%, #FFF0E6 30%, #FFFAF7 70%, #FFFFFF 100%) !important;
    border-right: 1px solid #FDDCCA !important;
    min-width: 270px !important;
    max-width: 270px !important;
}
section[data-testid="stSidebar"] > div {
    background: transparent !important;
    padding-top: 0 !important;
}
section[data-testid="stSidebar"] .block-container {
    padding: 0 !important;
}

/* collapse button (X inside sidebar) */
button[data-testid="stSidebarCollapseButton"] { color: #FF5A00 !important; }
button[data-testid="stSidebarCollapseButton"]:hover { color: #E65000 !important; }

/* expand button (arrow when sidebar is collapsed) */
div[data-testid="stSidebarCollapsedControl"] {
    display: flex !important;
    position: fixed !important;
    top: 12px !important;
    left: 12px !important;
    z-index: 999999 !important;
}
div[data-testid="stSidebarCollapsedControl"] button {
    background: #111827 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 10px !important;
    width: 40px !important;
    height: 40px !important;
    box-shadow: 0 3px 12px rgba(0,0,0,0.30) !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
}
div[data-testid="stSidebarCollapsedControl"] button:hover {
    background: #000000 !important;
    box-shadow: 0 5px 16px rgba(0,0,0,0.40) !important;
    transform: scale(1.05) !important;
}
div[data-testid="stSidebarCollapsedControl"] button svg {
    color: #FFFFFF !important;
}

section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown p {
    color: #374151 !important;
}

/* nav buttons - inactive */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    background: transparent !important;
    border: 1px solid transparent !important;
    color: #4B5563 !important;
    border-radius: 10px !important;
    padding: 10px 14px !important;
    font-size: 0.88rem !important;
    font-weight: 500 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    transition: all 0.2s ease !important;
}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover {
    background: rgba(255,90,0,0.06) !important;
    border: 1px solid rgba(255,90,0,0.12) !important;
    color: #FF5A00 !important;
}

/* nav buttons - active */
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, #FF5A00, #FF7F32) !important;
    border: none !important;
    color: #FFFFFF !important;
    border-radius: 10px !important;
    padding: 10px 14px !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
    text-align: left !important;
    justify-content: flex-start !important;
    box-shadow: 0 4px 14px rgba(255,90,0,0.25) !important;
}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #E65000, #FF6A14) !important;
    box-shadow: 0 6px 18px rgba(255,90,0,0.35) !important;
}
</style>
"""


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _set_page(target):
    st.session_state["page"] = target


def _section_label(text):
    st.markdown(
        f'<div style="padding:14px 16px 5px 16px;">'
        f'<span style="font-size:0.65rem; font-weight:700; color:#C4A882; '
        f'text-transform:uppercase; letter-spacing:0.1em;">{text}</span></div>',
        unsafe_allow_html=True,
    )


def _nav_btn(label, target, current_page):
    btn_type = "primary" if current_page == target else "secondary"
    st.button(label, key=f"nav_{target}", use_container_width=True, type=btn_type,
              on_click=_set_page, args=(target,))


# ══════════════════════════════════════════════════════════════
#  SIDEBAR  (only Data Sources for now)
# ══════════════════════════════════════════════════════════════

def _render_sidebar():
    user = st.session_state.get("full_name", st.session_state.get("user", ""))
    role = st.session_state.get("role", "")
    page = st.session_state.get("page", "datasources")

    with st.sidebar:
        # ── Brand ──
        st.markdown(
            """<div style="padding:22px 16px 18px 16px; border-bottom:1px solid #FDDCCA;">
                <div style="display:flex; align-items:center; gap:11px;">
                    <div style="width:38px; height:38px; background:linear-gradient(135deg,#FF5A00,#FF7F32);
                                border-radius:10px; display:flex; align-items:center; justify-content:center;
                                font-size:1.15rem; color:white; font-weight:800;
                                box-shadow:0 3px 10px rgba(255,90,0,0.25);">E</div>
                    <div>
                        <div style="font-size:1.05rem; font-weight:700; color:#111827; line-height:1.2;">
                            ESG Data Platform</div>
                        <div style="font-size:0.68rem; color:#9CA3AF; font-weight:500;
                                    letter-spacing:0.06em; text-transform:uppercase;">
                            AI Document Intelligence</div>
                    </div>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── User card ──
        role_colors = {"Admin": "#FF5A00", "Manager": "#8b5cf6", "Analyst": "#3b82f6", "Viewer": "#6b7280"}
        rc = role_colors.get(role, "#6b7280")
        initial = user[0].upper() if user else "U"
        st.markdown(
            f"""<div style="padding:12px 14px; margin:14px 12px 6px 12px; background:white;
                            border-radius:12px; border:1px solid #F3E8E0;
                            box-shadow:0 1px 4px rgba(255,90,0,0.06);">
                <div style="display:flex; align-items:center; gap:10px;">
                    <div style="width:36px; height:36px; background:linear-gradient(135deg,#FFF0E6,#FDDCCA);
                                border-radius:50%; display:flex; align-items:center; justify-content:center;
                                font-size:0.85rem; font-weight:700; color:#FF5A00;
                                border:2px solid #FFE4D0;">{initial}</div>
                    <div style="flex:1; min-width:0;">
                        <div style="font-size:0.85rem; font-weight:600; color:#111827; white-space:nowrap;
                                    overflow:hidden; text-overflow:ellipsis;">{user}</div>
                        <div style="font-size:0.7rem; color:{rc}; font-weight:600;">{role}</div>
                    </div>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── Navigation ──
        _section_label("Navigation")
        _nav_btn("🏠  Home", "home", page)
        _nav_btn("🔗  Data Sources", "datasources", page)
        _nav_btn("🤖  Registration Agent", "registration_agent", page)
        _nav_btn("📊  Metric Analysis", "metric_analysis", page)
        _nav_btn("📋  Regulatory Tracker", "compliance_agent", page)
        _nav_btn("📈  Benchmarking", "benchmarking", page)
        _nav_btn("⚡  Risk & Opportunity", "risk_opportunity", page)
        _nav_btn("🔍  Review & Report", "review_governance", page)

        # ── Help ──
        _section_label("Help")
        st.markdown(
            '<div style="padding:4px 14px 10px 14px;">'
            '<div style="font-size:0.78rem; color:#6B7280; line-height:1.6;">'
            '<b style="color:#374151;">Need help?</b> Click the '
            '<span style="color:#FF5A00;">expandable tips</span> '
            'on each page for step-by-step guidance.</div></div>',
            unsafe_allow_html=True,
        )

        # ── Logout ──
        st.markdown(
            '<div style="margin-top:16px; border-top:1px solid #FDDCCA; margin-left:12px; margin-right:12px;"></div>',
            unsafe_allow_html=True,
        )

        def _do_logout():
            logout_user()
            st.session_state["page"] = "login"

        st.button("🚪  Logout", key="nav_logout", use_container_width=True, on_click=_do_logout)

        st.markdown(
            '<div style="padding:10px 16px; text-align:center;">'
            '<span style="font-size:0.65rem; color:#D1D5DB;">v2.0 · PwC ESG Platform</span></div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    if "page" not in st.session_state:
        st.session_state["page"] = "login"

    if not is_logged_in():
        st.session_state["page"] = "login"

    st.markdown(_BASE_CSS, unsafe_allow_html=True)

    page = st.session_state["page"]

    if page == "login":
        st.markdown(_HIDE_SIDEBAR_CSS, unsafe_allow_html=True)
        login.render()
    else:
        st.markdown(_SIDEBAR_CSS, unsafe_allow_html=True)
        _render_sidebar()
        if page == "registration_agent":
            registration_agent.render()
        elif page == "metric_analysis":
            metric_analysis_agent.render()
        elif page == "compliance_agent":
            compliance_agent.render()
        elif page == "benchmarking":
            benchmarking_agent.render()
        elif page == "risk_opportunity":
            risk_opportunity_agent.render()
        elif page == "review_governance":
            review_governance_agent.render()
        elif page == "datasources":
            datasources.render()
        else:
            home.render()


if __name__ == "__main__":
    main()
