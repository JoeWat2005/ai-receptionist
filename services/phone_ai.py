"""Scaffold helpers for AI phone-call transcript processing."""

from __future__ import annotations

from typing import Any

from ai_logic import extract_fields_from_message
from booking_logic import (
    decide_booking_outcome,
    empty_booking_state,
    merge_booking_state,
    normalize_and_validate_state,
)


def build_phone_agent_prompt(clinic: dict[str, Any]) -> str:
    """Return a starter instruction block for a real-time voice agent."""
    treatments = ", ".join(clinic.get("treatments", []))
    return (
        f"You are the phone receptionist for {clinic.get('name', 'the clinic')}. "
        "Speak clearly and warmly, ask one question at a time, and never provide medical advice. "
        "Collect treatment interest, date, time, name, phone, and email before confirming a booking. "
        f"Available treatment consultations: {treatments}."
    )


def extract_state_from_transcript(
    transcript: str,
    clinic: dict[str, Any],
    current_state: dict[str, str] | None = None,
) -> dict[str, str]:
    """Extract structured booking state from call transcript turns."""
    state = dict(current_state or empty_booking_state())
    for raw_line in transcript.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        updates = extract_fields_from_message(line, state, clinic)
        state = merge_booking_state(state, updates)

    normalized_state, _ = normalize_and_validate_state(state)
    return normalized_state


def evaluate_phone_booking(
    state: dict[str, str],
    clinic: dict[str, Any],
    confirmed_bookings: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    """Run deterministic booking decision against extracted call state."""
    normalized_state, validation_errors = normalize_and_validate_state(state)
    decision = decide_booking_outcome(
        state=normalized_state,
        validation_errors=validation_errors,
        business_hours=clinic["business_hours"],
        slot_length_minutes=int(clinic["slot_length_minutes"]),
        confirmed_bookings=confirmed_bookings,
    )
    return normalized_state, validation_errors, decision


def summarize_call_result(normalized_state: dict[str, str], decision: dict[str, Any]) -> str:
    """Return short status summary for dashboard logs."""
    status = decision.get("status")
    if status == "confirmed":
        return (
            "Confirmed: "
            f"{normalized_state.get('preferred_date', '')} {normalized_state.get('preferred_time', '')}"
        ).strip()
    if status == "booking_request":
        return f"Pending request: {decision.get('reason', 'needs_follow_up')}"
    return f"Needs follow-up: {decision.get('reason', 'more_info')}"
