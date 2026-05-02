"""
MAIHERA Brain Layer — BrainService
Single interface between all MAIHERA services and Neo4j.
Nothing queries Neo4j directly except this file.
"""

import os
import json
import math
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)

# Signal decay rates per hour
DECAY_RATE_IMPORTANCE = 0.002   # very slow — weeks to decay
DECAY_RATE_ATTENTION = 0.05     # fast — hours to days
SIGNAL_FLOOR = 0.05             # never decay below this


class BrainService:
    """
    Core interface to the Neo4j brain graph.
    Coordinates between Neo4j, ChromaDB, and SQLite.
    All graph reads and writes pass through this class.
    """

    def __init__(self, driver, vector_store, db_manager):
        self.driver = driver
        self.vector_store = vector_store
        self.db = db_manager

    # ── Node Operations ───────────────────────────────────────────

    def create_node(self, node_data) -> str:
        """
        Create a node in Neo4j and register its embedding
        in ChromaDB. Returns the node id.
        node_data can be a NodeSchema instance or a dict.
        """
        if hasattr(node_data, 'model_dump'):
            data = node_data.model_dump()
        else:
            data = dict(node_data)

        now = datetime.utcnow().isoformat()
        data['created_at'] = now
        data['last_touched'] = now

        # Convert list fields to JSON strings for Neo4j storage
        for field in ['alternatives']:
            if isinstance(data.get(field), list):
                import json
                data[field] = json.dumps(data[field])

        with self.driver.session() as session:
            session.run("""
                CREATE (n:Node $props)
            """, props=data)

        # Register in ChromaDB
        metadata = {
            'type': str(data.get('type', 'unknown')),
            'project_id': str(data.get('project_id', '')),
            'status': str(data.get('status', 'active')),
            'label': str(data.get('label', '')),
        }
        self.vector_store.upsert_node(
            node_id=data['id'],
            description=data.get('description', data.get('label', '')),
            metadata=metadata
        )

        # Update embedding_ref on Neo4j node
        with self.driver.session() as session:
            session.run("""
                MATCH (n:Node {id: $id})
                SET n.embedding_ref = $ref
            """, id=data['id'], ref=data['id'])

        logger.info("Created node: %s (%s)", data['label'], data['id'])
        return data['id']

    def get_node(self, node_id: str) -> Optional[dict]:
        """Retrieve full node data from Neo4j by id."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Node {id: $id})
                RETURN properties(n) as props
            """, id=node_id)
            record = result.single()
            if not record:
                return None
            return dict(record['props'])

    def update_node(self, node_id: str, updates: dict) -> None:
        """
        Update specified fields on a node.
        Always updates last_touched timestamp.
        """
        updates['last_touched'] = datetime.utcnow().isoformat()

        # If description changed, re-embed
        if 'description' in updates or 'label' in updates:
            node = self.get_node(node_id)
            if node:
                new_description = updates.get(
                    'description', node.get('description', '')
                )
                new_label = updates.get(
                    'label', node.get('label', '')
                )
                metadata = {
                    'type': str(node.get('type', 'unknown')),
                    'project_id': str(updates.get(
                        'project_id',
                        node.get('project_id', '')
                    )),
                    'status': str(updates.get(
                        'status', node.get('status', 'active')
                    )),
                    'label': new_label,
                }
                self.vector_store.upsert_node(
                    node_id=node_id,
                    description=new_description,
                    metadata=metadata
                )

        with self.driver.session() as session:
            session.run("""
                MATCH (n:Node {id: $id})
                SET n += $updates
            """, id=node_id, updates=updates)

        logger.debug("Updated node %s with %s", node_id,
                     list(updates.keys()))

    def update_signal(
        self,
        node_id: str,
        signal: str,
        value: float
    ) -> None:
        """
        Update a single signal field on a node.
        Validates 0.0-1.0 range. Updates last_touched.
        Signal must be: importance, attention, or resistance.
        """
        valid_signals = {'importance', 'attention', 'resistance'}
        if signal not in valid_signals:
            raise ValueError(
                f"Invalid signal '{signal}'. "
                f"Must be one of: {valid_signals}"
            )
        value = max(0.0, min(1.0, float(value)))
        now = datetime.utcnow().isoformat()

        with self.driver.session() as session:
            session.run(f"""
                MATCH (n:Node {{id: $id}})
                SET n.{signal} = $value, n.last_touched = $now
            """, id=node_id, value=value, now=now)

        logger.debug(
            "Signal update: node=%s %s=%.3f", node_id, signal, value
        )

    def list_nodes(
        self,
        project_id: Optional[str] = None,
        node_type: Optional[str] = None,
        status: Optional[str] = None
    ) -> list[dict]:
        """
        List nodes with optional filters.
        Returns list of node property dicts.
        """
        conditions = ["1=1"]
        params = {}

        if project_id:
            conditions.append("n.project_id = $project_id")
            params['project_id'] = project_id
        if node_type:
            conditions.append("n.type = $node_type")
            params['node_type'] = node_type
        if status:
            conditions.append("n.status = $status")
            params['status'] = status

        where = " AND ".join(conditions)

        with self.driver.session() as session:
            result = session.run(f"""
                MATCH (n:Node)
                WHERE {where}
                RETURN properties(n) as props
                ORDER BY n.last_touched DESC
            """, **params)
            return [dict(r['props']) for r in result]

    def search_nodes(
        self,
        query: str,
        project_id: Optional[str] = None
    ) -> list[dict]:
        """
        Semantic search via ChromaDB.
        Enriches results with full Neo4j node data.
        """
        chroma_results = self.vector_store.search_similar(
            query=query,
            n_results=10,
            filter_project_id=project_id
        )

        enriched = []
        for r in chroma_results:
            node = self.get_node(r['node_id'])
            if node:
                node['_search_distance'] = r['distance']
                enriched.append(node)

        return enriched

    # ── Edge Operations ───────────────────────────────────────────

    def create_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        properties: Optional[dict] = None
    ) -> None:
        """Create a relationship between two nodes in Neo4j."""
        props = properties or {}
        props['created_at'] = datetime.utcnow().isoformat()

        with self.driver.session() as session:
            session.run(f"""
                MATCH (a:Node {{id: $from_id}})
                MATCH (b:Node {{id: $to_id}})
                CREATE (a)-[r:{edge_type} $props]->(b)
            """, from_id=from_id, to_id=to_id, props=props)

        logger.debug(
            "Edge created: %s -[%s]-> %s",
            from_id, edge_type, to_id
        )

    def get_edges(
        self,
        node_id: str,
        direction: str = 'both'
    ) -> list[dict]:
        """
        Get all edges for a node.
        direction: 'in', 'out', or 'both'
        """
        if direction == 'out':
            query = """
                MATCH (n:Node {id: $id})-[r]->(m:Node)
                RETURN type(r) as type,
                       n.id as from_id,
                       m.id as to_id,
                       properties(r) as props
            """
        elif direction == 'in':
            query = """
                MATCH (n:Node {id: $id})<-[r]-(m:Node)
                RETURN type(r) as type,
                       m.id as from_id,
                       n.id as to_id,
                       properties(r) as props
            """
        else:
            query = """
                MATCH (n:Node {id: $id})-[r]-(m:Node)
                RETURN type(r) as type,
                       startNode(r).id as from_id,
                       endNode(r).id as to_id,
                       properties(r) as props
            """

        with self.driver.session() as session:
            result = session.run(query, id=node_id)
            return [
                {
                    'type': r['type'],
                    'from_id': r['from_id'],
                    'to_id': r['to_id'],
                    'properties': dict(r['props'])
                }
                for r in result
            ]

    def create_resistance_edge(
        self,
        from_id: str,
        to_id: str,
        resistance_data
    ) -> None:
        """
        Create a resistance relationship from self node to a target.
        Automatically recomputes resistance on the target node.
        resistance_data: ResistanceEdge instance or dict.
        """
        if hasattr(resistance_data, 'model_dump'):
            props = resistance_data.model_dump()
        else:
            props = dict(resistance_data)

        props['created_at'] = datetime.utcnow().isoformat()

        with self.driver.session() as session:
            session.run("""
                MATCH (a:Node {id: $from_id})
                MATCH (b:Node {id: $to_id})
                CREATE (a)-[r:HAS_RESISTANCE $props]->(b)
            """, from_id=from_id, to_id=to_id, props=props)

        # Recompute resistance on target node automatically
        self._recompute_resistance(to_id)
        logger.info(
            "Resistance edge created: %s -> %s (score=%.2f)",
            from_id, to_id, props.get('score', 0)
        )

    def _recompute_resistance(self, node_id: str) -> None:
        """
        Recompute the resistance field on a node from all
        incoming HAS_RESISTANCE edges.
        Uses max score (worst-case signal).
        Fires automatically on every resistance edge change.
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (s:Node)-[r:HAS_RESISTANCE]->(n:Node {id: $id})
                RETURN r.score as score
            """, id=node_id)

            scores = [record['score'] for record in result
                      if record['score'] is not None]

        aggregate = max(scores) if scores else 0.0
        aggregate = max(0.0, min(1.0, aggregate))

        with self.driver.session() as session:
            session.run("""
                MATCH (n:Node {id: $id})
                SET n.resistance = $resistance,
                    n.last_touched = $now
            """, id=node_id, resistance=aggregate,
                now=datetime.utcnow().isoformat())

        logger.debug(
            "Resistance recomputed for %s: %.3f", node_id, aggregate
        )

    # ── Signal Decay ──────────────────────────────────────────────

    def apply_decay(
        self,
        node_id: str,
        hours_elapsed: float
    ) -> dict:
        """
        Apply exponential decay to importance and attention.
        Decay formula: new = current * exp(-rate * hours)
        Never decays below SIGNAL_FLOOR (0.05).
        Logs each decay to SQLite signal_decay_log.
        Returns dict of {signal: (before, after)} pairs.
        """
        node = self.get_node(node_id)
        if not node:
            return {}

        changes = {}

        for signal, rate in [
            ('importance', DECAY_RATE_IMPORTANCE),
            ('attention', DECAY_RATE_ATTENTION)
        ]:
            current = float(node.get(signal, 0.5))
            decayed = current * math.exp(-rate * hours_elapsed)
            new_value = max(SIGNAL_FLOOR, decayed)

            if abs(new_value - current) > 0.001:
                self.update_signal(node_id, signal, new_value)
                self.db.log_decay(
                    node_id=node_id,
                    signal_name=signal,
                    value_before=current,
                    value_after=new_value
                )
                changes[signal] = (current, new_value)

        return changes

    def apply_decay_all(self, hours_elapsed: float = 1.0) -> int:
        """
        Apply decay to all active nodes.
        Called by the scheduler every hour.
        Returns count of nodes decayed.
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Node)
                WHERE n.status = 'active'
                RETURN n.id as id
            """)
            node_ids = [r['id'] for r in result]

        count = 0
        for node_id in node_ids:
            try:
                changes = self.apply_decay(node_id, hours_elapsed)
                if changes:
                    count += 1
            except Exception as e:
                logger.error(
                    "Decay failed for node %s: %s", node_id, e
                )

        logger.info(
            "Decay applied to %d/%d active nodes "
            "(%.1f hours elapsed)",
            count, len(node_ids), hours_elapsed
        )
        return count

    # ── Urgency Computation ───────────────────────────────────────

    def compute_urgency(self, node_id: str) -> float:
        """
        Compute urgency live — never stored, always computed.
        Formula:
          No deadline: urgency = importance * 0.3
          With deadline: urgency = importance * (1 / (1 + days * 0.1))
        Returns float 0.0-1.0.
        """
        node = self.get_node(node_id)
        if not node:
            return 0.0

        importance = float(node.get('importance', 0.5))
        deadline_str = node.get('deadline')

        if not deadline_str:
            return round(importance * 0.3, 4)

        try:
            deadline = datetime.fromisoformat(deadline_str)
            now = datetime.utcnow()
            days_remaining = (deadline - now).total_seconds() / 86400

            if days_remaining <= 0:
                return round(min(1.0, importance * 2.0), 4)

            urgency = importance * (
                1.0 / (1.0 + days_remaining * 0.1)
            )
            return round(min(1.0, urgency), 4)

        except (ValueError, TypeError):
            return round(importance * 0.3, 4)

    # ── Graph Queries ─────────────────────────────────────────────

    def get_project_graph(self, project_id: str) -> dict:
        """
        Return all nodes and edges for a project.
        Format suitable for Three.js force-directed graph.
        """
        with self.driver.session() as session:
            node_result = session.run("""
                MATCH (n:Node)
                WHERE n.project_id = $project_id
                   OR n.id = $project_id
                RETURN properties(n) as props
            """, project_id=project_id)
            nodes = [dict(r['props']) for r in node_result]

            node_ids = [n['id'] for n in nodes]

            if not node_ids:
                return {'nodes': [], 'edges': []}

            edge_result = session.run("""
                MATCH (a:Node)-[r]->(b:Node)
                WHERE a.id IN $ids AND b.id IN $ids
                RETURN type(r) as type,
                       a.id as from_id,
                       b.id as to_id,
                       properties(r) as props
            """, ids=node_ids)

            edges = [
                {
                    'type': r['type'],
                    'from_id': r['from_id'],
                    'to_id': r['to_id'],
                    'properties': dict(r['props'])
                }
                for r in edge_result
            ]

        return {'nodes': nodes, 'edges': edges}

    def get_full_graph(self) -> dict:
        """
        Return the entire brain graph.
        Format suitable for Three.js force-directed graph.
        """
        with self.driver.session() as session:
            node_result = session.run("""
                MATCH (n:Node)
                RETURN properties(n) as props
                ORDER BY n.importance DESC
            """)
            nodes = [dict(r['props']) for r in node_result]

            edge_result = session.run("""
                MATCH (a:Node)-[r]->(b:Node)
                RETURN type(r) as type,
                       a.id as from_id,
                       b.id as to_id,
                       properties(r) as props
            """)
            edges = [
                {
                    'type': r['type'],
                    'from_id': r['from_id'],
                    'to_id': r['to_id'],
                    'properties': dict(r['props'])
                }
                for r in edge_result
            ]

        return {'nodes': nodes, 'edges': edges}

    def get_high_signal_nodes(
        self,
        importance_threshold: float = 0.6,
        attention_threshold: float = 0.4
    ) -> list[dict]:
        """
        Return nodes above signal thresholds.
        Sorted by urgency descending.
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n:Node)
                WHERE n.importance >= $imp
                  AND n.attention >= $att
                  AND n.status = 'active'
                RETURN properties(n) as props
            """, imp=importance_threshold, att=attention_threshold)
            nodes = [dict(r['props']) for r in result]

        # Sort by live urgency
        for node in nodes:
            node['_urgency'] = self.compute_urgency(node['id'])

        nodes.sort(key=lambda n: n['_urgency'], reverse=True)
        return nodes

    def get_stats(self) -> dict:
        """Return brain graph statistics."""
        with self.driver.session() as session:
            node_count = session.run(
                "MATCH (n:Node) RETURN count(n) as count"
            ).single()['count']

            edge_count = session.run(
                "MATCH ()-[r]->() RETURN count(r) as count"
            ).single()['count']

            type_counts_result = session.run("""
                MATCH (n:Node)
                RETURN n.type as type, count(n) as count
                ORDER BY count DESC
            """)
            type_counts = {
                r['type']: r['count']
                for r in type_counts_result
            }

        return {
            'node_count': node_count,
            'edge_count': edge_count,
            'type_counts': type_counts
        }
    
    def update_self_node_energy(self, energy_level: int) -> None:
        """Update energy_level on the self node."""
        with self.driver.session() as session:
            session.run("""
                MATCH (n:Node {type: 'self'})
                SET n.energy_level = $level,
                    n.last_touched = $now
            """, level=energy_level, now=datetime.utcnow().isoformat())
        logger.info("Self node energy updated: %d", energy_level)
    
    def export_to_json(self, export_dir: Optional[str] = None) -> str:
        """
        Export all nodes and edges to a JSON file.
        Saves to backups/ directory by default.
        Returns the path of the created export file.
        This is a recoverable data snapshot — not a true DB backup
        but sufficient to reconstruct the graph if needed.
        """
        if export_dir:
            backup_path = Path(export_dir)
        else:
            backup_path = (
                Path(__file__).parent.parent.parent / 'backups'
            )
        backup_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"maihera_brain_{timestamp}.json"
        filepath = backup_path / filename

        with self.driver.session() as session:
            node_result = session.run("""
                MATCH (n:Node)
                RETURN properties(n) as props
                ORDER BY n.created_at ASC
            """)
            nodes = [dict(r['props']) for r in node_result]

            edge_result = session.run("""
                MATCH (a:Node)-[r]->(b:Node)
                RETURN type(r) as type,
                       a.id as from_id,
                       b.id as to_id,
                       properties(r) as props
            """)
            edges = [
                {
                    'type': r['type'],
                    'from_id': r['from_id'],
                    'to_id': r['to_id'],
                    'properties': dict(r['props'])
                }
                for r in edge_result
            ]

        export_data = {
            'exported_at': datetime.utcnow().isoformat(),
            'node_count': len(nodes),
            'edge_count': len(edges),
            'nodes': nodes,
            'edges': edges
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str)

        # Log to SQLite
        self.db.log_export(
            node_count=len(nodes),
            edge_count=len(edges),
            export_path=str(filepath),
            status='success'
        )

        logger.info(
            "Brain exported: %d nodes, %d edges → %s",
            len(nodes), len(edges), filepath
        )
        return str(filepath)


def get_driver_with_retry() -> object:
    """
    Create Neo4j driver with exponential backoff retry.
    Handles Neo4j Aura Free inactivity pauses gracefully.
    Retries every 30 seconds for up to 10 minutes.
    Surfaces a clear alert if all retries fail.
    """
    import time

    uri = os.getenv('NEO4J_URI')
    user = os.getenv('NEO4J_USER')
    password = os.getenv('NEO4J_PASSWORD')

    if not all([uri, user, password]):
        raise ValueError(
            "Missing Neo4j credentials in .env — "
            "NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD required"
        )

    max_attempts = 20          # 20 attempts × 30s = 10 minutes
    wait_seconds = 30
    attempt = 0

    while attempt < max_attempts:
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            if attempt > 0:
                logger.info(
                    "Neo4j reconnected after %d attempts.",
                    attempt + 1
                )
            return driver

        except Exception as e:
            attempt += 1
            if attempt == 1:
                # First failure — likely Aura pause
                logger.warning(
                    "Neo4j connection failed. "
                    "If using Aura Free, the instance may be paused. "
                    "Resume at console.neo4j.io — "
                    "retrying every %ds for up to 10 minutes...",
                    wait_seconds
                )
                print(
                    "\n⚠️  MAIHERA: Boss, Neo4j is not responding. "
                    "If your Aura instance is paused, resume it at "
                    "console.neo4j.io — I will keep retrying.\n"
                )

            if attempt >= max_attempts:
                logger.critical(
                    "Neo4j unreachable after %d attempts (%d minutes). "
                    "Last error: %s",
                    max_attempts,
                    (max_attempts * wait_seconds) // 60,
                    e
                )
                raise RuntimeError(
                    "Boss, Neo4j is still unreachable after 10 minutes. "
                    "Please resume the instance at console.neo4j.io "
                    "and restart MAIHERA."
                ) from e

            logger.info(
                "Retry %d/%d in %ds...",
                attempt, max_attempts, wait_seconds
            )
            time.sleep(wait_seconds)


def get_brain_service():
    """
    Factory function — creates and returns a fully
    initialized BrainService instance.
    Uses retry logic for Neo4j connection.
    Use this in FastAPI lifespan and tests.
    """
    from brain.vector_store import VectorStore
    from brain.sqlite_store import DatabaseManager

    driver = get_driver_with_retry()

    vector_store = VectorStore()
    vector_store.initialize()

    db_manager = DatabaseManager()
    db_manager.initialize()

    return BrainService(driver, vector_store, db_manager), driver


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    print("Testing MAIHERA BrainService...")
    brain, driver = get_brain_service()

    try:
        # Test 1: Create a node
        print("\n[1] Creating test node...")
        from brain.schema import NodeSchema, NodeType, NodeSource
        node = NodeSchema(
            type=NodeType.TASK,
            label="BrainService test task",
            description=(
                "A test task to verify the BrainService "
                "creates nodes correctly in Neo4j and ChromaDB"
            ),
            source=NodeSource.MANUAL,
            importance=0.7,
            attention=0.8
        )
        node_id = brain.create_node(node)
        print(f"   Node created: {node_id}")

        # Test 2: Get the node back
        print("\n[2] Retrieving node...")
        retrieved = brain.get_node(node_id)
        assert retrieved is not None, "Node not found"
        assert retrieved['label'] == "BrainService test task"
        print(f"   Retrieved: {retrieved['label']}")

        # Test 3: Update signal
        print("\n[3] Updating attention signal...")
        brain.update_signal(node_id, 'attention', 0.9)
        updated = brain.get_node(node_id)
        assert abs(updated['attention'] - 0.9) < 0.001
        print(f"   Attention updated to: {updated['attention']}")

        # Test 4: Create an edge
        print("\n[4] Creating a second node and edge...")
        node2 = NodeSchema(
            type=NodeType.IDEA,
            label="Related idea node",
            description="An idea that relates to the test task",
            source=NodeSource.MANUAL,
            importance=0.5,
            attention=0.4
        )
        node2_id = brain.create_node(node2)
        brain.create_edge(node_id, node2_id, 'RELATES_TO')
        edges = brain.get_edges(node_id, direction='out')
        assert len(edges) > 0
        print(f"   Edge created. Edges from node: {len(edges)}")

        # Test 5: Decay
        print("\n[5] Testing signal decay...")
        changes = brain.apply_decay(node_id, hours_elapsed=24.0)
        print(f"   Decay changes: {changes}")
        decayed = brain.get_node(node_id)
        assert decayed['attention'] < 0.9, "Attention should decay"
        assert decayed['attention'] >= 0.05, "Should not go below floor"
        print(f"   Attention after 24h decay: {decayed['attention']:.4f}")

        # Test 6: Urgency
        print("\n[6] Computing urgency...")
        urgency = brain.compute_urgency(node_id)
        assert 0.0 <= urgency <= 1.0
        print(f"   Urgency: {urgency}")

        # Test 7: Graph query
        print("\n[7] Getting full graph...")
        graph = brain.get_full_graph()
        print(f"   Nodes: {len(graph['nodes'])}, "
              f"Edges: {len(graph['edges'])}")

        # Test 8: Semantic search
        print("\n[8] Semantic search...")
        results = brain.search_nodes("test task verification")
        print(f"   Search results: {len(results)}")
        if results:
            print(f"   Top result: {results[0]['label']}")

        # Test 9: Stats
        print("\n[9] Brain stats...")
        stats = brain.get_stats()
        print(f"   Stats: {stats}")

        # Cleanup test nodes
        print("\n[Cleanup] Removing test nodes...")
        with driver.session() as session:
            session.run("""
                MATCH (n:Node)
                WHERE n.label IN [
                    'BrainService test task',
                    'Related idea node'
                ]
                DETACH DELETE n
            """)
        print("   Test nodes removed.")

        print("\n✅ BrainService test PASSED — all 9 checks OK")

    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        raise
    finally:
        driver.close()