"""
MAIHERA Orchestrator — Core
Single authority for all execution.
Nothing executes without passing through here.

submit() → autonomy check → confirmation or queue → execute → verify → complete
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from orchestrator.base_tool import AutonomyTier, ToolResult, VerificationResult

if TYPE_CHECKING:
    from brain.sqlite_store import DatabaseManager
    from api.websocket_manager import WebSocketManager
    from orchestrator.confirmation_broker import ConfirmationBroker

logger = logging.getLogger(__name__)

# Cooldown in seconds per tool_name — enforced at submit time
TOOL_COOLDOWNS: dict[str, int] = {
    "github_repo_reader": 48 * 3600,   # 48 hours — expensive analysis
    "web_researcher":      300,         # 5 minutes — prevent rapid re-search
}


class Orchestrator:
    """
    Central control for all MAIHERA execution.

    Responsibilities:
    - Autonomy tier enforcement
    - Confirmation routing via ConfirmationBroker
    - Task lifecycle management in SQLite
    - Retry with exponential backoff
    - Verification after every execution
    - Cooldown enforcement per tool
    - Failure surfacing to Yash — never silent drops
    """

    def __init__(
        self,
        db: "DatabaseManager",
        confirmation_broker: "ConfirmationBroker",
    ):
        self.db = db
        self.broker = confirmation_broker
        self._ws_manager: Optional["WebSocketManager"] = None
        self._voice_service = None
        self._tool_registry: dict[str, object] = {}
        # populated by ToolRegistry.register_all()

    def set_ws_manager(self, ws_manager: "WebSocketManager") -> None:
        self._ws_manager = ws_manager

    def set_voice_service(self, voice_service) -> None:
        self._voice_service = voice_service

    def register_tool(self, tool) -> None:
        """Called by ToolRegistry to register each tool."""
        self._tool_registry[tool.name] = tool
        logger.info("Tool registered: %s (tier=%s)", tool.name, tool.autonomy_tier)

    # ── Public API ────────────────────────────────────────────────

    async def submit(
        self,
        action_type: str,
        tool_name: str,
        payload: dict,
        explicit_instruction: bool = False,
        parent_skill_id: Optional[str] = None,
        skill_step_index: Optional[int] = None,
    ) -> str:
        """
        Submit a task for execution.
        Returns task_id.

        explicit_instruction=True bypasses explicit_only tier check.
        Used when Yash directly instructs an action in conversation.
        """
        tool = self._tool_registry.get(tool_name)
        if not tool:
            raise ValueError(
                f"Tool '{tool_name}' not registered. "
                f"Available: {list(self._tool_registry.keys())}"
            )

        autonomy_tier = tool.autonomy_tier
        task_id = str(uuid.uuid4())

        # ── Explicit-only gate ────────────────────────────────────
        if (autonomy_tier == AutonomyTier.EXPLICIT_ONLY
                and not explicit_instruction):
            await self._surface_to_yash(
                f"Boss, I need your explicit instruction before I can "
                f"run '{action_type}'. Tell me directly to proceed."
            )
            logger.warning(
                "Task rejected — explicit_only tier not satisfied: %s",
                action_type
            )
            return task_id  # task never written to DB

        # ── Cooldown check ────────────────────────────────────────
        cooldown = TOOL_COOLDOWNS.get(tool_name)
        if cooldown:
            last = self.db.get_last_completed_task_by_tool(tool_name)
            if last and last.get("completed_at"):
                elapsed = (
                    datetime.utcnow()
                    - datetime.fromisoformat(last["completed_at"])
                ).total_seconds()
                if elapsed < cooldown:
                    remaining_h = int((cooldown - elapsed) / 3600)
                    remaining_m = int(((cooldown - elapsed) % 3600) / 60)
                    msg = (
                        f"Boss, '{tool_name}' was last run "
                        f"{int(elapsed/3600)}h ago. "
                        f"Cooldown: {remaining_h}h {remaining_m}m remaining."
                    )
                    await self._surface_to_yash(msg)
                    logger.info(
                        "Task blocked by cooldown: %s (%.0fs remaining)",
                        tool_name, cooldown - elapsed
                    )
                    return task_id

        # ── Write task to DB ──────────────────────────────────────
        requires_confirmation = autonomy_tier in (
            AutonomyTier.CONFIRM_FIRST,
            AutonomyTier.ALWAYS_CONFIRM,
        )
        initial_status = (
            "pending_confirmation" if requires_confirmation else "queued"
        )

        self.db.create_orchestrator_task({
            "id": task_id,
            "action_type": action_type,
            "tool_name": tool_name,
            "payload": payload,
            "status": initial_status,
            "requires_confirmation": requires_confirmation,
            "autonomy_tier": autonomy_tier.value,
            "max_retries": tool.max_retries,
            "parent_skill_id": parent_skill_id,
            "skill_step_index": skill_step_index,
        })

        logger.info(
            "Task submitted: %s | tool=%s | tier=%s | status=%s",
            task_id, tool_name, autonomy_tier.value, initial_status
        )

        # ── Route by autonomy tier ────────────────────────────────
        if requires_confirmation:
            await self._request_confirmation(task_id, action_type, payload)
        else:
            asyncio.create_task(self._execute_task(task_id))

        return task_id

    async def get_status(self, task_id: str) -> Optional[dict]:
        return self.db.get_orchestrator_task(task_id)

    async def cancel(self, task_id: str) -> None:
        task = self.db.get_orchestrator_task(task_id)
        if not task:
            logger.warning("cancel() called on unknown task: %s", task_id)
            return
        if task["status"] in ("completed", "failed", "cancelled"):
            logger.info(
                "cancel() ignored — task already terminal: %s (%s)",
                task_id, task["status"]
            )
            return
        self.db.update_orchestrator_task(task_id, {"status": "cancelled"})
        logger.info("Task cancelled: %s", task_id)

    # ── Confirmation Flow ─────────────────────────────────────────

    async def _request_confirmation(
        self, task_id: str, action_type: str, payload: dict
    ) -> None:
        action_summary = self._build_action_summary(action_type, payload)

        async def on_confirmed():
            self.db.update_orchestrator_task(
                task_id, {"status": "queued"}
            )
            asyncio.create_task(self._execute_task(task_id))

        async def on_cancelled():
            self.db.update_orchestrator_task(
                task_id, {"status": "cancelled"}
            )
            logger.info("Task cancelled via confirmation: %s", task_id)

        confirmation_id = await self.broker.request(
            task_id=task_id,
            action_summary=action_summary,
            full_detail=payload,
            on_confirmed=on_confirmed,
            on_cancelled=on_cancelled,
            expires_minutes=30,
        )

        self.db.update_orchestrator_task(
            task_id, {"confirmation_id": confirmation_id}
        )

    # ── Execution ─────────────────────────────────────────────────

    async def _execute_task(self, task_id: str) -> None:
        task = self.db.get_orchestrator_task(task_id)
        if not task:
            logger.error("_execute_task: task not found: %s", task_id)
            return

        tool = self._tool_registry.get(task["tool_name"])
        if not tool:
            logger.error(
                "_execute_task: tool not found: %s", task["tool_name"]
            )
            return

        payload = __import__("json").loads(task["payload"])
        retry_count = task["retry_count"]
        max_retries = task["max_retries"]

        self.db.update_orchestrator_task(task_id, {
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
        })

        # ── Retry loop ────────────────────────────────────────────
        result: Optional[ToolResult] = None
        last_error: Optional[str] = None

        for attempt in range(retry_count, max_retries + 1):
            if attempt > retry_count:
                backoff = min(2 ** attempt, 60)
                logger.info(
                    "Retry %d/%d for task %s — waiting %ds",
                    attempt, max_retries, task_id, backoff
                )
                await asyncio.sleep(backoff)

            try:
                result = await asyncio.wait_for(
                    tool.execute(payload),
                    timeout=tool.timeout_seconds
                )
            except asyncio.TimeoutError:
                last_error = (
                    f"Tool '{tool.name}' timed out "
                    f"after {tool.timeout_seconds}s"
                )
                logger.warning(last_error)
                self.db.update_orchestrator_task(task_id, {
                    "retry_count": attempt + 1,
                    "last_error": last_error,
                })
                continue
            except Exception as e:
                last_error = str(e)
                logger.error(
                    "Tool '%s' raised unexpected exception: %s",
                    tool.name, e
                )
                self.db.update_orchestrator_task(task_id, {
                    "retry_count": attempt + 1,
                    "last_error": last_error,
                })
                continue

            if result.success:
                break
            else:
                last_error = result.error or "Unknown error"
                logger.warning(
                    "Task %s attempt %d failed: %s",
                    task_id, attempt + 1, last_error
                )
                self.db.update_orchestrator_task(task_id, {
                    "retry_count": attempt + 1,
                    "last_error": last_error,
                })

        # ── Post-execution ────────────────────────────────────────
        if result and result.success:
            await self._post_success(task_id, tool, payload, result)
        else:
            await self._post_failure(task_id, last_error or "Max retries exceeded")

    async def _post_success(
        self,
        task_id: str,
        tool,
        payload: dict,
        result: ToolResult,
    ) -> None:
        # Run verification
        try:
            verification = await tool.verify(payload, result)
        except Exception as e:
            verification = VerificationResult(
                passed=False,
                method=__import__(
                    "orchestrator.base_tool",
                    fromlist=["VerificationMethod"]
                ).VerificationMethod.NOT_APPLICABLE,
                detail=f"Verification raised exception: {e}"
            )

        self.db.update_orchestrator_task(task_id, {
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "result": __import__("json").dumps(result.data),
            "verified": int(verification.passed),
            "verification_result": __import__("json").dumps({
                "passed": verification.passed,
                "method": verification.method.value,
                "detail": verification.detail,
            }),
        })

        if verification.passed:
            logger.info(
                "Task completed and verified: %s", task_id
            )
        else:
            # Completed but verification failed — surface to Yash
            msg = (
                f"Boss, the action completed but verification flagged "
                f"an issue: {verification.detail}. "
                f"You may want to check manually."
            )
            logger.warning(
                "Task %s completed but verification failed: %s",
                task_id, verification.detail
            )
            await self._surface_to_yash(msg)

    async def _post_failure(
        self, task_id: str, error: str
    ) -> None:
        self.db.update_orchestrator_task(task_id, {
            "status": "failed",
            "completed_at": datetime.utcnow().isoformat(),
            "last_error": error,
        })
        task = self.db.get_orchestrator_task(task_id)
        action_type = task["action_type"] if task else "unknown action"

        msg = (
            f"Boss, I wasn't able to complete '{action_type}'. "
            f"Error: {error}. I've logged it — want me to try again?"
        )
        logger.error("Task failed: %s — %s", task_id, error)
        await self._surface_to_yash(msg)

    # ── Utilities ─────────────────────────────────────────────────

    def _build_action_summary(
        self, action_type: str, payload: dict
    ) -> str:
        """
        Build a human-readable summary of the action for
        the confirmation message. Extend this as tools are added.
        """
        summaries = {
            "calendar_create": lambda p: (
                f"create a calendar event: "
                f"'{p.get('title', 'untitled')}' on "
                f"{p.get('date', 'unknown date')}"
            ),
            "github_issue_create": lambda p: (
                f"create a GitHub issue: "
                f"'{p.get('title', 'untitled')}' in "
                f"{p.get('repo', 'unknown repo')}"
            ),
            "drive_create": lambda p: (
                f"create a Drive document: "
                f"'{p.get('title', 'untitled')}'"
            ),
            "canva_create": lambda p: (
                f"create a Canva asset: "
                f"'{p.get('title', 'untitled')}'"
            ),
        }
        builder = summaries.get(action_type)
        if builder:
            try:
                return builder(payload)
            except Exception:
                pass
        return f"{action_type.replace('_', ' ')}"

    async def _surface_to_yash(self, message: str) -> None:
        """Send a message to Yash via voice and chat."""
        if self._voice_service:
            try:
                await self._voice_service.enqueue_speech(
                    text=message, node_ids=[], priority="normal"
                )
            except Exception as e:
                logger.error("Voice surface error: %s", e)
        if self._ws_manager:
            try:
                await self._ws_manager.send_maihera_speak(
                    text=message, node_ids=[], priority="normal"
                )
            except Exception as e:
                logger.error("WS surface error: %s", e)