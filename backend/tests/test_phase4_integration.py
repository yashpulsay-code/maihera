"""
MAIHERA Phase 4 — Full Integration Tests
Tests the complete Phase 4 stack against the live backend.
Backend must be running on port 8000 before executing these tests.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000
    python -m pytest tests/test_phase4_integration.py -v
"""

import json
import time
import urllib.request
import urllib.error
import urllib.parse
import pytest

BASE = "http://localhost:8000"


# ── Helpers ───────────────────────────────────────────────────────

def get(path: str) -> dict:
    resp = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(resp.read())


def post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def wait_for_task_terminal(task_id: str, timeout: int = 15) -> dict:
    terminal = {"completed", "failed", "cancelled", "expired"}
    for _ in range(timeout * 10):
        task = get(f"/orchestrator/status/{task_id}")
        if task["status"] in terminal:
            return task
        time.sleep(0.1)
    return get(f"/orchestrator/status/{task_id}")


# ── Backend Availability ──────────────────────────────────────────

def test_backend_is_live():
    """Backend must be running before any other test."""
    data = get("/health")
    assert data["status"] == "live"
    print(f"  Backend live: {data['version']}")


# ── Tools ─────────────────────────────────────────────────────────

def test_all_13_tools_registered():
    """All 13 tools must be registered with correct autonomy tiers."""
    data = get("/orchestrator/tools")
    assert data["count"] == 13

    always_allow = [
        t for t in data["tools"] if t["autonomy_tier"] == "always_allow"
    ]
    confirm_first = [
        t for t in data["tools"] if t["autonomy_tier"] == "confirm_first"
    ]
    always_confirm = [
        t for t in data["tools"] if t["autonomy_tier"] == "always_confirm"
    ]

    assert len(always_allow) == 8
    assert len(confirm_first) == 1
    assert always_confirm[0]["name"] if always_confirm else True
    assert len(always_confirm) == 4

    tool_names = [t["name"] for t in data["tools"]]
    for expected in [
        "calendar_reader", "github_reader", "calendar_writer",
        "github_writer", "signal_updater", "web_researcher",
    ]:
        assert expected in tool_names, f"Missing tool: {expected}"
    print(f"  13 tools registered with correct tiers: PASSED")


# ── Orchestrator — always_allow ───────────────────────────────────

def test_always_allow_task_executes_without_confirmation():
    """
    signal_updater is always_allow.
    Must not enter pending_confirmation.
    """
    resp = post("/orchestrator/submit", {
        "action_type": "signal_update",
        "tool_name": "signal_updater",
        "payload": {"node_id": "test-node-integration"},
    })
    assert "task_id" in resp
    assert resp["status"] != "pending_confirmation"

    task = wait_for_task_terminal(resp["task_id"])
    assert task["status"] in ("completed", "failed")
    assert not task["requires_confirmation"]
    print(f"  always_allow no confirmation: PASSED (status={task['status']})")


# ── Orchestrator — always_confirm ────────────────────────────────

def test_always_confirm_task_enters_pending():
    """
    drive_writer is always_confirm.
    Must enter pending_confirmation immediately.
    """
    resp = post("/orchestrator/submit", {
        "action_type": "drive_create",
        "tool_name": "drive_writer",
        "payload": {"title": "Integration test doc"},
    })
    assert resp["status"] == "pending_confirmation"
    task_id = resp["task_id"]

    task = get(f"/orchestrator/status/{task_id}")
    assert task["status"] == "pending_confirmation"
    assert task["requires_confirmation"]
    assert task["confirmation_id"] is not None

    # Clean up — cancel it
    post(f"/orchestrator/cancel/{task_id}", {})
    task = get(f"/orchestrator/status/{task_id}")
    assert task["status"] == "cancelled"
    print(f"  always_confirm pending + cancel: PASSED")


# ── Confirmations endpoint ────────────────────────────────────────

def test_pending_confirmations_endpoint():
    """Pending confirmations endpoint returns correct structure."""
    data = get("/orchestrator/confirmations")
    assert "count" in data
    assert "confirmations" in data
    assert isinstance(data["confirmations"], list)
    print(f"  confirmations endpoint: PASSED (pending={data['count']})")


# ── Task List ─────────────────────────────────────────────────────

def test_task_list_returns_results():
    """Task list endpoint returns tasks from this test run."""
    data = get("/orchestrator/tasks?limit=10")
    assert "count" in data
    assert "tasks" in data
    assert data["count"] >= 0
    print(f"  task list: PASSED ({data['count']} tasks)")


# ── Skills ────────────────────────────────────────────────────────

def test_three_skills_registered():
    """Three seed skills must be available."""
    data = get("/skills/")
    assert data["count"] == 3
    skill_ids = [s["id"] for s in data["skills"]]
    assert "create_github_issue_with_comment" in skill_ids
    assert "research_and_capture" in skill_ids
    assert "calendar_event_with_drive_doc" in skill_ids
    print(f"  3 skills registered: PASSED")


def test_get_skill_by_id():
    """Individual skill lookup returns correct structure."""
    data = get("/skills/research_and_capture")
    assert data["id"] == "research_and_capture"
    assert len(data["steps"]) == 2
    assert data["steps"][0]["tool_name"] == "web_researcher"
    assert data["steps"][1]["tool_name"] == "signal_updater"
    assert data["steps"][1]["depends_on"] == [0]
    print(f"  skill lookup by ID: PASSED")


def test_unknown_skill_returns_404():
    """Unknown skill ID returns 404."""
    try:
        get("/skills/nonexistent_skill_xyz")
        assert False, "Should have raised"
    except urllib.error.HTTPError as e:
        assert e.code == 404
    print(f"  unknown skill 404: PASSED")


# ── Context Capture ───────────────────────────────────────────────

def test_capture_creates_staged_node():
    """Capturing a thought creates a staged node."""
    before = get("/capture/count")["count"]

    result = post("/capture/", {
        "text": "We should add keyboard shortcuts to the MAIHERA interface for power users",
        "project_hint": "MAIHERA",
        "workspace": "personal",
    })

    assert "capture_id" in result
    assert "node_id" in result
    assert "confirmation" in result
    assert "staged" in result["confirmation"].lower() or "got it" in result["confirmation"].lower()

    after = get("/capture/count")["count"]
    assert after == before + 1

    print(f"  capture creates staged node: PASSED (id={result['capture_id'][:8]}...)")
    return result["capture_id"]


def test_capture_staged_list_contains_capture():
    """Staged list contains the capture created above."""
    # Capture another thought
    result = post("/capture/", {
        "text": "Investigate using streaming TTS to reduce briefing latency",
        "project_hint": "MAIHERA",
    })
    capture_id = result["capture_id"]

    staged = get("/capture/staged")
    ids = [c["id"] for c in staged["captures"]]
    assert capture_id in ids
    print(f"  staged list contains capture: PASSED")
    return capture_id


def test_capture_promote():
    """Promoting a capture moves it out of staged."""
    result = post("/capture/", {
        "text": "Add conflict detection to morning briefing summary",
        "project_hint": "MAIHERA",
    })
    capture_id = result["capture_id"]

    before = get("/capture/count")["count"]
    post("/capture/triage", {
        "action": "promote",
        "capture_id": capture_id,
    })
    after = get("/capture/count")["count"]
    assert after == before - 1
    print(f"  capture promote: PASSED (staged {before} → {after})")


def test_capture_archive():
    """Archiving a capture removes it from staged."""
    result = post("/capture/", {
        "text": "Maybe add a dark mode toggle — actually MAIHERA is already dark mode only",
        "project_hint": "MAIHERA",
    })
    capture_id = result["capture_id"]

    before = get("/capture/count")["count"]
    post("/capture/triage", {
        "action": "archive",
        "capture_id": capture_id,
        "reason": "Redundant — already dark mode",
    })
    after = get("/capture/count")["count"]
    assert after == before - 1
    print(f"  capture archive: PASSED (staged {before} → {after})")


def test_capture_too_short_returns_400():
    """Capture text under 3 chars returns 400."""
    try:
        post("/capture/", {"text": "hi"})
        assert False, "Should have raised"
    except urllib.error.HTTPError as e:
        assert e.code == 400
    print(f"  short capture 400: PASSED")


# ── Health Full ───────────────────────────────────────────────────

def test_health_full_all_services_ok():
    """Full health check — all core services must report ok."""
    data = get("/health/full")
    assert data["status"] == "live"
    assert data["services"]["brain"]["status"] == "ok"
    assert data["services"]["llm_router"]["status"] == "ok"
    assert data["services"]["decay_worker"]["status"] == "ok"
    assert data["services"]["websocket"]["status"] == "ok"
    print(f"  full health check: PASSED")