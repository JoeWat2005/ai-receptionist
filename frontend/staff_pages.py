"""Staff-facing pages: calendar, dashboard, leads, bookings, conversations."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
import streamlit as st

import db
from booking_logic import empty_booking_state, list_available_slots, reason_to_text
from clinic_data import DAY_LABELS, DAY_ORDER, business_hours_to_text
from services.calling import build_local_voice_reply, build_outbound_call_request
from services.phone_ai import (
    build_phone_agent_prompt,
    evaluate_phone_booking,
    extract_state_from_transcript,
    summarize_call_result,
)


def _hhmm_to_time(hhmm: str) -> time:
    """Convert HH:MM string to datetime.time."""
    return datetime.strptime(hhmm, "%H:%M").time()


def _time_to_hhmm(value: time) -> str:
    """Convert datetime.time to HH:MM string."""
    return value.strftime("%H:%M")


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


def render_staff_overview(clinic: dict[str, Any]) -> None:
    """Render operational widgets and a short bookings trend chart for staff."""
    today_iso = date.today().isoformat()
    today_confirmed = db.get_confirmed_bookings_for_date(clinic["id"], today_iso)
    today_available = list_available_slots(
        date_iso=today_iso,
        business_hours=clinic["business_hours"],
        slot_length_minutes=int(clinic["slot_length_minutes"]),
        confirmed_bookings=today_confirmed,
    )

    m1, m2, m3 = st.columns(3)
    m1.metric("Today confirmed", len(today_confirmed))
    m2.metric("Today free slots", len(today_available))
    m3.metric("Appointment slot length", f"{int(clinic['slot_length_minutes'])} min")

    trend_rows = db.get_confirmed_booking_trend(clinic["id"], days=14)
    if trend_rows:
        st.markdown("**Confirmed bookings trend (last 14 days)**")
        trend_df = pd.DataFrame(trend_rows)
        st.line_chart(data=trend_df, x="date", y="confirmed_count", use_container_width=True)


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


def _render_business_onboarding(clinic: dict[str, Any]) -> None:
    """Render business onboarding profile form."""
    st.markdown("### Business Onboarding")
    if clinic.get("onboarding_completed"):
        st.success("Onboarding is marked complete.")
    else:
        st.warning("Onboarding is not complete yet. Fill business profile details below.")

    with st.form("business_onboarding_form"):
        contact_name = st.text_input(
            "Business contact name",
            value=str(clinic.get("business_contact_name") or ""),
        )
        contact_email = st.text_input(
            "Business contact email",
            value=str(clinic.get("business_contact_email") or ""),
        )
        contact_phone = st.text_input(
            "Business contact phone",
            value=str(clinic.get("business_contact_phone") or ""),
        )
        website = st.text_input(
            "Business website (optional)",
            value=str(clinic.get("business_website") or ""),
        )
        onboarding_notes = st.text_area(
            "Onboarding notes",
            value=str(clinic.get("onboarding_notes") or ""),
            height=110,
        )
        onboarding_completed = st.checkbox(
            "Mark onboarding complete",
            value=bool(clinic.get("onboarding_completed")),
        )

        save = st.form_submit_button("Save business onboarding", use_container_width=True)

    if save:
        db.update_clinic_onboarding(
            clinic_id=clinic["id"],
            business_contact_name=contact_name,
            business_contact_email=contact_email,
            business_contact_phone=contact_phone,
            business_website=website,
            onboarding_notes=onboarding_notes,
            onboarding_completed=onboarding_completed,
        )
        st.success("Business onboarding profile saved.")
        st.rerun()


def _render_operating_settings(clinic: dict[str, Any]) -> None:
    """Render business hours and slot length settings."""
    st.markdown("### Operating Settings")
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

        submitted = st.form_submit_button("Save operating settings", use_container_width=True)

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
        st.success("Operating settings saved.")
        st.rerun()

    st.markdown(f"**Current opening hours:** {clinic.get('opening_hours_text', '')}")
    st.markdown(f"**Current slot length:** {clinic.get('slot_length_minutes', 30)} minutes")


def _render_business_accounts(clinic: dict[str, Any]) -> None:
    """Render staff/customer account overview and role-management controls."""
    st.markdown("### Business Accounts")
    st.caption("Staff can access operations tabs. Customers only access chat.")

    filter_role = st.selectbox("Filter accounts", options=["all", "staff", "customer"], index=0)
    role_arg = None if filter_role == "all" else filter_role
    accounts = db.list_business_accounts(clinic_id=clinic["id"], role=role_arg)

    if accounts:
        st.dataframe(accounts, use_container_width=True, hide_index=True)
    else:
        st.info("No stored accounts yet. Accounts are created automatically after sign-in.")

    with st.form("update_account_role_form"):
        email = st.text_input("Email to update role")
        role = st.selectbox("New role", options=["customer", "staff"], index=0)
        update = st.form_submit_button("Update role", use_container_width=True)

    if update:
        ok = db.set_business_account_role(clinic_id=clinic["id"], email=email, role=role)
        if ok:
            st.success(f"Updated {email.strip().lower()} to role: {role}")
            st.rerun()
        else:
            st.error("No account row was updated. Ask the user to sign in once first.")


def _render_calling_scaffold(clinic: dict[str, Any]) -> None:
    """Render local phone-call processing scaffold panel."""
    st.markdown("### AI Phone Calling Scaffold")
    st.caption("Local scaffold only: use this to process sample call transcripts and store structured call logs.")

    with st.expander("Voice agent starter prompt", expanded=False):
        st.code(build_phone_agent_prompt(clinic), language="text")

    with st.expander("Outbound call payload scaffold", expanded=False):
        to_number = st.text_input("To number", value="+447700900123", key="call_to_number")
        from_number = st.text_input("From number", value="+441610000000", key="call_from_number")
        intro = st.text_area(
            "Intro script",
            value="Hi, this is Glow Aesthetics Clinic calling to confirm your consultation details.",
            key="call_intro_script",
        )
        payload = build_outbound_call_request(to_number=to_number, from_number=from_number, intro_script=intro)
        st.json(payload)
        st.code(build_local_voice_reply(intro), language="xml")

    st.markdown("**Process inbound call transcript**")
    with st.form("call_transcript_form"):
        direction = st.selectbox("Call direction", options=["inbound", "outbound"], index=0)
        caller_name = st.text_input("Caller name")
        phone_number = st.text_input("Caller phone")
        transcript = st.text_area(
            "Transcript",
            placeholder="Paste transcript lines here...",
            height=180,
        )
        submit = st.form_submit_button("Process call transcript", use_container_width=True)

    if submit:
        normalized_state = extract_state_from_transcript(
            transcript=transcript,
            clinic=clinic,
            current_state=empty_booking_state(),
        )
        date_iso = normalized_state.get("preferred_date", "")
        confirmed_bookings = (
            db.get_confirmed_bookings_for_date(clinic_id=clinic["id"], date_iso=date_iso) if date_iso else []
        )
        normalized_state, validation_errors, decision = evaluate_phone_booking(
            state=normalized_state,
            clinic=clinic,
            confirmed_bookings=confirmed_bookings,
        )
        summary = summarize_call_result(normalized_state, decision)

        db.add_phone_call(
            clinic_id=clinic["id"],
            direction=direction,
            phone_number=phone_number,
            caller_name=caller_name,
            status=decision.get("status") or "needs_follow_up",
            transcript=transcript,
            extracted_state=normalized_state,
            decision=decision,
            notes=summary,
        )

        st.success("Call processed and logged.")
        st.markdown(f"**Summary:** {summary}")
        if validation_errors:
            st.warning("Validation issues were detected:")
            st.json(validation_errors)
        st.json({"state": normalized_state, "decision": decision})

    st.markdown("**Recent call logs**")
    calls = db.list_phone_calls(clinic_id=clinic["id"], limit=50)
    if calls:
        st.dataframe(calls, use_container_width=True, hide_index=True)
    else:
        st.info("No call logs yet.")


def render_dashboard_tab(clinic: dict[str, Any]) -> None:
    """Render combined staff dashboard sections."""
    st.subheader("Dashboard")
    _render_business_onboarding(clinic)
    st.divider()
    _render_operating_settings(clinic)
    st.divider()
    _render_business_accounts(clinic)
    st.divider()
    _render_calling_scaffold(clinic)


def render_leads_tab() -> None:
    """Staff lead table."""
    st.subheader("Leads")
    leads = db.list_leads()
    if not leads:
        st.info("No leads captured yet.")
        return
    st.dataframe(leads, use_container_width=True, hide_index=True)


def render_bookings_tab(clinic: dict[str, Any]) -> None:
    """Staff bookings table with status filter and export."""
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
    """Staff conversation list with transcript viewer."""
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


def render_bookings_status_pill() -> None:
    """Compatibility stub for potential future widget extraction."""
    return
