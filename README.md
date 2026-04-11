# AI Receptionist Booking MVP (Streamlit + SQLite)

A local, modular prototype for an aesthetics clinic where the AI receptionist handles FAQ, lead qualification, slot availability checks, and booking outcomes in chat.

## Stack
- Python
- Streamlit
- OpenAI API
- sqlite3 (local database)
- python-dotenv

## Project Files
- `app.py`
  - UI + orchestration only (tabs, chat turn processing, dashboard actions).
- `clinic_data.py`
  - Default clinic data, day labels, and opening-hours text helpers.
- `db.py`
  - Schema + persistence helpers + lightweight migrations.
- `booking_logic.py`
  - Deterministic validation, business-hour checks, slot generation, overlap checks, booking decisions.
- `ai_logic.py`
  - Field extraction helpers + prompt building + model/fallback response generation.
- `requirements.txt`
- `.env.example`

## What It Does
- Streamlit chat UI with persistent conversations/messages in SQLite.
- Persistent structured leads and booking outcomes.
- Deterministic booking engine controlled by Python (AI does language only).
- Opening hours and slot length editable in dashboard tab.
- DB-driven daily availability and calendar exports (`.ics`).
- Admin tabs for Leads, Bookings, Conversations.

## Database Schema
SQLite file: `clinic_receptionist.db`

Tables:
1. `clinics`
- Clinic profile, timezone, opening hours JSON/text, slot length, treatments/FAQ JSON.

2. `conversations`
- One row per chat thread.

3. `messages`
- Full transcript (`user`/`assistant`) linked to conversation.

4. `leads`
- One structured lead per conversation.
- Fields: `treatment_interest`, `booking_type`, `preferred_date`, `preferred_time`, `timeframe`, `name`, `phone`, `email`, `notes`.

5. `bookings`
- One booking outcome per conversation.
- Includes `status` (`confirmed` or `booking_request`), `outcome_reason`, and `duration_minutes`.

## Deterministic Booking Rules
Implemented in `booking_logic.py`:
- Validate and normalize phone/email/date/time inputs.
- Reject malformed slot data cleanly.
- Generate valid slots from opening hours + slot length.
- Prevent overlaps against confirmed bookings already in DB.
- If slot outside hours: `booking_request`.
- If slot occupied: `booking_request`.
- If slot valid/free and required fields exist: `confirmed`.
- Otherwise continue follow-up flow or create pending request if incomplete.

## Tabs
- `Chat`
  - Conversation history
  - Live structured booking state
  - Final booking outcome display
- `Calendar`
  - Date availability view (free slots + confirmed bookings)
  - Download `.ics` for selected day
- `Dashboard`
  - Edit opening times per day
  - Edit slot length
- `Leads`
  - Lead table from SQLite
- `Bookings`
  - Booking table with status filter + `.ics` export
- `Conversations`
  - Conversation list + transcript viewer

## Run Locally
1. Create/activate virtualenv.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Create `.env` from `.env.example`:
   - `OPENAI_API_KEY=your_key_here`
   - `OPENAI_MODEL=gpt-4.1-mini` (optional override)
4. Start app:
   - `streamlit run app.py`
5. Open local URL shown by Streamlit (typically `http://localhost:8501`).

## Notes
- No external booking APIs, no external DB, no auth.
- If API key is missing, deterministic fallback responses keep the app functional.
- Important state and booking outcomes are always controlled by Python + SQLite.
