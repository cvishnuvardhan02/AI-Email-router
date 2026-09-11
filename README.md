# AI-Email-router
An unattended pipeline that watches a shared Zoho Mail inbox, uses a single Gemini call to understand each new email, routes it to the right person (a named contact if the email addresses one, otherwise a default fallback), sends that person a real notification email, and tracks exactly how fast they open and reply to it .
