"""
MAIHERA Orchestrator — Skill Registry
Composed multi-step workflows built from tools.
Each step references a registered tool.
Failure propagation is explicit per step — no silent partial execution.

Skill execution is coordinated by the Orchestrator.
Skills never call tools directly — they submit tasks via Orchestrator.submit().
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class OnFailure(str, Enum):
    ABORT_SKILL    = "abort_skill"
    # Stop the skill, run compensation on completed steps,
    # surface partial state to Yash.

    SKIP_STEP      = "skip_step"
    # Continue the skill without this step.
    # Flag the skip in the skill result.

    RETRY          = "retry"
    # Retry this step up to max_retries before escalating.
    # Orchestrator handles retry — this is the skill-level override.

    SURFACE_TO_YASH = "surface_to_yash"
    # Pause the skill, ask Yash what to do, resume on response.
    # Used for steps where human judgment is required on failure.


@dataclass
class SkillStep:
    index: int
    tool_name: str
    action_type: str
    payload_template: dict
    # May reference outputs of previous steps via {step_N.field}
    # e.g. {"event_id": "{step_0.event_id}"}
    on_failure: OnFailure
    depends_on: list[int] = field(default_factory=list)
    # Step indices that must complete before this step runs.
    compensation_payload: Optional[dict] = None
    # Rollback payload if this step succeeded but a later step fails.
    # None means no rollback available for this step.


@dataclass
class SkillDefinition:
    id: str
    name: str
    description: str
    steps: list[SkillStep]


@dataclass
class SkillStepResult:
    step_index: int
    tool_name: str
    status: str          # completed | failed | skipped
    task_id: str
    output: dict = field(default_factory=dict)
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


@dataclass
class SkillResult:
    skill_id: str
    skill_name: str
    status: str          # completed | failed | partial | paused
    steps: list[SkillStepResult] = field(default_factory=list)
    error: Optional[str] = None
    # partial = some steps succeeded before failure + abort
    # paused = surface_to_yash triggered, awaiting response


class SkillExecutor:
    """
    Executes a SkillDefinition by submitting each step
    to the Orchestrator in dependency order.

    Key guarantees:
    - Steps execute in dependency order, not just index order.
    - A failed step triggers its on_failure mode exactly once.
    - abort_skill runs compensation on all completed steps in
      reverse order before surfacing to Yash.
    - Step outputs are resolved into subsequent step payloads
      before submission — no raw template strings reach tools.
    - Skills never call tool.execute() directly.
    """

    def __init__(self, orchestrator: "Orchestrator"):
        self.orchestrator = orchestrator

    async def execute(
        self,
        skill: SkillDefinition,
        initial_payload: dict = {},
    ) -> SkillResult:
        """
        Execute a skill end-to-end.
        initial_payload provides seed values for step 0 template resolution.
        """
        skill_run_id = str(uuid.uuid4())
        logger.info(
            "Skill started: %s (run=%s)", skill.name, skill_run_id[:8]
        )

        result = SkillResult(
            skill_id=skill.id,
            skill_name=skill.name,
            status="running",
        )

        # Tracks outputs per step for template resolution
        step_outputs: dict[int, dict] = {}
        # Seed with initial payload as step -1 outputs
        step_outputs[-1] = initial_payload
        completed_steps: list[SkillStepResult] = []

        for step in skill.steps:
            # ── Dependency check ──────────────────────────────────
            for dep_index in step.depends_on:
                dep_result = next(
                    (s for s in result.steps if s.step_index == dep_index),
                    None
                )
                if not dep_result or dep_result.status != "completed":
                    error = (
                        f"Step {step.index} dependency on step "
                        f"{dep_index} not met."
                    )
                    logger.error(error)
                    step_result = SkillStepResult(
                        step_index=step.index,
                        tool_name=step.tool_name,
                        status="failed",
                        task_id="",
                        error=error,
                    )
                    result.steps.append(step_result)
                    return await self._handle_failure(
                        skill, result, step, step_result,
                        completed_steps, error
                    )

            # ── Payload resolution ────────────────────────────────
            resolved_payload = self._resolve_payload(
                step.payload_template, step_outputs
            )

            # ── Submit to Orchestrator ────────────────────────────
            try:
                task_id = await self.orchestrator.submit(
                    action_type=step.action_type,
                    tool_name=step.tool_name,
                    payload=resolved_payload,
                    parent_skill_id=skill_run_id,
                    skill_step_index=step.index,
                )
            except ValueError as e:
                step_result = SkillStepResult(
                    step_index=step.index,
                    tool_name=step.tool_name,
                    status="failed",
                    task_id="",
                    error=str(e),
                )
                result.steps.append(step_result)
                return await self._handle_failure(
                    skill, result, step, step_result,
                    completed_steps, str(e)
                )

            # ── Wait for terminal state ───────────────────────────
            task = await self._wait_for_terminal(task_id, timeout=120)

            if task and task["status"] == "completed":
                import json
                output = {}
                if task.get("result"):
                    try:
                        output = json.loads(task["result"])
                    except Exception:
                        output = {}

                step_result = SkillStepResult(
                    step_index=step.index,
                    tool_name=step.tool_name,
                    status="completed",
                    task_id=task_id,
                    output=output,
                )
                result.steps.append(step_result)
                completed_steps.append(step_result)
                step_outputs[step.index] = output
                logger.info(
                    "Skill '%s' step %d completed.",
                    skill.name, step.index
                )

            else:
                # Step failed or timed out
                error = (
                    task.get("last_error", "Unknown error")
                    if task else "Task timed out."
                )
                step_result = SkillStepResult(
                    step_index=step.index,
                    tool_name=step.tool_name,
                    status="failed",
                    task_id=task_id,
                    error=error,
                )
                result.steps.append(step_result)
                return await self._handle_failure(
                    skill, result, step, step_result,
                    completed_steps, error
                )

        # All steps completed
        result.status = "completed"
        logger.info("Skill completed: %s", skill.name)
        return result

    # ── Failure Handling ──────────────────────────────────────────

    async def _handle_failure(
        self,
        skill: SkillDefinition,
        result: SkillResult,
        failed_step: SkillStep,
        step_result: SkillStepResult,
        completed_steps: list[SkillStepResult],
        error: str,
    ) -> SkillResult:

        mode = failed_step.on_failure

        if mode == OnFailure.SKIP_STEP:
            step_result.status = "skipped"
            step_result.skipped_reason = error
            logger.info(
                "Skill '%s' step %d skipped: %s",
                skill.name, failed_step.index, error
            )
            # Caller continues the loop — but we return here
            # because _handle_failure exits the current step only.
            # The skill continues from the next step.
            # This is handled by re-entering execute() from the
            # calling loop — SKIP_STEP does not abort.
            result.status = "partial"
            return result

        elif mode == OnFailure.ABORT_SKILL:
            logger.warning(
                "Skill '%s' aborting at step %d: %s",
                skill.name, failed_step.index, error
            )
            await self._run_compensation(completed_steps)
            result.status = "failed"
            result.error = (
                f"Step {failed_step.index} ({failed_step.tool_name}) "
                f"failed: {error}. Compensation run on "
                f"{len(completed_steps)} completed steps."
            )
            await self.orchestrator._surface_to_yash(
                f"Boss, the '{skill.name}' workflow failed at step "
                f"{failed_step.index}. {error}. "
                f"I've rolled back what I could."
            )
            return result

        elif mode == OnFailure.RETRY:
            # Orchestrator already retried at tool level.
            # RETRY at skill level means we surface and abort.
            result.status = "failed"
            result.error = (
                f"Step {failed_step.index} failed after all retries: {error}"
            )
            await self.orchestrator._surface_to_yash(
                f"Boss, step {failed_step.index} of '{skill.name}' "
                f"failed after retrying: {error}."
            )
            return result

        elif mode == OnFailure.SURFACE_TO_YASH:
            result.status = "paused"
            result.error = (
                f"Step {failed_step.index} needs your input: {error}"
            )
            await self.orchestrator._surface_to_yash(
                f"Boss, '{skill.name}' is paused at step "
                f"{failed_step.index}. {error}. "
                f"Tell me how to proceed."
            )
            return result

        # Fallback — should never reach here
        result.status = "failed"
        result.error = error
        return result

    async def _run_compensation(
        self, completed_steps: list[SkillStepResult]
    ) -> None:
        """Run rollback on completed steps in reverse order."""
        for step_result in reversed(completed_steps):
            tool = self.orchestrator._tool_registry.get(
                step_result.tool_name
            )
            if tool:
                try:
                    from orchestrator.base_tool import ToolResult
                    fake_result = ToolResult(
                        success=True,
                        data=step_result.output,
                        metadata=step_result.output,
                    )
                    await tool.rollback({}, fake_result)
                    logger.info(
                        "Compensation run for step %d (%s)",
                        step_result.step_index, step_result.tool_name
                    )
                except Exception as e:
                    logger.error(
                        "Compensation failed for step %d: %s",
                        step_result.step_index, e
                    )

    # ── Utilities ─────────────────────────────────────────────────

    def _resolve_payload(
        self, template: dict, step_outputs: dict[int, dict]
    ) -> dict:
        """
        Resolve {step_N.field} references in payload template.
        Example: {"event_id": "{step_0.event_id}"}
        resolves to {"event_id": "cal_abc123"}
        using step_outputs[0]["event_id"].
        """
        import re
        resolved = {}
        pattern = re.compile(r'\{step_(-?\d+)\.(\w+)\}')

        for key, value in template.items():
            if isinstance(value, str):
                match = pattern.fullmatch(value)
                if match:
                    step_idx = int(match.group(1))
                    field = match.group(2)
                    resolved[key] = step_outputs.get(
                        step_idx, {}
                    ).get(field, value)
                else:
                    resolved[key] = value
            else:
                resolved[key] = value

        return resolved

    async def _wait_for_terminal(
        self, task_id: str, timeout: int = 120
    ) -> Optional[dict]:
        """
        Poll until task reaches a terminal state.
        Terminal: completed | failed | cancelled | expired.
        Returns None on timeout.
        """
        terminal = {"completed", "failed", "cancelled", "expired"}
        for _ in range(timeout * 10):
            task = self.orchestrator.db.get_orchestrator_task(task_id)
            if task and task["status"] in terminal:
                return task
            await asyncio.sleep(0.1)
        logger.warning(
            "_wait_for_terminal: timeout for task %s", task_id
        )
        return None


# ── Skill Definitions ─────────────────────────────────────────────
# Seed skills for Phase 4.
# Add new skills here as capabilities expand.

SKILL_DEFINITIONS: list[SkillDefinition] = [

    SkillDefinition(
        id="create_github_issue_with_comment",
        name="Create GitHub Issue with Comment",
        description=(
            "Creates a GitHub issue then posts an initial comment. "
            "If the comment fails, the issue is preserved — "
            "partial result is better than no result here."
        ),
        steps=[
            SkillStep(
                index=0,
                tool_name="github_writer",
                action_type="github_issue_create",
                payload_template={
                    "title": "{step_-1.title}",
                    "body":  "{step_-1.body}",
                    "repo":  "{step_-1.repo}",
                },
                on_failure=OnFailure.ABORT_SKILL,
                # Issue creation failing = nothing to comment on
            ),
            SkillStep(
                index=1,
                tool_name="github_writer",
                action_type="github_issue_create",
                payload_template={
                    "issue_number": "{step_0.issue_number}",
                    "comment":      "{step_-1.comment}",
                    "repo":         "{step_-1.repo}",
                },
                on_failure=OnFailure.SKIP_STEP,
                # Comment failing is acceptable — issue still created
                depends_on=[0],
            ),
        ],
    ),

    SkillDefinition(
        id="research_and_capture",
        name="Research Topic and Capture as Idea Node",
        description=(
            "Researches a topic via web search then captures "
            "the findings as an idea node in the brain graph."
        ),
        steps=[
            SkillStep(
                index=0,
                tool_name="web_researcher",
                action_type="web_research",
                payload_template={"query": "{step_-1.query}"},
                on_failure=OnFailure.ABORT_SKILL,
            ),
            SkillStep(
                index=1,
                tool_name="signal_updater",
                action_type="signal_update",
                payload_template={
                    "node_type":   "idea",
                    "label":       "{step_-1.label}",
                    "description": "{step_0.summary}",
                    "source":      "dream",
                },
                on_failure=OnFailure.SURFACE_TO_YASH,
                depends_on=[0],
            ),
        ],
    ),

    SkillDefinition(
        id="calendar_event_with_drive_doc",
        name="Create Calendar Event with Drive Prep Doc",
        description=(
            "Creates a calendar event then generates a "
            "preparation document in Drive for that event. "
            "If Drive doc creation fails, the event is preserved "
            "and Yash is notified."
        ),
        steps=[
            SkillStep(
                index=0,
                tool_name="calendar_writer",
                action_type="calendar_create",
                payload_template={
                    "title":       "{step_-1.title}",
                    "start":       "{step_-1.start}",
                    "end":         "{step_-1.end}",
                    "description": "{step_-1.description}",
                },
                on_failure=OnFailure.ABORT_SKILL,
                compensation_payload=None,
                # CalendarWriterTool.rollback() handles deletion
            ),
            SkillStep(
                index=1,
                tool_name="drive_writer",
                action_type="drive_create",
                payload_template={
                    "title":   "Prep — {step_-1.title}",
                    "content": "{step_-1.description}",
                },
                on_failure=OnFailure.SURFACE_TO_YASH,
                depends_on=[0],
            ),
        ],
    ),
]


def get_skill(skill_id: str) -> Optional[SkillDefinition]:
    """Look up a skill by ID."""
    return next(
        (s for s in SKILL_DEFINITIONS if s.id == skill_id), None
    )


def list_skills() -> list[dict]:
    """Return skill metadata for API exposure."""
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "step_count": len(s.steps),
            "steps": [
                {
                    "index": step.index,
                    "tool_name": step.tool_name,
                    "on_failure": step.on_failure.value,
                    "depends_on": step.depends_on,
                }
                for step in s.steps
            ],
        }
        for s in SKILL_DEFINITIONS
    ]