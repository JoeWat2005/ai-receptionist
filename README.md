# AI Receptionist Booking MVP (Streamlit + SQLite)

Local, modular aesthetics clinic prototype with deterministic booking logic and Clerk access control.

## What changed
- Clerk auth now uses a **single `.env`** setup.
- Users can book as **guest** (no account required).
- Signed-in users get a **member bonus**:
  - profile autofill (name/email) during booking
  - priority follow-up marker on pending booking requests
- Admin access is email-whitelisted:
  - `watmoughjoe2005@gmail.com`

## Access behavior
- Guest: `Chat` only
- Signed-in non-admin user: `Chat` only + member bonus
- Admin: `Chat`, `Calendar`, `Dashboard`, `Leads`, `Bookings`, `Conversations`

## Required `.env` config
Copy `.env.example` to `.env` and fill values:

```env
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4.1-mini

AUTH_PROVIDER=clerk
CLERK_ADMIN_ROLE_VALUE=admin
CLERK_ADMIN_EMAILS=watmoughjoe2005@gmail.com

CLERK_CLIENT_ID=pk_test_...
CLERK_CLIENT_SECRET=sk_test_...

# Either set this:
CLERK_SERVER_METADATA_URL=https://your-clerk-domain/.well-known/openid-configuration
# Or this:
CLERK_FRONTEND_API_URL=https://your-clerk-domain

STREAMLIT_REDIRECT_URI=http://localhost:8501/oauth2callback
STREAMLIT_COOKIE_SECRET=replace_with_random_hex_string
```

Notes:
- App auto-generates `.streamlit/secrets.toml` from `.env` at startup.
- You do not need to maintain Clerk values in separate files.
- Set either `CLERK_SERVER_METADATA_URL` or `CLERK_FRONTEND_API_URL`. If using `CLERK_FRONTEND_API_URL`, leave `CLERK_SERVER_METADATA_URL` blank.

## Run
1. `pip install -r requirements.txt`
2. `streamlit run app.py`
3. Open `http://localhost:8501`
4. Use sidebar:
   - Continue as guest, or
   - Sign in with Clerk for member bonus/admin access

## Security
- Keep `.env` private and never commit it.
- Rotate keys immediately if they are ever shared.
