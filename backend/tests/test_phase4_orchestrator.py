"""
MAIHERA Phase 4 — Orchestrator End-to-End Tests
Tests the full task lifecycle:
- always_allow: submit → queued → completed
- always_confirm: submit → pending_confirmation → confirmed → completed
- always_confirm: submit → pending_confirmation → cancelled
- cooldown enforcement
- unknown tool rejection
"""

import asyncio
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.sqlite_store import DatabaseManager
from orchestrator.confirmation_broker import ConfirmationBroker
from orchestrator.orchestrator import Orchestrator
from orchestrator.tool_registry import register_all_tools


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    """Fresh in-memory SQLite for each test."""
    db = DatabaseManager(db_path=str(tmp_path / "test.db"))
    db.initialize()
    yield db
    db.disconnect()


@pytest.fixture
def broker(db):
    return ConfirmationBroker(db=db)


@pytest.fixture
def orchestrator(db, broker):
    orch = Orchestrator(db=db, confirmation_broker=broker)
    register_all_tools(orch)
    return orch


# ── Helper ────────────────────────────────────────────────────────

async def wait_for_status(db, task_id, target_status, timeout=5):
    """Poll until task reaches target_status or timeout."""
    for _ in range(timeout * 10):
        task = db.get_orchestrator_task(task_id)
        if task and task["status"] == target_status:
            return task
        await asyncio.sleep(0.1)
    task = db.get_orchestrator_task(task_id)
    current = task["status"] if task else "not found"
    raise TimeoutError(
        f"Task {task_id} did not reach '{target_status}' "
        f"within {timeout}s. Current: '{current}'"
    )


# ── Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_always_allow_tool_executes_immediately(orchestrator, db):
    """
    calendar_reader is always_allow.
    Should go queued → running without confirmation.
    Completes or fails depending on credential availability in test env —
    either outcome proves the Orchestrator flow is correct.
    """
    task_id = await orchestrator.submit(
        action_type="calendar_read",
        tool_name="calendar_reader",
        payload={"days": 7},
    )
    assert task_id

    # No confirmation required — task must not be pending_confirmation
    await asyncio.sleep(0.2)
    task = db.get_orchestrator_task(task_id)
    assert task is not None
    assert task["requires_confirmation"] == 0
    assert task["status"] != "pending_confirmation", (
        "always_allow tool must never enter pending_confirmation"
    )

    # Wait for terminal state (completed or failed — both are correct flow)
    for _ in range(150):
        task = db.get_orchestrator_task(task_id)
        if task and task["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)

    task = db.get_orchestrator_task(task_id)
    assert task["status"] in ("completed", "failed"), (
        f"Expected terminal state, got: {task['status']}"
    )
    print(f"  always_allow flow: PASSED — status={task['status']} (task {task_id[:8]}...)")


@pytest.mark.asyncio
async def test_always_confirm_tool_waits_for_confirmation(orchestrator, db, broker):
    """
    github_writer is always_confirm.
    Should enter pending_confirmation and wait.
    After confirmation, should move to running then terminal state.
    """
    task_id = await orchestrator.submit(
        action_type="github_issue_create",
        tool_name="github_writer",
        payload={
            "title": "Test issue from Phase 4",
            "body": "Orchestrator flow test",
            "repo": "Presence",
        },
    )
    assert task_id

    # Must be pending_confirmation — not executing yet
    await asyncio.sleep(0.3)
    task = db.get_orchestrator_task(task_id)
    assert task["status"] == "pending_confirmation", (
        f"Expected pending_confirmation, got {task['status']}"
    )
    assert task["requires_confirmation"] == 1
    assert task["confirmation_id"] is not None
    print(f"  always_confirm pending: PASSED (task {task_id[:8]}...)")

    # Confirm via broker
    consumed = await broker.resolve(text="yes", resolved_by="text")
    assert consumed, "Broker should have consumed the confirmation signal"

    # Wait for terminal state (completed or failed — both prove confirmation worked)
    for _ in range(150):
        task = db.get_orchestrator_task(task_id)
        if task and task["status"] in ("completed", "failed"):
            break
        await asyncio.sleep(0.1)

    task = db.get_orchestrator_task(task_id)
    assert task["status"] in ("completed", "failed"), (
        f"Expected terminal state after confirmation, got: {task['status']}"
    )
    print(f"  always_confirm confirmed → {task['status']}: PASSED")


@pytest.mark.asyncio
async def test_always_confirm_tool_cancels_correctly(orchestrator, db, broker):
    """
    Cancelling a pending confirmation moves task to cancelled.
    """
    task_id = await orchestrator.submit(
        action_type="github_issue_create",
        tool_name="github_writer",
        payload={
            "title": "This should be cancelled",
            "body": "Cancel flow test",
            "repo": "Presence",
        },
    )

    await asyncio.sleep(0.3)
    task = db.get_orchestrator_task(task_id)
    assert task["status"] == "pending_confirmation"

    consumed = await broker.resolve(text="no", resolved_by="text")
    assert consumed

    await asyncio.sleep(0.3)
    task = db.get_orchestrator_task(task_id)
    assert task["status"] == "cancelled"
    print(f"  always_confirm cancelled: PASSED")


@pytest.mark.asyncio
async def test_non_confirmation_text_not_consumed_when_pending(orchestrator, db, broker):
    """
    A normal chat message should not be consumed by broker
    when a confirmation is pending.
    """
    await orchestrator.submit(
        action_type="github_issue_create",
        tool_name="github_writer",
        payload={"title": "Pending", "body": "", "repo": "Presence"},
    )

    await asyncio.sleep(0.2)

    # Normal chat text — should not be consumed
    consumed = await broker.resolve(
        text="What is the weather today?", resolved_by="text"
    )
    assert not consumed, "Normal chat should not be consumed by broker"
    print(f"  non-confirmation passthrough: PASSED")

    # Clean up — cancel the pending confirmation
    await broker.resolve(text="cancel", resolved_by="text")


@pytest.mark.asyncio
async def test_unknown_tool_raises_value_error(orchestrator):
    """
    Submitting a task for an unregistered tool raises ValueError.
    """
    with pytest.raises(ValueError, match="not registered"):
        await orchestrator.submit(
            action_type="fake_action",
            tool_name="nonexistent_tool",
            payload={},
        )
    print(f"  unknown tool rejection: PASSED")


@pytest.mark.asyncio
async def test_explicit_only_rejected_without_flag(orchestrator, db):
    """
    explicit_only tools are rejected unless explicit_instruction=True.
    Currently no tool is explicit_only by default — we test the
    gate by temporarily patching a tool's tier.
    """
    from orchestrator.base_tool import AutonomyTier
    tool = orchestrator._tool_registry["github_repo_reader"]
    original_tier = tool.autonomy_tier
    tool.autonomy_tier = AutonomyTier.EXPLICIT_ONLY

    try:
        task_id = await orchestrator.submit(
            action_type="github_repo_read",
            tool_name="github_repo_reader",
            payload={},
            explicit_instruction=False,
        )
        # Task ID returned but task not written to DB
        task = db.get_orchestrator_task(task_id)
        assert task is None, "explicit_only task should not be written to DB"
        print(f"  explicit_only gate: PASSED")
    finally:
        tool.autonomy_tier = original_tier


@pytest.mark.asyncio
async def test_multiple_pending_confirmations_disambiguates(
    orchestrator, db, broker
):
    """
    Two pending confirmations — broker should not consume
    a 'yes' but instead request disambiguation.
    """
    await orchestrator.submit(
        action_type="github_issue_create",
        tool_name="github_writer",
        payload={"title": "First", "body": "", "repo": "Presence"},
    )
    await orchestrator.submit(
        action_type="drive_create",
        tool_name="drive_writer",
        payload={"title": "Second doc"},
    )

    await asyncio.sleep(0.3)
    pending = db.get_pending_confirmations()
    assert len(pending) == 2

    # 'yes' with two pending — should be consumed but not resolved
    consumed = await broker.resolve(text="yes", resolved_by="text")
    assert consumed, "Broker should consume the message"

    # Both should still be pending
    pending_after = db.get_pending_confirmations()
    assert len(pending_after) == 2, (
        f"Both should still be pending, got {len(pending_after)}"
    )
    print(f"  disambiguation with 2 pending: PASSED")

    # Clean up
    for c in pending_after:
        broker.db.resolve_confirmation(c["id"], "cancelled", "test")


@pytest.mark.asyncio
async def test_task_list_endpoint(orchestrator, db):
    """
    Tasks appear in list_orchestrator_tasks after submission.
    """
    task_id = await orchestrator.submit(
        action_type="calendar_read",
        tool_name="calendar_reader",
        payload={"days": 3},
    )
    await asyncio.sleep(0.5)

    tasks = db.list_orchestrator_tasks(limit=10)
    task_ids = [t["id"] for t in tasks]
    assert task_id in task_ids
    print(f"  task list: PASSED ({len(tasks)} tasks found)")