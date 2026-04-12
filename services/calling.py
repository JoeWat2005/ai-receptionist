"""Calling-integration scaffold (provider-agnostic, local MVP)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CallWebhookEvent:
    """Normalized incoming call event shape for future provider webhooks."""

    call_id: str
    direction: str
    from_number: str
    to_number: str
    status: str
    transcript: str
    timestamp_utc: str


def parse_call_webhook(payload: dict[str, Any]) -> CallWebhookEvent:
    """Normalize webhook-style payload into internal call event model."""
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return CallWebhookEvent(
        call_id=str(payload.get("call_id") or payload.get("CallSid") or "local-call"),
        direction=str(payload.get("direction") or payload.get("Direction") or "inbound").lower(),
        from_number=str(payload.get("from") or payload.get("From") or "").strip(),
        to_number=str(payload.get("to") or payload.get("To") or "").strip(),
        status=str(payload.get("status") or payload.get("CallStatus") or "received").lower(),
        transcript=str(payload.get("transcript") or "").strip(),
        timestamp_utc=str(payload.get("timestamp_utc") or now_iso),
    )


def build_outbound_call_request(to_number: str, from_number: str, intro_script: str) -> dict[str, str]:
    """Build provider payload scaffold for outbound reminder calls."""
    return {
        "to": to_number.strip(),
        "from": from_number.strip(),
        "script": intro_script.strip(),
        "channel": "voice",
        "mode": "scaffold_only",
    }


def build_local_voice_reply(prompt_text: str) -> str:
    """Build basic XML-like response placeholder for voice providers (TwiML-style)."""
    safe_text = prompt_text.replace("&", "and").replace("<", "(").replace(">", ")")
    return (
        "<Response>"
        f"<Say voice=\"alice\">{safe_text}</Say>"
        "<Pause length=\"1\"/>"
        "</Response>"
    )
