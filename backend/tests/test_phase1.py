"""
MAIHERA Integration Tests — Phase 1
Verifies all 9 success criteria for Phase 1: The Brain is Born.
Runs against live Neo4j, ChromaDB, and SQLite.
Zero LLM API calls — Groq only where needed, Ollama never.
"""

import asyncio
import math
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def brain_service():
    """Single BrainService instance for the entire test session."""
    from brain.brain_service import get_brain_service
    brain, driver = get_brain_service()
    yield brain
    # Cleanup test nodes after all tests
    with driver.session() as session:
        session.run("""
            MATCH (n:Node)
            WHERE n.label STARTS WITH 'TEST_'
            DETACH DELETE n
        """)
    driver.close()


@pytest.fixture(scope="session")
def db_manager():
    """Single DatabaseManager instance for the entire test session."""
    from brain.sqlite_store import DatabaseManager
    db = DatabaseManager()
    db.initialize()
    yield db
    db.disconnect()


@pytest.fixture(scope="session")
def llm_router():
    """LLM router with Ollama quota maxed — forces Groq only."""
    from llm.router import LLMRouter
    router = LLMRouter()
    router._ollama_session_count = router.ollama_session_cap
    return router


# ── Test 1: Schema ────────────────────────────────────────────────────

class TestSchema:
    """Verify Neo4j constraints and indexes exist."""

    def test_constraint_exists(self, brain_service):
        """maihera_node_id uniqueness constraint must exist."""
        with brain_service.driver.session() as session:
            result = session.run("SHOW CONSTRAINTS")
            constraints = [r.data() for r in result]
            names = [
                c.get('name', '') for c in constraints
            ]
            assert 'maihera_node_id' in names, (
                f"Constraint 'maihera_node_id' not found. "
                f"Found: {names}"
            )

    def test_indexes_exist(self, brain_service):
        """All 4 custom indexes must exist."""
        with brain_service.driver.session() as session:
            result = session.run("SHOW INDEXES")
            indexes = [r.data() for r in result]
            names = [i.get('name', '') for i in indexes]

        expected = [
            'maihera_node_type',
            'maihera_node_project',
            'maihera_node_status',
            'maihera_node_last_touched',
        ]
        for idx in expected:
            assert idx in names, (
                f"Index '{idx}' not found. Found: {names}"
            )


# ── Test 2: Node Creation ─────────────────────────────────────────────

class TestNodeCreation:
    """Verify node creation in Neo4j and ChromaDB."""

    def test_create_node_neo4j(self, brain_service):
        """Node must appear in Neo4j after creation."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_node_creation",
            "description": "Integration test node for creation check",
            "source": "manual",
            "status": "active",
            "importance": 0.6,
            "attention": 0.7,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        assert node_id is not None

        retrieved = brain_service.get_node(node_id)
        assert retrieved is not None
        assert retrieved['label'] == "TEST_node_creation"
        assert retrieved['type'] == "task"

    def test_create_node_chromadb(self, brain_service):
        """Node must appear in ChromaDB after creation."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "idea",
            "label": "TEST_chromadb_creation",
            "description": (
                "Testing that ChromaDB receives the embedding "
                "when a node is created in Neo4j"
            ),
            "source": "manual",
            "status": "active",
            "importance": 0.5,
            "attention": 0.4,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)

        chroma_node = brain_service.vector_store.get_node(node_id)
        assert chroma_node is not None
        assert chroma_node['node_id'] == node_id

    def test_last_touched_set_on_creation(self, brain_service):
        """last_touched must be set when node is created."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "question",
            "label": "TEST_last_touched",
            "description": "Testing last_touched timestamp on creation",
            "source": "manual",
            "status": "active",
            "importance": 0.4,
            "attention": 0.3,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        retrieved = brain_service.get_node(node_id)
        assert retrieved.get('last_touched') is not None
        assert len(retrieved['last_touched']) > 0


# ── Test 3: Signal Updates ────────────────────────────────────────────

class TestSignalUpdates:
    """Verify signal updates persist and validate correctly."""

    def test_signal_update_persists(self, brain_service):
        """Updated signal must persist in Neo4j."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_signal_update",
            "description": "Testing signal persistence",
            "source": "manual",
            "status": "active",
            "importance": 0.5,
            "attention": 0.3,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)

        brain_service.update_signal(node_id, 'attention', 0.85)
        updated = brain_service.get_node(node_id)
        assert abs(updated['attention'] - 0.85) < 0.001

    def test_signal_clamped_to_range(self, brain_service):
        """Signal values must be clamped to 0.0-1.0."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_signal_clamp",
            "description": "Testing signal clamping",
            "source": "manual",
            "status": "active",
            "importance": 0.5,
            "attention": 0.3,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)

        brain_service.update_signal(node_id, 'importance', 1.5)
        updated = brain_service.get_node(node_id)
        assert updated['importance'] <= 1.0

        brain_service.update_signal(node_id, 'importance', -0.5)
        updated = brain_service.get_node(node_id)
        assert updated['importance'] >= 0.0

    def test_invalid_signal_name_raises(self, brain_service):
        """Invalid signal name must raise ValueError."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_signal_invalid",
            "description": "Testing invalid signal rejection",
            "source": "manual",
            "status": "active",
            "importance": 0.5,
            "attention": 0.3,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)

        with pytest.raises(ValueError):
            brain_service.update_signal(node_id, 'fake_signal', 0.5)


# ── Test 4: Resistance Recomputation ─────────────────────────────────

class TestResistance:
    """Verify resistance edge creation triggers recomputation."""

    def test_resistance_recomputed_on_edge_creation(
        self, brain_service
    ):
        """Node resistance must update when resistance edge is created."""
        from brain.schema import ResistanceEdge

        self_node_data = {
            "id": str(uuid.uuid4()),
            "type": "person",
            "label": "TEST_self_resistance",
            "description": "Test self node for resistance",
            "source": "manual",
            "status": "active",
            "importance": 1.0,
            "attention": 1.0,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        self_id = brain_service.create_node(self_node_data)

        target_node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_resistance_target",
            "description": "Task that will have resistance",
            "source": "manual",
            "status": "active",
            "importance": 0.7,
            "attention": 0.5,
            "resistance": 0.0,
            "current_load": 0.0,
            "trust_level": 0.3,
            "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        target_id = brain_service.create_node(target_node_data)

        before = brain_service.get_node(target_id)
        assert before['resistance'] == 0.0

        resistance = ResistanceEdge(
            score=0.75,
            reason="avoidant",
            evidence=["has not touched in 3 days"],
            maihera_response="push",
            trend="rising",
            since=datetime.utcnow().isoformat()
        )
        brain_service.create_resistance_edge(
            self_id, target_id, resistance
        )

        after = brain_service.get_node(target_id)
        assert after['resistance'] > 0.0
        assert abs(after['resistance'] - 0.75) < 0.01


# ── Test 5: Semantic Search ───────────────────────────────────────────

class TestSemanticSearch:
    """Verify semantic similarity search works correctly."""

    def test_semantic_search_finds_relevant_node(self, brain_service):
        """Paraphrased query must find the correct node in top 3."""
        nodes = [
            {
                "id": str(uuid.uuid4()),
                "type": "issue",
                "label": "TEST_search_voice",
                "description": (
                    "Voice cloning quality is degraded in Presence "
                    "speech-to-speech mode after the latest update"
                ),
                "source": "manual", "status": "active",
                "importance": 0.7, "attention": 0.5,
                "resistance": 0.0, "current_load": 0.0,
                "trust_level": 0.3, "workspace": "personal",
                "visibility": "private",
                "created_at": datetime.utcnow().isoformat(),
                "last_touched": datetime.utcnow().isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "type": "task",
                "label": "TEST_search_database",
                "description": (
                    "Optimize the Supabase database queries "
                    "for faster response times"
                ),
                "source": "manual", "status": "active",
                "importance": 0.5, "attention": 0.3,
                "resistance": 0.0, "current_load": 0.0,
                "trust_level": 0.3, "workspace": "personal",
                "visibility": "private",
                "created_at": datetime.utcnow().isoformat(),
                "last_touched": datetime.utcnow().isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "type": "idea",
                "label": "TEST_search_animation",
                "description": (
                    "Add smooth fade animations to the "
                    "Presence chat interface"
                ),
                "source": "manual", "status": "active",
                "importance": 0.4, "attention": 0.2,
                "resistance": 0.0, "current_load": 0.0,
                "trust_level": 0.3, "workspace": "personal",
                "visibility": "private",
                "created_at": datetime.utcnow().isoformat(),
                "last_touched": datetime.utcnow().isoformat(),
            },
        ]

        for n in nodes:
            brain_service.create_node(n)

        results = brain_service.search_nodes(
            "audio and speech problems in the app"
        )
        top_labels = [r['label'] for r in results[:3]]
        assert "TEST_search_voice" in top_labels, (
            f"Expected voice node in top 3. Got: {top_labels}"
        )


# ── Test 6: Urgency Computation ───────────────────────────────────────

class TestUrgency:
    """Verify urgency is computed correctly and never stored."""

    def test_urgency_range(self, brain_service):
        """Urgency must always be between 0.0 and 1.0."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_urgency_range",
            "description": "Testing urgency range",
            "source": "manual", "status": "active",
            "importance": 0.8, "attention": 0.6,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        urgency = brain_service.compute_urgency(node_id)
        assert 0.0 <= urgency <= 1.0

    def test_urgency_not_stored(self, brain_service):
        """Urgency must not appear as a stored field on the node."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_urgency_not_stored",
            "description": "Testing urgency is never stored",
            "source": "manual", "status": "active",
            "importance": 0.8, "attention": 0.6,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        brain_service.compute_urgency(node_id)
        node = brain_service.get_node(node_id)
        assert 'urgency' not in node

    def test_closer_deadline_higher_urgency(self, brain_service):
        """Node with closer deadline must have higher urgency."""
        from datetime import timedelta

        near_id = str(uuid.uuid4())
        far_id = str(uuid.uuid4())

        near = {
            "id": near_id, "type": "task",
            "label": "TEST_urgency_near",
            "description": "Task due very soon",
            "deadline": (
                datetime.utcnow() + timedelta(days=2)
            ).isoformat(),
            "source": "manual", "status": "active",
            "importance": 0.8, "attention": 0.6,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        far = {
            "id": far_id, "type": "task",
            "label": "TEST_urgency_far",
            "description": "Task due far away",
            "deadline": (
                datetime.utcnow() + timedelta(days=60)
            ).isoformat(),
            "source": "manual", "status": "active",
            "importance": 0.8, "attention": 0.6,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        brain_service.create_node(near)
        brain_service.create_node(far)

        near_urgency = brain_service.compute_urgency(near_id)
        far_urgency = brain_service.compute_urgency(far_id)
        assert near_urgency > far_urgency, (
            f"Near urgency ({near_urgency}) should be > "
            f"far urgency ({far_urgency})"
        )


# ── Test 7: Signal Decay ──────────────────────────────────────────────

class TestDecay:
    """Verify decay applies correctly and respects the floor."""

    def test_attention_decays_after_24h(self, brain_service):
        """Attention must decrease after 24 hours of decay."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_decay_attention",
            "description": "Testing attention decay",
            "source": "manual", "status": "active",
            "importance": 0.8, "attention": 0.9,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        brain_service.update_signal(node_id, 'attention', 0.9)

        changes = brain_service.apply_decay(node_id, hours_elapsed=24.0)
        after = brain_service.get_node(node_id)

        assert after['attention'] < 0.9, (
            "Attention should have decayed after 24 hours"
        )

    def test_decay_never_below_floor(self, brain_service):
        """Decay must never bring a signal below 0.05."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_decay_floor",
            "description": "Testing decay floor",
            "source": "manual", "status": "active",
            "importance": 0.5, "attention": 0.1,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        brain_service.update_signal(node_id, 'attention', 0.1)

        brain_service.apply_decay(node_id, hours_elapsed=10000.0)
        after = brain_service.get_node(node_id)

        assert after['attention'] >= 0.05, (
            f"Attention {after['attention']} went below floor 0.05"
        )

    def test_decay_logged_to_sqlite(self, brain_service, db_manager):
        """Decay events must be logged to SQLite signal_decay_log."""
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "task",
            "label": "TEST_decay_logging",
            "description": "Testing decay audit logging",
            "source": "manual", "status": "active",
            "importance": 0.8, "attention": 0.9,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain_service.create_node(node_data)
        brain_service.update_signal(node_id, 'attention', 0.9)

        brain_service.apply_decay(node_id, hours_elapsed=24.0)

        history = db_manager.get_decay_history(node_id)
        assert len(history) > 0, (
            "Decay should be logged to SQLite"
        )
        assert history[0]['signal_name'] in (
            'importance', 'attention'
        )


# ── Test 8: LLM Router ────────────────────────────────────────────────

class TestLLMRouter:
    """Verify LLM router works and quota tracking is correct."""

    def test_groq_returns_response(self, llm_router):
        """Groq must return a non-empty response."""
        result = llm_router._call_groq(
            messages=[{
                "role": "user",
                "content": (
                    "Reply with exactly: "
                    "MAIHERA integration test OK"
                )
            }],
            system_prompt=None,
            max_tokens=20,
            task_type='conversation'
        )
        assert len(result) > 0

    def test_quota_increments(self, llm_router):
        """Groq quota counter must increment after each call."""
        before = llm_router._groq_daily_count
        llm_router._call_groq(
            messages=[{
                "role": "user",
                "content": "Reply with: quota test"
            }],
            system_prompt=None,
            max_tokens=10,
            task_type='signal_update'
        )
        after = llm_router._groq_daily_count
        assert after == before + 1

    def test_cascade_to_groq_when_ollama_exhausted(self, llm_router):
        """Router must cascade to Groq when Ollama quota is full."""

        async def run():
            result = await llm_router.route(
                task_type='conversation',
                messages=[{
                    "role": "user",
                    "content": "Reply with: cascade OK"
                }],
                max_tokens=15
            )
            return result

        result = asyncio.get_event_loop().run_until_complete(run())
        assert len(result) > 0

        log = llm_router.get_request_log()
        last = log[-1]
        assert last['provider'] == 'groq'
        assert last['success'] is True


# ── Test 9: Persistence ───────────────────────────────────────────────

class TestPersistence:
    """Verify data persists across new service connections."""

    def test_node_persists_across_reconnect(self):
        """Node created in one connection must exist in a new one."""
        from brain.brain_service import get_brain_service

        # Create node with first connection
        brain1, driver1 = get_brain_service()
        node_data = {
            "id": str(uuid.uuid4()),
            "type": "insight",
            "label": "TEST_persistence_check",
            "description": "Testing persistence across reconnects",
            "source": "manual", "status": "active",
            "importance": 0.6, "attention": 0.5,
            "resistance": 0.0, "current_load": 0.0,
            "trust_level": 0.3, "workspace": "personal",
            "visibility": "private",
            "created_at": datetime.utcnow().isoformat(),
            "last_touched": datetime.utcnow().isoformat(),
        }
        node_id = brain1.create_node(node_data)
        driver1.close()

        # Retrieve with second connection
        brain2, driver2 = get_brain_service()
        retrieved = brain2.get_node(node_id)

        assert retrieved is not None
        assert retrieved['label'] == "TEST_persistence_check"
        assert retrieved['id'] == node_id

        # Cleanup
        with driver2.session() as session:
            session.run(
                "MATCH (n:Node {id: $id}) DETACH DELETE n",
                id=node_id
            )
        driver2.close()