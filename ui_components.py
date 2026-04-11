"""Reusable Streamlit UI components for styling and profile presentation."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st


def _role_label(auth_user: dict[str, Any], admin_mode: bool, guest_mode: bool) -> str:
    """Return display role label for current user."""
    if admin_mode:
        return "Admin"
    if guest_mode or str(auth_user.get("role", "")).strip().lower() == "guest":
        return "Guest"
    return "Member"


def _user_name(auth_user: dict[str, Any], guest_mode: bool) -> str:
    """Return display name for current user."""
    if guest_mode:
        return "Guest"
    return str(auth_user.get("full_name") or auth_user.get("email") or "Signed-in user")


def apply_app_styles() -> None:
    """Apply cleaner visual styling for a demo-ready MVP."""
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Sans:wght@400;500;700&display=swap');

:root {
  --bg: #f5f7fb;
  --panel: #ffffff;
  --ink: #1e2547;
  --muted: #5c6384;
  --line: #e4e8f3;
}

.stApp {
  background:
    radial-gradient(1100px 500px at -10% -20%, #dbeafe 0%, transparent 60%),
    radial-gradient(900px 450px at 110% -25%, #ccfbf1 0%, transparent 55%),
    var(--bg);
}

h1, h2, h3, h4 {
  font-family: 'Space Grotesk', sans-serif !important;
  color: var(--ink);
}

div, p, span, label, input, textarea, button {
  font-family: 'DM Sans', sans-serif !important;
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #f9fbff 0%, #f3f6ff 100%);
  border-right: 1px solid var(--line);
}

[data-testid="stMetric"] {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 8px 12px;
}

[data-testid="stDataFrame"], .stTabs [data-baseweb="tab-panel"] {
  background: var(--panel);
  border-radius: 14px;
}

div.stButton > button {
  border-radius: 12px;
  border: 1px solid #d7ddf0;
}

.hero {
  background: linear-gradient(120deg, #1e40af 0%, #0f766e 100%);
  border-radius: 18px;
  padding: 22px 24px;
  color: #f8fbff;
  margin-bottom: 10px;
  box-shadow: 0 10px 24px rgba(31, 41, 55, 0.18);
}

.hero h1 {
  color: #f8fbff !important;
  margin: 0 0 4px 0;
}

.hero-sub {
  color: #e6eefc;
  margin: 0;
}

.pill-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.pill {
  display: inline-block;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  color: #f8fbff;
  font-size: 0.82rem;
}

.profile-card {
  border: 1px solid #d9e2f2;
  border-radius: 14px;
  background: #ffffff;
  padding: 12px 14px;
  margin-bottom: 10px;
}

.profile-name {
  font-weight: 700;
  color: #1e2547;
}

.profile-meta {
  font-size: 0.9rem;
  color: #5c6384;
}

.badge {
  display: inline-block;
  margin-top: 8px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
}

.badge-admin {
  background: #dbeafe;
  color: #1d4ed8;
}

.badge-member {
  background: #dcfce7;
  color: #166534;
}

.badge-guest {
  background: #f3f4f6;
  color: #374151;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_header(clinic: dict[str, Any], auth_user: dict[str, Any], admin_mode: bool, guest_mode: bool) -> None:
    """Render top branded hero with clinic and user context."""
    role_label = _role_label(auth_user, admin_mode, guest_mode)
    user_name = _user_name(auth_user, guest_mode)
    st.markdown(
        f"""
<div class="hero">
  <h1>{html.escape(str(clinic["name"]))} - AI Receptionist</h1>
  <p class="hero-sub">Conversational booking assistant with live availability and persistent records.</p>
  <div class="pill-row">
    <span class="pill">{html.escape(str(clinic["location"]))}</span>
    <span class="pill">{html.escape(str(clinic.get("opening_hours_text", "")))}</span>
    <span class="pill">Slot length: {int(clinic.get("slot_length_minutes", 30))} mins</span>
    <span class="pill">Signed in: {html.escape(user_name)} ({role_label})</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_profile_card(auth_user: dict[str, Any], admin_mode: bool, guest_mode: bool, member_bonus_active: bool) -> None:
    """Render clear signed-in profile card in main content area."""
    role_label = _role_label(auth_user, admin_mode, guest_mode)
    badge_class = "badge-admin" if admin_mode else ("badge-member" if member_bonus_active else "badge-guest")
    user_name = _user_name(auth_user, guest_mode)
    email = str(auth_user.get("email", "")).strip() or "No account email"
    user_id = str(auth_user.get("user_id", "")).strip() or "-"

    st.markdown(
        f"""
<div class="profile-card">
  <div class="profile-name">{html.escape(user_name)}</div>
  <div class="profile-meta">{html.escape(email)}</div>
  <div class="profile-meta">User ID: {html.escape(user_id)}</div>
  <span class="badge {badge_class}">{role_label}</span>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_auth_hint(member_bonus_active: bool, guest_mode: bool) -> None:
    """Render concise chat mode status banner."""
    if guest_mode:
        st.info("Guest booking is enabled. Sign in to unlock member bonus: autofill + priority follow-up.")
    elif member_bonus_active:
        st.success("Signed in. Member bonus active: your profile details help speed up booking.")


def render_sidebar_account_summary(
    auth_user: dict[str, Any],
    admin_mode: bool,
    guest_mode: bool,
    member_bonus_active: bool,
    redirect_uri: str,
) -> None:
    """Render concise account status block in sidebar."""
    role = _role_label(auth_user, admin_mode, guest_mode)
    name = _user_name(auth_user, guest_mode)
    email = str(auth_user.get("email", "")).strip() or "No account email"

    st.sidebar.markdown("### Account")
    st.sidebar.markdown(f"**Name:** {name}")
    st.sidebar.markdown(f"**Email:** {email}")
    st.sidebar.markdown(f"**Role:** {role}")
    if member_bonus_active:
        st.sidebar.success("Member bonus active")
    elif guest_mode:
        st.sidebar.info("Guest mode")
    st.sidebar.caption(f"OAuth redirect URI: {redirect_uri}")
