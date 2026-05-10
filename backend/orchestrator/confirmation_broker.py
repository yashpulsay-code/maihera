"""
MAIHERA Orchestrator — Confirmation Broker
Single authority for all pending confirmations.
The Orchestrator submits confirmation requests here.
The chat handler resolves them here.
No tool handles confirmation directly.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from brain.sqlite_store import DatabaseManager
    from api.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)

# Words that signal a positive confirmation from Yash
CONFIRM_SIGNALS = {
    "yes", "yeah", "yep", "yup", "confirm", "confirmed",
    "do it", "go ahead", "proceed", "sure", "ok", "okay",
    "approved", "approve", "execute", "run it", "yes do it",
}

# Words that signal a cancellation
CANCEL_SIGNALS = {
    "no", "nope", "cancel", "cancelled", "skip", "abort",
    "don't", "do not", "stop", "nevermind", "never mind",
    "forget it", "reject", "no thanks",
}


class ConfirmationBroker:
    """
    Owns the full lifecycle of pending confirmations.

    Flow:
        Orchestrator calls request() when a task needs confirmation.
        Broker stores it, notifies Yash via WS + voice.
        Chat handler calls resolve() when Yash responds.
        Broker validates, updates DB, notifies Orchestrator callback.
        APScheduler calls expire_stale() periodically.
    """

    def __init__(self, db: "DatabaseManager"):
        self.db = db
        self._ws_manager: Optional["WebSocketManager"] = None
        self._voice_service = None
        self._pending_callbacks: dict[str, callable] = {}
        # confirmation_id → async callable invoked on resolution

    def set_ws_manager(self, ws_manager: "WebSocketManager") -> None:
        self._ws_manager = ws_manager

    def set_voice_service(self, voice_service) -> None:
        self._voice_service = voice_service

    # ── Public API ────────────────────────────────────────────────

    async def request(
        self,
        task_id: str,
        action_summary: str,
        full_detail: dict,
        on_confirmed: callable,
        on_cancelled: callable,
        expires_minutes: int = 30,
    ) -> str:
        """
        Register a new confirmation request.
        Returns confirmation_id.

        on_confirmed: async callable() — called when Yash confirms.
        on_cancelled: async callable() — called when Yash cancels
                      or confirmation expires.
        """
        confirmation_id = str(uuid.uuid4())
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=expires_minutes)

        self.db.create_confirmation({
            "id": confirmation_id,
            "task_id": task_id,
            "action_summary": action_summary,
            "full_detail": full_detail,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        })

        self._pending_callbacks[confirmation_id] = {
            "on_confirmed": on_confirmed,
            "on_cancelled": on_cancelled,
        }

        logger.info(
            "Confirmation requested: %s — %s",
            confirmation_id, action_summary
        )

        # Notify frontend via WebSocket
        await self._notify_requested(
            confirmation_id, task_id,
            action_summary, full_detail,
            expires_at.isoformat()
        )

        # Speak the confirmation request
        await self._speak_request(action_summary)

        return confirmation_id

    async def resolve(
        self,
        text: str,
        resolved_by: str = "text"
    ) -> bool:
        """
        Attempt to resolve a pending confirmation from
        Yash's chat or voice input.

        Returns True if the text was a confirmation signal
        and was routed here (chat handler should not process
        the message further).
        Returns False if the text was not a confirmation signal
        or no confirmation is pending.

        Critical rule: only resolves if exactly ONE confirmation
        is pending. If multiple are pending, sends disambiguation
        message and returns True (message consumed, not passed
        to LLM).
        """
        pending = self.db.get_pending_confirmations()

        if not pending:
            return False

        normalized = text.lower().strip()
        is_confirm = any(s in normalized for s in CONFIRM_SIGNALS)
        is_cancel = any(s in normalized for s in CANCEL_SIGNALS)

        if not is_confirm and not is_cancel:
            # Not a resolution signal — pass through to chat
            return False

        if len(pending) > 1:
            # Ambiguous — ask for clarification
            summaries = "\n".join(
                f"• {c['action_summary']}" for c in pending
            )
            msg = (
                f"Boss, I have {len(pending)} actions waiting. "
                f"Which one?\n{summaries}"
            )
            await self._speak(msg)
            if self._ws_manager:
                await self._ws_manager.send_maihera_speak(
                    text=msg, node_ids=[], priority="normal"
                )
            return True  # message consumed

        # Exactly one pending — resolve it
        confirmation = pending[0]
        confirmation_id = confirmation["id"]

        if is_confirm:
            await self._do_resolve(
                confirmation_id, "confirmed", resolved_by
            )
        else:
            await self._do_resolve(
                confirmation_id, "cancelled", resolved_by
            )

        return True  # message consumed

    async def expire_stale(self) -> None:
        """
        Called by APScheduler. Expires timed-out confirmations
        and fires their on_cancelled callbacks.
        """
        expired_ids = self.db.expire_stale_confirmations()
        for confirmation_id in expired_ids:
            logger.info("Confirmation expired: %s", confirmation_id)
            confirmation = self.db.get_confirmation(confirmation_id)
            action_summary = confirmation["action_summary"] if confirmation else "unknown action"

            # Fire cancelled callback
            callbacks = self._pending_callbacks.pop(confirmation_id, {})
            on_cancelled = callbacks.get("on_cancelled")
            if on_cancelled:
                try:
                    await on_cancelled()
                except Exception as e:
                    logger.error(
                        "on_cancelled callback error for %s: %s",
                        confirmation_id, e
                    )

            # Notify frontend
            if self._ws_manager:
                await self._ws_manager.broadcast({
                    "type": "confirmation_expired",
                    "payload": {
                        "confirmation_id": confirmation_id,
                        "action_summary": action_summary,
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                })

            # Speak the expiry notice
            msg = (
                f"Boss, the confirmation for '{action_summary}' "
                f"timed out. Want me to re-propose it?"
            )
            await self._speak(msg)
            if self._ws_manager:
                await self._ws_manager.send_maihera_speak(
                    text=msg, node_ids=[], priority="normal"
                )

    def get_pending_count(self) -> int:
        """Used by chat handler before routing a message."""
        return len(self.db.get_pending_confirmations())

    # ── Internal ──────────────────────────────────────────────────

    async def _do_resolve(
        self,
        confirmation_id: str,
        status: str,
        resolved_by: str
    ) -> None:
        self.db.resolve_confirmation(confirmation_id, status, resolved_by)

        callbacks = self._pending_callbacks.pop(confirmation_id, {})
        confirmation = self.db.get_confirmation(confirmation_id)
        action_summary = confirmation["action_summary"] if confirmation else ""

        if status == "confirmed":
            on_confirmed = callbacks.get("on_confirmed")
            if on_confirmed:
                try:
                    await on_confirmed()
                except Exception as e:
                    logger.error(
                        "on_confirmed callback error for %s: %s",
                        confirmation_id, e
                    )
            msg = f"Got it Boss. Executing: {action_summary}."
        else:
            on_cancelled = callbacks.get("on_cancelled")
            if on_cancelled:
                try:
                    await on_cancelled()
                except Exception as e:
                    logger.error(
                        "on_cancelled callback error for %s: %s",
                        confirmation_id, e
                    )
            msg = f"Cancelled. I won't proceed with: {action_summary}."

        logger.info(
            "Confirmation %s — %s (by %s)",
            status, confirmation_id, resolved_by
        )

        # Notify frontend
        if self._ws_manager:
            await self._ws_manager.broadcast({
                "type": "confirmation_resolved",
                "payload": {
                    "confirmation_id": confirmation_id,
                    "resolved_by": resolved_by,
                    "action_summary": action_summary,
                },
                "timestamp": datetime.utcnow().isoformat(),
            })

        await self._speak(msg)
        if self._ws_manager:
            await self._ws_manager.send_maihera_speak(
                text=msg, node_ids=[], priority="normal"
            )

    async def _notify_requested(
        self,
        confirmation_id: str,
        task_id: str,
        action_summary: str,
        full_detail: dict,
        expires_at: str,
    ) -> None:
        if self._ws_manager:
            await self._ws_manager.broadcast({
                "type": "confirmation_requested",
                "payload": {
                    "confirmation_id": confirmation_id,
                    "task_id": task_id,
                    "action_summary": action_summary,
                    "full_detail": full_detail,
                    "expires_at": expires_at,
                },
                "timestamp": datetime.utcnow().isoformat(),
            })

    async def _speak_request(self, action_summary: str) -> None:
        msg = f"Boss, I want to {action_summary}. Confirm?"
        await self._speak(msg)
        if self._ws_manager:
            await self._ws_manager.send_maihera_speak(
                text=msg, node_ids=[], priority="normal"
            )

    async def _speak(self, text: str) -> None:
        if self._voice_service:
            try:
                await self._voice_service.enqueue_speech(
                    text=text, node_ids=[], priority="normal"
                )
            except Exception as e:
                logger.error("Voice error in broker: %s", e)