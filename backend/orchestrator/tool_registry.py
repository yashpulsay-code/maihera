"""
MAIHERA Orchestrator — Tool Registry
All tools are registered here.
Nothing executes outside this registry.

Tools are registered in order: readers first, writers after.
Readers have no confirmation flow and no side effects —
they validate the Orchestrator is working before confirmation
complexity is introduced.
"""

import logging
from typing import TYPE_CHECKING

from orchestrator.base_tool import BaseTool, AutonomyTier, ToolResult, VerificationResult, VerificationMethod

if TYPE_CHECKING:
    from orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


# ── Concrete Tool Implementations ─────────────────────────────────
# Phase 4 — stub implementations for all 13 tools.
# Each tool's execute() and verify() will be fully implemented
# as the tool's backing service is wired in subsequent steps.
# Stubs return success=True so the Orchestrator flow can be
# tested end-to-end before service wiring.


class CalendarReaderTool(BaseTool):
    name = "calendar_reader"
    action_type = "calendar_read"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 15
    max_retries = 3

    async def execute(self, payload: dict) -> ToolResult:
        try:
            from services.calendar_service import CalendarService
            svc = CalendarService()
            events = await svc.get_upcoming_events(
                days=payload.get("days", 7)
            )
            return ToolResult(
                success=True,
                data={"events": events},
                metadata={"count": len(events)}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = (
            result.success
            and isinstance(result.data.get("events"), list)
        )
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="Events list returned and is a list." if passed
                   else "Events list missing or wrong type."
        )


class CalendarWriterTool(BaseTool):
    name = "calendar_writer"
    action_type = "calendar_create"
    autonomy_tier = AutonomyTier.CONFIRM_FIRST
    timeout_seconds = 20
    max_retries = 3

    async def execute(self, payload: dict) -> ToolResult:
        try:
            from services.calendar_service import CalendarService
            svc = CalendarService()
            event_id = await svc.create_event(
                title=payload["title"],
                start=payload["start"],
                end=payload["end"],
                description=payload.get("description", ""),
                attendees=payload.get("attendees", []),
            )
            return ToolResult(
                success=True,
                data={"event_id": event_id},
                metadata={"event_id": event_id}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        try:
            from services.calendar_service import CalendarService
            svc = CalendarService()
            event_id = result.metadata.get("event_id")
            if not event_id:
                return VerificationResult(
                    passed=False,
                    method=VerificationMethod.EXISTENCE_CHECK,
                    detail="No event_id in metadata — cannot verify."
                )
            event = await svc.get_event(event_id)
            passed = event is not None
            return VerificationResult(
                passed=passed,
                method=VerificationMethod.EXISTENCE_CHECK,
                detail=f"Re-fetched event {event_id} — {'found' if passed else 'NOT FOUND'}."
            )
        except Exception as e:
            return VerificationResult(
                passed=False,
                method=VerificationMethod.EXISTENCE_CHECK,
                detail=f"Verification failed with exception: {e}"
            )

    async def rollback(self, payload: dict, result: ToolResult) -> None:
        try:
            from services.calendar_service import CalendarService
            svc = CalendarService()
            event_id = result.metadata.get("event_id")
            if event_id:
                await svc.delete_event(event_id)
                logger.info("CalendarWriter rollback: deleted event %s", event_id)
        except Exception as e:
            logger.error("CalendarWriter rollback failed: %s", e)


class GitHubReaderTool(BaseTool):
    name = "github_reader"
    action_type = "github_read"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 20
    max_retries = 3

    async def execute(self, payload: dict) -> ToolResult:
        try:
            from services.github_service import GitHubService
            svc = GitHubService()
            data = await svc.get_recent_commits(
                limit=payload.get("limit", 10)
            )
            return ToolResult(
                success=True,
                data={"commits": data},
                metadata={"count": len(data)}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = result.success and "commits" in result.data
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="Commits data returned." if passed else "No commits data."
        )


class GitHubWriterTool(BaseTool):
    name = "github_writer"
    action_type = "github_issue_create"
    autonomy_tier = AutonomyTier.ALWAYS_CONFIRM
    timeout_seconds = 20
    max_retries = 3

    async def execute(self, payload: dict) -> ToolResult:
        try:
            from services.github_service import GitHubService
            svc = GitHubService()
            issue_number = await svc.create_issue(
                title=payload["title"],
                body=payload.get("body", ""),
                labels=payload.get("labels", []),
                repo=payload.get("repo", "Presence"),
            )
            return ToolResult(
                success=True,
                data={"issue_number": issue_number},
                metadata={"issue_number": issue_number, "repo": payload.get("repo", "Presence")}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        try:
            from services.github_service import GitHubService
            svc = GitHubService()
            issue_number = result.metadata.get("issue_number")
            repo = result.metadata.get("repo", "Presence")
            if not issue_number:
                return VerificationResult(
                    passed=False,
                    method=VerificationMethod.EXISTENCE_CHECK,
                    detail="No issue_number in metadata."
                )
            issue = await svc.get_issue(issue_number, repo)
            passed = issue is not None
            return VerificationResult(
                passed=passed,
                method=VerificationMethod.EXISTENCE_CHECK,
                detail=f"Re-fetched issue #{issue_number} — {'found' if passed else 'NOT FOUND'}."
            )
        except Exception as e:
            return VerificationResult(
                passed=False,
                method=VerificationMethod.EXISTENCE_CHECK,
                detail=f"Verification exception: {e}"
            )


class GitHubRepoReaderTool(BaseTool):
    name = "github_repo_reader"
    action_type = "github_repo_read"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 300   # full repo analysis is slow
    max_retries = 1         # expensive — do not retry automatically

    async def execute(self, payload: dict) -> ToolResult:
        try:
            from services.codebase_analysis_service import CodebaseAnalysisService
            svc = CodebaseAnalysisService()
            findings = await svc.analyze()
            return ToolResult(
                success=True,
                data={"findings_count": findings},
                metadata={"analyzed_at": __import__("datetime").datetime.utcnow().isoformat()}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = result.success and result.data.get("findings_count", 0) >= 0
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail=f"Analysis returned {result.data.get('findings_count')} findings."
        )


class GmailSenderTool(BaseTool):
    name = "gmail_sender"
    action_type = "gmail_send"
    autonomy_tier = AutonomyTier.ALWAYS_CONFIRM
    timeout_seconds = 20
    max_retries = 2

    async def execute(self, payload: dict) -> ToolResult:
        try:
            from services.gmail_service import GmailService
            svc = GmailService()
            message_id = await svc.send_email(
                subject=payload["subject"],
                body=payload["body"],
                html=payload.get("html", False),
            )
            return ToolResult(
                success=True,
                data={"message_id": message_id},
                metadata={"message_id": message_id}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        # Send-only scope — cannot re-fetch sent mail
        # Verify by checking message_id was returned
        passed = bool(result.metadata.get("message_id"))
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="message_id returned by Gmail API." if passed
                   else "No message_id — send may have failed silently."
        )


class WebResearcherTool(BaseTool):
    name = "web_researcher"
    action_type = "web_research"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 45
    max_retries = 2

    async def execute(self, payload: dict) -> ToolResult:
        try:
            query = payload.get("query", "")
            if not query:
                return ToolResult(success=False, error="No query provided.")
            # Web research via LLM router web search capability
            # Full implementation wired in tool service step
            return ToolResult(
                success=True,
                data={"query": query, "results": []},
                metadata={"query": query}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = result.success and "results" in result.data
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="Results key present in response." if passed
                   else "Results key missing."
        )


class DriveWriterTool(BaseTool):
    name = "drive_writer"
    action_type = "drive_create"
    autonomy_tier = AutonomyTier.ALWAYS_CONFIRM
    timeout_seconds = 30
    max_retries = 2

    async def execute(self, payload: dict) -> ToolResult:
        try:
            # Drive integration wired in Phase 4 service step
            return ToolResult(
                success=True,
                data={"file_id": "stub"},
                metadata={"file_id": "stub"}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = bool(result.metadata.get("file_id"))
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="file_id returned." if passed else "No file_id."
        )


class FigmaReaderTool(BaseTool):
    name = "figma_reader"
    action_type = "figma_read"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 30
    max_retries = 2

    async def execute(self, payload: dict) -> ToolResult:
        try:
            # Figma MCP integration — Phase 4 service step
            return ToolResult(
                success=True,
                data={"file_key": payload.get("file_key"), "data": {}},
                metadata={"file_key": payload.get("file_key")}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = result.success and "data" in result.data
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="Figma data returned." if passed else "No data returned."
        )


class CanvaCreatorTool(BaseTool):
    name = "canva_creator"
    action_type = "canva_create"
    autonomy_tier = AutonomyTier.ALWAYS_CONFIRM
    timeout_seconds = 60
    max_retries = 2

    async def execute(self, payload: dict) -> ToolResult:
        try:
            # Canva MCP integration — Phase 4 service step
            return ToolResult(
                success=True,
                data={"asset_url": "stub"},
                metadata={"asset_url": "stub"}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        passed = bool(result.metadata.get("asset_url"))
        return VerificationResult(
            passed=passed,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="asset_url returned." if passed else "No asset_url."
        )


class SystemObserverTool(BaseTool):
    name = "system_observer"
    action_type = "system_observe"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 10
    max_retries = 1

    async def execute(self, payload: dict) -> ToolResult:
        try:
            # System activity observation — Phase 5
            return ToolResult(
                success=True,
                data={"active_window": None, "context": "unknown"},
                metadata={}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        return VerificationResult(
            passed=True,
            method=VerificationMethod.NOT_APPLICABLE,
            detail="Read-only observer — no verification required."
        )


class SignalUpdaterTool(BaseTool):
    name = "signal_updater"
    action_type = "signal_update"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 10
    max_retries = 3

    async def execute(self, payload: dict) -> ToolResult:
        try:
            # Signal updates go directly to brain service
            # Full wiring in orchestrator lifespan step
            return ToolResult(
                success=True,
                data={"node_id": payload.get("node_id")},
                metadata={"node_id": payload.get("node_id")}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        return VerificationResult(
            passed=result.success,
            method=VerificationMethod.EXISTENCE_CHECK,
            detail="Signal update accepted." if result.success
                   else "Signal update failed."
        )


class VoiceOutputTool(BaseTool):
    name = "voice_output"
    action_type = "voice_speak"
    autonomy_tier = AutonomyTier.ALWAYS_ALLOW
    timeout_seconds = 10
    max_retries = 2

    async def execute(self, payload: dict) -> ToolResult:
        try:
            return ToolResult(
                success=True,
                data={"text": payload.get("text")},
                metadata={}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def verify(self, payload: dict, result: ToolResult) -> VerificationResult:
        return VerificationResult(
            passed=True,
            method=VerificationMethod.NOT_APPLICABLE,
            detail="Cartesia handles delivery — no re-fetch possible."
        )


# ── Registry Builder ──────────────────────────────────────────────

ALL_TOOLS: list[BaseTool] = [
    # Readers first — no confirmation, no side effects
    CalendarReaderTool(),
    GitHubReaderTool(),
    GitHubRepoReaderTool(),
    SystemObserverTool(),
    SignalUpdaterTool(),
    VoiceOutputTool(),
    WebResearcherTool(),
    FigmaReaderTool(),
    # Writers after — confirmation required
    CalendarWriterTool(),
    GitHubWriterTool(),
    GmailSenderTool(),
    DriveWriterTool(),
    CanvaCreatorTool(),
]


def register_all_tools(orchestrator: "Orchestrator") -> None:
    """Register all tools with the Orchestrator. Call during lifespan init."""
    for tool in ALL_TOOLS:
        orchestrator.register_tool(tool)
    logger.info(
        "ToolRegistry: %d tools registered.", len(ALL_TOOLS)
    )