"""
MAIHERA Avoidance Detector
Runs every 30 minutes via APScheduler.
Applies the 6-condition decision tree to identify tasks
Yash is avoiding and writes resistance edges to the brain.

Decision tree (all conditions must be met):
  1. Node status = active
  2. last_touched > avoidance_threshold_hours ago
  3. workspace = personal
  4. No existing resistance edge with reason = external or blocked
  5. last_surfaced is None OR last_surfaced > 24h ago
  6. Positive Yash-attributed activity confirmed via observer
     (whitelisted app was active in the last 48h)
     AND no matching project context detected
     (i.e. Yash was working but not on this)

Resistance reason mapping:
  - No whitelisted app activity at all → do not fire
  - Activity detected but not on this project → avoidant
  - Node has no clear definition → unclear
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "observer_config.json"


class AvoidanceDetector:
    """
    Evaluates all active personal-workspace task nodes
    and writes resistance edges for those meeting avoidance criteria.

    Wired into APScheduler in the lifespan — runs every 30 minutes.
    Requires access to brain_service and the SQLite activity log.
    """

    def __init__(self, brain_service, db_manager):
        self._brain = brain_service
        self._db = db_manager
        self._threshold_hours: float = 48.0
        self._load_config()
        logger.info("AvoidanceDetector initialized.")

    # ── Config ────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Load avoidance_threshold_hours from observer_config.json."""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            self._threshold_hours = float(
                config.get("avoidance_threshold_hours", 48.0)
            )
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            self._threshold_hours = 48.0

    # ── Main Entry ────────────────────────────────────────────────

    async def evaluate(self) -> None:
        """
        Main evaluation — called every 30 minutes by APScheduler.
        Scans all active personal-workspace nodes and applies
        the 6-condition decision tree.
        """
        logger.debug("AvoidanceDetector: evaluating...")
        self._load_config()

        try:
            nodes = self._brain.list_nodes(status="active")
        except Exception as e:
            logger.error("AvoidanceDetector: failed to list nodes: %s", e)
            return

        # Filter to personal workspace task/feature/issue nodes only
        candidates = [
            n for n in nodes
            if n.get("workspace") == "personal"
            and n.get("type") in (
                "task", "feature", "issue", "question"
            )
        ]

        if not candidates:
            logger.debug("AvoidanceDetector: no personal candidates.")
            return

        logger.debug(
            "AvoidanceDetector: %d personal candidates.", len(candidates)
        )

        # Check if Yash has been active in the threshold window
        yash_was_active = self._was_yash_active_recently()

        if not yash_was_active:
            logger.debug(
                "AvoidanceDetector: no confirmed Yash activity "
                "in last %dh — skipping all avoidance checks.",
                int(self._threshold_hours)
            )
            return

        fired = 0
        for node in candidates:
            try:
                did_fire = await self._evaluate_node(node)
                if did_fire:
                    fired += 1
            except Exception as e:
                logger.error(
                    "AvoidanceDetector: error on node %s: %s",
                    node.get("id"), e
                )

        if fired:
            logger.info(
                "AvoidanceDetector: %d resistance edge(s) written.", fired
            )

    # ── Node Evaluation ───────────────────────────────────────────

    async def _evaluate_node(self, node: dict) -> bool:
        """
        Apply the 6-condition decision tree to one node.
        Returns True if a resistance edge was written.
        """
        node_id    = node.get("id")
        node_label = node.get("label", "unknown")

        # Condition 1 — active status (already filtered above)

        # Condition 2 — last_touched older than threshold
        if not self._is_stale(node):
            return False

        # Condition 3 — personal workspace (already filtered above)

        # Condition 4 — no existing blocking resistance edge
        if self._has_blocking_resistance(node_id):
            logger.debug(
                "AvoidanceDetector: skipping %s — "
                "existing blocked/external resistance.",
                node_label
            )
            return False

        # Condition 5 — not surfaced recently
        if not self._can_resurface(node):
            logger.debug(
                "AvoidanceDetector: skipping %s — "
                "surfaced within last 24h.",
                node_label
            )
            return False

        # Condition 6 — Yash was active but not on this project
        reason = self._determine_resistance_reason(node)
        if reason is None:
            return False

        # All conditions met — write resistance edge
        self._write_resistance_edge(node_id, node_label, reason)
        return True

    # ── Condition Checks ──────────────────────────────────────────

    def _is_stale(self, node: dict) -> bool:
        """Condition 2 — last_touched older than threshold."""
        last_touched = node.get("last_touched")
        if not last_touched:
            return True  # Never touched — definitely stale

        try:
            last = datetime.fromisoformat(last_touched)
            # Normalize to UTC if naive
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last).total_seconds() / 3600
            return hours_since >= self._threshold_hours
        except (ValueError, TypeError):
            return True

    def _has_blocking_resistance(self, node_id: str) -> bool:
        """
        Condition 4 — check for existing external or blocked
        resistance edges on this node.
        If one exists, avoidance detection should not override it.
        """
        try:
            edges = self._brain.get_edges(node_id, direction="in")
            for edge in edges:
                if edge.get("type") == "HAS_RESISTANCE":
                    props = edge.get("properties", {})
                    if props.get("reason") in ("external", "blocked"):
                        return True
        except Exception as e:
            logger.error(
                "AvoidanceDetector: edge check failed for %s: %s",
                node_id, e
            )
        return False

    def _can_resurface(self, node: dict) -> bool:
        """
        Condition 5 — last_surfaced is None or older than 24h.
        Prevents MAIHERA from nudging about the same node repeatedly.
        """
        last_surfaced = node.get("last_surfaced")
        if not last_surfaced:
            return True

        try:
            last = datetime.fromisoformat(last_surfaced)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_since = (now - last).total_seconds() / 3600
            return hours_since >= 24.0
        except (ValueError, TypeError):
            return True

    def _was_yash_active_recently(self) -> bool:
        """
        Condition 6a — confirms Yash was active on the laptop
        in the last threshold window by checking the self node's
        last_active field (written by the observer worker).
        """
        try:
            with self._brain.driver.session() as session:
                result = session.run("""
                    MATCH (n:Node {type: 'self'})
                    RETURN n.last_active as last_active,
                           n.last_context as last_context
                """)
                record = result.single()
                if not record or not record["last_active"]:
                    return False

                last_active = datetime.fromisoformat(
                    record["last_active"]
                )
                if last_active.tzinfo is None:
                    last_active = last_active.replace(
                        tzinfo=timezone.utc
                    )

                now = datetime.now(timezone.utc)
                hours_since = (
                    now - last_active
                ).total_seconds() / 3600

                return hours_since <= self._threshold_hours

        except Exception as e:
            logger.error(
                "AvoidanceDetector: self node check failed: %s", e
            )
            return False

    def _determine_resistance_reason(
        self, node: dict
    ) -> Optional[str]:
        """
        Condition 6b — determine WHY Yash is avoiding this node.
        Returns resistance reason string or None if should not fire.

        Logic:
        - Node description is empty or very short → unclear
        - Node belongs to a project where Yash has been active
          (observer detected matching context) → avoidant
        - Node belongs to a project with no recent activity → disengaged
        """
        description = node.get("description", "")
        if not description or len(description.strip()) < 20:
            return "unclear"

        # Check if Yash has been working on the parent project recently
        project_id = node.get("project_id")
        if project_id:
            project_active = self._was_project_active_recently(
                project_id
            )
            if project_active:
                # Working on the project but skipping this node
                return "avoidant"
            else:
                # Not working on the project at all
                return "disengaged"

        return "avoidant"

    def _was_project_active_recently(self, project_id: str) -> bool:
        """
        Check if the parent project node has been touched recently.
        Uses last_touched on the project node as a proxy for
        whether Yash has been actively working in that project space.
        Threshold: 24 hours (shorter than avoidance threshold).
        """
        try:
            project = self._brain.get_node(project_id)
            if not project:
                return False

            last_touched = project.get("last_touched")
            if not last_touched:
                return False

            last = datetime.fromisoformat(last_touched)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            hours_since = (now - last).total_seconds() / 3600
            return hours_since <= 24.0

        except Exception as e:
            logger.error(
                "AvoidanceDetector: project active check failed: %s",
                e
            )
            return False

    # ── Resistance Edge Write ─────────────────────────────────────

    def _write_resistance_edge(
        self,
        node_id: str,
        node_label: str,
        reason: str,
    ) -> None:
        """
        Write a HAS_RESISTANCE edge from the self node to the target.
        Removes any existing avoidance/disengaged/unclear edge first
        to prevent duplicate edges accumulating over time.
        """
        try:
            # Get self node id
            with self._brain.driver.session() as session:
                result = session.run("""
                    MATCH (n:Node {type: 'self'})
                    RETURN n.id as id
                """)
                record = result.single()
                if not record:
                    logger.error(
                        "AvoidanceDetector: self node not found."
                    )
                    return
                self_id = record["id"]

            # Remove stale avoidance edges for this node
            with self._brain.driver.session() as session:
                session.run("""
                    MATCH (s:Node {id: $self_id})
                          -[r:HAS_RESISTANCE]->
                          (t:Node {id: $target_id})
                    WHERE r.reason IN [
                        'avoidant', 'disengaged', 'unclear'
                    ]
                    DELETE r
                """, self_id=self_id, target_id=node_id)

            # Determine MAIHERA response from reason
            response_map = {
                "avoidant":   "push",
                "disengaged": "surface",
                "unclear":    "assist",
                "overwhelmed":"reframe",
                "blocked":    "assist",
                "external":   "hold",
            }
            mahera_response = response_map.get(reason, "surface")

            resistance_data = {
                "score":            0.65,
                "reason":           reason,
                "since":            datetime.utcnow().isoformat(),
                "source":           "behavioral",
                "evidence":         json.dumps([
                    "last_touched exceeded threshold",
                    "yash_active_confirmed",
                    f"reason_detected: {reason}",
                ]),
                "mahera_response":  mahera_response,
                "last_intervention":None,
                "trend":            "stable",
            }

            self._brain.create_resistance_edge(
                from_id=self_id,
                to_id=node_id,
                resistance_data=resistance_data,
            )

            logger.info(
                "AvoidanceDetector: resistance edge written — "
                "%s [reason=%s, response=%s]",
                node_label, reason, mahera_response
            )

        except Exception as e:
            logger.error(
                "AvoidanceDetector: failed to write resistance "
                "edge for %s: %s",
                node_label, e
            )