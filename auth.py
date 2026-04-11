"""Authentication helpers for Clerk-backed role checks in Streamlit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient


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


def _extract_email(claims: dict[str, Any]) -> str:
    """Best-effort email extraction from Clerk token claims."""
    direct = _coalesce(claims.get("email"), claims.get("email_address"), claims.get("primary_email_address"))
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
    return role.lower() if role else "user"


def _extract_name(claims: dict[str, Any]) -> str:
    """Build display name from claims."""
    full = _coalesce(claims.get("name"), claims.get("full_name"))
    if full:
        return full
    first = _coalesce(claims.get("first_name"))
    last = _coalesce(claims.get("last_name"))
    if first or last:
        return f"{first} {last}".strip()
    return _extract_email(claims) or "Signed in user"


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


def is_admin_user(auth_user: dict[str, Any]) -> bool:
    """Authorize admin users via role or explicit admin email list."""
    role = str(auth_user.get("role", "")).strip().lower()
    expected_role = os.getenv("CLERK_ADMIN_ROLE_VALUE", "admin").strip().lower()
    if role and role == expected_role:
        return True

    admin_emails_raw = os.getenv("CLERK_ADMIN_EMAILS", "").strip()
    admin_emails = {email.strip().lower() for email in admin_emails_raw.split(",") if email.strip()}
    email = str(auth_user.get("email", "")).strip().lower()
    return bool(email and email in admin_emails)


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

