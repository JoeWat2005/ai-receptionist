> [!WARNING]
> **Deprecated: no longer maintained.** Last updated in April 2026; kept for reference.

# AI receptionist prototype

Streamlit prototype of an AI receptionist for an aesthetics clinic: a chat assistant that collects booking details, checks availability and records bookings and leads in SQLite.

Status: deprecated early prototype, superseded by [DeskCaptain](https://github.com/JoeWat2005/deskcaptain).

## Features

- Chat assistant for a sample clinic, defined in `clinic_data.py`, that answers common questions and gathers booking details: treatment, booking type, date, time, timeframe, name, phone, email and notes
- Deterministic booking rules in `booking_logic.py`. They validate dates, times, phone numbers and emails, check business hours and slot availability, and decide whether a request becomes a confirmed booking or a pending booking request.
- Replies written by an OpenAI model, with templated fallback replies when no API key is set
- Optional Clerk sign-in through Streamlit's built-in OIDC login. Guests can chat without an account.
- Signed-in members get their name and email filled in automatically, and their pending requests are marked for priority follow-up
- Admin tabs for calendar, dashboard (including clinic settings), leads, bookings and conversations, with `.ics` calendar downloads

## Tech stack

- Python and Streamlit
- OpenAI Python SDK
- SQLite through the standard library `sqlite3` module
- Clerk as the OIDC provider, through Streamlit authentication with Authlib, plus PyJWT
- python-dotenv

## Getting started

### Prerequisites

- Python 3. No version is pinned; the committed bytecode was built with CPython 3.13.
- Optional: an OpenAI API key
- Optional, for sign-in: a Clerk application set up for OIDC login

### Installation

```bash
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and fill in the values. At startup the app loads `.env` from the project folder. When `AUTH_PROVIDER=clerk`, it also writes `.streamlit/secrets.toml` for Streamlit's OIDC login, so the Clerk settings only need to be kept in `.env`. Both files are ignored by git.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API key. Without it the app uses deterministic fallback replies. |
| `OPENAI_MODEL` | Chat model name (default `gpt-4.1-mini`) |
| `AUTH_PROVIDER` | `clerk` enables Clerk sign-in. Any other value, or none, runs local demo mode (see below). |
| `CLERK_ADMIN_ROLE_VALUE` | Role claim value that grants admin access (default `admin`) |
| `CLERK_ADMIN_EMAILS` | Comma-separated email addresses that get admin access |
| `CLERK_CLIENT_ID` | Client ID for the Clerk OIDC login. `.env.example` describes it as the publishable key; `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is accepted instead. |
| `CLERK_CLIENT_SECRET` | Client secret for the Clerk OIDC login. `.env.example` describes it as the secret key; `CLERK_SECRET_KEY` is accepted instead. |
| `CLERK_SERVER_METADATA_URL` | Clerk OpenID configuration URL. Set either this or `CLERK_FRONTEND_API_URL`. |
| `CLERK_FRONTEND_API_URL` | Clerk Frontend API URL, used to derive the metadata URL when `CLERK_SERVER_METADATA_URL` is blank |
| `STREAMLIT_REDIRECT_URI` | OIDC callback URL (default `http://localhost:8501/oauth2callback`) |
| `STREAMLIT_COOKIE_SECRET` | Secret used by Streamlit to sign its login cookie |
| `CLERK_OIDC_PROMPT` | OIDC `prompt` parameter (default `login`). `select_account` is replaced with `login` because Clerk rejects it in this flow. |
| `CLERK_OIDC_SCOPE` | OIDC scopes (default `openid email profile`) |

### Running locally

```bash
streamlit run app.py
```

Open `http://localhost:8501` (the address and port are set in `.streamlit/config.toml`). Use the sidebar to continue as a guest or to sign in with Clerk.

If Clerk reports a redirect URI mismatch, check that the redirect URIs in your Clerk OAuth application include exactly `http://localhost:8501/oauth2callback`, and that the change has been saved.

On first run the app creates `clinic_receptionist.db` next to `app.py` and adds the default clinic. There are no automated tests.

## How it works

Each chat turn goes through `process_user_message()` in `app.py`:

1. `ai_logic.py` pulls booking fields out of the message with pattern matching and merges them into the conversation's booking state.
2. `booking_logic.py` normalises and validates that state. `decide_booking_outcome()` asks for the next missing or invalid detail until the required details are in. It then checks the requested slot against business hours, slot length and existing confirmed bookings. A free slot within opening hours becomes a confirmed booking. Otherwise the request is saved as a pending booking request, and the reply can offer the other free slots that day.
3. `db.py` saves the message, the lead and any booking to SQLite.
4. `ai_logic.py` builds a system prompt from the clinic details and the decision, and asks the OpenAI model to phrase the reply. The model only writes the wording; booking decisions stay in `booking_logic.py`.

### Modules

- `app.py` is the Streamlit entry point. It loads configuration, renders the authentication sidebar and the tabs, and orchestrates chat turns.
- `db.py` defines the SQLite schema (clinics, conversations, messages, leads and bookings), with small in-place migrations and query helpers.
- `auth.py` maps Streamlit OIDC claims to a user and grants admin access by role claim or by `CLERK_ADMIN_EMAILS`.
- `clinic_data.py` holds the default clinic profile, opening hours, treatments and FAQ answers.
- `ui_components.py` provides shared styling, the header, the profile card and the sidebar account summary.

### Access levels

| User | Tabs |
| --- | --- |
| Guest | Chat |
| Signed-in user | Chat, with member perks |
| Admin (role claim or email allow-list) | Chat, Calendar, Dashboard, Leads, Bookings, Conversations |
| Local demo mode (`AUTH_PROVIDER` is not `clerk`) | Every visitor is treated as an admin |

## Project structure

```
.streamlit/config.toml   Streamlit server settings (localhost:8501)
app.py                   Streamlit app and chat orchestration
ai_logic.py              Field extraction, prompts and OpenAI replies
booking_logic.py         Booking validation, availability and decision rules
db.py                    SQLite schema and persistence helpers
auth.py                  Clerk OIDC user mapping and admin checks
clinic_data.py           Default clinic configuration and FAQ answers
ui_components.py         Shared Streamlit UI components
.env.example             Configuration template
requirements.txt         Python dependencies
todo.txt                 Development notes
```

The `__pycache__/` folder is also committed, even though `.gitignore` excludes it.

## Related repositories

- [deskcaptain](https://github.com/JoeWat2005/deskcaptain): the full AI receptionist product that followed this prototype
