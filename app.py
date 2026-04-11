"""Streamlit UI orchestration for the modular AI receptionist MVP."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

import db
from ai_logic import (
    detect_availability_query,
    detect_flexible_time_request,
    extract_fields_from_message,
    generate_assistant_reply,
)
from booking_logic import (
    decide_booking_outcome,
    empty_booking_state,
    list_available_slots,
    merge_booking_state,
    normalize_and_validate_state,
    reason_to_text,
    find_first_available_slot,
)
from clinic_data import DAY_LABELS, DAY_ORDER, DEFAULT_CLINIC, business_hours_to_text

def load_env_settings() -> None:
    """Load .env from project root and repair BOM-prefixed keys if present."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    # Some editors/shell commands write UTF-8 BOM; dotenv then sets a BOM-prefixed key.
    bom_key = "\ufeffOPENAI_API_KEY"
    if not os.getenv("OPENAI_API_KEY") and os.getenv(bom_key):
        os.environ["OPENAI_API_KEY"] = os.getenv(bom_key, "")


load_env_settings()

WELCOME_TEMPLATE = "Hi, welcome to {clinic_name}. How can I help today?"


def _hhmm_to_time(hhmm: str) -> time:
    """Convert HH:MM string to datetime.time."""
    return datetime.strptime(hhmm, "%H:%M").time()


def _time_to_hhmm(value: time) -> str:
    """Convert datetime.time to HH:MM string."""
    return value.strftime("%H:%M")


def bootstrap_clinic() -> dict[str, Any]:
    """Initialize DB, seed clinic, and return the latest clinic settings."""
    db.init_db()
    clinic_id = db.ensure_default_clinic(DEFAULT_CLINIC)
    clinic = db.get_clinic(clinic_id)
    clinic["id"] = clinic_id
    return clinic


def start_new_conversation(clinic: dict[str, Any]) -> int:
    """Create new conversation and seed the opening assistant greeting."""
    conversation_id = db.create_conversation(clinic["id"])
    db.add_message(
        conversation_id,
        "assistant",
        WELCOME_TEMPLATE.format(clinic_name=clinic["name"]),
    )
    return conversation_id


def ensure_session_conversation(clinic: dict[str, Any]) -> int:
    """Ensure user session points to a valid active conversation."""
    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = start_new_conversation(clinic)
    return int(st.session_state.conversation_id)


def build_ics_for_bookings(clinic: dict[str, Any], bookings: list[dict[str, Any]]) -> str:
    """Create an iCalendar payload for confirmed bookings."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GlowAesthetics//AIReceptionist//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    tzid = clinic.get("timezone", "Europe/London")
    now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    for booking in bookings:
        booking_date = booking.get("preferred_date")
        booking_time = booking.get("preferred_time")
        if not booking_date or not booking_time:
            continue

        duration = int(booking.get("duration_minutes") or clinic.get("slot_length_minutes") or 30)
        start_dt = datetime.strptime(f"{booking_date} {booking_time}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration)

        booking_id = booking.get("id") or booking.get("conversation_id") or "x"
        summary = f"{clinic['name']} - {booking.get('treatment_interest') or 'Consultation'}"
        description = (
            f"Status: {booking.get('status', 'confirmed')}"
            f"\\nName: {booking.get('name', '')}"
            f"\\nPhone: {booking.get('phone', '')}"
            f"\\nEmail: {booking.get('email', '')}"
        )

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:booking-{booking_id}@glow-local",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;TZID={tzid}:{start_dt.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={tzid}:{end_dt.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def render_chat_history(messages: list[dict[str, Any]]) -> None:
    """Render transcript in Streamlit chat UI."""
    for msg in messages:
        role = msg.get("role", "assistant")
        if role not in {"assistant", "user"}:
            continue
        with st.chat_message(role):
            st.markdown(msg.get("content", ""))


def process_user_message(conversation_id: int, clinic: dict[str, Any], user_text: str) -> None:
    """Process one conversation turn with deterministic booking logic + persisted state."""
    db.add_message(conversation_id, "user", user_text)

    existing_state = db.get_lead(conversation_id) or empty_booking_state()
    extracted = extract_fields_from_message(user_text, existing_state, clinic)
    merged_state = merge_booking_state(existing_state, extracted)
    normalized_state, validation_errors = normalize_and_validate_state(merged_state)

    flexible_time = detect_flexible_time_request(user_text)
    availability_query = detect_availability_query(user_text)

    date_iso = normalized_state.get("preferred_date", "")
    confirmed_bookings_for_date: list[dict[str, Any]] = []
    available_slots_for_date: list[str] = []
    auto_assigned_time = ""

    if date_iso and "preferred_date" not in validation_errors:
        confirmed_bookings_for_date = db.get_confirmed_bookings_for_date(
            clinic_id=clinic["id"],
            date_iso=date_iso,
            exclude_conversation_id=conversation_id,
        )

        available_slots_for_date = list_available_slots(
            date_iso=date_iso,
            business_hours=clinic["business_hours"],
            slot_length_minutes=int(clinic["slot_length_minutes"]),
            confirmed_bookings=confirmed_bookings_for_date,
        )

        # If user is flexible and gave a day without a specific valid time, auto-pick earliest free slot.
        if flexible_time and not normalized_state.get("preferred_time") and available_slots_for_date:
            suggested = find_first_available_slot(
                date_iso=date_iso,
                business_hours=clinic["business_hours"],
                slot_length_minutes=int(clinic["slot_length_minutes"]),
                confirmed_bookings=confirmed_bookings_for_date,
            )
            if suggested:
                normalized_state["preferred_time"] = suggested
                auto_assigned_time = suggested

    # Re-normalize once after potential auto-assignment.
    normalized_state, validation_errors = normalize_and_validate_state(normalized_state)

    # Refresh same-day booking list if date is valid.
    date_iso = normalized_state.get("preferred_date", "")
    if date_iso and "preferred_date" not in validation_errors:
        confirmed_bookings_for_date = db.get_confirmed_bookings_for_date(
            clinic_id=clinic["id"],
            date_iso=date_iso,
            exclude_conversation_id=conversation_id,
        )
        available_slots_for_date = list_available_slots(
            date_iso=date_iso,
            business_hours=clinic["business_hours"],
            slot_length_minutes=int(clinic["slot_length_minutes"]),
            confirmed_bookings=confirmed_bookings_for_date,
        )
    else:
        confirmed_bookings_for_date = []
        available_slots_for_date = []

    decision = decide_booking_outcome(
        state=normalized_state,
        validation_errors=validation_errors,
        business_hours=clinic["business_hours"],
        slot_length_minutes=int(clinic["slot_length_minutes"]),
        confirmed_bookings=confirmed_bookings_for_date,
    )

    lead_id = db.upsert_lead(conversation_id, clinic["id"], normalized_state)

    if decision["action"] == "create_outcome":
        db.upsert_booking(
            conversation_id=conversation_id,
            clinic_id=clinic["id"],
            lead_id=lead_id,
            booking_payload={
                "treatment_interest": normalized_state.get("treatment_interest", ""),
                "booking_type": normalized_state.get("booking_type", ""),
                "preferred_date": normalized_state.get("preferred_date", ""),
                "preferred_time": normalized_state.get("preferred_time", ""),
                "duration_minutes": int(clinic["slot_length_minutes"]),
                "status": decision.get("status", "booking_request"),
                "outcome_reason": decision.get("reason", "incomplete_details"),
                "notes": normalized_state.get("notes", ""),
            },
        )

    availability_context = {
        "date": date_iso,
        "asked_for_availability": availability_query,
        "available_slots_count": len(available_slots_for_date),
        "available_slots_preview": available_slots_for_date[:6],
        "auto_assigned_time": auto_assigned_time,
    }

    history = db.get_messages(conversation_id)
    assistant_text = generate_assistant_reply(
        user_text=user_text,
        clinic=clinic,
        history=history,
        state=normalized_state,
        decision=decision,
        validation_errors=validation_errors,
        availability_context=availability_context,
    )
    db.add_message(conversation_id, "assistant", assistant_text)


def render_chat_tab(clinic: dict[str, Any], conversation_id: int) -> None:
    """Render receptionist chat flow and live structured outcome state."""
    st.subheader("Reception Chat")

    left, right = st.columns([1, 1])
    with left:
        if st.button("Start new conversation", use_container_width=True):
            st.session_state.conversation_id = start_new_conversation(clinic)
            st.rerun()
    with right:
        st.caption(f"Conversation ID: {conversation_id}")

    messages = db.get_messages(conversation_id)
    render_chat_history(messages)

    state = db.get_lead(conversation_id) or empty_booking_state()
    _, validation_errors = normalize_and_validate_state(state)
    booking = db.get_booking_for_conversation(conversation_id)

    st.divider()
    st.subheader("Current extracted structured booking state")
    st.json(state)

    if validation_errors:
        st.warning("Some inputs are malformed and need correction.")
        st.json(validation_errors)

    if booking:
        status = booking.get("status", "booking_request")
        if status == "confirmed":
            st.success(
                f"Final outcome: CONFIRMED for {booking.get('preferred_date')} at {booking.get('preferred_time')}"
            )
        else:
            st.info("Final outcome: BOOKING REQUEST (pending human follow-up)")
        st.caption(f"Reason: {reason_to_text(str(booking.get('outcome_reason', '')))}")

    date_iso = state.get("preferred_date", "")
    if date_iso:
        confirmed = db.get_confirmed_bookings_for_date(clinic["id"], date_iso)
        slots = list_available_slots(
            date_iso=date_iso,
            business_hours=clinic["business_hours"],
            slot_length_minutes=int(clinic["slot_length_minutes"]),
            confirmed_bookings=confirmed,
        )
        st.caption(f"Availability on {date_iso}: {', '.join(slots[:8]) if slots else 'No free slots'}")

    user_text = st.chat_input("Type a message to the receptionist...")
    if user_text:
        process_user_message(conversation_id, clinic, user_text)
        st.rerun()


def render_calendar_tab(clinic: dict[str, Any]) -> None:
    """Calendar integration view with date availability and ICS export."""
    st.subheader("Calendar")

    selected_date = st.date_input("Select date", value=date.today())
    date_iso = selected_date.isoformat()

    confirmed = db.get_confirmed_bookings_for_date(clinic_id=clinic["id"], date_iso=date_iso)
    available = list_available_slots(
        date_iso=date_iso,
        business_hours=clinic["business_hours"],
        slot_length_minutes=int(clinic["slot_length_minutes"]),
        confirmed_bookings=confirmed,
    )

    metric_a, metric_b = st.columns(2)
    metric_a.metric("Confirmed bookings", len(confirmed))
    metric_b.metric("Available slots", len(available))

    st.markdown("**Available times**")
    if available:
        st.write(", ".join(available))
    else:
        st.write("No available slots for this date.")

    st.markdown("**Confirmed bookings**")
    if confirmed:
        st.dataframe(confirmed, use_container_width=True, hide_index=True)
        ics = build_ics_for_bookings(clinic, confirmed)
        st.download_button(
            "Download day calendar (.ics)",
            data=ics,
            file_name=f"{clinic['name'].replace(' ', '_').lower()}_{date_iso}.ics",
            mime="text/calendar",
            use_container_width=True,
        )
    else:
        st.info("No confirmed bookings on this date.")


def render_dashboard_tab(clinic: dict[str, Any]) -> None:
    """Clinic settings dashboard for opening times and slot length."""
    st.subheader("Clinic Dashboard")
    st.caption("Adjust opening times and slot length used by booking/availability logic.")

    with st.form("clinic_settings_form"):
        slot_length = st.number_input(
            "Slot length (minutes)",
            min_value=10,
            max_value=180,
            value=int(clinic.get("slot_length_minutes") or 30),
            step=5,
        )

        updated_hours: dict[str, dict[str, str] | None] = {}

        for day in DAY_ORDER:
            current_hours = clinic["business_hours"].get(day)
            day_cols = st.columns([1, 1, 1])

            with day_cols[0]:
                closed = st.checkbox(
                    f"{DAY_LABELS[day]} closed",
                    value=current_hours is None,
                    key=f"closed_{day}",
                )

            if closed:
                updated_hours[day] = None
                with day_cols[1]:
                    st.caption("Closed")
                with day_cols[2]:
                    st.caption("Closed")
                continue

            default_open = (current_hours or {"open": "09:00"})["open"]
            default_close = (current_hours or {"close": "17:00"})["close"]

            with day_cols[1]:
                open_time = st.time_input(
                    f"{DAY_LABELS[day]} open",
                    value=_hhmm_to_time(default_open),
                    key=f"open_{day}",
                )
            with day_cols[2]:
                close_time = st.time_input(
                    f"{DAY_LABELS[day]} close",
                    value=_hhmm_to_time(default_close),
                    key=f"close_{day}",
                )

            updated_hours[day] = {
                "open": _time_to_hhmm(open_time),
                "close": _time_to_hhmm(close_time),
            }

        submitted = st.form_submit_button("Save clinic settings", use_container_width=True)

    if submitted:
        invalid_days: list[str] = []
        for day in DAY_ORDER:
            hours = updated_hours.get(day)
            if hours is None:
                continue
            if _hhmm_to_time(hours["close"]) <= _hhmm_to_time(hours["open"]):
                invalid_days.append(DAY_LABELS[day])

        if invalid_days:
            st.error(f"Closing time must be after opening time for: {', '.join(invalid_days)}")
            return

        opening_text = business_hours_to_text(updated_hours)
        db.update_clinic_settings(
            clinic_id=clinic["id"],
            business_hours=updated_hours,
            opening_hours_text=opening_text,
            slot_length_minutes=int(slot_length),
            timezone=clinic.get("timezone", "Europe/London"),
        )
        st.success("Clinic settings saved. Booking availability now uses the new settings.")
        st.rerun()

    st.markdown(f"**Current opening hours:** {clinic.get('opening_hours_text', '')}")
    st.markdown(f"**Current slot length:** {clinic.get('slot_length_minutes', 30)} minutes")


def render_leads_tab() -> None:
    """Admin lead table."""
    st.subheader("Leads")
    leads = db.list_leads()
    if not leads:
        st.info("No leads captured yet.")
        return
    st.dataframe(leads, use_container_width=True, hide_index=True)


def render_bookings_tab(clinic: dict[str, Any]) -> None:
    """Admin bookings table with status filter and export."""
    st.subheader("Bookings")

    filter_status = st.selectbox(
        "Filter by status",
        options=["all", "confirmed", "booking_request"],
        index=0,
    )

    status_query = None if filter_status == "all" else filter_status
    bookings = db.list_bookings(status=status_query)

    if not bookings:
        st.info("No bookings found for this filter.")
        return

    st.dataframe(bookings, use_container_width=True, hide_index=True)

    confirmed = [b for b in bookings if b.get("status") == "confirmed"]
    if confirmed:
        ics = build_ics_for_bookings(clinic, confirmed)
        st.download_button(
            "Download confirmed bookings (.ics)",
            data=ics,
            file_name="confirmed_bookings.ics",
            mime="text/calendar",
            use_container_width=True,
        )


def render_conversations_tab(active_conversation_id: int) -> None:
    """Admin conversation list with transcript viewer."""
    st.subheader("Conversations")

    conversations = db.list_conversations()
    if not conversations:
        st.info("No conversations yet.")
        return

    st.dataframe(conversations, use_container_width=True, hide_index=True)

    options = [int(item["id"]) for item in conversations]
    default_index = options.index(active_conversation_id) if active_conversation_id in options else 0

    selected_id = st.selectbox(
        "Select conversation",
        options=options,
        index=default_index,
        format_func=lambda cid: f"Conversation {cid}",
    )

    transcript = db.get_messages(int(selected_id))
    st.markdown("**Latest transcript**")
    if not transcript:
        st.info("No messages for this conversation.")
        return

    for row in transcript[-80:]:
        st.markdown(f"**{row['role'].title()}** ({row['created_at']}): {row['content']}")


def main() -> None:
    st.set_page_config(page_title="AI Receptionist Booking MVP", page_icon=":calendar:")
    st.title("Glow Aesthetics Clinic - AI Receptionist Booking MVP")

    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "OPENAI_API_KEY is missing. The app still works with deterministic fallback responses."
        )

    clinic = bootstrap_clinic()
    conversation_id = ensure_session_conversation(clinic)

    chat_tab, calendar_tab, dashboard_tab, leads_tab, bookings_tab, conversations_tab = st.tabs(
        ["Chat", "Calendar", "Dashboard", "Leads", "Bookings", "Conversations"]
    )

    with chat_tab:
        render_chat_tab(clinic, conversation_id)

    with calendar_tab:
        render_calendar_tab(clinic)

    with dashboard_tab:
        render_dashboard_tab(clinic)

    with leads_tab:
        render_leads_tab()

    with bookings_tab:
        render_bookings_tab(clinic)

    with conversations_tab:
        render_conversations_tab(conversation_id)


if __name__ == "__main__":
    main()
