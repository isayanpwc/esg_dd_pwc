import streamlit as st
from datetime import datetime
from utils.auth import login_user
from utils.security import hash_password, validate_email, validate_password_strength, sanitize_input
from utils.json_manager import username_exists, email_exists, save_user, add_audit_log


_BG_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ─────────────────────────────────────────────────
   PREMIUM LOGIN BACKGROUND
   ───────────────────────────────────────────────── */
.stApp {
    background: linear-gradient(
        165deg,
        #FFDCC4 0%,
        #FFE4D0 6%,
        #FFEDD9 12%,
        #FFF3E8 20%,
        #FFF8F2 30%,
        #FFFBF8 42%,
        #FEFEFE 58%,
        #FAFAFA 100%
    ) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}

.stApp::before {
    content: '';
    position: fixed;
    inset: 0;
    background:
        radial-gradient(ellipse 80% 70% at 10% 0%, rgba(255,130,50,0.16) 0%, transparent 65%),
        radial-gradient(ellipse 60% 60% at 90% 5%, rgba(255,90,0,0.10) 0%, transparent 55%),
        radial-gradient(ellipse 120% 50% at 50% 0%, rgba(255,180,120,0.12) 0%, transparent 50%),
        radial-gradient(ellipse 40% 40% at 75% 85%, rgba(255,160,80,0.05) 0%, transparent 60%),
        radial-gradient(ellipse 50% 50% at 20% 90%, rgba(255,140,60,0.04) 0%, transparent 60%);
    pointer-events: none;
    z-index: 0;
}

/* ── Card entry animation ── */
@keyframes loginFadeIn {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
}

.block-container,
div[data-testid="stMainBlockContainer"] {
    animation: loginFadeIn 0.6s cubic-bezier(0.23,1,0.32,1) both !important;
    max-width: 1100px !important;
    padding-top: 40px !important;
}

/* ─────────────────────────────────────────────────
   PREMIUM FLOATING CARD  (st.container(border=True))
   Target the vertical block that has a visible border
   ───────────────────────────────────────────────── */
div[data-testid="stVerticalBlock"] > div > div[data-testid="stVerticalBlock"] {
    background: rgba(255,255,255,0.92) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    border-radius: 20px !important;
    border: 1px solid rgba(255,90,0,0.10) !important;
    box-shadow:
        0 8px 30px rgba(0,0,0,0.06),
        0 20px 60px rgba(255,90,0,0.08) !important;
    padding: 24px 28px !important;
    transition: box-shadow 0.3s ease !important;
}

/* ─────────────────────────────────────────────────
   TABS → SEGMENTED PILL CONTROLS
   Streamlit 1.59 uses React Aria: [role="tablist"],
   [role="tab"], div[data-testid="stTab"]
   ───────────────────────────────────────────────── */
div[data-testid="stTabs"] [role="tablist"] {
    background: #F3F4F6 !important;
    border-radius: 12px !important;
    padding: 4px !important;
    border-bottom: none !important;
    gap: 4px !important;
    display: inline-flex !important;
    width: auto !important;
}

div[data-testid="stTabs"] [role="tab"],
div[data-testid="stTab"] {
    background: transparent !important;
    border-radius: 10px !important;
    padding: 10px 28px !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
    color: #6B7280 !important;
    border: none !important;
    border-bottom: none !important;
    transition: all 0.25s cubic-bezier(0.23,1,0.32,1) !important;
    letter-spacing: 0.01em !important;
    min-height: unset !important;
    line-height: 1.4 !important;
    cursor: pointer !important;
    text-decoration: none !important;
}

div[data-testid="stTabs"] [role="tab"]:hover,
div[data-testid="stTab"]:hover {
    color: #374151 !important;
    background: rgba(0,0,0,0.04) !important;
}

div[data-testid="stTabs"] [aria-selected="true"],
div[data-testid="stTab"][aria-selected="true"] {
    background: #FF5A00 !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 8px rgba(255,90,0,0.30) !important;
    border-bottom: none !important;
}

/* Hide any underline/highlight elements the tab system renders */
div[data-testid="stTabs"] [role="tablist"]::after,
div[data-testid="stTabs"] [role="tablist"]::before {
    display: none !important;
}

/* ── Section headings ── */
.section-heading {
    font-family: 'Inter', sans-serif !important;
    font-size: 1.75rem !important;
    font-weight: 700 !important;
    color: #111827 !important;
    line-height: 1.25 !important;
    letter-spacing: -0.02em !important;
    margin-bottom: 4px !important;
}
.section-heading::after {
    content: '';
    display: block;
    width: 40px;
    height: 3px;
    background: linear-gradient(90deg, #FF5A00, #FF7F32);
    margin-top: 10px;
    border-radius: 2px;
}
.section-subtitle {
    font-family: 'Inter', sans-serif !important;
    color: #6B7280 !important;
    font-size: 0.9rem !important;
    font-weight: 400 !important;
    line-height: 1.6 !important;
    margin-top: 8px !important;
}

/* ─────────────────────────────────────────────────
   INPUT FIELDS
   Root container: div[data-testid="stTextInputRootElement"]
   Actual input:   .stTextInput input
   ───────────────────────────────────────────────── */
div[data-testid="stTextInputRootElement"] {
    border-radius: 12px !important;
    border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important;
    transition: all 0.25s ease !important;
    overflow: hidden !important;
}
div[data-testid="stTextInputRootElement"]:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12), 0 1px 3px rgba(0,0,0,0.04) !important;
}
div[data-testid="stTextInputRootElement"]:hover:not(:focus-within) {
    border-color: #D1D5DB !important;
}

div[data-testid="stTextInput"] input {
    height: 50px !important;
    border: none !important;
    background: transparent !important;
    padding: 12px 16px !important;
    font-size: 0.95rem !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 400 !important;
    color: #111827 !important;
    box-sizing: border-box !important;
    outline: none !important;
    box-shadow: none !important;
}
div[data-testid="stTextInput"] input::placeholder {
    color: #9CA3AF !important;
    font-weight: 400 !important;
}

/* ── Labels ── */
div[data-testid="stTextInput"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stCheckbox"] label {
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.875rem !important;
    color: #374151 !important;
    letter-spacing: 0.01em !important;
    margin-bottom: 6px !important;
}

/* ─────────────────────────────────────────────────
   SELECTBOX / DROPDOWN
   ───────────────────────────────────────────────── */
div[data-testid="stSelectbox"] > div > div {
    border-radius: 12px !important;
    border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important;
    min-height: 50px !important;
    font-size: 0.95rem !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.25s ease !important;
}
div[data-testid="stSelectbox"] > div > div:hover {
    border-color: #D1D5DB !important;
}
div[data-testid="stSelectbox"] > div > div:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12) !important;
}
div[data-testid="stSelectbox"] input {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
    color: #111827 !important;
}
div[data-testid="stSelectbox"] svg {
    transition: transform 0.25s ease !important;
    color: #6B7280 !important;
}

/* ── Dropdown popover ── */
div[data-testid="stSelectboxVirtualDropdown"] {
    border-radius: 12px !important;
    border: 1px solid #E5E7EB !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.10) !important;
    overflow: hidden !important;
}

/* ─────────────────────────────────────────────────
   PRIMARY CTA BUTTON
   ───────────────────────────────────────────────── */
button[data-testid="stBaseButton-primary"] {
    height: 52px !important;
    border-radius: 12px !important;
    background: linear-gradient(135deg, #FF5A00, #FF7F32) !important;
    border: none !important;
    color: #FFFFFF !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
    letter-spacing: 0.3px !important;
    transition: all 0.25s cubic-bezier(0.23,1,0.32,1) !important;
    box-shadow: 0 2px 8px rgba(255,90,0,0.25) !important;
    cursor: pointer !important;
}
button[data-testid="stBaseButton-primary"]:hover {
    background: linear-gradient(135deg, #E65000, #FF6A14) !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(255,90,0,0.35), 0 2px 6px rgba(0,0,0,0.08) !important;
}
button[data-testid="stBaseButton-primary"]:active {
    transform: translateY(0px) !important;
    box-shadow: 0 1px 4px rgba(255,90,0,0.20) !important;
}

/* ─────────────────────────────────────────────────
   CHECKBOX
   ───────────────────────────────────────────────── */
div[data-testid="stCheckbox"] label {
    font-size: 0.85rem !important;
    color: #4B5563 !important;
    line-height: 1.5 !important;
}
div[data-testid="stCheckbox"] label > div:first-child {
    border-radius: 5px !important;
    border: 1.5px solid #D1D5DB !important;
    transition: all 0.2s ease !important;
}

/* ── Error messages ── */
div[data-testid="stAlert"] {
    border-radius: 12px !important;
}

/* ── Help tooltips ── */
div[data-testid="stTooltipIcon"],
[data-testid="stTooltipIcon"] {
    color: #9CA3AF !important;
    transition: color 0.2s ease !important;
}
[data-testid="stTooltipIcon"]:hover {
    color: #FF5A00 !important;
}

/* ── Password toggle icon ── */
div[data-testid="stTextInput"] button {
    color: #6B7280 !important;
    transition: color 0.2s ease !important;
}
div[data-testid="stTextInput"] button:hover {
    color: #FF5A00 !important;
}

/* ── Text area root (for consistency) ── */
div[data-testid="stTextAreaRootElement"] {
    border-radius: 12px !important;
    border: 1px solid #E5E7EB !important;
    background: #FFFFFF !important;
    transition: all 0.25s ease !important;
}
div[data-testid="stTextAreaRootElement"]:focus-within {
    border-color: #FF5A00 !important;
    box-shadow: 0 0 0 3px rgba(255,90,0,0.12) !important;
}

/* ── Widget labels (global) ── */
span[data-testid="stWidgetLabel"] {
    font-family: 'Inter', sans-serif !important;
}
</style>
"""


def render():
    st.markdown(_BG_CSS, unsafe_allow_html=True)

    col_left, col_center, col_right = st.columns([1.2, 2, 1.2])

    with col_center:
        tab_signin, tab_create = st.tabs(["Sign in", "Create account"])

        with tab_signin:
            _render_sign_in()

        with tab_create:
            _render_create_account()


def _render_sign_in():
    st.markdown("")

    col_title, col_desc = st.columns([1, 1.5])
    with col_title:
        st.markdown(
            '<div class="section-heading">Welcome back</div>',
            unsafe_allow_html=True,
        )
    with col_desc:
        st.markdown(
            '<p class="section-subtitle" style="margin-top:8px;">'
            'Sign in with your username or email to resume your ESG pipeline.</p>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    with st.container(border=True):
        identifier = st.text_input(
            "Username or email",
            key="login_id",
            placeholder="jane.doe  or  jane@example.com",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="login_pw",
            placeholder="",
        )

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        if st.button("Sign in", key="btn_signin", use_container_width=True, type="primary"):
            identifier = sanitize_input(identifier)
            if not identifier or not password:
                st.error("Please fill in all fields.")
                return
            if login_user(identifier, password):
                st.session_state["page"] = "home"
                st.rerun()
            else:
                st.error("Invalid credentials.")


def _render_create_account():
    st.markdown("")

    col_title, col_desc = st.columns([1, 1.5])
    with col_title:
        st.markdown(
            '<div class="section-heading">Create your<br>account</div>',
            unsafe_allow_html=True,
        )
    with col_desc:
        st.markdown(
            '<p class="section-subtitle" style="margin-top:8px;">'
            'Self-serve signup. Your account is stored in a private, persistent registry.</p>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    with st.container(border=True):
        col_name, col_email = st.columns(2)
        with col_name:
            full_name = st.text_input("Full name", key="reg_name", placeholder="Jane Doe")
        with col_email:
            email = st.text_input("Work email", key="reg_email", placeholder="jane@example.com")

        col_user, col_role = st.columns(2)
        with col_user:
            username = st.text_input("Username", key="reg_user", placeholder="jane.doe",
                                     help="Must be unique across all accounts")
        with col_role:
            role = st.selectbox("Role", ["viewer", "analyst", "manager", "admin"], key="reg_role",
                                help="Determines your access level")

        password = st.text_input("Password", type="password", key="reg_pw", placeholder="",
                                 help="Min 8 chars, uppercase, lowercase, digit, special char")
        confirm = st.text_input("Confirm password", type="password", key="reg_pw2", placeholder="")

        st.markdown("<div style='height:2px'></div>", unsafe_allow_html=True)

        terms = st.checkbox(
            "I understand my credentials are stored securely and can be deleted on request.",
            key="reg_terms",
        )

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        if st.button("Create account", key="btn_create", use_container_width=True, type="primary"):
            full_name = sanitize_input(full_name)
            email = sanitize_input(email)
            username = sanitize_input(username)

            if not all([full_name, email, username, password, confirm]):
                st.error("Please fill in all fields.")
                return

            if not validate_email(email):
                st.error("Please enter a valid email address.")
                return

            if email_exists(email.lower()):
                st.error("An account with this email already exists.")
                return

            if username_exists(username):
                st.error("Username already exists. Please select another username.")
                return

            valid, msg = validate_password_strength(password)
            if not valid:
                st.error(msg)
                return

            if password != confirm:
                st.error("Passwords do not match.")
                return

            if not terms:
                st.error("You must agree to the Terms & Conditions.")
                return

            display_role = role.capitalize()
            user_data = {
                "full_name": full_name,
                "email": email.lower(),
                "username": username,
                "role": display_role,
                "password_hash": hash_password(password),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_user(user_data)
            add_audit_log(username, "User Registered")

            st.session_state["logged_in"] = True
            st.session_state["user"] = username
            st.session_state["role"] = display_role
            st.session_state["full_name"] = full_name
            st.session_state["page"] = "home"
            st.rerun()
