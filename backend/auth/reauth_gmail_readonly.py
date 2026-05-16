"""
MAIHERA — Add gmail.readonly to existing OAuth token.
Run this once to expand the Gmail scope.
The existing calendar scope is preserved.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow
from services.secrets_service import SecretsService
import json

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"

def main():
    secrets = SecretsService()

    print("Re-authorizing Google OAuth with gmail.readonly scope...")
    print("A browser window will open. Sign in as maihera.ai@gmail.com")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=0)

    token_data = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        list(creds.scopes),
    }
    secrets.set("GOOGLE_TOKEN", json.dumps(token_data))
    print()
    print("New token stored in keyring with scopes:")
    for s in creds.scopes:
        print(f"  {s}")
    print()
    print("Re-auth complete.")

if __name__ == "__main__":
    main()