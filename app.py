"""Main Streamlit entrypoint for modular AI receptionist MVP."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import db
from clinic_data import DEFAULT_CLINIC
from frontend.auth_sidebar import AuthSession, render_auth_sidebar
from frontend.chat_page import render_chat_tab
from frontend.components import apply_app_styles, render_hero_header
from frontend.staff_pages import (
    render_bookings_tab,
    render_calendar_tab,
    render_conversations_tab,
    render_dashboard_tab,
    render_leads_tab,
    render_staff_overview,
)

WELCOME_TEMPLATE = "Hi, welcome to {clinic_name}. How can I help today?"


def _toml_escape(value: str) -> str:
    """Escape string for safe TOML double-quoted value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_placeholder_value(value: str) -> bool:
    """Heuristic check for template/example placeholder values."""
    lowered = value.strip().lower()
    if not lowered:
        return True
    placeholders = [
        "your-clerk-domain",
        "replace_with_",
        "xxxxxxxx",
        "pk_test_xxxxxxxxx",
        "sk_test_xxxxxxxxx",
    ]
    return any(token in lowered for token in placeholders)


def _build_streamlit_secrets_from_env() -> str:
    """
    Build Streamlit OIDC secrets TOML from environment variables.

    Required:
      - CLERK_CLIENT_ID (or NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)
      - CLERK_CLIENT_SECRET (or CLERK_SECRET_KEY)
      - CLERK_SERVER_METADATA_URL (or CLERK_FRONTEND_API_URL)
      - STREAMLIT_COOKIE_SECRET
    Optional:
      - STREAMLIT_REDIRECT_URI (default localhost callback)
      - CLERK_OIDC_PROMPT (default login)
      - CLERK_OIDC_SCOPE (default openid profile email)
    """
    client_id = (
        os.getenv("CLERK_CLIENT_ID", "").strip()
        or os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "").strip()
    )
    client_secret = (
        os.getenv("CLERK_CLIENT_SECRET", "").strip()
        or os.getenv("CLERK_SECRET_KEY", "").strip()
    )
    server_metadata_url = os.getenv("CLERK_SERVER_METADATA_URL", "").strip()
    frontend_api_url = os.getenv("CLERK_FRONTEND_API_URL", "").strip().rstrip("/")
    if _is_placeholder_value(server_metadata_url):
        server_metadata_url = ""
    if not server_metadata_url and frontend_api_url:
        server_metadata_url = f"{frontend_api_url}/.well-known/openid-configuration"

    redirect_uri = os.getenv("STREAMLIT_REDIRECT_URI", "http://localhost:8501/oauth2callback").strip()
    cookie_secret = os.getenv("STREAMLIT_COOKIE_SECRET", "").strip()
    prompt = os.getenv("CLERK_OIDC_PROMPT", "login").strip()
    scope = os.getenv("CLERK_OIDC_SCOPE", "openid email profile").strip()

    if prompt.startswith("[") and prompt.endswith("]"):
        prompt = prompt.strip("[] ").strip("'").strip('"')
    if "," in prompt:
        prompt = prompt.split(",", 1)[0].strip()
    if not prompt:
        prompt = "login"
    if prompt not in {"none", "login", "consent", "select_account"}:
        prompt = "login"
    # Clerk rejects `select_account` for this flow.
    if prompt == "select_account":
        prompt = "login"

    if not scope:
        scope = "openid email profile"

    required_values = [client_id, client_secret, server_metadata_url, cookie_secret]
    if _is_placeholder_value(client_id) or _is_placeholder_value(client_secret):
        return ""
    if _is_placeholder_value(frontend_api_url) and not server_metadata_url:
        return ""
    if not all(required_values):
        return ""

    lines = [
        "[auth]",
        f'redirect_uri = "{_toml_escape(redirect_uri)}"',
        f'cookie_secret = "{_toml_escape(cookie_secret)}"',
        "",
        "[auth.clerk]",
        f'client_id = "{_toml_escape(client_id)}"',
        f'client_secret = "{_toml_escape(client_secret)}"',
        f'server_metadata_url = "{_toml_escape(server_metadata_url)}"',
        f'client_kwargs = {{ prompt = "{_toml_escape(prompt)}", scope = "{_toml_escape(scope)}" }}',
        "",
    ]
    return "\n".join(lines)


def ensure_streamlit_secrets_from_env() -> None:
    """Write `.streamlit/secrets.toml` from `.env` for Clerk OIDC login."""
    if os.getenv("AUTH_PROVIDER", "none").strip().lower() != "clerk":
        return

    toml_content = _build_streamlit_secrets_from_env()
    if not toml_content:
        return

    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = secrets_path.read_text(encoding="utf-8") if secrets_path.exists() else ""
        if existing != toml_content:
            secrets_path.write_text(toml_content, encoding="utf-8")
    except OSError:
        return


def load_env_settings() -> None:
    """Load .env from project root and repair BOM-prefixed keys if present."""
    env_path = Path(__file__).resolve().parent / ".env"
    # Ensure project-local `.env` values win over stale machine/user env vars.
    load_dotenv(dotenv_path=env_path, override=True)

    # Some editors/shell commands write UTF-8 BOM; dotenv then sets a BOM-prefixed key.
    bom_key = "\ufeffOPENAI_API_KEY"
    if not os.getenv("OPENAI_API_KEY") and os.getenv(bom_key):
        os.environ["OPENAI_API_KEY"] = os.getenv(bom_key, "")

    ensure_streamlit_secrets_from_env()


load_env_settings()


def bootstrap_clinic() -> dict[str, object]:
    """Initialize DB, seed clinic, and return active clinic settings."""
    db.init_db()
    clinic_id = db.ensure_default_clinic(DEFAULT_CLINIC)
    clinic = db.get_clinic(clinic_id)
    clinic["id"] = clinic_id
    return clinic


def start_new_conversation(clinic: dict[str, object]) -> int:
    """Create new conversation and seed opening assistant greeting."""
    conversation_id = db.create_conversation(int(clinic["id"]))
    db.add_message(
        conversation_id,
        "assistant",
        WELCOME_TEMPLATE.format(clinic_name=clinic["name"]),
    )
    return conversation_id


def ensure_session_conversation(clinic: dict[str, object]) -> int:
    """Ensure session points to a valid active conversation id."""
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = start_new_conversation(clinic)
    return int(st.session_state.conversation_id)


def _sync_signed_in_account(clinic_id: int, session: AuthSession) -> AuthSession:
    """Upsert signed-in account and apply DB-managed staff/customer overrides."""
    if session.guest_mode:
        return session

    auth_user = session.auth_user
    email = str(auth_user.get("email") or "").strip().lower()
    if not email:
        return session

    full_name = str(auth_user.get("full_name") or "").strip()
    user_id = str(auth_user.get("user_id") or "").strip()

    initial_role = "staff" if session.staff_mode else "customer"
    db.upsert_business_account(
        clinic_id=clinic_id,
        auth_user_id=user_id,
        email=email,
        full_name=full_name,
        role=initial_role,
    )

    stored = db.get_business_account_by_email(clinic_id=clinic_id, email=email)
    if not stored:
        return session

    db_role = str(stored.get("role") or "customer").strip().lower()
    if db_role not in {"staff", "customer"}:
        db_role = "customer"

    if db_role == session.access_role:
        return session

    return AuthSession(
        auth_user=auth_user,
        access_role=db_role,
        staff_mode=db_role == "staff",
        guest_mode=False,
        member_bonus_active=True,
    )


def main() -> None:
    st.set_page_config(page_title="AI Receptionist Booking MVP", page_icon=":calendar:", layout="wide")
    apply_app_styles()

    clinic = bootstrap_clinic()
    auth_session = render_auth_sidebar()
    auth_session = _sync_signed_in_account(clinic_id=int(clinic["id"]), session=auth_session)

    if not os.getenv("OPENAI_API_KEY"):
        st.warning("OPENAI_API_KEY is missing. The app still works with deterministic fallback responses.")

    render_hero_header(
        clinic=clinic,
        auth_user=auth_session.auth_user,
        access_role=auth_session.access_role,
        guest_mode=auth_session.guest_mode,
    )

    conversation_id = ensure_session_conversation(clinic)

    if auth_session.staff_mode:
        render_staff_overview(clinic)

    # User/customer UI: chat only. Staff UI: full operations pages.
    if not auth_session.staff_mode:
        tabs = st.tabs(["Chat"])
        with tabs[0]:
            render_chat_tab(
                clinic=clinic,
                conversation_id=conversation_id,
                auth_user=auth_session.auth_user,
                member_bonus_active=auth_session.member_bonus_active,
                guest_mode=auth_session.guest_mode,
                on_new_conversation=lambda: start_new_conversation(clinic),
            )
        return

    tab_names = ["Chat", "Bookings", "Calendar", "Dashboard", "Leads", "Conversations"]
    tabs = st.tabs(tab_names)
    tab_map = {name: tab for name, tab in zip(tab_names, tabs)}

    with tab_map["Chat"]:
        render_chat_tab(
            clinic=clinic,
            conversation_id=conversation_id,
            auth_user=auth_session.auth_user,
            member_bonus_active=auth_session.member_bonus_active,
            guest_mode=auth_session.guest_mode,
            on_new_conversation=lambda: start_new_conversation(clinic),
        )
    with tab_map["Bookings"]:
        render_bookings_tab(clinic)
    with tab_map["Calendar"]:
        render_calendar_tab(clinic)
    with tab_map["Dashboard"]:
        render_dashboard_tab(clinic)
    with tab_map["Leads"]:
        render_leads_tab()
    with tab_map["Conversations"]:
        render_conversations_tab(conversation_id)


if __name__ == "__main__":
    main()
