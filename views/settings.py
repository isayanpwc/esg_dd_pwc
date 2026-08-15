"""
Settings — platform configuration page.
"""

import streamlit as st
from utils.auth import get_current_user, is_admin


def render():
    st.markdown(
        '<div style="margin-bottom:24px;">'
        '<h2 class="section-heading" style="font-size:1.55rem;">Settings</h2>'
        '<p class="section-subtitle">Platform configuration and preferences.</p></div>',
        unsafe_allow_html=True,
    )

    user = get_current_user()
    role = st.session_state.get("role", "")
    full_name = st.session_state.get("full_name", user)

    # ── Profile section ──
    st.markdown(
        '<div style="background:white;border:1px solid #E5E7EB;border-radius:16px;'
        'padding:28px;margin-bottom:20px;">'
        '<div style="font-size:1rem;font-weight:700;color:#111827;margin-bottom:16px;">'
        'Profile</div>',
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Full Name", value=full_name, disabled=True, key="settings_name")
    with c2:
        st.text_input("Role", value=role, disabled=True, key="settings_role")

    st.text_input("Username", value=user, disabled=True, key="settings_user")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── Platform section ──
    st.markdown(
        '<div style="background:white;border:1px solid #E5E7EB;border-radius:16px;'
        'padding:28px;margin-bottom:20px;">'
        '<div style="font-size:1rem;font-weight:700;color:#111827;margin-bottom:16px;">'
        'Platform Configuration</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="display:flex;align-items:center;gap:12px;padding:14px 0;'
        'border-bottom:1px solid #F3F4F6;">'
        '<div style="flex:1;">'
        '<div style="font-size:0.9rem;font-weight:600;color:#111827;">Pipeline Auto-Run</div>'
        '<div style="font-size:0.8rem;color:#6B7280;margin-top:2px;">'
        'Automatically run the full pipeline when new data sources are connected.</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    st.toggle("Enable auto-run", value=False, key="settings_autorun")

    st.markdown(
        '<div style="display:flex;align-items:center;gap:12px;padding:14px 0;'
        'border-bottom:1px solid #F3F4F6;">'
        '<div style="flex:1;">'
        '<div style="font-size:0.9rem;font-weight:600;color:#111827;">Notifications</div>'
        '<div style="font-size:0.8rem;color:#6B7280;margin-top:2px;">'
        'Receive in-app notifications for compliance alerts and pipeline completions.</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    st.toggle("Enable notifications", value=True, key="settings_notifs")

    st.markdown('</div>', unsafe_allow_html=True)

    if is_admin():
        st.markdown(
            '<div style="background:white;border:1px solid #E5E7EB;border-radius:16px;'
            'padding:28px;">'
            '<div style="font-size:1rem;font-weight:700;color:#111827;margin-bottom:16px;">'
            'Administration</div>'
            '<div style="font-size:0.88rem;color:#6B7280;line-height:1.6;">'
            'User management, audit log access, and system configuration '
            'are available to administrators.</div></div>',
            unsafe_allow_html=True,
        )
