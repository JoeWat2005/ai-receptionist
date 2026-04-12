"""Backward-compatible wrappers for UI components.

This file remains to avoid breaking older imports after modular refactor.
"""

from __future__ import annotations

from typing import Any

from frontend.components import (
    apply_app_styles,
    render_chat_mode_hint as render_auth_hint,
    render_hero_header,
    render_sidebar_account_panel,
)


def render_header(clinic: dict[str, Any], auth_user: dict[str, Any], admin_mode: bool, guest_mode: bool) -> None:
    """Compatibility wrapper for older function signatures."""
    access_role = "staff" if admin_mode else ("guest" if guest_mode else "customer")
    render_hero_header(
        clinic=clinic,
        auth_user=auth_user,
        access_role=access_role,
        guest_mode=guest_mode,
    )


def render_profile_card(auth_user: dict[str, Any], admin_mode: bool, guest_mode: bool, member_bonus_active: bool) -> None:
    """Compatibility no-op (profile now lives in sidebar account panel)."""
    return


def render_sidebar_account_summary(
    auth_user: dict[str, Any],
    admin_mode: bool,
    guest_mode: bool,
    member_bonus_active: bool,
    redirect_uri: str,
) -> None:
    """Compatibility wrapper for account summary block."""
    access_role = "staff" if admin_mode else ("guest" if guest_mode else "customer")
    render_sidebar_account_panel(
        auth_user=auth_user,
        access_role=access_role,
        guest_mode=guest_mode,
        member_bonus_active=member_bonus_active,
        redirect_uri=redirect_uri,
    )
