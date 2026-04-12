"""Chat page flow and deterministic booking orchestration."""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

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
    find_first_available_slot,
    list_available_slots,
    merge_booking_state,
    normalize_and_validate_state,
    reason_to_text,
)
from frontend.components import render_chat_mode_hint


def render_chat_history(messages: list[dict[str, Any]]) -> None:
    """Render transcript in Streamlit chat UI."""
    for msg in messages:
        role = msg.get("role", "assistant")
        if role not in {"assistant", "user"}:
            continue
        with st.chat_message(role):
            st.markdown(msg.get("content", ""))


def build_confirmation_notice(state: dict[str, str]) -> str:
    """Return deterministic confirmation-sent notice for confirmed bookings."""
    email = state.get("email", "").strip()
    phone = state.get("phone", "").strip()

    if email and phone:
        return f"A confirmation has been sent to {email} and {phone}."
    if email:
        return f"A confirmation has been sent to {email}."
    if phone:
        return f"A confirmation has been sent to {phone}."
    return "A confirmation has been sent to your contact details."


def process_user_message(
    conversation_id: int,
    clinic: dict[str, Any],
    user_text: str,
    auth_user: dict[str, Any],
    member_bonus_active: bool,
) -> None:
    """Process one conversation turn with deterministic booking logic + persisted state."""
    db.add_message(conversation_id, "user", user_text)

    existing_state = db.get_lead(conversation_id) or empty_booking_state()
    extracted = extract_fields_from_message(user_text, existing_state, clinic)
    merged_state = merge_booking_state(existing_state, extracted)
    normalized_state, validation_errors = normalize_and_validate_state(merged_state)

    # Member bonus: prefill known profile details to reduce friction.
    if member_bonus_active:
        profile_name = str(auth_user.get("full_name", "")).strip()
        profile_email = str(auth_user.get("email", "")).strip()

        if profile_name and profile_name.lower() not in {"guest", "signed in user", "member"}:
            if not normalized_state.get("name"):
                normalized_state["name"] = profile_name

        if profile_email and not normalized_state.get("email"):
            normalized_state["email"] = profile_email

        notes = normalized_state.get("notes", "")
        if "member bonus" not in notes.lower():
            normalized_state["notes"] = (
                f"{notes} | Member bonus: priority follow-up.".strip(" |") if notes else "Member bonus: priority follow-up."
            )

        normalized_state, validation_errors = normalize_and_validate_state(normalized_state)

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
    existing_booking = db.get_booking_for_conversation(conversation_id)

    booking_notes = normalized_state.get("notes", "")
    if member_bonus_active and decision.get("status") == "booking_request":
        if "priority member" not in booking_notes.lower():
            booking_notes = (
                f"{booking_notes} | Priority member booking request.".strip(" |")
                if booking_notes
                else "Priority member booking request."
            )

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
                "notes": booking_notes,
            },
        )
    elif existing_booking and existing_booking.get("status") == "booking_request":
        # Clear stale pending outcome while still gathering required information.
        db.delete_booking_for_conversation(conversation_id)

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

    # Ensure confirmed bookings always include a clear confirmation-delivered notice.
    if decision.get("status") == "confirmed":
        notice = build_confirmation_notice(normalized_state)
        if notice.lower() not in assistant_text.lower():
            assistant_text = f"{assistant_text} {notice}".strip()
        if member_bonus_active:
            perk_msg = "Your member bonus has been applied with priority support for any changes."
            if perk_msg.lower() not in assistant_text.lower():
                assistant_text = f"{assistant_text} {perk_msg}".strip()
    elif decision.get("status") == "booking_request" and member_bonus_active:
        perk_msg = "As a signed-in member, your pending request has been marked priority."
        if perk_msg.lower() not in assistant_text.lower():
            assistant_text = f"{assistant_text} {perk_msg}".strip()

    db.add_message(conversation_id, "assistant", assistant_text)


def render_chat_tab(
    clinic: dict[str, Any],
    conversation_id: int,
    auth_user: dict[str, Any],
    member_bonus_active: bool,
    guest_mode: bool,
    on_new_conversation: Callable[[], int],
) -> None:
    """Render receptionist chat flow and live structured outcome state."""
    st.subheader("Reception Chat")
    render_chat_mode_hint(member_bonus_active=member_bonus_active, guest_mode=guest_mode)

    left, right = st.columns([1, 1])
    with left:
        if st.button("Start new conversation", use_container_width=True):
            st.session_state.conversation_id = int(on_new_conversation())
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
        process_user_message(
            conversation_id=conversation_id,
            clinic=clinic,
            user_text=user_text,
            auth_user=auth_user,
            member_bonus_active=member_bonus_active,
        )
        st.rerun()
