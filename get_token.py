import requests

# Fill in your Client Secret here
CLIENT_ID = ""
CLIENT_SECRET = "" 
GRANT_TOKEN = ""

url = "https://accounts.zoho.in/oauth/v2/token"

payload = {
    "grant_type": "authorization_code",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": "http://localhost:8000/callback",
    "code": GRANT_TOKEN
}

response = requests.post(url, data=payload)

print("\n--- YOUR ZOHO TOKENS ---")
print(response.json())
