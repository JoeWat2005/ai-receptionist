"""Reusable Streamlit UI components and styling."""

from __future__ import annotations

import html
from typing import Any

import streamlit as st


def user_display_name(auth_user: dict[str, Any], guest_mode: bool) -> str:
    """Return display name without showing raw fallback ids."""
    if guest_mode:
        return "Guest"
    name = str(auth_user.get("full_name") or "").strip()
    if name:
        return name
    email = str(auth_user.get("email") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return "Member"


def role_label(access_role: str) -> str:
    """Return a human-readable role label."""
    mapping = {
        "staff": "Staff",
        "customer": "Customer",
        "guest": "Guest",
    }
    return mapping.get(access_role, access_role.title() or "Guest")


def apply_app_styles() -> None:
    """Apply polished MVP styles and avoid icon-font collisions in sidebar."""
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Manrope:wght@400;500;600;700&display=swap');

:root {
  --ink: #18233f;
  --muted: #58617b;
  --line: #dfe5f4;
  --panel: #ffffff;
  --bg: #f4f6fc;
  --brand-a: #1d4ed8;
  --brand-b: #0f766e;
}

html, body, [class*="css"] {
  font-family: 'Manrope', sans-serif;
}

h1, h2, h3, h4 {
  font-family: 'Space Grotesk', sans-serif !important;
  color: var(--ink);
}

.stApp {
  background:
    radial-gradient(1200px 500px at -15% -15%, #dbeafe 0%, transparent 60%),
    radial-gradient(800px 400px at 115% -20%, #ccfbf1 0%, transparent 58%),
    var(--bg);
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #f9fbff 0%, #eef3ff 100%);
  border-right: 1px solid var(--line);
}

/* Keep Material icon glyphs intact. */
.material-icons,
.material-symbols-rounded,
[data-testid="stSidebarCollapseButton"] span,
span[class*="material-symbols"] {
  font-family: 'Material Symbols Rounded', 'Material Icons' !important;
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
  border: 1px solid #d4ddf2;
}

.hero {
  background: linear-gradient(120deg, var(--brand-a) 0%, var(--brand-b) 100%);
  border-radius: 18px;
  padding: 22px 24px;
  color: #f8fbff;
  margin-bottom: 12px;
  box-shadow: 0 12px 24px rgba(20, 32, 61, 0.2);
}

.hero h1 {
  margin: 0 0 5px 0;
  color: #f8fbff !important;
}

.hero-sub {
  margin: 0;
  color: #e8f1ff;
}

.pills {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.pill {
  display: inline-block;
  border-radius: 999px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.16);
  color: #f8fbff;
  font-size: 0.82rem;
}

.account-chip {
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 12px;
  padding: 10px 12px;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_hero_header(clinic: dict[str, Any], auth_user: dict[str, Any], access_role: str, guest_mode: bool) -> None:
    """Render top branded hero with clinic and active role summary."""
    user_name = user_display_name(auth_user, guest_mode)
    st.markdown(
        f"""
<div class="hero">
  <h1>{html.escape(str(clinic['name']))} - AI Receptionist</h1>
  <p class="hero-sub">Conversational booking assistant with persistent scheduling and records.</p>
  <div class="pills">
    <span class="pill">{html.escape(str(clinic['location']))}</span>
    <span class="pill">{html.escape(str(clinic.get('opening_hours_text', '')))}</span>
    <span class="pill">Role: {html.escape(role_label(access_role))}</span>
    <span class="pill">Signed in: {html.escape(user_name)}</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_account_panel(
    auth_user: dict[str, Any],
    access_role: str,
    guest_mode: bool,
    member_bonus_active: bool,
    redirect_uri: str,
) -> None:
    """Render click-to-open account panel in sidebar."""
    with st.sidebar.expander("\N{BUST IN SILHOUETTE} Account", expanded=True):
        st.markdown(f"**Role:** {role_label(access_role)}")
        st.markdown(f"**Name:** {user_display_name(auth_user, guest_mode)}")
        email = str(auth_user.get("email") or "").strip() or "No account email"
        st.markdown(f"**Email:** {email}")
        user_id = str(auth_user.get("user_id") or "").strip()
        if user_id:
            st.caption(f"User ID: {user_id}")
        if member_bonus_active:
            st.success("Member bonus active")
        elif guest_mode:
            st.info("Guest mode")
        st.caption(f"OAuth redirect URI: {redirect_uri}")


def render_chat_mode_hint(member_bonus_active: bool, guest_mode: bool) -> None:
    """Render concise chat status indicator."""
    if guest_mode:
        st.info("Guest booking is enabled. Sign in to unlock member bonus: autofill + priority follow-up.")
    elif member_bonus_active:
        st.success("Signed in member mode: profile autofill and priority pending-request follow-up are active.")
