"""
MAIHERA Calendar OAuth Re-authentication
Run this script once to refresh the Google Calendar OAuth token.
After running, the token auto-refreshes silently indefinitely.

Usage:
    cd C:\\Users\\HP\\maihera\\backend
    python auth/reauth_calendar.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.secrets_service import secrets
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
import json

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"


def reauth():
    print("MAIHERA Calendar + Gmail Re-authentication")
    print("=" * 45)

    if not CREDENTIALS_PATH.exists():
        print(
            f"\n❌ credentials.json not found at {CREDENTIALS_PATH}\n"
            "Download it from Google Cloud Console:\n"
            "  APIs & Services → Credentials → OAuth 2.0 Client → Download JSON\n"
            "Save it to backend/auth/credentials.json (never commit this file)."
        )
        sys.exit(1)

    print("\nOpening browser for Google authentication...")
    print("Sign in with the MAIHERA Google account.\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH), SCOPES
    )
    creds = flow.run_local_server(port=0)

    # Store token components in keyring
    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes) if creds.scopes else SCOPES,
    }

    secrets.set("GOOGLE_TOKEN", json.dumps(token_data))
    print("\n✅ Token stored in Windows Credential Manager.")
    print("   Key: GOOGLE_TOKEN")
    print("   Scopes:", SCOPES)
    print("\nMAIHERA will now auto-refresh this token silently.")
    print("You will not need to re-authenticate again unless you")
    print("revoke access or change the OAuth app scopes.")


if __name__ == "__main__":
    reauth()