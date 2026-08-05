import streamlit as st
from utils.json_manager import find_user, add_audit_log
from utils.security import verify_password


def login_user(identifier, password):
    user = find_user(identifier)
    if user and verify_password(password, user["password_hash"]):
        st.session_state["logged_in"] = True
        st.session_state["user"] = user["username"]
        st.session_state["role"] = user["role"]
        st.session_state["full_name"] = user["full_name"]
        add_audit_log(user["username"], "User Logged In")
        return True
    return False


def logout_user():
    if "user" in st.session_state:
        add_audit_log(st.session_state["user"], "Logout")
    for key in ["logged_in", "user", "role", "full_name"]:
        st.session_state.pop(key, None)


def is_logged_in():
    return st.session_state.get("logged_in", False)


def get_current_user():
    return st.session_state.get("user", None)


def get_current_role():
    return st.session_state.get("role", None)


def is_admin():
    return get_current_role() == "Admin"


def require_admin():
    if not is_admin():
        st.error("Access Denied — this section requires Admin privileges.")
        return False
    return True
