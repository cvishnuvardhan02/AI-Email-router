import requests
import time
import re

# Hardcoded keys
CLIENT_ID = "1000.G25H7IKF1N5VS0SOER6KK7NZVP9EYS"
CLIENT_SECRET = "b2ba53e0eb1b45ba20fc5cd3cf3aba9009301333c9"
REFRESH_TOKEN = "1000.3ef23d296b368aa9be12ff7ffe1469ce.6d04e57026e09d670a4b3bbc60ae9bce"

# Memory variables for token caching
CACHED_TOKEN = None
TOKEN_EXPIRY = 0

# Default routing target when no specific person is named/emailed in an incoming message.
DEFAULT_ROUTING_NAME = "Adam"
DEFAULT_ROUTING_EMAIL = "cvishnuvardhan002@gmail.com"


def get_zoho_access_token():
    """Uses your refresh token to get a fresh 1-hour access token, caching it to prevent API limits."""
    global CACHED_TOKEN, TOKEN_EXPIRY

    # Check if we already have a token and if it is still valid
    # (We subtract 60 seconds as a safety buffer so it doesn't expire while in use)
    if CACHED_TOKEN and time.time() < (TOKEN_EXPIRY - 60):
        return CACHED_TOKEN

    url = "https://accounts.zoho.in/oauth/v2/token"
    payload = {
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token"
    }

    response = requests.post(url, data=payload)
    data = response.json()

    if "error" in data:
        print(f"\n⚠️ ZOHO AUTH REJECTED: {data}\n")
        return None

    # Save the new token into Python's memory
    CACHED_TOKEN = data.get("access_token")

    # Save the exact time it will expire (Current time + 3600 seconds)
    TOKEN_EXPIRY = time.time() + data.get("expires_in", 3600)

    print("\n🔄 Successfully generated and cached a new 1-hour Zoho Access Token!")
    return CACHED_TOKEN


def search_crm_for_owner(sender_email):
    """Searches Zoho CRM to see who owns this email address.
    NOTE: no longer used by the main routing path in agent_poller.py (routing is now
    based on who the email itself names/addresses, not the CRM owner) — kept here in
    case you want CRM-owner lookups for something else later.
    Falls back to DEFAULT_ROUTING_EMAIL (Adam) if no CRM contact/owner is found."""
    token = get_zoho_access_token()
    if not token:
        return DEFAULT_ROUTING_EMAIL

    url = f"https://www.zohoapis.in/crm/v3/Contacts/search?email={sender_email}"
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    try:
        response = requests.get(url, headers=headers)
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            owner_email = data["data"][0]["Owner"]["email"]
            return owner_email
    except Exception as e:
        print(f"CRM Error: {e}")

    return DEFAULT_ROUTING_EMAIL


# --- NEW: full-body reading + live read-status checking, used by agent_poller.py ---

def _strip_html(html):
    """Small HTML -> plain text helper so the LLM reads a clean body instead of raw markup."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?(</\1>)", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (text.replace("&nbsp;", " ")
                .replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"'))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_full_email_content(account_id, folder_id, message_id, headers):
    """Fetches the COMPLETE body of one email (not just the truncated 'summary' preview)
    so the agent genuinely reads the whole thing before deciding spam/routing/meeting status.

    NOTE: this is a plain GET. Zoho exposes a *separate*, explicit "mark as read" PUT
    action (mode=markAsRead), which strongly implies this GET does not itself flip the
    message's read/unread status — but Zoho doesn't document that either way, so it's
    worth a 30-second manual check in your own mailbox (fetch a message's content once
    via this function, then confirm in the Zoho web UI it still shows unread).
    """
    if not folder_id or not message_id:
        return ""
    url = f"https://mail.zoho.in/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/content"
    try:
        res = requests.get(url, headers=headers).json()
        html = res.get("data", {}).get("content", "")
        return _strip_html(html)
    except Exception as e:
        print(f"Content Fetch Error: {e}")
        return ""


def get_message_status(account_id, folder_id, message_id, headers):
    """Fetches the LIVE read/unread status of one specific message directly, instead of
    inferring it from a thread listing (which Zoho only populates once the message is
    actually part of a multi-message thread — see the threadId note in agent_poller.py).
    Returns '1' (unread), '0' (read), or None on failure."""
    if not folder_id or not message_id:
        return None
    url = f"https://mail.zoho.in/api/accounts/{account_id}/folders/{folder_id}/messages/{message_id}/details"
    try:
        res = requests.get(url, headers=headers).json()
        return res.get("data", {}).get("status")
    except Exception as e:
        print(f"Status Check Error: {e}")
        return None


def send_notification_email(account_id, from_address, to_address, subject, content_html, headers):
    """Sends a REAL notification email via Zoho Mail's Send Email API
    (POST /accounts/{accountId}/messages) to whoever the incoming email got routed to.
    Uses the same mailbox that's being polled as the sender. Requires the
    ZohoMail.messages.ALL scope, which the existing refresh token already has.
    Returns True on success, False otherwise — never raises, so a failed notification
    doesn't take down the rest of the pipeline."""
    if not from_address or not to_address:
        print(f"⚠️ Cannot send notification — missing from/to address (from={from_address!r}, to={to_address!r}).")
        return False
    url = f"https://mail.zoho.in/api/accounts/{account_id}/messages"
    payload = {
        "fromAddress": from_address,
        "toAddress": to_address,
        "subject": subject,
        "content": content_html,
        "mailFormat": "html",
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        data = res.json()
        if data.get("status", {}).get("code") == 200:
            msg_id = data.get("data", {}).get("messageId")
            print(f"📤 Notification email sent to {to_address} (messageId={msg_id})")
            return True
        print(f"⚠️ Zoho rejected the notification email: {data}")
        return False
    except Exception as e:
        print(f"⚠️ Notification Send Error: {e}")
        return False
