"""
MAIHERA Phase 6 Integration Tests
Tests for Dream Mode service, worker, idle detection,
Tavily integration, briefing highlight, and proposal system.
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_brain():
    brain = MagicMock()
    brain.list_nodes.return_value = []
    brain.get_node.return_value = None
    brain.update_node.return_value = None
    brain.update_signal.return_value = None

    session_mock = MagicMock()
    session_mock.__enter__ = MagicMock(return_value=session_mock)
    session_mock.__exit__ = MagicMock(return_value=False)
    session_mock.run.return_value = MagicMock(
        single=MagicMock(return_value=None)
    )
    brain.driver.session.return_value = session_mock

    return brain


@pytest.fixture
def mock_router():
    router = AsyncMock()
    router.route = AsyncMock(return_value=None)
    return router


@pytest.fixture
def mock_voice():
    voice = AsyncMock()
    voice.enqueue_speech = AsyncMock(return_value=None)
    return voice


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send_highlight_node = AsyncMock(return_value=None)
    ws.send_maihera_speak = AsyncMock(return_value=None)
    ws.send_briefing_start = AsyncMock(return_value=None)
    ws.send_briefing_end = AsyncMock(return_value=None)
    return ws


@pytest.fixture
def dream_service(mock_brain, mock_router):
    from services.dream_mode_service import DreamModeService
    service = DreamModeService(
        brain_service=mock_brain,
        llm_router=mock_router,
    )
    service.set_tavily_key("tvly-test-key")
    return service


# ── Test 1: DreamModeService initializes correctly ────────────────

def test_dream_service_init(dream_service):
    """DreamModeService initializes with correct defaults."""
    assert dream_service.is_active is False
    assert dream_service.tasks_completed == 0
    assert dream_service._tavily_key == "tvly-test-key"
    print("✓ DreamModeService initializes correctly.")


# ── Test 2: Task queue builder — empty brain ──────────────────────

def test_task_queue_empty_brain(dream_service, mock_brain):
    """Task queue is empty when brain has no active nodes."""
    mock_brain.list_nodes.return_value = []
    tasks = dream_service._build_task_queue()
    assert tasks == []
    print("✓ Task queue is empty when brain has no qualifying nodes.")


# ── Test 3: Task queue builder — low signal filtered out ─────────

def test_task_queue_low_signal_filtered(dream_service, mock_brain):
    """Nodes below signal threshold are excluded from task queue."""
    mock_brain.list_nodes.return_value = [
        {
            "id": "node-1",
            "type": "task",
            "label": "Low signal task",
            "description": "Not important",
            "status": "active",
            "workspace": "personal",
            "importance": 0.1,
            "attention": 0.1,
            "resistance": 0.0,
            "project_id": "proj-1",
            "last_dream_touched": None,
        }
    ]
    tasks = dream_service._build_task_queue()
    assert len(tasks) == 0
    print("✓ Low signal nodes excluded from task queue.")


# ── Test 4: Task queue builder — high signal included ────────────

def test_task_queue_high_signal_included(dream_service, mock_brain):
    """High signal nodes are included and scored correctly."""
    mock_brain.list_nodes.side_effect = [
        # All nodes
        [
            {
                "id": "node-1",
                "type": "issue",
                "label": "Personality accuracy",
                "description": "Mimicry not accurate enough",
                "status": "active",
                "workspace": "personal",
                "importance": 0.8,
                "attention": 0.7,
                "resistance": 0.5,
                "project_id": "proj-presence",
                "last_dream_touched": None,
            }
        ],
        # Projects
        [
            {"id": "proj-presence", "label": "Presence", "type": "project"}
        ],
    ]

    tasks = dream_service._build_task_queue()
    assert len(tasks) == 1
    assert tasks[0].node_id == "node-1"
    assert tasks[0].task_type == "web_research"  # issue → web_research
    assert tasks[0].priority_score > 0.5
    print("✓ High signal issue node queued as web_research task.")


# ── Test 5: Task type assignment ──────────────────────────────────

def test_task_type_assignment(dream_service, mock_brain):
    """Task type is correctly assigned based on node type."""
    nodes = [
        {
            "id": f"node-{i}",
            "type": node_type,
            "label": f"Test {node_type}",
            "description": "Test description",
            "status": "active",
            "workspace": "personal",
            "importance": 0.7,
            "attention": 0.6,
            "resistance": 0.1,
            "project_id": "proj-1",
            "last_dream_touched": None,
        }
        for i, node_type in enumerate(
            ["issue", "idea", "decision", "task"]
        )
    ]

    mock_brain.list_nodes.side_effect = [nodes, []]

    tasks = dream_service._build_task_queue()

    type_map = {t.node_id: t.task_type for t in tasks}
    assert type_map["node-0"] == "web_research"    # issue
    assert type_map["node-1"] == "pattern_synthesis"  # idea
    assert type_map["node-2"] == "proposal_generation"  # decision
    assert type_map["node-3"] == "pattern_synthesis"  # task (no cross-project)
    print("✓ Task type assignment correct for all node types.")


# ── Test 6: Dream cooldown respected ─────────────────────────────

def test_dream_cooldown_respected(dream_service, mock_brain):
    """Nodes touched by Dream Mode in last 24h are skipped."""
    recent = (
        datetime.utcnow() - timedelta(hours=12)
    ).isoformat()

    mock_brain.list_nodes.return_value = [
        {
            "id": "node-1",
            "type": "task",
            "label": "Recently dreamed",
            "description": "Already processed",
            "status": "active",
            "workspace": "personal",
            "importance": 0.9,
            "attention": 0.9,
            "resistance": 0.0,
            "project_id": "proj-1",
            "last_dream_touched": recent,
        }
    ]

    tasks = dream_service._build_task_queue()
    assert len(tasks) == 0
    print("✓ Dream cooldown correctly filters recently processed nodes.")


# ── Test 7: Idle start triggers session ──────────────────────────

@pytest.mark.asyncio
async def test_dream_worker_idle_start(dream_service):
    """DreamModeWorker starts a session on idle_start event."""
    from workers.dream_mode_worker import DreamModeWorker
    from services.system_observer import ContextEvent

    queue = asyncio.Queue()
    worker = DreamModeWorker(queue, dream_service)

    idle_event = ContextEvent(
        timestamp=datetime.utcnow().isoformat(),
        process_name="",
        process_label="idle",
        context="idle",
        window_title="",
        event_type="idle_start",
        dwell_seconds=600.0,
    )

    with patch.object(
        dream_service,
        "run_session",
        new_callable=AsyncMock
    ) as mock_run:
        await worker._handle_event(idle_event)
        # Give the task a moment to be created
        await asyncio.sleep(0.05)
        mock_run.assert_called_once()

    print("✓ DreamModeWorker starts session on idle_start.")


# ── Test 8: Idle end stops session ───────────────────────────────

@pytest.mark.asyncio
async def test_dream_worker_idle_end(dream_service):
    """DreamModeWorker signals stop on idle_end when session active."""
    from workers.dream_mode_worker import DreamModeWorker
    from services.system_observer import ContextEvent

    queue = asyncio.Queue()
    worker = DreamModeWorker(queue, dream_service)

    # Simulate active session
    dream_service._session_active = True

    idle_end = ContextEvent(
        timestamp=datetime.utcnow().isoformat(),
        process_name="Code.exe",
        process_label="VS Code",
        context="coding",
        window_title="main.py",
        event_type="idle_end",
        dwell_seconds=900.0,
    )

    with patch.object(dream_service, "stop_session") as mock_stop:
        await worker._handle_event(idle_end)
        mock_stop.assert_called_once()

    print("✓ DreamModeWorker signals stop on idle_end.")


# ── Test 9: idle_start routed to dream queue ─────────────────────

@pytest.mark.asyncio
async def test_observer_worker_routes_idle_to_dream_queue(mock_brain):
    """SystemObserverWorker routes idle events to dream queue."""
    from workers.system_observer_worker import SystemObserverWorker
    from services.system_observer import ContextEvent

    observer_queue = asyncio.Queue()
    dream_queue = asyncio.Queue()

    worker = SystemObserverWorker(observer_queue, mock_brain)
    worker.set_dream_queue(dream_queue)

    idle_event = ContextEvent(
        timestamp=datetime.utcnow().isoformat(),
        process_name="",
        process_label="idle",
        context="idle",
        window_title="",
        event_type="idle_start",
        dwell_seconds=600.0,
    )

    await worker._handle_event(idle_event)

    assert not dream_queue.empty()
    routed = await dream_queue.get()
    assert routed.event_type == "idle_start"
    print("✓ Observer worker routes idle_start to dream queue.")


# ── Test 10: idle_end routed to dream queue ───────────────────────

@pytest.mark.asyncio
async def test_observer_worker_routes_idle_end_to_dream_queue(mock_brain):
    """SystemObserverWorker routes idle_end to dream queue."""
    from workers.system_observer_worker import SystemObserverWorker
    from services.system_observer import ContextEvent

    observer_queue = asyncio.Queue()
    dream_queue = asyncio.Queue()

    worker = SystemObserverWorker(observer_queue, mock_brain)
    worker.set_dream_queue(dream_queue)

    idle_end = ContextEvent(
        timestamp=datetime.utcnow().isoformat(),
        process_name="Code.exe",
        process_label="VS Code",
        context="coding",
        window_title="main.py",
        event_type="idle_end",
        dwell_seconds=900.0,
    )

    await worker._handle_event(idle_end)

    assert not dream_queue.empty()
    routed = await dream_queue.get()
    assert routed.event_type == "idle_end"
    print("✓ Observer worker routes idle_end to dream queue.")


# ── Test 11: No dream queue — warning logged, no crash ───────────

@pytest.mark.asyncio
async def test_observer_worker_no_dream_queue(mock_brain):
    """SystemObserverWorker logs warning if dream queue not wired."""
    from workers.system_observer_worker import SystemObserverWorker
    from services.system_observer import ContextEvent

    observer_queue = asyncio.Queue()
    worker = SystemObserverWorker(observer_queue, mock_brain)
    # Intentionally do NOT call set_dream_queue

    idle_event = ContextEvent(
        timestamp=datetime.utcnow().isoformat(),
        process_name="",
        process_label="idle",
        context="idle",
        window_title="",
        event_type="idle_start",
        dwell_seconds=600.0,
    )

    # Should not raise — just log warning
    await worker._handle_event(idle_event)
    print("✓ Observer worker handles missing dream queue gracefully.")


# ── Test 12: JSON parse — clean JSON ─────────────────────────────

def test_json_parse_clean(dream_service):
    """DreamModeService parses clean JSON correctly."""
    raw = '{"insight_title": "Test insight", "confidence": 0.8}'
    result = dream_service._parse_json(raw)
    assert result is not None
    assert result["confidence"] == 0.8
    assert result["insight_title"] == "Test insight"
    print("✓ JSON parser handles clean JSON correctly.")


# ── Test 13: JSON parse — markdown fenced ────────────────────────

def test_json_parse_fenced(dream_service):
    """DreamModeService strips markdown fences before parsing."""
    raw = '```json\n{"insight_title": "Fenced", "confidence": 0.7}\n```'
    result = dream_service._parse_json(raw)
    assert result is not None
    assert result["confidence"] == 0.7
    print("✓ JSON parser strips markdown fences correctly.")


# ── Test 14: JSON parse — malformed returns None ─────────────────

def test_json_parse_malformed(dream_service):
    """DreamModeService returns None on malformed JSON."""
    raw = "This is not JSON at all"
    result = dream_service._parse_json(raw)
    assert result is None
    print("✓ JSON parser returns None on malformed input.")


# ── Test 15: Pattern synthesis — low confidence discarded ────────

@pytest.mark.asyncio
async def test_pattern_synthesis_low_confidence_discarded(
    dream_service, mock_router, mock_brain
):
    """Pattern synthesis discards results below confidence threshold."""
    mock_router.route = AsyncMock(return_value=json.dumps({
        "insight_title": "Weak insight",
        "insight_body": "Not very confident about this.",
        "action_recommendation": "Maybe do something.",
        "confidence": 0.2,
    }))

    mock_brain.driver.session.return_value.__enter__ = MagicMock(
        return_value=mock_brain.driver.session.return_value
    )

    task = MagicMock()
    task.node_id = "node-1"
    task.node_label = "Test node"
    task.node_description = "Test description"
    task.project_label = "MAIHERA"

    with patch.object(dream_service, "_get_related_nodes", return_value=[]):
        with patch.object(
            dream_service, "_create_dream_node"
        ) as mock_create:
            await dream_service._task_pattern_synthesis(task)
            mock_create.assert_not_called()

    print("✓ Pattern synthesis discards low confidence results.")


# ── Test 16: Proposal — decision stands, no node created ─────────

@pytest.mark.asyncio
async def test_proposal_decision_stands_no_node(
    dream_service, mock_router
):
    """Proposal generation creates no node when decision stands."""
    mock_router.route = AsyncMock(return_value=json.dumps({
        "proposal_title": "Keep current approach",
        "proposal_body": "The decision is sound.",
        "challenge_type": "self_improvement",
        "verdict": "stands",
        "confidence": 0.3,
    }))

    task = MagicMock()
    task.node_id = "decision-1"
    task.node_label = "Use Neo4j"
    task.node_description = "Graph database choice"
    task.project_label = "MAIHERA"

    with patch.object(
        dream_service, "_create_dream_node"
    ) as mock_create:
        await dream_service._task_proposal(task)
        mock_create.assert_not_called()

    print("✓ Proposal generation skips node creation when decision stands.")


# ── Test 17: Stop session sets flag ──────────────────────────────

def test_stop_session_sets_flag(dream_service):
    """stop_session sets _stop_requested flag when session active."""
    dream_service._session_active = True
    dream_service.stop_session()
    assert dream_service._stop_requested is True
    print("✓ stop_session correctly sets _stop_requested flag.")


# ── Test 18: Stop session no-op when not active ──────────────────

def test_stop_session_noop_when_inactive(dream_service):
    """stop_session is silent when no session is running."""
    dream_service._session_active = False
    dream_service.stop_session()
    assert dream_service._stop_requested is False
    print("✓ stop_session is no-op when session not active.")


# ── Test 19: Idle threshold in SystemObserver ────────────────────

def test_idle_threshold_constant():
    """IDLE_THRESHOLD_SECONDS is set to 600 (10 minutes)."""
    from services.system_observer import IDLE_THRESHOLD_SECONDS
    assert IDLE_THRESHOLD_SECONDS == 600
    print("✓ Idle threshold is correctly set to 600 seconds.")


# ── Test 20: dream_synthesis in LLM router table ─────────────────

def test_dream_synthesis_in_routing_table():
    """dream_synthesis task type exists in LLM router table."""
    from llm.router import ROUTING_TABLE
    assert "dream_synthesis" in ROUTING_TABLE
    assert len(ROUTING_TABLE["dream_synthesis"]) > 0
    print("✓ dream_synthesis task type registered in routing table.")


# ── Runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest",
         "tests/test_phase6.py", "-v", "--tb=short"],
        cwd=Path(__file__).parent.parent,
    )
    sys.exit(result.returncode)