"""
MAIHERA Orchestrator — Base Tool Interface
Every tool in the ToolRegistry implements this contract.
No tool executes outside this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AutonomyTier(str, Enum):
    ALWAYS_ALLOW   = "always_allow"
    CONFIRM_FIRST  = "confirm_first"
    ALWAYS_CONFIRM = "always_confirm"
    EXPLICIT_ONLY  = "explicit_only"


class VerificationMethod(str, Enum):
    EXISTENCE_CHECK    = "existence_check"
    SEMANTIC_CHECK     = "semantic_check"
    IDEMPOTENCY_CHECK  = "idempotency_check"
    NOT_APPLICABLE     = "not_applicable"


@dataclass
class ToolResult:
    success: bool
    data: dict = field(default_factory=dict)
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    # metadata carries IDs, timestamps, API response codes
    # needed by verify() to re-fetch and confirm the action


@dataclass
class VerificationResult:
    passed: bool
    method: VerificationMethod
    detail: str
    # detail explains what was checked and what was found
    # e.g. "Re-fetched event ID cal_abc123 — title and time match payload"


class BaseTool(ABC):
    """
    Abstract base class for all MAIHERA tools.
    Subclasses must implement execute() and verify().
    rollback() is optional — only tools with reversible
    side effects need to implement it.
    """

    # Every subclass declares these as class attributes
    name: str                        # unique tool identifier
    action_type: str                 # maps to orchestrator_tasks.action_type
    autonomy_tier: AutonomyTier      # default confirmation requirement
    timeout_seconds: int = 30        # max execution time before abort
    max_retries: int = 3             # max retry attempts on failure

    @abstractmethod
    async def execute(self, payload: dict) -> ToolResult:
        """
        Execute the tool action.
        Must be idempotent where possible.
        Never raises — catches all exceptions and returns
        ToolResult(success=False, error=str(e)).
        """
        ...

    @abstractmethod
    async def verify(
        self, payload: dict, result: ToolResult
    ) -> VerificationResult:
        """
        Verify the action was executed correctly.
        Called after every successful execute().
        Uses result.metadata to re-fetch and confirm.
        """
        ...

    async def rollback(
        self, payload: dict, result: ToolResult
    ) -> None:
        """
        Undo a completed action if a later skill step fails.
        Optional — only implement for tools with side effects.
        Default: no-op with a log warning.
        """
        import logging
        logging.getLogger(__name__).warning(
            "rollback() called on %s but not implemented. "
            "Manual cleanup may be required. Payload: %s",
            self.name, payload
        )

    def __repr__(self) -> str:
        return (
            f"<Tool name={self.name} "
            f"tier={self.autonomy_tier} "
            f"timeout={self.timeout_seconds}s>"
        )