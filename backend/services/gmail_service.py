"""
MAIHERA Gmail Service
Send-only Gmail integration via Google API.
Triggered explicitly on command — never sends autonomously.
Supports plain text and HTML emails with optional attachments.
"""

import sys
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.google_auth_service import google_auth

logger = logging.getLogger(__name__)

# MAIHERA always sends to Yash's main account
YASH_EMAIL = "yashpulsay@gmail.com"
MAIHERA_EMAIL = "maihera.ai@gmail.com"


class GmailService:
    """
    Send-only Gmail service.
    All emails go from maihera.ai@gmail.com to yashpulsay@gmail.com.
    Never reads inbox. Never sends to third parties.
    """

    def _get_service(self):
        """Return authenticated Gmail API service."""
        return google_auth.get_gmail_service()

    def _build_message(
        self,
        subject: str,
        body: str,
        html: bool = False,
        attachments: list[dict] | None = None
    ) -> dict:
        """
        Build a Gmail API message dict.
        attachments: list of {"filename": str, "path": str} dicts
        Returns {"raw": base64url_encoded_string}
        """
        if attachments:
            msg = MIMEMultipart()
            msg['to']      = YASH_EMAIL
            msg['from']    = MAIHERA_EMAIL
            msg['subject'] = subject

            # Body
            mime_type = 'html' if html else 'plain'
            msg.attach(MIMEText(body, mime_type))

            # Attachments
            for att in attachments:
                att_path = Path(att['path'])
                if not att_path.exists():
                    logger.warning(
                        "Attachment not found, skipping: %s", att_path
                    )
                    continue
                with open(att_path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    'attachment',
                    filename=att.get('filename', att_path.name)
                )
                msg.attach(part)
        else:
            mime_type = 'html' if html else 'plain'
            msg = MIMEText(body, mime_type)
            msg['to']      = YASH_EMAIL
            msg['from']    = MAIHERA_EMAIL
            msg['subject'] = subject

        raw = base64.urlsafe_b64encode(
            msg.as_bytes()
        ).decode('utf-8')
        return {'raw': raw}

    async def send(
        self,
        subject: str,
        body: str,
        html: bool = False,
        attachments: list[dict] | None = None
    ) -> dict:
        """
        Send an email from MAIHERA to Yash.
        Always sends to YASH_EMAIL — no other recipients possible.

        attachments: list of {"filename": str, "path": str}
            path must be an absolute path on the local filesystem.

        Returns {"status": "sent", "message_id": str} on success.
        Raises on failure.
        """
        import asyncio
        loop = asyncio.get_event_loop()

        def _send_blocking():
            service = self._get_service()
            message = self._build_message(
                subject=subject,
                body=body,
                html=html,
                attachments=attachments
            )
            result = service.users().messages().send(
                userId='me',
                body=message
            ).execute()
            return result

        result = await loop.run_in_executor(None, _send_blocking)
        message_id = result.get('id', 'unknown')
        logger.info(
            "Gmail sent: subject='%s' message_id=%s",
            subject, message_id
        )
        return {"status": "sent", "message_id": message_id}

    async def send_brain_export(self, export_path: str) -> dict:
        """
        Send the latest brain export JSON to Yash.
        Convenience method — called by weekly review or on demand.
        """
        path = Path(export_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Brain export not found: {export_path}"
            )

        subject = (
            f"MAIHERA Brain Export — "
            f"{path.stem.replace('maihera_brain_', '')}"
        )
        body = (
            "Boss,\n\n"
            "Attached is your latest brain export. "
            "This contains all nodes and edges as of the export time.\n\n"
            "— MAIHERA"
        )
        return await self.send(
            subject=subject,
            body=body,
            attachments=[{
                "filename": path.name,
                "path":     str(path)
            }]
        )

    async def send_weekly_summary(self, summary_text: str) -> dict:
        """
        Send weekly review summary as formatted email.
        Called by weekly review feature on Sunday.
        """
        subject = (
            f"MAIHERA Weekly Review — "
            f"Week of {__import__('datetime').date.today().isoformat()}"
        )
        return await self.send(
            subject=subject,
            body=summary_text,
            html=False
        )

    async def send_analysis_findings(
        self,
        findings: list[dict]
    ) -> dict:
        """
        Send Presence codebase analysis findings as formatted email.
        Called after a successful analysis run.
        """
        lines = [
            "Boss,\n",
            "Here are MAIHERA's findings from the latest "
            "Presence codebase analysis:\n"
        ]
        for i, f in enumerate(findings, 1):
            lines.append(
                f"\n{i}. [{f['type'].upper()}] {f['label']}\n"
                f"   {f['description']}\n"
                f"   Evidence: {', '.join(f.get('evidence', []))}\n"
                f"   Confidence: {f.get('confidence', 0):.0%}"
            )
        lines.append("\n\n— MAIHERA")

        return await self.send(
            subject="MAIHERA — Presence Codebase Analysis Findings",
            body="\n".join(lines)
        )


# Module-level singleton
gmail_service = GmailService()