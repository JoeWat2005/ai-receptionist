# AI Receptionist Booking MVP (Streamlit + SQLite)

Local modular prototype for an aesthetics clinic with:
- AI receptionist chat
- deterministic booking decisions
- SQLite persistence
- staff/customer role model
- business onboarding flow
- phone-call processing scaffold

## Project structure

```text
ai-receptionist/
  app.py
  auth.py
  db.py
  booking_logic.py
  ai_logic.py
  clinic_data.py
  frontend/
    auth_sidebar.py
    chat_page.py
    components.py
    staff_pages.py
  services/
    calling.py
    phone_ai.py
  .env.example
  requirements.txt
```

## Access model

- Guest: `Chat` only
- Signed-in customer: `Chat` only + member bonus (profile autofill + priority follow-up)
- Staff: full operations pages
  - `Chat`
  - `Bookings`
  - `Calendar`
  - `Dashboard`
  - `Leads`
  - `Conversations`

## Dashboard includes

- Business onboarding form
- Opening-hours + slot-length settings
- Staff/customer account management
- AI phone-call scaffold (transcript processing + call log storage)

## Required `.env` config

Copy `.env.example` to `.env` and fill values.

Important keys:

```env
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini

AUTH_PROVIDER=clerk
CLERK_STAFF_ROLE_VALUES=staff,owner,admin
CLERK_STAFF_EMAILS=watmoughjoe2005@gmail.com

CLERK_CLIENT_ID=...
CLERK_CLIENT_SECRET=...
CLERK_SERVER_METADATA_URL=https://<your-clerk-domain>/.well-known/openid-configuration

STREAMLIT_REDIRECT_URI=http://localhost:8501/oauth2callback
STREAMLIT_COOKIE_SECRET=<random_hex>
CLERK_OIDC_PROMPT=login
CLERK_OIDC_SCOPE=openid profile email
```

Notes:
- App auto-generates `.streamlit/secrets.toml` from `.env`.
- Clerk OAuth app must include redirect URI exactly:
  - `http://localhost:8501/oauth2callback`
- `CLERK_OIDC_PROMPT=login` avoids Clerk rejecting Streamlit default select-account prompt.

## Run locally

1. Install deps:
   - `pip install -r requirements.txt`
2. Start app:
   - `streamlit run app.py`
3. Open:
   - `http://localhost:8501`

## Phone calls (current state)

This MVP includes local scaffolding only:
- parse/store call transcript logs
- extract booking fields from transcript
- run deterministic booking decision
- show outbound payload and XML-like voice reply scaffold

To make it production-ready, wire `services/calling.py` to a real provider webhook + call API.

## Security

- Keep `.env` private and never commit it.
- Rotate keys immediately if exposed.
