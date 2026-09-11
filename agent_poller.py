import re
import time
import requests
import sqlite3
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
import database
import zoho_tools

load_dotenv()

# --- 1. STRUCTURED TRIAGE MODEL ---
# One Gemini call per email extracts everything needed: a 2-line summary, who (if
# anyone specific) the email is addressed to, and any meeting/timing details. Routing
# itself, and sending the notification, both happen afterward as plain Python — no
# extra LLM calls needed for those.
class EmailTriage(BaseModel):
    summary: str = Field(
        description="A 1 to 2 sentence summary of what the sender wants, in your own words."
    )
    mentioned_name: str = Field(
        default="",
        description="The specific person's name this email is addressed to or asks for "
                    "(e.g. a 'Dear <Name>' salutation), if any. Empty string if it's "
                    "addressed generically (e.g. 'Dear Sales Team') or to no one in "
                    "particular."
    )
    mentioned_email: str = Field(
        default="",
        description="An explicit email address for that specific named contact, if one "
                    "appears ANYWHERE in the email body OTHER than the sender's own "
                    "signature address. Empty string if none is mentioned."
    )
    meeting_requested: bool = Field(
        description="True if the email requests or discusses a meeting, call, or a "
                    "specific time to connect."
    )
    meeting_details: str = Field(
        default="",
        description="A short note on any specific date, time, or meeting details "
                    "discussed, if mentioned. Empty string if none."
    )

TRIAGE_PROMPT = (
    "You are an AI assistant that triages inbound business emails for a sales team.\n"
    "Read the FULL email body below and extract:\n"
    "1. summary — a 1 to 2 sentence summary of what the sender wants, in your own words.\n"
    "2. mentioned_name — the specific person's name this email is addressed to or asks "
    "for (e.g. a 'Dear <Name>' salutation), if any. Leave empty if it's addressed "
    "generically (e.g. 'Dear Sales Team') or to no one in particular.\n"
    "3. mentioned_email — an explicit email address for that specific contact, if one "
    "appears ANYWHERE in the body OTHER than the sender's own signature address. Leave "
    "empty if none is mentioned.\n"
    "4. meeting_requested — true if a meeting, call, or specific time to connect is "
    "requested or discussed.\n"
    "5. meeting_details — a short note on any specific date/time/meeting details "
    "discussed, if mentioned. Leave empty if none.\n\n"
    "Sender: {sender}\n"
    "Subject: '{subject}'\n"
    "Full Email Body:\n'{body}'"
)

llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=0)
# method="json_schema" uses Gemini's native structured-output mode (a single
# generate_content call) rather than a tool-calling round trip.
triage_llm = llm.with_structured_output(EmailTriage, method="json_schema")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def resolve_recipient(result: EmailTriage, sender_email: str):
    """Decides who this email actually gets routed to.
    - If the email itself names a specific contact's address, route there directly.
    - Otherwise (or if the 'mentioned' address is junk, or is just the sender's own
      address misread as a contact), fall back to the default: Adam.
    Returns (display_name, email_address)."""
    candidate_email = (result.mentioned_email or "").strip()
    candidate_name = (result.mentioned_name or "").strip()
    if (candidate_email
            and _EMAIL_RE.match(candidate_email)
            and candidate_email.lower() != sender_email.lower()):
        return candidate_name or candidate_email, candidate_email
    return f"{zoho_tools.DEFAULT_ROUTING_NAME} (default)", zoho_tools.DEFAULT_ROUTING_EMAIL

def build_notification_email(sender, subject, result: EmailTriage):
    meeting_line = result.meeting_details if result.meeting_requested else "No meeting requested."
    subject_line = f"New Lead Routed To You: {subject}"
    body_html = (
        f"<p>Hi,</p>"
        f"<p>A new email just came in and has been routed to you for follow-up.</p>"
        f"<p><b>From:</b> {sender}<br>"
        f"<b>Subject:</b> {subject}</p>"
        f"<p><b>Summary:</b> {result.summary}</p>"
        f"<p><b>Meeting/Timing:</b> {meeting_line}</p>"
        f"<p>Please respond as soon as you can — your response time is being tracked.</p>"
    )
    return subject_line, body_html

# --- 2. ZOHO MAIL AUTOMATION ---
def get_account_id(headers):
    """Returns (account_id, from_address) — from_address is needed as the sender
    identity when sending the real notification email below."""
    acc_url = "https://mail.zoho.in/api/accounts"
    res = requests.get(acc_url, headers=headers).json()
    if "data" not in res:
        print(f"⚠️ Could not fetch account list. RAW RESPONSE: {res}")
        return None, None
    accounts = res["data"]
    if len(accounts) > 1:
        print(f"ℹ️ {len(accounts)} Zoho accounts found — polling accountId="
              f"{accounts[0]['accountId']} ({accounts[0].get('mailboxAddress', accounts[0].get('emailAddress',''))}). "
              f"All accounts: {[(a.get('accountId'), a.get('mailboxAddress', a.get('emailAddress'))) for a in accounts]}")
    account_id = accounts[0]["accountId"]
    from_address = accounts[0].get("mailboxAddress") or accounts[0].get("emailAddress")
    return account_id, from_address

def check_inbox(token):
    print("\n🔍 Checking for new emails...")
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    account_id, from_address = get_account_id(headers)
    if not account_id: return

    # Fetch recent emails DIRECTLY to bypass Zoho's laggy search index
    msg_url = f"https://mail.zoho.in/api/accounts/{account_id}/messages/view?limit=15"
    msg_res = requests.get(msg_url, headers=headers).json()

    if "data" not in msg_res or not msg_res["data"]:
        print(f"📭 Inbox is empty. (account_id={account_id})")
        print(f"   RAW RESPONSE from {msg_url}:\n   {msg_res}")
        return

    # Manually filter for unread emails (status == "1") using Python
    unread_mails = [m for m in msg_res["data"] if str(m.get("status")) == "1"]

    if not unread_mails:
        print(f"📭 Inbox is clear (No unread emails). Fetched {len(msg_res['data'])} "
              f"message(s) total; statuses seen: {[m.get('status') for m in msg_res['data']]}")
        return

    for mail in unread_mails:
        # Zoho does NOT return a 'threadId' key at all for a message until it's part
        # of a real multi-message thread (i.e. after the first reply). Falling back to
        # the message's own ID avoids a primary-key collision across every new email.
        thread_id = str(mail.get("threadId") or mail.get("messageId"))
        message_id = str(mail.get("messageId"))
        folder_id = str(mail.get("folderId")) if mail.get("folderId") else None
        sender = mail.get("sender")
        subject = mail.get("subject", "No Subject")
        received_ms = mail.get("receivedTime")

        conn = sqlite3.connect("analytics.db")
        c = conn.cursor()
        c.execute("SELECT thread_id FROM email_logs WHERE thread_id=?", (thread_id,))
        exists = c.fetchone()
        conn.close()

        if exists: continue

        # Each email is handled in its own try/except: a failure (e.g. a Gemini rate
        # limit) only skips THIS email — it stays unread in Zoho, so it's automatically
        # retried on the next 15s poll cycle — while the rest of the batch still gets
        # processed normally.
        try:
            print(f"\n📨 NEW EMAIL CAUGHT: {sender} - {subject}")
            print("📖 Fetching full email body...")
            full_body = zoho_tools.get_full_email_content(account_id, folder_id, message_id, headers)
            if not full_body:
                # Fall back to the short list-view preview if the full-content fetch fails,
                # so triage can still happen instead of silently skipping the email.
                full_body = mail.get("summary", "No Content")

            print("🧠 AI is triaging the email (1 call)...")
            prompt = TRIAGE_PROMPT.format(sender=sender, subject=subject, body=full_body)
            result = triage_llm.invoke(prompt)

            notify_name, notify_email = resolve_recipient(result, sender)
            notif_subject, notif_body = build_notification_email(sender, subject, result)
            sent_ok = zoho_tools.send_notification_email(
                account_id, from_address, notify_email, notif_subject, notif_body, headers
            )

            meeting_label = "Yes" if result.meeting_requested else "No"
            print("\n" + "="*50)
            print(f"🚨 ROUTED TO: {notify_name} <{notify_email}>")
            print(f"📝 SUMMARY: {result.summary}")
            print(f"📅 MEETING: {meeting_label} — {result.meeting_details or 'n/a'}")
            print(f"📤 Notification email sent: {sent_ok}")
            print("="*50 + "\n")

            database.log_incoming_email(
                thread_id, message_id, sender, notify_name, notify_email, received_ms,
                folder_id=folder_id, summary=result.summary, meeting_requested=meeting_label,
                meeting_details=result.meeting_details, notification_sent=int(sent_ok)
            )

        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print(f"\n⏳ Gemini rate limit hit while processing '{subject}'. "
                      f"Leaving it unread — it will be retried on the next poll cycle.")
            else:
                print(f"\n⚠️ Error processing '{subject}': {e}. "
                      f"Leaving it unread — it will be retried on the next poll cycle.")
            # Deliberately do NOT log to the DB here — leaving the row absent means
            # this same email gets picked up again next cycle instead of vanishing.
            continue

def track_reads_and_replies(token):
    print("🕵️ Tracking pending threads for reads/replies...")
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    account_id, _ = get_account_id(headers)
    if not account_id: return

    pending_threads = database.get_pending_threads()
    if not pending_threads:
        print("   (no threads awaiting a reply)")

    for thread_id, original_msg_id, folder_id, received_time in pending_threads:
        # 1. Check READS — query the SPECIFIC message directly. This works even before
        # Zoho has created a real thread (i.e. before any reply exists).
        status = zoho_tools.get_message_status(account_id, folder_id, original_msg_id, headers)
        print(f"   [{thread_id}] live status = {status!r}")
        if status is not None and str(status) != "1":
            database.update_read_time(thread_id)
            print(f"\n👀 LOGGED: Email '{thread_id}' was OPENED by sales rep!")

        # 2. Check for REPLIES by listing the thread. Zoho only starts returning
        # results here once a reply actually exists.
        thread_url = f"https://mail.zoho.in/api/accounts/{account_id}/messages/view?threadId={thread_id}&limit=25"
        res = requests.get(thread_url, headers=headers).json()

        messages = res.get("data", [])
        print(f"   [{thread_id}] thread listing returned {len(messages)} message(s)")
        if not isinstance(messages, list) or len(messages) < 2:
            continue

        messages.sort(key=lambda x: int(x.get("receivedTime", 0)))
        latest_msg = messages[-1]

        if str(latest_msg.get("messageId")) != str(original_msg_id):
            reply_ms = latest_msg.get("receivedTime")
            database.update_reply_time(thread_id, reply_ms)
            print(f"\n✅ LOGGED: Reply SENT for thread '{thread_id}'!")

if __name__ == "__main__":
    print("🚀 Fully Automated AI Tracker is running! (Press Ctrl+C to stop)")
    while True:
        try:
            token = zoho_tools.get_zoho_access_token()
            if token:
                check_inbox(token)
                track_reads_and_replies(token)
        except Exception as e:
            print(f"⚠️ Critical Python Crash: {e}")

        print("-" * 40)
        time.sleep(15)
