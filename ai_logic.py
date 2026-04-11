"""AI extraction + response layer (language only, no booking authority)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from openai import OpenAI

from booking_logic import BOOKING_FIELDS, parse_date_to_iso, parse_time_to_hhmm, reason_to_text
from clinic_data import faq_answer_for_text

FIELD_LABELS = {
    "treatment_interest": "treatment interest",
    "booking_type": "booking type",
    "preferred_date": "preferred date",
    "preferred_time": "preferred time",
    "timeframe": "timeframe",
    "name": "full name",
    "phone": "phone number",
    "email": "email address",
    "notes": "notes",
}

FLEXIBLE_TIME_TOKENS = {
    "any time",
    "anytime",
    "first available",
    "whenever",
    "flexible",
    "next available",
    "whatever time",
}


def field_label(field_name: str) -> str:
    """Return user-friendly field label."""
    return FIELD_LABELS.get(field_name, field_name)


def detect_flexible_time_request(user_text: str) -> bool:
    """Detect when user indicates they are flexible about time selection."""
    text = user_text.lower()
    return any(token in text for token in FLEXIBLE_TIME_TOKENS)


def detect_availability_query(user_text: str) -> bool:
    """Detect user intent to ask about available slots/times."""
    text = user_text.lower()
    return any(token in text for token in ["availability", "available", "free slot", "free time", "what times"])


def _extract_candidate_date(text: str) -> Optional[str]:
    """Extract likely date phrase for downstream parsing."""
    text_lower = text.lower().strip()

    for token in [
        "today",
        "tomorrow",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "next monday",
        "next tuesday",
        "next wednesday",
        "next thursday",
        "next friday",
        "next saturday",
        "next sunday",
    ]:
        if re.search(rf"\b{re.escape(token)}\b", text_lower):
            return token

    iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if iso:
        return iso.group(0)

    dmy = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b", text)
    if dmy:
        return dmy.group(0)

    month = re.search(
        r"\b\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?:\s+\d{4})?\b",
        text,
        flags=re.IGNORECASE,
    )
    if month:
        return month.group(0)

    return None


def _extract_candidate_time(text: str) -> Optional[str]:
    """Extract likely time phrase for downstream parsing."""
    text_lower = text.lower().strip()

    for keyword in ["noon", "midday", "midnight"]:
        if re.search(rf"\b{keyword}\b", text_lower):
            return keyword

    hhmm = re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", text_lower)
    if hhmm:
        return hhmm.group(0)

    ampm = re.search(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", text_lower)
    if ampm:
        return ampm.group(0)

    packed = re.search(r"\b\d{4}\b", text_lower)
    if packed:
        return packed.group(0)

    return None


def _extract_name(text: str) -> Optional[str]:
    """Extract likely person name from common introduction phrases."""
    lowered = text.lower()
    patterns = [
        r"\bmy name is\s+([a-z][a-z\s'\-]{1,50})\b",
        r"\bi am\s+([a-z][a-z\s'\-]{1,50})\b",
        r"\bi'm\s+([a-z][a-z\s'\-]{1,50})\b",
        r"\bthis is\s+([a-z][a-z\s'\-]{1,50})\b",
    ]
    disallowed = {"interested", "looking", "thinking", "ready", "from", "available"}

    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1).strip(" .,!?:;")
        tokens = [token for token in raw.split() if token]
        if not tokens:
            continue
        if any(token in disallowed for token in tokens):
            continue
        if len(tokens) > 4:
            continue
        return " ".join(token.capitalize() for token in tokens)

    return None


def _extract_treatment(text: str, clinic: dict[str, Any]) -> Optional[str]:
    """Match text against clinic treatment aliases."""
    lower = text.lower()

    aliases = {
        "botox": "Botox consultation",
        "lip filler": "Lip filler consultation",
        "filler": "Lip filler consultation",
        "skin booster": "Skin booster consultation",
        "facial aesthetics": "Facial aesthetics assessment",
        "assessment": "Facial aesthetics assessment",
    }

    for alias, treatment in aliases.items():
        if alias in lower:
            return treatment

    for treatment in clinic.get("treatments", []):
        if treatment.lower() in lower:
            return treatment

    return None


def extract_fields_from_message(
    user_text: str,
    current_state: dict[str, str],
    clinic: dict[str, Any],
) -> dict[str, str]:
    """Heuristically extract structured fields from user message."""
    updates: dict[str, str] = {}
    text = user_text.strip()
    lower = text.lower()

    treatment = _extract_treatment(text, clinic)
    if treatment:
        updates["treatment_interest"] = treatment

    if "consultation" in lower:
        updates["booking_type"] = "consultation"
    elif "assessment" in lower:
        updates["booking_type"] = "assessment"
    elif "follow up" in lower or "follow-up" in lower:
        updates["booking_type"] = "follow-up"

    timeframe = re.search(
        r"\b(asap|as soon as possible|today|tomorrow|this week|next week|this month|next month|in \d+ (?:day|days|week|weeks|month|months))\b",
        lower,
    )
    if timeframe:
        updates["timeframe"] = timeframe.group(0)

    date_candidate = _extract_candidate_date(text)
    if date_candidate:
        date_iso, _ = parse_date_to_iso(date_candidate)
        if date_iso:
            updates["preferred_date"] = date_iso
        else:
            updates["preferred_date"] = date_candidate

    time_candidate = _extract_candidate_time(text)
    if time_candidate:
        time_hhmm, _ = parse_time_to_hhmm(time_candidate)
        if time_hhmm:
            updates["preferred_time"] = time_hhmm
        else:
            updates["preferred_time"] = time_candidate

    name = _extract_name(text)
    if name:
        updates["name"] = name

    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if email:
        updates["email"] = email.group(0)

    phone = re.search(r"(\+?\d[\d\s\-\(\)]{8,}\d)", text)
    if phone:
        updates["phone"] = re.sub(r"\s+", " ", phone.group(1)).strip()

    if "note:" in lower or "notes:" in lower:
        split_note = re.split(r"notes?:", text, maxsplit=1, flags=re.IGNORECASE)
        if len(split_note) > 1:
            updates["notes"] = split_note[1].strip()

    if not updates.get("notes") and not current_state.get("notes"):
        if any(token in lower for token in ["allergy", "sensitive", "history", "concern"]):
            updates["notes"] = text[:350]

    return {field: value for field, value in updates.items() if field in BOOKING_FIELDS and value}


def build_system_prompt(
    clinic: dict[str, Any],
    state: dict[str, str],
    decision: dict[str, Any],
    validation_errors: dict[str, str],
    availability_context: dict[str, Any],
) -> str:
    """Build strict receptionist prompt constrained by Python decisions."""
    faq_text = "\n".join(f"- {k}: {v}" for k, v in clinic["faq"].items())
    treatments_text = ", ".join(clinic["treatments"])
    missing = decision.get("missing_fields", [])

    return f"""
You are the AI receptionist for {clinic['name']}.
Tone: concise, warm, professional. Ask one question at a time.

Non-negotiable behavior:
- Do not invent prices, treatment outcomes, or medical advice.
- If clinical/risky/out-of-scope, recommend speaking directly to the clinic.
- Do not ask for fields already captured.

Clinic:
- Name: {clinic['name']}
- Location: {clinic['location']}
- Opening hours: {clinic['opening_hours_text']}
- Slot length: {clinic['slot_length_minutes']} minutes
- Treatments: {treatments_text}
- FAQ:
{faq_text}

Python booking decision context:
- Action: {decision.get('action')}
- Status: {decision.get('status')}
- Reason: {reason_to_text(str(decision.get('reason')))}
- Missing fields: {', '.join(missing) if missing else 'none'}
- Next field to ask: {decision.get('next_field') or 'none'}

Validation errors:
{json.dumps(validation_errors, ensure_ascii=True)}

Availability context from DB:
{json.dumps(availability_context, ensure_ascii=True)}

Structured booking state:
{json.dumps(state, ensure_ascii=True)}

Response rules:
- If status confirmed: confirm the booked date/time clearly.
- If status booking_request: explain it is pending and a human will follow up.
- If action need_more_info: ask only one next question.
- If availability was asked, include up to 3 available times if present.
- Keep to 2-4 short sentences.
""".strip()


def fallback_assistant_reply(
    user_text: str,
    state: dict[str, str],
    decision: dict[str, Any],
    validation_errors: dict[str, str],
    availability_context: dict[str, Any],
) -> str:
    """Deterministic fallback response when model call/key is unavailable."""
    faq_reply = faq_answer_for_text(user_text)

    if decision.get("status") == "confirmed":
        return (
            f"Thanks {state.get('name') or ''}. Your booking is confirmed for "
            f"{state.get('preferred_date')} at {state.get('preferred_time')}. "
            "Our team will follow up shortly with final details."
        ).strip()

    if decision.get("status") == "booking_request":
        reason = decision.get("reason")
        if reason == "outside_business_hours":
            return (
                "That requested time is outside opening hours, so I have logged a pending booking request. "
                "Our team will contact you with suitable alternatives."
            )
        if reason in {"slot_occupied", "no_slots_on_date"}:
            preview = availability_context.get("available_slots_preview") or []
            if preview:
                options = ", ".join(preview[:3])
                return (
                    "That slot is not currently available, so I have logged a pending booking request. "
                    f"The closest free times on that date include {options}."
                )
            return (
                "That slot is not currently available, so I have logged a pending booking request. "
                "Our team will propose alternatives."
            )
        return (
            "I have logged this as a pending booking request because some details are still incomplete. "
            "Our team will follow up to complete it."
        )

    if validation_errors:
        first_field = next(iter(validation_errors))
        return (
            f"I couldn't validate your {field_label(first_field)}. "
            f"{validation_errors[first_field]} Could you resend it?"
        )

    if detect_availability_query(user_text):
        preview = availability_context.get("available_slots_preview") or []
        target_date = availability_context.get("date") or state.get("preferred_date")
        if preview:
            return (
                f"On {target_date}, available times include {', '.join(preview[:3])}. "
                "Which time would you like?"
            )

    next_field = decision.get("next_field") or "preferred_date"
    question = f"Could you share your {field_label(next_field)}?"
    if faq_reply:
        return f"{faq_reply} {question}"
    return question


def generate_assistant_reply(
    user_text: str,
    clinic: dict[str, Any],
    history: list[dict[str, str]],
    state: dict[str, str],
    decision: dict[str, Any],
    validation_errors: dict[str, str],
    availability_context: dict[str, Any],
) -> str:
    """Generate assistant reply with model, fallback to deterministic template."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return fallback_assistant_reply(
            user_text=user_text,
            state=state,
            decision=decision,
            validation_errors=validation_errors,
            availability_context=availability_context,
        )

    prompt = build_system_prompt(
        clinic=clinic,
        state=state,
        decision=decision,
        validation_errors=validation_errors,
        availability_context=availability_context,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
    for item in history[-24:]:
        role = item.get("role", "assistant")
        if role not in {"assistant", "user", "system"}:
            continue
        messages.append({"role": role, "content": item.get("content", "")})

    try:
        model_name = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.2,
            messages=messages,
        )
        text = (response.choices[0].message.content or "").strip()
        if text:
            return text
    except Exception:
        pass

    return fallback_assistant_reply(
        user_text=user_text,
        state=state,
        decision=decision,
        validation_errors=validation_errors,
        availability_context=availability_context,
    )
