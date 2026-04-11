"""Streamlit UI orchestration for the modular AI receptionist MVP."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from auth import (
    auth_provider,
    clerk_oidc_is_configured,
    get_authenticated_user_from_streamlit,
    is_admin_user,
    streamlit_user_is_logged_in,
)
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


def _toml_escape(value: str) -> str:
    """Escape string for safe TOML double-quoted value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_streamlit_secrets_from_env() -> str:
    """
    Build Streamlit OIDC secrets TOML from environment variables.

    Required:
      - CLERK_CLIENT_ID (or NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY)
      - CLERK_CLIENT_SECRET (or CLERK_SECRET_KEY)
      - CLERK_SERVER_METADATA_URL (or CLERK_FRONTEND_API_URL)
      - STREAMLIT_COOKIE_SECRET
    Optional:
      - STREAMLIT_REDIRECT_URI (default localhost callback)
    """
    client_id = (
        os.getenv("CLERK_CLIENT_ID", "").strip()
        or os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "").strip()
    )
    client_secret = (
        os.getenv("CLERK_CLIENT_SECRET", "").strip()
        or os.getenv("CLERK_SECRET_KEY", "").strip()
    )
    server_metadata_url = os.getenv("CLERK_SERVER_METADATA_URL", "").strip()
    frontend_api_url = os.getenv("CLERK_FRONTEND_API_URL", "").strip().rstrip("/")
    if not server_metadata_url and frontend_api_url:
        server_metadata_url = f"{frontend_api_url}/.well-known/openid-configuration"

    redirect_uri = os.getenv("STREAMLIT_REDIRECT_URI", "http://localhost:8501/oauth2callback").strip()
    cookie_secret = os.getenv("STREAMLIT_COOKIE_SECRET", "").strip()

    required_values = [client_id, client_secret, server_metadata_url, cookie_secret]
    if not all(required_values):
        return ""

    lines = [
        "[auth]",
        f'redirect_uri = "{_toml_escape(redirect_uri)}"',
        f'cookie_secret = "{_toml_escape(cookie_secret)}"',
        "",
        "[auth.clerk]",
        f'client_id = "{_toml_escape(client_id)}"',
        f'client_secret = "{_toml_escape(client_secret)}"',
        f'server_metadata_url = "{_toml_escape(server_metadata_url)}"',
        "",
    ]
    return "\n".join(lines)


def ensure_streamlit_secrets_from_env() -> None:
    """Write `.streamlit/secrets.toml` from `.env` for Clerk OIDC login."""
    if auth_provider() != "clerk":
        return

    toml_content = _build_streamlit_secrets_from_env()
    if not toml_content:
        return

    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = secrets_path.read_text(encoding="utf-8") if secrets_path.exists() else ""
        if existing != toml_content:
            secrets_path.write_text(toml_content, encoding="utf-8")
    except OSError:
        # Auth helper will surface a readable setup error in the sidebar.
        return


def load_env_settings() -> None:
    """Load .env from project root and repair BOM-prefixed keys if present."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path, override=False)

    # Some editors/shell commands write UTF-8 BOM; dotenv then sets a BOM-prefixed key.
    bom_key = "\ufeffOPENAI_API_KEY"
    if not os.getenv("OPENAI_API_KEY") and os.getenv(bom_key):
        os.environ["OPENAI_API_KEY"] = os.getenv(bom_key, "")

    # Keep Clerk setup in one .env file by generating Streamlit OIDC secrets automatically.
    ensure_streamlit_secrets_from_env()


load_env_settings()

WELCOME_TEMPLATE = "Hi, welcome to {clinic_name}. How can I help today?"


def apply_app_styles() -> None:
    """Apply a cleaner visual theme for demo-ready presentation."""
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Sans:wght@400;500;700&display=swap');

:root {
  --bg: #f5f7fb;
  --panel: #ffffff;
  --ink: #1e2547;
  --muted: #5c6384;
  --brand: #2563eb;
  --accent: #0ea5a4;
  --line: #e4e8f3;
}

.stApp {
  background:
    radial-gradient(1100px 500px at -10% -20%, #dbeafe 0%, transparent 60%),
    radial-gradient(900px 450px at 110% -25%, #ccfbf1 0%, transparent 55%),
    var(--bg);
}

h1, h2, h3, h4 {
  font-family: 'Space Grotesk', sans-serif !important;
  color: var(--ink);
}

div, p, span, label, input, textarea, button {
  font-family: 'DM Sans', sans-serif !important;
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #f9fbff 0%, #f3f6ff 100%);
  border-right: 1px solid var(--line);
}

[data-testid="stMetric"] {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 8px 12px;
}

[data-testid="stDataFrame"], .stTabs [data-baseweb="tab-panel"] {
  background: var(--panel);
  border-radius: 14px;
}

div.stButton > button {
  border-radius: 12px;
  border: 1px solid #d7ddf0;
}

.hero {
  background: linear-gradient(120deg, #1e40af 0%, #0f766e 100%);
  border-radius: 18px;
  padding: 22px 24px;
  color: #f8fbff;
  margin-bottom: 10px;
  box-shadow: 0 10px 24px rgba(31, 41, 55, 0.18);
}

.hero h1 {
  color: #f8fbff !important;
  margin: 0 0 4px 0;
}

.hero-sub {
  color: #e6eefc;
  margin: 0;
}

.pill-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.pill {
  display: inline-block;
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  color: #f8fbff;
  font-size: 0.82rem;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_header(clinic: dict[str, Any], auth_user: dict[str, Any], admin_mode: bool) -> None:
    """Render branded app header with quick clinic and user context."""
    user_name = auth_user.get("full_name") or auth_user.get("email") or "Guest"
    if admin_mode:
        role_label = "Admin"
    elif str(auth_user.get("role", "")).strip().lower() == "guest":
        role_label = "Guest"
    else:
        role_label = "User"
    st.markdown(
        f"""
<div class="hero">
  <h1>{clinic["name"]} - AI Receptionist</h1>
  <p class="hero-sub">Conversational booking assistant with live availability and persistent records.</p>
  <div class="pill-row">
    <span class="pill">{clinic["location"]}</span>
    <span class="pill">{clinic.get("opening_hours_text", "")}</span>
    <span class="pill">Slot length: {clinic.get("slot_length_minutes", 30)} mins</span>
    <span class="pill">Signed in: {user_name} ({role_label})</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def init_auth_state() -> None:
    """Initialize auth-related session state keys."""
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None
    if "guest_mode" not in st.session_state:
        st.session_state.guest_mode = False


def render_auth_sidebar() -> tuple[dict[str, Any], bool, bool]:
    """
    Render authentication controls.

    Returns:
      (auth_user_dict, is_admin, is_guest)
    """
    init_auth_state()
    provider = auth_provider()
    st.sidebar.subheader("Authentication")

    # Open mode for local demos when Clerk is not configured.
    if provider != "clerk":
        st.sidebar.caption("`AUTH_PROVIDER` is not `clerk`. Running in local demo access mode.")
        local_user = {
            "user_id": "local_demo",
            "email": "demo@local",
            "full_name": "Local Demo User",
            "role": "admin",
            "claims": {},
        }
        st.session_state.auth_user = local_user
        st.session_state.guest_mode = False
        return local_user, True, False

    oidc_ok, oidc_message = clerk_oidc_is_configured()
    guest_user = {
        "user_id": "guest",
        "email": "",
        "full_name": "Guest",
        "role": "guest",
        "claims": {},
    }

    if not oidc_ok:
        st.sidebar.error(oidc_message)
        st.sidebar.info("Guest booking is still available while Clerk setup is being completed.")
        st.session_state.auth_user = guest_user
        st.session_state.guest_mode = True
        return guest_user, False, True

    if streamlit_user_is_logged_in():
        user = get_authenticated_user_from_streamlit()
        if not user:
            st.sidebar.warning("Sign-in state could not be loaded. Please sign in again.")
            if st.sidebar.button("Sign in with Clerk", type="primary", use_container_width=True):
                st.login("clerk")
            st.session_state.auth_user = guest_user
            st.session_state.guest_mode = True
            return guest_user, False, True

        auth_user = user.to_session_dict()
        st.session_state.auth_user = auth_user
        st.session_state.guest_mode = False

        st.sidebar.success("Authenticated")
        st.sidebar.write(f"**User:** {auth_user.get('full_name') or auth_user.get('email')}")
        st.sidebar.write(f"**Email:** {auth_user.get('email') or 'Unknown'}")
        st.sidebar.write("**Access:** " + ("Admin" if is_admin_user(auth_user) else "User"))
        st.sidebar.caption("Member bonus unlocked: faster booking with prefilled profile details.")

        if st.sidebar.button("Sign out", use_container_width=True):
            st.logout()
        return auth_user, is_admin_user(auth_user), False

    st.session_state.auth_user = guest_user
    st.session_state.guest_mode = True
    st.sidebar.info("No account needed. Continue as guest, or sign in for member bonus.")
    if st.sidebar.button("Sign in with Clerk", type="primary", use_container_width=True):
        st.session_state.guest_mode = False
        st.login("clerk")
    st.sidebar.caption("Member bonus: profile autofill + priority follow-up on pending requests.")
    return guest_user, False, True


def render_today_overview(clinic: dict[str, Any]) -> None:
    """Show quick operational metrics for today's bookings."""
    today_iso = date.today().isoformat()
    today_confirmed = db.get_confirmed_bookings_for_date(clinic["id"], today_iso)
    today_available = list_available_slots(
        date_iso=today_iso,
        business_hours=clinic["business_hours"],
        slot_length_minutes=int(clinic["slot_length_minutes"]),
        confirmed_bookings=today_confirmed,
    )
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Today confirmed", len(today_confirmed))
    col_b.metric("Today free slots", len(today_available))
    col_c.metric("Slot length", f"{int(clinic['slot_length_minutes'])} min")


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

        if profile_name and profile_name.lower() not in {"guest", "signed in user"}:
            if not normalized_state.get("name"):
                normalized_state["name"] = profile_name

        if profile_email and not normalized_state.get("email"):
            normalized_state["email"] = profile_email

        notes = normalized_state.get("notes", "")
        if "member bonus" not in notes.lower():
            normalized_state["notes"] = (
                f"{notes} | Member bonus: priority follow-up.".strip(" |")
                if notes
                else "Member bonus: priority follow-up."
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
) -> None:
    """Render receptionist chat flow and live structured outcome state."""
    st.subheader("Reception Chat")

    if guest_mode:
        st.info("Guest booking is enabled. Sign in to unlock member bonus: autofill + priority follow-up.")
    elif member_bonus_active:
        st.success("Member bonus active: your profile details can be used to speed up booking.")

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
        process_user_message(
            conversation_id=conversation_id,
            clinic=clinic,
            user_text=user_text,
            auth_user=auth_user,
            member_bonus_active=member_bonus_active,
        )
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
    st.set_page_config(page_title="AI Receptionist Booking MVP", page_icon=":calendar:", layout="wide")
    apply_app_styles()

    clinic = bootstrap_clinic()
    auth_user, admin_mode, guest_mode = render_auth_sidebar()

    if not os.getenv("OPENAI_API_KEY"):
        st.warning(
            "OPENAI_API_KEY is missing. The app still works with deterministic fallback responses."
        )

    member_bonus_active = auth_provider() == "clerk" and not guest_mode and bool(auth_user)

    render_header(clinic, auth_user, admin_mode)
    render_today_overview(clinic)
    conversation_id = ensure_session_conversation(clinic)

    # User role: chat-only; admin role: full operations views.
    tab_names = ["Chat"]
    if admin_mode:
        tab_names.extend(["Calendar", "Dashboard", "Leads", "Bookings", "Conversations"])

    tabs = st.tabs(tab_names)
    tab_map = {name: tab for name, tab in zip(tab_names, tabs)}

    with tab_map["Chat"]:
        render_chat_tab(
            clinic=clinic,
            conversation_id=conversation_id,
            auth_user=auth_user,
            member_bonus_active=member_bonus_active,
            guest_mode=guest_mode,
        )

    if admin_mode:
        with tab_map["Calendar"]:
            render_calendar_tab(clinic)
        with tab_map["Dashboard"]:
            render_dashboard_tab(clinic)
        with tab_map["Leads"]:
            render_leads_tab()
        with tab_map["Bookings"]:
            render_bookings_tab(clinic)
        with tab_map["Conversations"]:
            render_conversations_tab(conversation_id)


if __name__ == "__main__":
    main()
