"""Authentication helpers for Clerk-backed role checks in Streamlit."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import jwt
from jwt import PyJWKClient
import streamlit as st


@dataclass
class AuthUser:
    """Normalized authenticated user shape for app authorization checks."""

    user_id: str
    email: str
    full_name: str
    role: str
    claims: dict[str, Any]

    def to_session_dict(self) -> dict[str, Any]:
        """Serialize to a session-friendly dictionary."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "claims": self.claims,
        }


def auth_provider() -> str:
    """Return configured auth provider mode."""
    return os.getenv("AUTH_PROVIDER", "none").strip().lower()


def clerk_oidc_is_configured() -> tuple[bool, str]:
    """
    Validate Streamlit OIDC secrets config for Clerk login flow.

    Required environment-driven settings:
      - CLERK_CLIENT_ID (or NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)
      - CLERK_CLIENT_SECRET (or CLERK_SECRET_KEY)
      - CLERK_SERVER_METADATA_URL (or CLERK_FRONTEND_API_URL)
      - STREAMLIT_COOKIE_SECRET
    """
    try:
        auth_cfg = st.secrets.get("auth", {})
    except Exception:
        return (
            False,
            "Clerk auth is not configured. Set CLERK_CLIENT_ID, CLERK_CLIENT_SECRET, "
            "CLERK_SERVER_METADATA_URL (or CLERK_FRONTEND_API_URL), and STREAMLIT_COOKIE_SECRET in `.env`.",
        )

    if not auth_cfg:
        return (
            False,
            "Clerk auth is not configured. Add required Clerk OIDC keys to `.env` and restart the app.",
        )

    missing_shared: list[str] = []
    for key in ["redirect_uri", "cookie_secret"]:
        value = str(auth_cfg.get(key, "")).strip()
        if not value:
            missing_shared.append(key)

    provider_cfg = auth_cfg.get("clerk", {})
    if not provider_cfg:
        return (
            False,
            "Clerk provider config missing. Check CLERK_CLIENT_ID, CLERK_CLIENT_SECRET, and CLERK_SERVER_METADATA_URL in `.env`.",
        )

    missing_provider: list[str] = []
    for key in ["client_id", "client_secret", "server_metadata_url"]:
        value = str(provider_cfg.get(key, "")).strip()
        if not value:
            missing_provider.append(key)

    missing_parts: list[str] = []
    if missing_shared:
        missing_parts.append(f"[auth]: {', '.join(missing_shared)}")
    if missing_provider:
        missing_parts.append(f"[auth.clerk]: {', '.join(missing_provider)}")

    if missing_parts:
        return False, "Missing OIDC settings generated from `.env` -> " + " | ".join(missing_parts)
    return True, ""


def _get_nested(data: dict[str, Any], path: str) -> Any:
    """Read nested claim value from dot-separated path."""
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]
    return current


def _coalesce(*values: Any) -> str:
    """Return first non-empty string value."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _friendly_name_from_email(email: str) -> str:
    """Create a readable fallback name from email local part."""
    if "@" not in email:
        return ""
    local = email.split("@", 1)[0].strip().lower()
    if not local:
        return ""

    chunks = [part for part in re.split(r"[._\-]+", local) if part]
    cleaned: list[str] = []
    for chunk in chunks[:3]:
        token = re.sub(r"[^a-z0-9]", "", chunk)
        if not token:
            continue
        cleaned.append(token.capitalize())
    return " ".join(cleaned)


def _extract_email(claims: dict[str, Any]) -> str:
    """Best-effort email extraction from Clerk token claims."""
    direct = _coalesce(
        claims.get("email"),
        claims.get("email_address"),
        claims.get("primary_email_address"),
        _get_nested(claims, "primary_email_address.email_address"),
    )
    if direct:
        return direct

    addresses = claims.get("email_addresses")
    if isinstance(addresses, list) and addresses:
        first = addresses[0]
        if isinstance(first, dict):
            return _coalesce(first.get("email_address"), first.get("email"))
        if isinstance(first, str):
            return first.strip()
    return ""


def _extract_role(claims: dict[str, Any]) -> str:
    """Extract role from common custom-claim paths."""
    role = _coalesce(
        claims.get("role"),
        _get_nested(claims, "public_metadata.role"),
        _get_nested(claims, "metadata.role"),
        _get_nested(claims, "unsafe_metadata.role"),
    )
    return role.lower() if role else "customer"


def _extract_name(claims: dict[str, Any]) -> str:
    """Build display name from claims and avoid defaulting directly to raw email."""
    full = _coalesce(
        claims.get("name"),
        claims.get("full_name"),
        claims.get("preferred_username"),
        claims.get("username"),
        _get_nested(claims, "user.full_name"),
        _get_nested(claims, "public_metadata.full_name"),
    )
    if full and "@" not in full:
        return full

    first = _coalesce(claims.get("given_name"), claims.get("first_name"), _get_nested(claims, "user.first_name"))
    last = _coalesce(claims.get("family_name"), claims.get("last_name"), _get_nested(claims, "user.last_name"))
    combined = f"{first} {last}".strip()
    if combined:
        return combined

    email = _extract_email(claims)
    fallback = _friendly_name_from_email(email)
    if fallback:
        return fallback

    return "Signed-in user"


def _read_streamlit_user_claims() -> dict[str, Any]:
    """Safely return Streamlit user claims from OIDC login state."""
    try:
        raw = st.user.to_dict()
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}
    return raw


def streamlit_user_is_logged_in() -> bool:
    """Check current Streamlit OIDC login status."""
    claims = _read_streamlit_user_claims()
    if not claims:
        return False

    logged = claims.get("is_logged_in")
    if isinstance(logged, bool):
        return logged
    return bool(claims.get("sub") or claims.get("email") or claims.get("user_id"))


def get_authenticated_user_from_streamlit() -> Optional[AuthUser]:
    """Map Streamlit OIDC user claims into normalized AuthUser."""
    claims = _read_streamlit_user_claims()
    if not claims or not streamlit_user_is_logged_in():
        return None

    user_id = _coalesce(claims.get("sub"), claims.get("user_id"), claims.get("uid")) or "unknown_user"
    email = _extract_email(claims)
    full_name = _extract_name(claims)
    role = _extract_role(claims)
    return AuthUser(
        user_id=user_id,
        email=email,
        full_name=full_name,
        role=role,
        claims=claims,
    )


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    """Cache JWKS client per URL to reduce repeated fetches."""
    return PyJWKClient(jwks_url)


def verify_clerk_token(token: str) -> AuthUser:
    """
    Verify Clerk JWT and return normalized AuthUser.

    Configure either:
    - CLERK_JWT_PUBLIC_KEY (PEM public key), or
    - CLERK_JWKS_URL (JWKS endpoint URL)
    """
    raw_token = token.strip()
    if not raw_token:
        raise RuntimeError("Missing token.")

    issuer = os.getenv("CLERK_ISSUER", "").strip() or None
    audience = os.getenv("CLERK_AUDIENCE", "").strip() or None
    public_key = os.getenv("CLERK_JWT_PUBLIC_KEY", "").strip()
    jwks_url = os.getenv("CLERK_JWKS_URL", "").strip()

    decode_kwargs: dict[str, Any] = {
        "algorithms": ["RS256"],
        "options": {"verify_signature": True, "verify_exp": True},
    }
    if issuer:
        decode_kwargs["issuer"] = issuer
    if audience:
        decode_kwargs["audience"] = audience
    else:
        decode_kwargs["options"]["verify_aud"] = False

    if public_key:
        claims = jwt.decode(raw_token, key=public_key, **decode_kwargs)
    else:
        if not jwks_url:
            raise RuntimeError("Set CLERK_JWT_PUBLIC_KEY or CLERK_JWKS_URL to verify Clerk tokens.")
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(raw_token).key
        claims = jwt.decode(raw_token, key=signing_key, **decode_kwargs)

    user_id = _coalesce(claims.get("sub"), claims.get("user_id"), claims.get("uid")) or "unknown_user"
    email = _extract_email(claims)
    full_name = _extract_name(claims)
    role = _extract_role(claims)

    return AuthUser(
        user_id=user_id,
        email=email,
        full_name=full_name,
        role=role,
        claims=claims,
    )


def _split_env_set(name: str) -> set[str]:
    """Split comma-separated environment values into lowercase set."""
    raw = os.getenv(name, "").strip()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_staff_user(auth_user: dict[str, Any]) -> bool:
    """Authorize staff users via role claims or explicit email allow list."""
    role = str(auth_user.get("role", "")).strip().lower()

    role_values = _split_env_set("CLERK_STAFF_ROLE_VALUES")
    if not role_values:
        # Backward compatibility for older env naming.
        fallback_role = os.getenv("CLERK_ADMIN_ROLE_VALUE", "admin").strip().lower()
        role_values = {"staff", "owner", fallback_role}

    if role and role in role_values:
        return True

    allowed_staff = _split_env_set("CLERK_STAFF_EMAILS")
    # Backward compatibility: if older admin allowlist exists, include it.
    allowed_staff.update(_split_env_set("CLERK_ADMIN_EMAILS"))

    email = str(auth_user.get("email", "")).strip().lower()
    return bool(email and email in allowed_staff)


def is_customer_user(auth_user: dict[str, Any]) -> bool:
    """Return True for signed-in, non-staff accounts."""
    if not auth_user:
        return False
    if str(auth_user.get("role", "")).strip().lower() == "guest":
        return False
    if not str(auth_user.get("user_id", "")).strip():
        return False
    return not is_staff_user(auth_user)


def resolve_business_role(auth_user: dict[str, Any]) -> str:
    """Resolve app-level access role: guest, customer, or staff."""
    if not auth_user:
        return "guest"
    if str(auth_user.get("role", "")).strip().lower() == "guest":
        return "guest"
    if is_staff_user(auth_user):
        return "staff"
    return "customer"


def is_admin_user(auth_user: dict[str, Any]) -> bool:
    """Backward-compatible alias: admin access maps to staff access."""
    return is_staff_user(auth_user)


def get_session_token_from_query(query_params: Any) -> str:
    """Read possible Clerk session token from query parameters."""
    for key in ["__session", "token", "session_token"]:
        try:
            value = query_params.get(key, "")
        except Exception:
            value = ""
        if isinstance(value, list):
            value = value[0] if value else ""
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
