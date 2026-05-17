"""
MAIHERA Phase 5 Integration Tests
Tests for system observer, file watcher, avoidance detector,
presence health monitor, and relationship tracker.
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mock_brain():
    """Minimal brain service mock."""
    brain = MagicMock()
    brain.list_nodes.return_value = []
    brain.get_node.return_value = None
    brain.update_node.return_value = None
    brain.update_signal.return_value = None
    brain.create_resistance_edge.return_value = None
    brain.get_edges.return_value = []
    brain.find_node_by_source_ref.return_value = None

    # Mock Neo4j driver session
    session_mock = MagicMock()
    session_mock.__enter__ = MagicMock(return_value=session_mock)
    session_mock.__exit__ = MagicMock(return_value=False)
    session_mock.run.return_value = MagicMock(single=MagicMock(return_value=None))
    brain.driver.session.return_value = session_mock

    return brain


@pytest.fixture
def mock_voice():
    voice = AsyncMock()
    voice.enqueue_speech = AsyncMock(return_value=None)
    return voice


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send_maihera_speak = AsyncMock(return_value=None)
    return ws


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def observer_config(tmp_path):
    """Write a temp observer_config.json for tests."""
    config = {
        "_comment": "test config",
        "app_whitelist": [
            {"process": "Code.exe",  "context": "coding", "label": "VS Code"},
            {"process": "figma.exe", "context": "design", "label": "Figma"},
        ],
        "watched_folders": [str(tmp_path)],
        "avoidance_threshold_hours": 48,
        "cold_contact_days_frequent": 14,
        "cold_contact_days_occasional": 45,
    }
    config_path = tmp_path / "observer_config.json"
    config_path.write_text(json.dumps(config))
    return config_path, tmp_path


# ── Test 1: Observer Config Loading ──────────────────────────────

def test_observer_config_loads(observer_config, monkeypatch):
    """SystemObserverService loads whitelist from config correctly."""
    config_path, tmp_path = observer_config

    from services.system_observer import SystemObserverService
    monkeypatch.setattr(
        "services.system_observer.CONFIG_PATH", config_path
    )

    queue = asyncio.Queue()
    observer = SystemObserverService(queue)

    assert "code.exe" in observer._whitelist
    assert "figma.exe" in observer._whitelist
    assert observer._whitelist["code.exe"]["context"] == "coding"
    assert observer._whitelist["figma.exe"]["context"] == "design"
    print("✓ Observer config loads whitelist correctly.")


# ── Test 2: Whitelist Matching ────────────────────────────────────

def test_whitelist_matching(observer_config, monkeypatch):
    """Whitelist matching is case-insensitive."""
    config_path, _ = observer_config

    from services.system_observer import SystemObserverService
    monkeypatch.setattr(
        "services.system_observer.CONFIG_PATH", config_path
    )

    queue = asyncio.Queue()
    observer = SystemObserverService(queue)

    assert observer._match_whitelist("Code.exe") is not None
    assert observer._match_whitelist("code.exe") is not None
    assert observer._match_whitelist("CODE.EXE") is not None
    assert observer._match_whitelist("notepad.exe") is None
    assert observer._match_whitelist("chrome.exe") is None
    print("✓ Whitelist matching is case-insensitive.")


# ── Test 3: ContextEvent Dataclass ───────────────────────────────

def test_context_event_dataclass():
    """ContextEvent can be instantiated with correct fields."""
    from services.system_observer import ContextEvent

    event = ContextEvent(
        timestamp=datetime.utcnow().isoformat(),
        process_name="Code.exe",
        process_label="VS Code",
        context="coding",
        window_title="main.py - maihera",
        event_type="focus_gained",
        dwell_seconds=0.0,
    )
    assert event.context == "coding"
    assert event.event_type == "focus_gained"
    assert event.dwell_seconds == 0.0
    print("✓ ContextEvent dataclass works correctly.")


# ── Test 4: Observer Worker Attention Boost ───────────────────────

@pytest.mark.asyncio
async def test_observer_worker_attention_boost(mock_brain):
    """SystemObserverWorker boosts attention on matching projects."""
    mock_brain.list_nodes.return_value = [
        {
            "id": "proj-maihera",
            "label": "MAIHERA",
            "type": "project",
            "status": "active",
            "attention": 0.3,
        }
    ]
    mock_brain.get_node.return_value = {
        "id": "proj-maihera",
        "label": "MAIHERA",
        "attention": 0.3,
    }

    queue = asyncio.Queue()
    from workers.system_observer_worker import SystemObserverWorker
    worker = SystemObserverWorker(queue, mock_brain)

    await worker._boost_project_attention(
        context="coding",
        boost=0.15,
        source_label="VS Code",
    )

    mock_brain.update_signal.assert_called_once()
    call_args = mock_brain.update_signal.call_args
    assert call_args[0][0] == "proj-maihera"
    assert call_args[0][1] == "attention"
    assert abs(call_args[0][2] - 0.45) < 0.01
    print("✓ Observer worker boosts attention on matching project.")


# ── Test 5: File Watcher Config Hot-Reload ────────────────────────

def test_file_watcher_config_reload(observer_config, monkeypatch):
    """FileWatcherService reloads watched_folders from config."""
    config_path, tmp_path = observer_config

    from services.file_watcher import FileWatcherService
    monkeypatch.setattr(
        "services.file_watcher.CONFIG_PATH", config_path
    )

    queue = asyncio.Queue()
    loop = asyncio.new_event_loop()
    watcher = FileWatcherService(queue, loop)

    folders = watcher._load_config()
    assert len(folders) == 1
    assert str(tmp_path) in folders[0]

    # Update config with new folder
    new_folder = str(tmp_path / "new_project")
    config = json.loads(config_path.read_text())
    config["watched_folders"].append(new_folder)
    config_path.write_text(json.dumps(config))

    # Force reload
    watcher._config_loaded_at = 0.0
    new_folders = watcher._load_config()
    assert len(new_folders) == 2
    assert new_folder in new_folders

    loop.close()
    print("✓ File watcher reloads config correctly.")


# ── Test 6: File Change Attribution ──────────────────────────────

@pytest.mark.asyncio
async def test_file_change_attribution(mock_brain):
    """FileWatcherWorker skips events when no whitelisted app active."""
    mock_brain.list_nodes.return_value = []

    queue = asyncio.Queue()
    from workers.file_watcher_worker import FileWatcherWorker

    # Mock observer worker with no active context
    mock_observer = MagicMock()
    mock_observer.current_context = None

    worker = FileWatcherWorker(queue, mock_brain, mock_observer)

    from services.file_watcher import FileChangeEvent
    event = FileChangeEvent(
        timestamp=datetime.utcnow().isoformat(),
        path="C:\\Users\\HP\\maihera\\backend\\main.py",
        filename="main.py",
        extension=".py",
        event_type="modified",
        folder="C:\\Users\\HP\\maihera",
    )

    await worker._handle_event(event)

    # No signal writes — not attributed to Yash
    mock_brain.update_signal.assert_not_called()
    print("✓ File change not attributed when no whitelisted app active.")


@pytest.mark.asyncio
async def test_file_change_attributed_when_active(mock_brain):
    """FileWatcherWorker writes signal when whitelisted app is active."""
    mock_brain.list_nodes.return_value = [
        {
            "id": "proj-maihera",
            "label": "MAIHERA",
            "type": "project",
            "status": "active",
        }
    ]
    mock_brain.get_node.return_value = {
        "id": "proj-maihera",
        "label": "MAIHERA",
        "attention": 0.4,
    }

    queue = asyncio.Queue()
    from workers.file_watcher_worker import FileWatcherWorker

    mock_observer = MagicMock()
    mock_observer.current_context = "coding"

    worker = FileWatcherWorker(queue, mock_brain, mock_observer)

    from services.file_watcher import FileChangeEvent
    event = FileChangeEvent(
        timestamp=datetime.utcnow().isoformat(),
        path="C:\\Users\\HP\\maihera\\backend\\main.py",
        filename="main.py",
        extension=".py",
        event_type="modified",
        folder="C:\\Users\\HP\\maihera",
    )

    await worker._handle_event(event)

    mock_brain.update_signal.assert_called_once()
    print("✓ File change attributed and signal written when app active.")


# ── Test 7: Avoidance Detector — Condition Checks ────────────────

@pytest.mark.asyncio
async def test_avoidance_detector_stale_check(mock_brain, mock_db, tmp_path):
    """AvoidanceDetector correctly identifies stale nodes."""
    config_path = tmp_path / "observer_config.json"
    config_path.write_text(json.dumps({
        "avoidance_threshold_hours": 48,
        "app_whitelist": [],
        "watched_folders": [],
    }))

    from services.avoidance_detector import AvoidanceDetector
    with patch(
        "services.avoidance_detector.CONFIG_PATH", config_path
    ):
        detector = AvoidanceDetector(mock_brain, mock_db)

    # Node touched 72 hours ago — stale
    stale_node = {
        "id": "task-1",
        "label": "Stale task",
        "last_touched": (
            datetime.now(timezone.utc) - timedelta(hours=72)
        ).isoformat(),
        "workspace": "personal",
        "status": "active",
    }
    assert detector._is_stale(stale_node) is True

    # Node touched 10 hours ago — not stale
    fresh_node = {
        "id": "task-2",
        "label": "Fresh task",
        "last_touched": (
            datetime.now(timezone.utc) - timedelta(hours=10)
        ).isoformat(),
        "workspace": "personal",
        "status": "active",
    }
    assert detector._is_stale(fresh_node) is False
    print("✓ Avoidance detector stale check works correctly.")


@pytest.mark.asyncio
async def test_avoidance_detector_resurface_check(
    mock_brain, mock_db, tmp_path
):
    """AvoidanceDetector respects 24h resurface cooldown."""
    config_path = tmp_path / "observer_config.json"
    config_path.write_text(json.dumps({
        "avoidance_threshold_hours": 48,
        "app_whitelist": [],
        "watched_folders": [],
    }))

    from services.avoidance_detector import AvoidanceDetector
    with patch(
        "services.avoidance_detector.CONFIG_PATH", config_path
    ):
        detector = AvoidanceDetector(mock_brain, mock_db)

    # Surfaced 2 hours ago — should NOT resurface
    node_recent = {
        "last_surfaced": (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
    }
    assert detector._can_resurface(node_recent) is False

    # Surfaced 30 hours ago — CAN resurface
    node_old = {
        "last_surfaced": (
            datetime.now(timezone.utc) - timedelta(hours=30)
        ).isoformat()
    }
    assert detector._can_resurface(node_old) is True

    # Never surfaced — CAN resurface
    node_never = {"last_surfaced": None}
    assert detector._can_resurface(node_never) is True
    print("✓ Avoidance detector resurface cooldown works correctly.")


# ── Test 8: Presence Health Worker ───────────────────────────────

@pytest.mark.asyncio
async def test_presence_health_smoke_test_success(mock_brain, mock_voice):
    """PresenceHealthWorker does not surface nudge on HTTP 200."""
    from workers.presence_health_worker import PresenceHealthWorker

    worker = PresenceHealthWorker(mock_brain, mock_voice)

    with patch.object(worker, "_http_get", return_value=200):
        await worker._run_smoke_test("abc12345", "fix: typo in readme")

    mock_voice.enqueue_speech.assert_not_called()
    print("✓ Health worker stays silent on HTTP 200.")


@pytest.mark.asyncio
async def test_presence_health_smoke_test_failure(
    mock_brain, mock_voice, mock_ws
):
    """PresenceHealthWorker surfaces nudge on non-200."""
    from workers.presence_health_worker import PresenceHealthWorker

    mock_brain.list_nodes.return_value = [
        {"id": "proj-presence", "label": "Presence", "type": "project"}
    ]

    worker = PresenceHealthWorker(mock_brain, mock_voice)
    worker.set_ws_manager(mock_ws)

    with patch.object(worker, "_http_get", return_value=503):
        await worker._run_smoke_test("abc12345", "deploy: new feature")

    mock_voice.enqueue_speech.assert_called_once()
    call_text = mock_voice.enqueue_speech.call_args[1]["text"]
    assert "503" in call_text or "HTTP" in call_text or "returning" in call_text
    print("✓ Health worker surfaces nudge on HTTP 503.")


@pytest.mark.asyncio
async def test_presence_health_cooldown(mock_brain, mock_voice):
    """PresenceHealthWorker respects 5-minute cooldown."""
    from workers.presence_health_worker import PresenceHealthWorker
    import time

    worker = PresenceHealthWorker(mock_brain, mock_voice)
    worker._last_test_at = time.monotonic()  # Set cooldown to now

    with patch.object(worker, "_run_smoke_test") as mock_test:
        await worker.on_presence_push("abc12345", "fix: something")
        mock_test.assert_not_called()

    print("✓ Health worker cooldown prevents rapid retriggers.")


# ── Test 9: Relationship Tracker ─────────────────────────────────

def test_relationship_tracker_tier_classification(mock_brain):
    """RelationshipTracker classifies tiers correctly."""
    from services.relationship_tracker import RelationshipTracker

    tracker = RelationshipTracker(mock_brain)

    # Old contact with many interactions → frequent
    frequent_node = {
        "interaction_count": 10,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat(),
    }
    assert tracker._classify_tier(frequent_node) == "frequent"

    # New contact — regardless of interaction count → occasional
    new_node = {
        "interaction_count": 10,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(days=5)
        ).isoformat(),
    }
    assert tracker._classify_tier(new_node) == "occasional"

    # Old contact but few interactions → occasional
    occasional_node = {
        "interaction_count": 2,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat(),
    }
    assert tracker._classify_tier(occasional_node) == "occasional"
    print("✓ Relationship tracker tier classification correct.")


def test_relationship_tracker_cold_detection(mock_brain):
    """RelationshipTracker correctly identifies cold contacts."""
    from services.relationship_tracker import RelationshipTracker

    tracker = RelationshipTracker(mock_brain)

    # Frequent contact not seen in 20 days → cold
    cold_frequent = {
        "interaction_count": 10,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat(),
        "last_interacted": (
            datetime.now(timezone.utc) - timedelta(days=20)
        ).isoformat(),
        "last_surfaced": None,
    }
    assert tracker._is_cold(cold_frequent) is True

    # Frequent contact seen 5 days ago → not cold
    warm_frequent = {
        "interaction_count": 10,
        "created_at": (
            datetime.now(timezone.utc) - timedelta(days=60)
        ).isoformat(),
        "last_interacted": (
            datetime.now(timezone.utc) - timedelta(days=5)
        ).isoformat(),
        "last_surfaced": None,
    }
    assert tracker._is_cold(warm_frequent) is False

    # No interaction history → never cold
    no_history = {
        "interaction_count": 0,
        "last_interacted": None,
        "last_surfaced": None,
    }
    assert tracker._is_cold(no_history) is False
    print("✓ Relationship tracker cold detection correct.")


@pytest.mark.asyncio
async def test_relationship_tracker_record_interaction(mock_brain):
    """RelationshipTracker updates person node on interaction."""
    mock_brain.get_node.return_value = {
        "id": "person-1",
        "label": "Alice",
        "type": "person",
        "interaction_count": 3,
    }

    from services.relationship_tracker import RelationshipTracker
    tracker = RelationshipTracker(mock_brain)

    tracker.record_interaction(
        person_node_id="person-1",
        source="calendar",
        detail="attended sprint review",
    )

    mock_brain.update_node.assert_called_once()
    call_args = mock_brain.update_node.call_args
    assert call_args[0][0] == "person-1"
    updates = call_args[0][1]
    assert updates["interaction_count"] == 4
    assert updates["last_interaction_source"] == "calendar"
    print("✓ Relationship tracker records interaction correctly.")


# ── Test 10: Observer Routes Config Update ────────────────────────

@pytest.mark.asyncio
async def test_observer_routes_folder_update(tmp_path):
    """Observer API correctly updates watched_folders in config."""
    config_path = tmp_path / "observer_config.json"
    config_path.write_text(json.dumps({
        "_comment": "test",
        "app_whitelist": [],
        "watched_folders": ["C:\\old\\path"],
        "avoidance_threshold_hours": 48,
        "cold_contact_days_frequent": 14,
        "cold_contact_days_occasional": 45,
    }))

    from api.routes.observer import update_watched_folders
    import api.routes.observer as observer_module
    observer_module.CONFIG_PATH = config_path

    result = await update_watched_folders({
        "folders": ["C:\\new\\path1", "C:\\new\\path2"]
    })

    assert result["status"] == "updated"
    assert len(result["watched_folders"]) == 2

    saved = json.loads(config_path.read_text())
    assert saved["watched_folders"] == ["C:\\new\\path1", "C:\\new\\path2"]
    print("✓ Observer routes update watched_folders correctly.")


# ── Runner ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest",
         "tests/test_phase5.py", "-v", "--tb=short"],
        cwd=Path(__file__).parent.parent,
    )
    sys.exit(result.returncode)