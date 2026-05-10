"""
MAIHERA Phase 3 Integration Tests
Tests all Phase 3 services and integrations.
Run with: python -m pytest tests/test_phase3.py -v
"""

import sys
import asyncio
import pytest
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def brain():
    from brain.brain_service import get_brain_service
    brain_service, driver = get_brain_service()
    yield brain_service
    driver.close()


@pytest.fixture(scope="module")
def llm_router():
    from llm.router import LLMRouter
    return LLMRouter()


# ── A1: Schema Migration ──────────────────────────────────────────────

def test_schema_provenance_fields():
    """NodeSchema has all Phase 3 provenance fields."""
    from brain.schema import NodeSchema, NodeType, NodeSource
    node = NodeSchema(
        type=NodeType.TASK,
        label="Test provenance",
        description="Testing provenance fields exist",
        source=NodeSource.CALENDAR,
        source_ref="gcal:test123",
        evidence=["test evidence"],
        node_weight=0.7,
        is_stale=False,
    )
    assert node.source_ref == "gcal:test123"
    assert node.evidence == ["test evidence"]
    assert node.node_weight == 0.7
    assert node.is_stale is False
    assert node.last_verified is None
    print("  Schema provenance fields: OK")


def test_schema_stale_status():
    """NodeStatus includes STALE."""
    from brain.schema import NodeStatus
    assert NodeStatus.STALE == "stale"
    print("  NodeStatus.STALE: OK")


# ── A2: Router Expansion ──────────────────────────────────────────────

def test_router_has_all_providers(llm_router):
    """Router has all 5 providers configured."""
    status = llm_router.get_quota_status()
    expected = {'ollama', 'groq', 'gemini_flash', 'gemini_flash_lite', 'openrouter'}
    assert set(status.keys()) == expected
    print(f"  Router providers: {list(status.keys())}")


def test_router_quota_tracking(llm_router):
    """Router tracks daily and RPM quotas per provider."""
    status = llm_router.get_quota_status()
    for provider, s in status.items():
        assert 'daily_used' in s
        assert 'rpm_current' in s
        assert 'rpm_cap' in s
    print("  Quota tracking fields: OK")


def test_router_cascade(llm_router):
    """Router cascades to fallback when primary exhausted."""
    # Exhaust ollama
    llm_router._quotas['ollama']._session_count = 9999
    result = asyncio.get_event_loop().run_until_complete(
        llm_router.route(
            task_type='classification',
            messages=[{"role": "user", "content": "Reply: cascade ok"}],
            max_tokens=20
        )
    )
    assert len(result) > 0
    # Reset
    llm_router._quotas['ollama']._session_count = 0
    print(f"  Cascade routing: OK (got {len(result)} chars)")


# ── A3: Secrets Service ───────────────────────────────────────────────

def test_secrets_service_keyring():
    """SecretsService reads managed keys from keyring."""
    from services.secrets_service import secrets, MANAGED_KEYS
    status = secrets.status()
    keyring_keys = [k for k, v in status.items() if v['keyring']]
    assert len(keyring_keys) >= 8, (
        f"Expected >=8 keys in keyring, got {len(keyring_keys)}"
    )
    print(f"  Keyring keys: {len(keyring_keys)}/{len(MANAGED_KEYS)}")


def test_secrets_groq_key():
    """GROQ_API_KEY is retrievable."""
    from services.secrets_service import secrets
    key = secrets.get('GROQ_API_KEY')
    assert key and len(key) > 10
    print("  GROQ_API_KEY: OK")


# ── B1: Calendar Service ──────────────────────────────────────────────

def test_google_auth_authenticated():
    """Google OAuth credentials are valid."""
    from services.google_auth_service import google_auth
    assert google_auth.is_authenticated()
    print("  Google OAuth: authenticated")


def test_calendar_service_connection():
    """Calendar service can connect to Google Calendar API."""
    from services.calendar_service import CalendarService
    svc = CalendarService()
    service = svc.get_service()
    result = service.calendarList().list().execute()
    assert 'items' in result
    print(f"  Calendar API: connected ({len(result['items'])} calendars)")


def test_calendar_signal_defaults():
    """Calendar nodes use correct signal defaults."""
    from brain.signal_defaults import get_defaults, calendar_attention
    from brain.schema import NodeSource
    defaults = get_defaults(NodeSource.CALENDAR)
    assert defaults['importance'] == 0.4
    assert defaults['node_weight'] == 0.7
    # Attention by proximity
    assert calendar_attention(0) == 1.0
    assert calendar_attention(12) == 1.0
    assert calendar_attention(48) == 0.8
    assert calendar_attention(200) == 0.4
    print("  Calendar signal defaults: OK")


def test_brain_find_node_by_source_ref(brain):
    """brain_service.find_node_by_source_ref works correctly."""
    from brain.schema import NodeSchema, NodeType, NodeSource
    # Create a node with known source_ref
    node = NodeSchema(
        type=NodeType.EVENT,
        label="Test source_ref node",
        description="Testing find_node_by_source_ref",
        source=NodeSource.CALENDAR,
        source_ref="gcal:test_find_ref_12345",
    )
    node_id = brain.create_node(node)

    # Find it
    found = brain.find_node_by_source_ref("gcal:test_find_ref_12345")
    assert found is not None
    assert found['id'] == node_id

    # Cleanup
    with brain.driver.session() as session:
        session.run("MATCH (n:Node {id: $id}) DETACH DELETE n", id=node_id)

    print("  find_node_by_source_ref: OK")


# ── B2: GitHub Service ────────────────────────────────────────────────

def test_github_repo_accessible():
    """GitHub API can access Presence repo."""
    import asyncio
    from services.github_service import github_service
    commit = asyncio.get_event_loop().run_until_complete(
        github_service.get_latest_commit()
    )
    assert 'sha' in commit
    assert len(commit['sha']) == 40
    print(f"  GitHub repo: accessible (latest {commit['sha'][:8]})")


def test_github_sha_storage(brain):
    """GitHub SHA can be stored and retrieved from SQLite."""
    from services.github_service import github_service
    test_sha = "abcdef1234567890" * 2 + "abcdef12"
    github_service._store_last_sha(brain, test_sha)
    retrieved = github_service._get_last_sha(brain)
    assert retrieved == test_sha
    print("  GitHub SHA storage: OK")


def test_github_state_table_exists(brain):
    """github_state table exists in SQLite."""
    cursor = brain.db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='github_state'"
    )
    row = cursor.fetchone()
    assert row is not None
    print("  github_state table: OK")


# ── B3: Gmail Service ─────────────────────────────────────────────────

def test_gmail_status():
    """Gmail service is authenticated."""
    from services.google_auth_service import google_auth
    assert google_auth.is_authenticated()
    print("  Gmail auth: OK")


def test_gmail_message_build():
    """Gmail service builds valid message structure."""
    from services.gmail_service import GmailService
    svc = GmailService()
    msg = svc._build_message(
        subject="Test",
        body="Test body",
        html=False
    )
    assert 'raw' in msg
    assert len(msg['raw']) > 0
    print("  Gmail message build: OK")


# ── C1: Signal Defaults ───────────────────────────────────────────────

def test_signal_defaults_all_sources():
    """Signal defaults exist for all NodeSource values."""
    from brain.signal_defaults import get_defaults
    from brain.schema import NodeSource
    for source in NodeSource:
        defaults = get_defaults(source)
        assert 'importance' in defaults
        assert 'attention' in defaults
        assert 'node_weight' in defaults
        assert 0.0 <= defaults['importance'] <= 1.0
        assert 0.0 <= defaults['node_weight'] <= 1.5
    print("  Signal defaults for all sources: OK")


def test_analysis_importance_scaling():
    """Analysis importance scales correctly from priority."""
    from brain.signal_defaults import analysis_importance
    imp_p1  = analysis_importance(1)
    imp_p10 = analysis_importance(10)
    assert imp_p1 == 0.8
    assert imp_p10 < imp_p1
    assert imp_p10 >= 0.4
    print(f"  Analysis importance: priority 1={imp_p1}, priority 10={imp_p10}")


# ── C2: Drip Service ─────────────────────────────────────────────────

def test_drip_service_status(brain):
    """Drip service returns valid status structure."""
    from services.drip_service import drip_service
    status = drip_service.get_drip_status(brain)
    assert 'total_findings' in status
    assert 'surfaced' in status
    assert 'remaining' in status
    assert 'drip_per_day' in status
    assert status['drip_per_day'] == 2
    print(f"  Drip status: {status['remaining']} findings remaining")


def test_drip_format_finding():
    """Drip service formats findings correctly for voice."""
    from services.drip_service import drip_service
    finding = {
        'id': 'test-id',
        'type': 'challenge',
        'label': 'Test Challenge',
        'description': 'This is a test description. It has two sentences.',
        'importance': 0.8,
    }
    text = drip_service.format_finding_for_briefing(finding)
    assert 'Boss' in text
    assert 'Test Challenge' in text
    assert len(text) < 500
    print(f"  Drip format: OK ({len(text)} chars)")


# ── D1: Standup Service ───────────────────────────────────────────────

def test_standup_sunday_skip(brain):
    """Standup skips on Sunday."""
    from services.standup_service import standup_service
    import datetime as dt
    from unittest.mock import patch

    # Mock today as Sunday
    sunday = dt.date(2026, 5, 10)  # a Sunday
    with patch('services.standup_service.date') as mock_date:
        mock_date.today.return_value = sunday
        mock_date.side_effect = lambda *args, **kw: dt.date(*args, **kw)
        result = standup_service.should_run_today(brain)
    assert result is False
    print("  Standup skips Sunday: OK")


def test_standup_questions_sequence():
    """Standup returns correct question sequence."""
    from services.standup_service import standup_service, STANDUP_QUESTIONS
    assert len(STANDUP_QUESTIONS) == 3
    assert standup_service.get_first_question() == STANDUP_QUESTIONS[0]
    assert standup_service.get_next_question(None, 0) == STANDUP_QUESTIONS[1]
    assert standup_service.get_next_question(None, 1) == STANDUP_QUESTIONS[2]
    assert standup_service.get_next_question(None, 2) is None
    print("  Standup question sequence: OK")


# ── D2: Weekly Review ─────────────────────────────────────────────────

def test_weekly_review_sunday_detection(brain):
    """Weekly review only runs on Sunday."""
    from services.weekly_review_service import weekly_review_service
    import datetime as dt
    from unittest.mock import patch

    # Mock a Monday
    monday = dt.date(2026, 5, 11)
    with patch('services.weekly_review_service.date') as mock_date:
        mock_date.today.return_value = monday
        mock_date.side_effect = lambda *args, **kw: dt.date(*args, **kw)
        result = weekly_review_service.should_run_today(brain)
    assert result is False
    print("  Weekly review skips non-Sunday: OK")


def test_weekly_review_brain_context(brain):
    """Weekly review builds brain context without error."""
    from services.weekly_review_service import weekly_review_service
    context = weekly_review_service._build_brain_context(brain)
    assert isinstance(context, str)
    assert len(context) > 0
    print(f"  Weekly review brain context: OK ({len(context)} chars)")


def test_weekly_review_segment_split():
    """Weekly review splits text into voice segments."""
    from services.weekly_review_service import weekly_review_service
    text = (
        "Boss, here is your weekly review. "
        "You completed three tasks this week. "
        "The Presence analysis is stalling. "
        "My recommendation is to focus on one thing."
    )
    segments = weekly_review_service._split_into_segments(text)
    assert len(segments) >= 1
    for s in segments:
        assert len(s) <= 200
    print(f"  Weekly review segments: {len(segments)} segments OK")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])