"""Deterministic booking validation, availability, and decision rules."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

BOOKING_FIELDS = [
    "treatment_interest",
    "booking_type",
    "preferred_date",
    "preferred_time",
    "timeframe",
    "name",
    "phone",
    "email",
    "notes",
]

REQUIRED_FOR_CONFIRMED = [
    "treatment_interest",
    "booking_type",
    "preferred_date",
    "preferred_time",
    "name",
    "phone",
    "email",
]

DAY_TO_INDEX = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
INDEX_TO_KEY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}


def empty_booking_state() -> dict[str, str]:
    """Return empty structured booking state."""
    return {field: "" for field in BOOKING_FIELDS}


def merge_booking_state(current: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Merge non-empty updates into existing structured state."""
    merged = dict(current)
    for field in BOOKING_FIELDS:
        value = (updates.get(field) or "").strip()
        if value:
            merged[field] = value
    return merged


def _today() -> date:
    """Small wrapper for current date to keep logic testable."""
    return datetime.now().date()


def parse_date_to_iso(value: str) -> tuple[Optional[str], Optional[str]]:
    """Parse date text into YYYY-MM-DD with support for common relative terms."""
    text = value.strip().lower()
    if not text:
        return "", None

    now = _today()

    if text in {"today"}:
        return now.isoformat(), None
    if text in {"tomorrow"}:
        return (now + timedelta(days=1)).isoformat(), None

    # next monday / monday style references
    day_match = re.fullmatch(r"(?:next\s+)?([a-z]+)", text)
    if day_match and day_match.group(1) in DAY_TO_INDEX:
        target = DAY_TO_INDEX[day_match.group(1)]
        delta = (target - now.weekday()) % 7
        if delta == 0:
            delta = 7
        if text.startswith("next "):
            delta += 7
        return (now + timedelta(days=delta)).isoformat(), None

    formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat(), None
        except ValueError:
            continue

    month_match = re.fullmatch(
        r"(\d{1,2})\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+(\d{4}))?",
        text,
    )
    if month_match:
        day = int(month_match.group(1))
        month = month_match.group(2)[:3].title()
        year = month_match.group(3) or str(now.year)
        try:
            parsed = datetime.strptime(f"{day} {month} {year}", "%d %b %Y").date()
            return parsed.isoformat(), None
        except ValueError:
            return None, "Date is not valid."

    return None, "Date must be in YYYY-MM-DD, DD/MM/YYYY, or clear day text like 'tomorrow'."


def parse_time_to_hhmm(value: str) -> tuple[Optional[str], Optional[str]]:
    """Parse time text into HH:MM (24-hour)."""
    text = value.strip().lower().replace(".", ":")
    if not text:
        return "", None

    if text in {"noon", "midday"}:
        return "12:00", None
    if text == "midnight":
        return "00:00", None

    compact = text.replace(" ", "")

    # 1530 style
    if re.fullmatch(r"\d{4}", compact):
        hh = int(compact[:2])
        mm = int(compact[2:])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}", None

    formats = ["%H:%M", "%I:%M%p", "%I%p"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(compact, fmt).time()
            return parsed.strftime("%H:%M"), None
        except ValueError:
            continue

    if re.fullmatch(r"\d{1,2}", compact):
        hour = int(compact)
        if 0 <= hour <= 23:
            return f"{hour:02d}:00", None

    return None, "Time must be HH:MM, 10am, 10:30am, or 1530."


def normalize_phone(phone: str) -> tuple[Optional[str], Optional[str]]:
    """Normalize phone to digits (+country when provided)."""
    raw = phone.strip()
    if not raw:
        return "", None

    compact = re.sub(r"[^\d+]", "", raw)
    if compact.startswith("00"):
        compact = "+" + compact[2:]

    if compact.count("+") > 1 or ("+" in compact and not compact.startswith("+")):
        return None, "Phone number format is invalid."

    digits = re.sub(r"\D", "", compact)
    if len(digits) < 10 or len(digits) > 15:
        return None, "Phone number must contain 10 to 15 digits."

    if compact.startswith("+"):
        return "+" + digits, None
    return digits, None


def validate_email(email: str) -> Optional[str]:
    """Return None when email is valid, else validation error text."""
    value = email.strip()
    if not value:
        return None

    if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value):
        return None
    return "Email address format is invalid."


def normalize_and_validate_state(state: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Normalize state values and return validation errors keyed by field."""
    normalized = empty_booking_state()
    errors: dict[str, str] = {}

    for field in BOOKING_FIELDS:
        normalized[field] = str(state.get(field, "") or "").strip()

    if normalized["phone"]:
        phone, phone_error = normalize_phone(normalized["phone"])
        if phone_error:
            errors["phone"] = phone_error
        else:
            normalized["phone"] = phone or ""

    if normalized["email"]:
        email_error = validate_email(normalized["email"])
        if email_error:
            errors["email"] = email_error

    if normalized["preferred_date"]:
        date_iso, date_error = parse_date_to_iso(normalized["preferred_date"])
        if date_error:
            errors["preferred_date"] = date_error
        else:
            normalized["preferred_date"] = date_iso or ""

    if normalized["preferred_time"]:
        time_hhmm, time_error = parse_time_to_hhmm(normalized["preferred_time"])
        if time_error:
            errors["preferred_time"] = time_error
        else:
            normalized["preferred_time"] = time_hhmm or ""

    return normalized, errors


def _to_minutes(hhmm: str) -> int:
    """Convert HH:MM to minutes since midnight."""
    hh, mm = [int(part) for part in hhmm.split(":", 1)]
    return hh * 60 + mm


def _from_minutes(total_minutes: int) -> str:
    """Convert minutes since midnight to HH:MM."""
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh:02d}:{mm:02d}"


def _day_hours_for_date(date_iso: str, business_hours: dict[str, Any]) -> Optional[dict[str, str]]:
    """Return opening hours config for specific date, or None if closed."""
    day_index = datetime.strptime(date_iso, "%Y-%m-%d").weekday()
    day_key = INDEX_TO_KEY[day_index]
    return business_hours.get(day_key)


def is_within_business_hours(date_iso: str, time_hhmm: str, business_hours: dict[str, Any]) -> bool:
    """True when slot start time is within opening hours for that day."""
    hours = _day_hours_for_date(date_iso, business_hours)
    if hours is None:
        return False

    slot = _to_minutes(time_hhmm)
    open_m = _to_minutes(hours["open"])
    close_m = _to_minutes(hours["close"])
    return open_m <= slot < close_m


def _slot_overlaps(
    request_start_min: int,
    request_duration_min: int,
    booked_start_min: int,
    booked_duration_min: int,
) -> bool:
    """Interval overlap for two slot windows in minutes."""
    request_end = request_start_min + request_duration_min
    booked_end = booked_start_min + booked_duration_min
    return request_start_min < booked_end and booked_start_min < request_end


def is_slot_available(
    date_iso: str,
    time_hhmm: str,
    slot_length_minutes: int,
    business_hours: dict[str, Any],
    confirmed_bookings: list[dict[str, Any]],
) -> bool:
    """Check if proposed slot is inside hours and not overlapping confirmed bookings."""
    if not is_within_business_hours(date_iso, time_hhmm, business_hours):
        return False

    requested_start = _to_minutes(time_hhmm)
    for booking in confirmed_bookings:
        booked_time = booking.get("preferred_time")
        if not booked_time:
            continue
        booked_start = _to_minutes(str(booked_time))
        booked_duration = int(booking.get("duration_minutes") or slot_length_minutes)
        if _slot_overlaps(requested_start, slot_length_minutes, booked_start, booked_duration):
            return False

    return True


def generate_daily_slots(
    date_iso: str,
    business_hours: dict[str, Any],
    slot_length_minutes: int,
) -> list[str]:
    """Generate all slot start times for one day based on opening hours and slot length."""
    hours = _day_hours_for_date(date_iso, business_hours)
    if hours is None:
        return []

    open_m = _to_minutes(hours["open"])
    close_m = _to_minutes(hours["close"])

    slots: list[str] = []
    cursor = open_m
    while cursor + slot_length_minutes <= close_m:
        slots.append(_from_minutes(cursor))
        cursor += slot_length_minutes

    return slots


def list_available_slots(
    date_iso: str,
    business_hours: dict[str, Any],
    slot_length_minutes: int,
    confirmed_bookings: list[dict[str, Any]],
) -> list[str]:
    """Return free slot starts for a date after removing occupied windows."""
    available: list[str] = []
    for slot in generate_daily_slots(date_iso, business_hours, slot_length_minutes):
        if is_slot_available(
            date_iso=date_iso,
            time_hhmm=slot,
            slot_length_minutes=slot_length_minutes,
            business_hours=business_hours,
            confirmed_bookings=confirmed_bookings,
        ):
            available.append(slot)
    return available


def find_first_available_slot(
    date_iso: str,
    business_hours: dict[str, Any],
    slot_length_minutes: int,
    confirmed_bookings: list[dict[str, Any]],
) -> Optional[str]:
    """Return first available slot start for day, or None when full/closed."""
    slots = list_available_slots(
        date_iso=date_iso,
        business_hours=business_hours,
        slot_length_minutes=slot_length_minutes,
        confirmed_bookings=confirmed_bookings,
    )
    return slots[0] if slots else None


def missing_fields(state: dict[str, str], fields: list[str]) -> list[str]:
    """Return ordered list of empty fields from given field list."""
    return [field for field in fields if not (state.get(field) or "").strip()]


def next_field_to_ask(state: dict[str, str], validation_errors: dict[str, str]) -> str:
    """Pick the best next question field, prioritizing invalid fields."""
    for field in ["preferred_date", "preferred_time", "phone", "email"]:
        if field in validation_errors:
            return field

    order = [
        "treatment_interest",
        "booking_type",
        "preferred_date",
        "preferred_time",
        "name",
        "phone",
        "email",
        "timeframe",
        "notes",
    ]
    for field in order:
        if not (state.get(field) or "").strip():
            return field
    return "notes"


def reason_to_text(reason: str) -> str:
    """Convert internal reason codes to readable text."""
    mapping = {
        "slot_confirmed": "Requested slot is valid and available.",
        "outside_business_hours": "Requested slot is outside clinic business hours.",
        "slot_occupied": "Requested slot is already occupied.",
        "incomplete_details": "Booking details are incomplete.",
        "missing_required_details": "Required booking details are still missing.",
        "invalid_slot": "Date or time input is malformed.",
        "invalid_contact": "Phone or email format is invalid.",
        "missing_slot": "Preferred date/time is still needed.",
        "no_slots_on_date": "No free slots remain on that date.",
    }
    return mapping.get(reason, reason)


def decide_booking_outcome(
    state: dict[str, str],
    validation_errors: dict[str, str],
    business_hours: dict[str, Any],
    slot_length_minutes: int,
    confirmed_bookings: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Deterministic decision engine for booking status.

    Outcomes:
    - need_more_info
    - create_outcome with status confirmed or booking_request
    """
    missing_required = missing_fields(state, REQUIRED_FOR_CONFIRMED)
    has_date = bool(state.get("preferred_date"))
    has_time = bool(state.get("preferred_time"))

    if "preferred_date" in validation_errors or "preferred_time" in validation_errors:
        invalid_fields = [field for field in ["preferred_date", "preferred_time"] if field in validation_errors]
        return {
            "action": "need_more_info",
            "status": None,
            "reason": "invalid_slot",
            "missing_fields": invalid_fields,
            "next_field": invalid_fields[0],
            "available_slots": [],
        }

    if not has_date or not has_time:
        return {
            "action": "need_more_info",
            "status": None,
            "reason": "missing_slot",
            "missing_fields": missing_fields(state, BOOKING_FIELDS),
            "next_field": next_field_to_ask(state, validation_errors),
            "available_slots": [],
        }

    if "phone" in validation_errors or "email" in validation_errors:
        invalid_contact_fields = [field for field in ["phone", "email"] if field in validation_errors]
        return {
            "action": "need_more_info",
            "status": None,
            "reason": "invalid_contact",
            "missing_fields": invalid_contact_fields,
            "next_field": invalid_contact_fields[0],
            "available_slots": [],
        }

    # Do not finalize booking outcomes until required fields are present.
    if missing_required:
        return {
            "action": "need_more_info",
            "status": None,
            "reason": "missing_required_details",
            "missing_fields": missing_required,
            "next_field": missing_required[0],
            "available_slots": [],
        }

    date_iso = state["preferred_date"]
    time_hhmm = state["preferred_time"]

    available_slots = list_available_slots(
        date_iso=date_iso,
        business_hours=business_hours,
        slot_length_minutes=slot_length_minutes,
        confirmed_bookings=confirmed_bookings,
    )

    if not is_within_business_hours(date_iso, time_hhmm, business_hours):
        return {
            "action": "create_outcome",
            "status": "booking_request",
            "reason": "outside_business_hours",
            "missing_fields": missing_required,
            "next_field": missing_required[0] if missing_required else None,
            "available_slots": available_slots,
        }

    if not is_slot_available(
        date_iso=date_iso,
        time_hhmm=time_hhmm,
        slot_length_minutes=slot_length_minutes,
        business_hours=business_hours,
        confirmed_bookings=confirmed_bookings,
    ):
        reason = "slot_occupied" if available_slots else "no_slots_on_date"
        return {
            "action": "create_outcome",
            "status": "booking_request",
            "reason": reason,
            "missing_fields": missing_required,
            "next_field": missing_required[0] if missing_required else None,
            "available_slots": available_slots,
        }

    return {
        "action": "create_outcome",
        "status": "confirmed",
        "reason": "slot_confirmed",
        "missing_fields": [],
        "next_field": None,
        "available_slots": available_slots,
    }
