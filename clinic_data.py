"""Static clinic configuration and helpers."""

from __future__ import annotations

from typing import Optional

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}

DEFAULT_CLINIC = {
    "name": "Glow Aesthetics Clinic",
    "location": "Manchester city centre",
    "timezone": "Europe/London",
    "opening_hours_text": "Mon-Fri 9am-6pm, Sat 10am-4pm",
    "slot_length_minutes": 30,
    "business_contact_name": "",
    "business_contact_email": "",
    "business_contact_phone": "",
    "business_website": "",
    "onboarding_completed": False,
    "onboarding_notes": "",
    "business_hours": {
        "mon": {"open": "09:00", "close": "18:00"},
        "tue": {"open": "09:00", "close": "18:00"},
        "wed": {"open": "09:00", "close": "18:00"},
        "thu": {"open": "09:00", "close": "18:00"},
        "fri": {"open": "09:00", "close": "18:00"},
        "sat": {"open": "10:00", "close": "16:00"},
        "sun": None,
    },
    "treatments": [
        "Botox consultation",
        "Lip filler consultation",
        "Skin booster consultation",
        "Facial aesthetics assessment",
    ],
    "faq": {
        "consultations offered": "Yes, we offer consultations before treatment.",
        "location": "We are based in Manchester city centre.",
        "opening hours": "We are open Mon-Fri 9am-6pm and Sat 10am-4pm.",
        "exact quote in chat": (
            "No. Exact pricing depends on an in-person or clinician assessment."
        ),
    },
}


def _format_ampm(hhmm: str) -> str:
    """Convert HH:MM to compact am/pm for display."""
    hour, minute = [int(x) for x in hhmm.split(":", 1)]
    suffix = "am" if hour < 12 else "pm"
    hour12 = hour % 12 or 12
    if minute == 0:
        return f"{hour12}{suffix}"
    return f"{hour12}:{minute:02d}{suffix}"


def business_hours_to_text(business_hours: dict[str, dict | None]) -> str:
    """Build readable opening-hours text from business hour map."""
    ranges: list[str] = []
    i = 0
    while i < len(DAY_ORDER):
        day = DAY_ORDER[i]
        hours = business_hours.get(day)
        if hours is None:
            i += 1
            continue

        start = i
        open_time = hours["open"]
        close_time = hours["close"]

        while i + 1 < len(DAY_ORDER):
            next_day = DAY_ORDER[i + 1]
            next_hours = business_hours.get(next_day)
            if next_hours is None:
                break
            if next_hours["open"] == open_time and next_hours["close"] == close_time:
                i += 1
                continue
            break

        end = i
        if start == end:
            day_label = DAY_LABELS[DAY_ORDER[start]]
        else:
            day_label = f"{DAY_LABELS[DAY_ORDER[start]]}-{DAY_LABELS[DAY_ORDER[end]]}"
        ranges.append(f"{day_label} {_format_ampm(open_time)}-{_format_ampm(close_time)}")
        i += 1

    if business_hours.get("sun") is None:
        ranges.append("Sun closed")

    return ", ".join(ranges)


def faq_answer_for_text(user_text: str) -> Optional[str]:
    """Return known FAQ answer for common question intents."""
    text = user_text.lower()

    if any(token in text for token in ["consultation", "consultations", "do you offer"]):
        return DEFAULT_CLINIC["faq"]["consultations offered"]
    if any(token in text for token in ["where", "located", "location", "manchester"]):
        return DEFAULT_CLINIC["faq"]["location"]
    if any(token in text for token in ["open", "opening", "hours", "times"]):
        return DEFAULT_CLINIC["faq"]["opening hours"]
    if any(token in text for token in ["quote", "price", "pricing", "cost", "exact"]):
        return DEFAULT_CLINIC["faq"]["exact quote in chat"]

    return None
