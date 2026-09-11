# Autonomous AI Email Router & Sales Response Tracker

An unattended pipeline that watches a shared Zoho Mail inbox, uses a single
Gemini call to understand each new email, routes it to the right person (a
named contact if the email addresses one, otherwise a default fallback),
sends that person a real notification email, and tracks exactly how fast
they open and reply to it — surfaced on a live Streamlit dashboard.

## How it works

**1. Ingestion & routing** (`agent_poller.py`)
A background loop polls the inbox every 15 seconds for unread mail. For each
new email it fetches the *full* body (not a preview snippet) and sends it to
Gemini in a single structured-output call, which returns:
- a 1-2 sentence summary
- the name/email of anyone specifically addressed in the message, if any
- whether a meeting/call was requested, and any details discussed

Plain Python then decides where it goes: if the email names a real contact
address, it's routed there; otherwise it falls back to a default recipient
(currently "Adam"). Either way, a genuine email is sent via Zoho's Send Email
API — not just a console alert — and the result is logged to SQLite.

**2. Read/reply tracking** (`agent_poller.py` + `database.py`)
The same loop checks, for every email still awaiting a reply, whether the
recipient has opened it (via Zoho's live per-message status) and whether a
reply now exists in the thread (via Zoho's thread listing). Both timestamps
get written back to SQLite the moment they change.

**3. Dashboard** (`dashboard.py`)
A Streamlit app reads that data and shows: emails received, opened, and
pending; average response time; a per-rep response-time leaderboard; and,
per email, the AI-generated summary and meeting details — visible without
anyone opening the original message.

## Repo layout

| File | Role |
|---|---|
| `agent_poller.py` | Main loop — polling, triage, routing, notification, read/reply tracking |
| `zoho_tools.py` | Zoho Mail/CRM API calls — auth, fetch content, message status, send email |
| `database.py` | SQLite schema and read/write helpers |
| `dashboard.py` | Streamlit analytics dashboard |
| `get_token.py` / `quick_auth.py` | One-time helpers for generating a Zoho refresh token |

## Setup

1. `pip install -r requirements.txt`
2. Create a `.env` file with your Gemini key:
   ```
   GOOGLE_API_KEY=your_google_gemini_api_key_here
   ```
3. **Zoho credentials are currently hardcoded** at the top of `zoho_tools.py`
   (`CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN`) rather than read from
   `.env`. To get your own: register an app at the
   [Zoho API Console](https://api-console.zoho.com/), then run
   `quick_auth.py`, which walks you through the OAuth consent flow and
   prints a refresh token to paste in.
   > ⚠️ **Before pushing this repo anywhere public**, move those three
   > values out of `zoho_tools.py` and into `.env` instead — as hardcoded
   > constants in a tracked file, they'll be exposed in your git history
   > even if you delete them later.
4. `python database.py` — creates/resets `analytics.db` (this drops any
   existing rows, by design, whenever the schema changes).
5. Run the poller: `python agent_poller.py`
6. In a second terminal, run the dashboard: `streamlit run dashboard.py`

## Notes & known limitations

- **Data center**: all Zoho endpoints are hardcoded to the India (`.in`)
  data center (`mail.zoho.in`, `accounts.zoho.in`, `zohoapis.in`). Change
  these in `zoho_tools.py`/`agent_poller.py` if your Zoho org is elsewhere.
- **Model**: uses `gemini-3.6-flash`. `gemini-2.5-flash` is no longer issued
  to new Google accounts as of mid-2026 — if Google deprecates 3.6 Flash
  later, swap the model string in `agent_poller.py`.
- **Free-tier quota**: Gemini's free tier has a daily request cap that
  resets at midnight Pacific time. Each email costs exactly one Gemini call.
- **Name-only mentions**: if an email says "Dear John" with no email address
  anywhere in the body, there's currently no directory to resolve "John" to
  an address — it falls back to the default (Adam) same as a fully generic
  email. Extending this would mean adding a small name→email roster.
- **Zoho's `threadId` quirk**: Zoho only returns a `threadId` for a message
  once it's part of a real multi-message thread (i.e. after the first
  reply) — a brand-new email has none. The code falls back to the message's
  own ID in that case, which is also what Zoho itself uses as the thread ID
  once a reply arrives.

## Tech stack

Python · Zoho Mail API · Zoho CRM API · Google Gemini 3.6 Flash
(`langchain-google-genai`, structured output) · SQLite · Streamlit
