"""
MAIHERA Secrets Service
Secure credential storage via Windows Credential Manager (keyring).
All sensitive credentials are stored and retrieved through this service.
Non-sensitive config (URLs, caps, paths) stays in .env.

Usage:
    from services.secrets_service import secrets

    key = secrets.get("GROQ_API_KEY")
    secrets.set("GROQ_API_KEY", "sk-...")

Migration (first run):
    python services/secrets_service.py migrate
"""

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Keys managed by this service — never read from .env at runtime
MANAGED_KEYS = [
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "OLLAMA_CLOUD_API_KEY",
    "CARTESIA_API_KEY",
    "CARTESIA_VOICE_ID",
    "GITHUB_TOKEN",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    # OAuth tokens added dynamically by integrations
    "GOOGLE_OAUTH_ACCESS_TOKEN",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
]

KEYRING_SERVICE = "MAIHERA"


class SecretsService:
    """
    Abstraction over Windows Credential Manager via keyring.
    Falls back to environment variable if keyring read fails,
    then warns loudly — .env is not the intended runtime store.
    """

    def __init__(self):
        try:
            import keyring
            self._keyring = keyring
            self._available = True
            logger.info("SecretsService: keyring backend active.")
        except ImportError:
            self._keyring = None
            self._available = False
            logger.warning(
                "SecretsService: keyring not installed. "
                "Falling back to environment variables. "
                "Run: pip install keyring"
            )

    def get(self, key: str) -> str | None:
        """
        Retrieve a credential.
        Primary: Windows Credential Manager via keyring.
        Fallback: environment variable (with warning).
        """
        if self._available:
            try:
                value = self._keyring.get_password(KEYRING_SERVICE, key)
                if value is not None:
                    return value
                # Not in keyring — check env as fallback
                env_value = os.getenv(key)
                if env_value:
                    logger.warning(
                        "SecretsService: '%s' not in keyring — "
                        "using .env fallback. Run migration to secure it.",
                        key
                    )
                    return env_value
                logger.debug("SecretsService: '%s' not found anywhere.", key)
                return None
            except Exception as e:
                logger.error(
                    "SecretsService: keyring read failed for '%s': %s. "
                    "Falling back to env.", key, e
                )
                return os.getenv(key)
        else:
            return os.getenv(key)

    def set(self, key: str, value: str) -> bool:
        """
        Store a credential in Windows Credential Manager.
        Returns True on success, False on failure.
        """
        if not self._available:
            logger.error(
                "SecretsService: keyring not available. "
                "Cannot store '%s' securely.", key
            )
            return False
        try:
            self._keyring.set_password(KEYRING_SERVICE, key, value)
            logger.info("SecretsService: '%s' stored in keyring.", key)
            return True
        except Exception as e:
            logger.error(
                "SecretsService: failed to store '%s': %s", key, e
            )
            return False

    def delete(self, key: str) -> bool:
        """Remove a credential from keyring."""
        if not self._available:
            return False
        try:
            self._keyring.delete_password(KEYRING_SERVICE, key)
            logger.info("SecretsService: '%s' deleted from keyring.", key)
            return True
        except Exception as e:
            logger.warning(
                "SecretsService: could not delete '%s': %s", key, e
            )
            return False

    def is_stored(self, key: str) -> bool:
        """Check if a key exists in keyring (not env fallback)."""
        if not self._available:
            return False
        try:
            return self._keyring.get_password(KEYRING_SERVICE, key) is not None
        except Exception:
            return False

    def status(self) -> dict:
        """Return storage status for all managed keys."""
        result = {}
        for key in MANAGED_KEYS:
            in_keyring = self.is_stored(key)
            in_env     = bool(os.getenv(key))
            result[key] = {
                "keyring": in_keyring,
                "env":     in_env,
                "secure":  in_keyring,
            }
        return result


# Module-level singleton — import this everywhere
secrets = SecretsService()


# ── Migration ─────────────────────────────────────────────────────────

def migrate_from_env(env_path: Path) -> None:
    """
    One-time migration: reads all managed keys from .env,
    stores them in keyring, then removes them from .env.
    Leaves a placeholder comment in .env so the key is documented.
    """
    load_dotenv(env_path)

    migrated   = []
    not_found  = []
    already_in = []

    svc = SecretsService()

    for key in MANAGED_KEYS:
        if svc.is_stored(key):
            already_in.append(key)
            continue

        value = os.getenv(key)
        if not value or value.startswith("your_"):
            not_found.append(key)
            continue

        success = svc.set(key, value)
        if success:
            migrated.append(key)
        else:
            print(f"  FAILED to migrate {key}")

    print(f"\nMigration complete:")
    print(f"  Migrated to keyring:  {len(migrated)}")
    print(f"  Already in keyring:   {len(already_in)}")
    print(f"  Not found / skipped:  {len(not_found)}")

    if migrated:
        print(f"\nMigrated keys: {', '.join(migrated)}")
    if not_found:
        print(f"Skipped (placeholder or missing): {', '.join(not_found)}")

    # Rewrite .env — replace real values with keyring markers
    env_lines  = env_path.read_text(encoding="utf-8").splitlines()
    new_lines  = []
    for line in env_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in migrated:
                new_lines.append(
                    f"# {k}=<stored in Windows Credential Manager>"
                )
                continue
        new_lines.append(line)

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"\n.env updated — migrated keys replaced with keyring markers.")
    print("Your credentials are now secured in Windows Credential Manager.")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(level=logging.INFO)
    env_path = Path(__file__).parent.parent / ".env"

    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        print("Migrating credentials from .env to Windows Credential Manager...")
        migrate_from_env(env_path)
    else:
        # Status check
        print("MAIHERA Secrets Service — credential status\n")
        svc = SecretsService()
        status = svc.status()
        for key, info in status.items():
            indicator = "✓ keyring" if info["keyring"] else (
                "⚠ env only" if info["env"] else "✗ missing"
            )
            print(f"  {indicator:12}  {key}")