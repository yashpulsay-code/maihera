"""
MAIHERA Google Auth Service
Handles OAuth 2.0 flow for Google Calendar and Gmail.
Tokens stored in Windows Credential Manager via SecretsService.
First run opens browser for consent. Subsequent runs use stored refresh token.
"""

import json
import logging
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from services.secrets_service import secrets

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
]

CREDENTIALS_FILE = Path(__file__).parent.parent / "auth" / "credentials.json"

# Keyring keys for token storage
_KEY_ACCESS_TOKEN  = "GOOGLE_OAUTH_ACCESS_TOKEN"
_KEY_REFRESH_TOKEN = "GOOGLE_OAUTH_REFRESH_TOKEN"
_KEY_CLIENT_ID     = "GOOGLE_OAUTH_CLIENT_ID"
_KEY_CLIENT_SECRET = "GOOGLE_OAUTH_CLIENT_SECRET"
_KEY_TOKEN_URI     = "GOOGLE_OAUTH_TOKEN_URI"


class GoogleAuthService:
    """
    Manages Google OAuth credentials lifecycle.
    - First run: browser consent flow, stores tokens in keyring
    - Subsequent runs: loads from keyring, auto-refreshes if expired
    - Never writes tokens to disk
    """

    def __init__(self):
        self._credentials: Credentials | None = None

    def _load_from_keyring(self) -> Credentials | None:
        """Attempt to reconstruct credentials from keyring."""
        refresh_token = secrets.get(_KEY_REFRESH_TOKEN)
        client_id     = secrets.get(_KEY_CLIENT_ID)
        client_secret = secrets.get(_KEY_CLIENT_SECRET)
        token_uri     = secrets.get(_KEY_TOKEN_URI) or "https://oauth2.googleapis.com/token"

        if not all([refresh_token, client_id, client_secret]):
            return None

        creds = Credentials(
            token=secrets.get(_KEY_ACCESS_TOKEN),
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        logger.info("GoogleAuthService: credentials loaded from keyring.")
        return creds

    def _save_to_keyring(self, creds: Credentials) -> None:
        """Persist all token components to keyring."""
        secrets.set(_KEY_ACCESS_TOKEN,  creds.token or "")
        secrets.set(_KEY_REFRESH_TOKEN, creds.refresh_token or "")
        secrets.set(_KEY_CLIENT_ID,     creds.client_id or "")
        secrets.set(_KEY_CLIENT_SECRET, creds.client_secret or "")
        secrets.set(_KEY_TOKEN_URI,     creds.token_uri or "")
        logger.info("GoogleAuthService: tokens saved to keyring.")

    def _run_oauth_flow(self) -> Credentials:
        """
        Run interactive OAuth consent flow.
        Opens browser, waits for user consent, returns credentials.
        """
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"credentials.json not found at {CREDENTIALS_FILE}. "
                "Download it from Google Cloud Console."
            )

        logger.info("GoogleAuthService: starting OAuth consent flow...")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            scopes=SCOPES
        )
        # run_local_server opens browser and handles localhost redirect
        creds = flow.run_local_server(
            port=0,              # OS picks available port
            prompt="consent",    # always show consent screen
            access_type="offline"  # ensures refresh token is returned
        )
        logger.info("GoogleAuthService: OAuth consent completed.")
        return creds

    def get_credentials(self) -> Credentials:
        """
        Return valid credentials. Handles full lifecycle:
        1. Load from keyring if available
        2. Refresh if expired
        3. Run consent flow if no credentials exist
        """
        # Try loading from keyring
        if self._credentials is None:
            self._credentials = self._load_from_keyring()

        # Refresh if expired and refresh token available
        if self._credentials and self._credentials.expired:
            if self._credentials.refresh_token:
                logger.info("GoogleAuthService: refreshing expired token...")
                self._credentials.refresh(Request())
                self._save_to_keyring(self._credentials)
                logger.info("GoogleAuthService: token refreshed.")
            else:
                logger.warning(
                    "GoogleAuthService: token expired, no refresh token. "
                    "Re-running consent flow."
                )
                self._credentials = None

        # Run consent flow if still no valid credentials
        if not self._credentials or not self._credentials.valid:
            self._credentials = self._run_oauth_flow()
            self._save_to_keyring(self._credentials)

        return self._credentials

    def is_authenticated(self) -> bool:
        """Check if valid credentials exist without triggering flow."""
        creds = self._load_from_keyring()
        if creds is None:
            return False
        if creds.expired and not creds.refresh_token:
            return False
        return True

    def revoke(self) -> None:
        """Clear all stored tokens from keyring."""
        for key in [
            _KEY_ACCESS_TOKEN, _KEY_REFRESH_TOKEN,
            _KEY_CLIENT_ID, _KEY_CLIENT_SECRET, _KEY_TOKEN_URI
        ]:
            secrets.delete(key)
        self._credentials = None
        logger.info("GoogleAuthService: all tokens revoked.")


# Module-level singleton
google_auth = GoogleAuthService()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if "--status" in sys.argv:
        print("Google Auth Status:")
        print(f"  Authenticated: {google_auth.is_authenticated()}")
        sys.exit(0)

    print("Running Google OAuth consent flow...")
    print("A browser window will open. Sign in with MAIHERA's Google account.")
    print()

    try:
        creds = google_auth.get_credentials()
        print("✅ Authentication successful.")
        print(f"   Scopes granted: {creds.scopes}")
        print(f"   Token valid:    {creds.valid}")
        print(f"   Has refresh:    {bool(creds.refresh_token)}")
        print()
        print("Tokens stored in Windows Credential Manager.")
        print("MAIHERA will use these automatically on every startup.")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        sys.exit(1)