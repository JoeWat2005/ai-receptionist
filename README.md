# AI Receptionist Booking MVP (Streamlit + SQLite)

A local, modular prototype for an aesthetics clinic where an AI receptionist handles FAQ, lead qualification, slot availability checks, and booking outcomes in chat.

## Stack
- Python
- Streamlit
- OpenAI API
- sqlite3 (local database)
- python-dotenv
- PyJWT (for Clerk token verification)

## Project Files
- `app.py`
  - UI orchestration, auth gating, tabs, and booking turn flow.
- `auth.py`
  - Clerk token verification and user/admin authorization helpers.
- `clinic_data.py`
  - Default clinic data and opening-hours text helpers.
- `db.py`
  - SQLite schema + persistence + lightweight migrations.
- `booking_logic.py`
  - Deterministic validation, slot generation, overlap checks, booking outcomes.
- `ai_logic.py`
  - Extraction helpers + prompt construction + model/fallback response generation.
- `requirements.txt`
- `.env.example`

## Highlights
- Persistent conversations, messages, leads, and bookings.
- Deterministic booking decisions in Python (AI does language only).
- Dashboard controls for opening hours and slot length.
- Calendar tab with free-slot view and `.ics` export.
- User/admin access model with optional Clerk authentication.
- Polished MVP styling for demos.

## Auth Modes
### 1) Local demo mode (default)
Set `AUTH_PROVIDER=none`.
- App opens directly.
- Full admin tabs are available for local demos.

### 2) Clerk mode
Set `AUTH_PROVIDER=clerk` and provide verification config:
- `CLERK_JWKS_URL` **or** `CLERK_JWT_PUBLIC_KEY`
- Optional: `CLERK_ISSUER`, `CLERK_AUDIENCE`
- Admin checks:
  - `CLERK_ADMIN_ROLE_VALUE=admin` (default)
  - optional `CLERK_ADMIN_EMAILS=owner@clinic.com,manager@clinic.com`

In Clerk mode:
- Users sign in via sidebar token input (or `?__session=...` query param).
- Non-admin users get `Chat` + `Calendar`.
- Admin users get all tabs (`Dashboard`, `Leads`, `Bookings`, `Conversations`).

## Database Schema
SQLite file: `clinic_receptionist.db`

Tables:
1. `clinics`
2. `conversations`
3. `messages`
4. `leads`
5. `bookings`

## Deterministic Booking Rules
Implemented in `booking_logic.py`:
- Normalize and validate phone/email/date/time.
- Require key fields before finalizing booking.
- Confirm only when slot is valid/free and required details are complete.
- Create `booking_request` when slot is outside hours or occupied.
- Use configured opening hours + slot length for availability generation.

## Run Locally
1. Create/activate virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Create `.env` from `.env.example` and set `OPENAI_API_KEY`.
4. Run app:
   - `streamlit run app.py`
5. Open local URL (usually `http://localhost:8501`).

## Notes
- No external DB, no external booking API, no auth server in this repo.
- Clerk verification is configurable and optional for local demos.
- Booking authority stays in Python + SQLite.
