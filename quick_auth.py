import requests

CLIENT_ID = "1000.G25H7IKF1N5VS0SOER6KK7NZVP9EYS"
CLIENT_SECRET = "b2ba53e0eb1b45ba20fc5cd3cf3aba9009301333c9"

print("="*60)
print("1. Click this link, log in, and click Accept:")
print(f"https://accounts.zoho.in/oauth/v2/auth?scope=ZohoCRM.modules.ALL,ZohoMail.messages.ALL,ZohoMail.accounts.READ&client_id={CLIENT_ID}&response_type=code&access_type=offline&redirect_uri=http://localhost:8000/callback&prompt=consent")
print("="*60)

# Wait for you to paste the code
code = input("\n2. Paste the 'code=' from the URL here and press Enter: ").strip()

payload = {
    "grant_type": "authorization_code",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": "http://localhost:8000/callback",
    "code": code
}

print("\nExchanging code for permanent token...")
res = requests.post("https://accounts.zoho.in/oauth/v2/token", data=payload).json()

if "refresh_token" in res:
    print("\n✅ SUCCESS! Here is your true, permanent Refresh Token:")
    print("-" * 60)
    print(res["refresh_token"])
    print("-" * 60)
    print("Go open your .env file, put this next to ZOHO_REFRESH_TOKEN=, and SAVE the file.")
else:
    print("\n❌ FAILED! Zoho rejected the code. Make sure you pasted it within 60 seconds.")
    print(f"Zoho's exact error: {res}")