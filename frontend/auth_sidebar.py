"""Sidebar authentication rendering and role mode resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import streamlit as st

from auth import (
    auth_provider,
    clerk_oidc_is_configured,
    get_authenticated_user_from_streamlit,
    resolve_business_role,
    streamlit_user_is_logged_in,
)
from frontend.components import render_sidebar_account_panel


@dataclass
class AuthSession:
    """Resolved auth context used by page orchestration."""

    auth_user: dict[str, Any]
    access_role: str
    staff_mode: bool
    guest_mode: bool
    member_bonus_active: bool


def _configured_redirect_uri() -> str:
    """Return effective redirect URI used by Streamlit auth."""
    try:
        auth_cfg = st.secrets.get("auth", {})
        redirect = str(auth_cfg.get("redirect_uri", "")).strip()
        if redirect:
            return redirect
    except Exception:
        pass
    return os.getenv("STREAMLIT_REDIRECT_URI", "http://localhost:8501/oauth2callback").strip()


def _guest_user() -> dict[str, Any]:
    """Create canonical guest-user shape."""
    return {
        "user_id": "guest",
        "email": "",
        "full_name": "Guest",
        "role": "guest",
        "claims": {},
    }


def _render_local_demo_mode() -> AuthSession:
    """Fallback local mode when AUTH_PROVIDER is not clerk."""
    st.sidebar.caption("AUTH_PROVIDER is not `clerk`. Running local demo auth mode.")
    role = st.sidebar.selectbox(
        "Demo role",
        options=["guest", "customer", "staff"],
        index=2,
        help="Switch local role while testing UI flows without Clerk.",
    )

    if role == "guest":
        user = _guest_user()
        guest_mode = True
    else:
        user = {
            "user_id": f"demo_{role}",
            "email": f"{role}@local.demo",
            "full_name": f"Local {role.title()} User",
            "role": role,
            "claims": {},
        }
        guest_mode = False

    staff_mode = role == "staff"
    member_bonus_active = role in {"customer", "staff"}

    render_sidebar_account_panel(
        auth_user=user,
        access_role=role,
        guest_mode=guest_mode,
        member_bonus_active=member_bonus_active,
        redirect_uri=_configured_redirect_uri(),
    )

    return AuthSession(
        auth_user=user,
        access_role=role,
        staff_mode=staff_mode,
        guest_mode=guest_mode,
        member_bonus_active=member_bonus_active,
    )


def render_auth_sidebar() -> AuthSession:
    """Render authentication controls and return resolved session role context."""
    st.sidebar.subheader("Authentication")

    if auth_provider() != "clerk":
        return _render_local_demo_mode()

    oidc_ok, oidc_message = clerk_oidc_is_configured()
    guest_user = _guest_user()

    if not oidc_ok:
        st.sidebar.error(oidc_message)
        st.sidebar.info("Guest booking is available while Clerk setup is being completed.")
        render_sidebar_account_panel(
            auth_user=guest_user,
            access_role="guest",
            guest_mode=True,
            member_bonus_active=False,
            redirect_uri=_configured_redirect_uri(),
        )
        return AuthSession(
            auth_user=guest_user,
            access_role="guest",
            staff_mode=False,
            guest_mode=True,
            member_bonus_active=False,
        )

    if streamlit_user_is_logged_in():
        user = get_authenticated_user_from_streamlit()
        if not user:
            st.sidebar.warning("Sign-in state could not be loaded. Please sign in again.")
            if st.sidebar.button("Sign in with Clerk", type="primary", use_container_width=True):
                try:
                    st.login("clerk")
                except Exception as exc:
                    err_text = str(exc)
                    st.sidebar.error(f"Clerk login failed: {err_text}")
                    if "redirect_uri" in err_text.lower():
                        st.sidebar.warning(
                            "Redirect URI mismatch. In Clerk OAuth app, click Save and ensure this exact URI is listed:"
                        )
                        st.sidebar.code(_configured_redirect_uri(), language="text")
            render_sidebar_account_panel(
                auth_user=guest_user,
                access_role="guest",
                guest_mode=True,
                member_bonus_active=False,
                redirect_uri=_configured_redirect_uri(),
            )
            return AuthSession(
                auth_user=guest_user,
                access_role="guest",
                staff_mode=False,
                guest_mode=True,
                member_bonus_active=False,
            )

        auth_user = user.to_session_dict()
        access_role = resolve_business_role(auth_user)
        staff_mode = access_role == "staff"
        guest_mode = access_role == "guest"
        member_bonus_active = access_role in {"customer", "staff"}

        render_sidebar_account_panel(
            auth_user=auth_user,
            access_role=access_role,
            guest_mode=guest_mode,
            member_bonus_active=member_bonus_active,
            redirect_uri=_configured_redirect_uri(),
        )

        if st.sidebar.button("Sign out", use_container_width=True):
            st.logout()

        return AuthSession(
            auth_user=auth_user,
            access_role=access_role,
            staff_mode=staff_mode,
            guest_mode=guest_mode,
            member_bonus_active=member_bonus_active,
        )

    st.sidebar.info("No account needed. Continue as guest or sign in for member bonus.")
    render_sidebar_account_panel(
        auth_user=guest_user,
        access_role="guest",
        guest_mode=True,
        member_bonus_active=False,
        redirect_uri=_configured_redirect_uri(),
    )

    if st.sidebar.button("Sign in with Clerk", type="primary", use_container_width=True):
        try:
            st.login("clerk")
        except Exception as exc:
            err_text = str(exc)
            st.sidebar.error(f"Clerk login failed: {err_text}")
            if "redirect_uri" in err_text.lower():
                st.sidebar.warning(
                    "Redirect URI mismatch. In Clerk OAuth app, click Save and ensure this exact URI is listed:"
                )
                st.sidebar.code(_configured_redirect_uri(), language="text")

    st.sidebar.caption("Member bonus: profile autofill + priority follow-up on pending requests.")

    return AuthSession(
        auth_user=guest_user,
        access_role="guest",
        staff_mode=False,
        guest_mode=True,
        member_bonus_active=False,
    )
