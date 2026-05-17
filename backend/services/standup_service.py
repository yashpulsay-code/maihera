"""
MAIHERA Standup Service
Daily structured check-in after morning briefing.
Three questions — answers feed brain as task and blocker updates.
Skipped on Sunday (weekly review takes its place).
Runs once per day, tracked via SQLite.
"""

import sys
import json
import logging
from datetime import datetime, date, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# SQLite key for standup tracking
KEY_LAST_STANDUP = "standup_last_date"
KEY_STANDUP_STATE = "standup_state"  # tracks which question we're on

STANDUP_QUESTIONS = [
    "What did you finish yesterday, Boss?",
    "What are you working on today?",
    "What's blocking you, if anything?",
]


class StandupService:
    """
    Manages the daily standup conversation flow.
    State persisted to SQLite so a restart mid-standup
    doesn't lose context.
    """

    def should_run_today(self, brain_service) -> bool:
        """
        Return True if standup should run today.
        - Not on Sunday (weekly review takes over)
        - Not if already completed today
        """
        today = date.today()

        # Skip Sunday
        if today.weekday() == 6:
            logger.debug("StandupService: Sunday — skipping standup.")
            return False

        last = brain_service.db.get_drip_state(KEY_LAST_STANDUP)
        if last == today.isoformat():
            logger.debug("StandupService: standup already done today.")
            return False

        return True

    def get_first_question(self) -> str:
        """Return the first standup question."""
        return STANDUP_QUESTIONS[0]

    def get_next_question(
        self,
        brain_service,
        current_index: int
    ) -> str | None:
        """
        Return next question or None if standup is complete.
        current_index is 0-based index of the question just answered.
        """
        next_index = current_index + 1
        if next_index >= len(STANDUP_QUESTIONS):
            return None
        return STANDUP_QUESTIONS[next_index]

    async def process_answer(
        self,
        brain_service,
        llm_router,
        question_index: int,
        answer: str
    ) -> dict:
        """
        Process a standup answer and update the brain.
        question_index: 0 = yesterday, 1 = today, 2 = blockers

        Returns {"nodes_created": N, "nodes_updated": N, "summary": str}
        """
        if question_index == 0:
            return await self._process_yesterday(
                brain_service, llm_router, answer
            )
        elif question_index == 1:
            return await self._process_today(
                brain_service, llm_router, answer
            )
        elif question_index == 2:
            return await self._process_blockers(
                brain_service, llm_router, answer
            )
        return {"nodes_created": 0, "nodes_updated": 0, "summary": ""}

    async def _process_yesterday(
        self,
        brain_service,
        llm_router,
        answer: str
    ) -> dict:
        """
        Process 'what did you finish yesterday'.
        Marks matching task nodes as completed.
        """
        if not answer.strip() or answer.lower() in [
            'nothing', 'not much', 'n/a', 'none'
        ]:
            return {
                "nodes_created": 0,
                "nodes_updated": 0,
                "summary": "Nothing completed yesterday."
            }

        # Extract completed items via LLM
        items = await self._extract_items(llm_router, answer, "completed")
        updated = 0

        for item in items:
            # Search for matching task node
            results = brain_service.search_nodes(query=item)
            for node in results[:1]:  # top match only
                if node.get('type') == 'task':
                    brain_service.update_node(
                        node['id'],
                        {'status': 'completed'}
                    )
                    updated += 1
                    logger.info(
                        "Standup: marked completed — %s", node['label']
                    )
                    break

        return {
            "nodes_created": 0,
            "nodes_updated": updated,
            "summary": f"Marked {updated} task(s) complete."
        }

    async def _process_today(
        self,
        brain_service,
        llm_router,
        answer: str
    ) -> dict:
        """
        Process 'what are you working on today'.
        Spikes attention on matching nodes or creates new task nodes.
        """
        if not answer.strip() or answer.lower() in [
            'nothing', 'not sure', 'n/a'
        ]:
            return {
                "nodes_created": 0,
                "nodes_updated": 0,
                "summary": "No tasks logged for today."
            }

        items = await self._extract_items(llm_router, answer, "today's tasks")
        created = 0
        updated = 0

        for item in items:
            results = brain_service.search_nodes(query=item)
            matched = False

            for node in results[:1]:
                similarity = 1.0 - node.get('_search_distance', 1.0)
                if similarity > 0.75:
                    # Spike attention on existing node
                    brain_service.update_node_signals(
                        node_id=node['id'],
                        attention=min(1.0, node.get('attention', 0.5) + 0.3)
                    )
                    updated += 1
                    matched = True
                    logger.info(
                        "Standup: attention spiked — %s", node['label']
                    )
                    break

            if not matched:
                # Create new task node
                from brain.schema import NodeSchema, NodeType, NodeSource
                from brain.signal_defaults import get_defaults
                defaults = get_defaults(NodeSource.MANUAL)
                node = NodeSchema(
                    type        = NodeType.TASK,
                    label       = item[:80],
                    description = f"Task added via daily standup: {item}",
                    source      = NodeSource.MANUAL,
                    importance  = defaults['importance'],
                    attention   = 0.9,  # high — just committed to this today
                    node_weight = defaults['node_weight'],
                )
                brain_service.create_node(node)
                created += 1
                logger.info("Standup: new task created — %s", item)

        return {
            "nodes_created": created,
            "nodes_updated": updated,
            "summary": (
                f"Logged {created} new task(s), "
                f"updated {updated} existing task(s)."
            )
        }

    async def _process_blockers(
        self,
        brain_service,
        llm_router,
        answer: str
    ) -> dict:
        """
        Process 'what's blocking you'.
        Creates blocker nodes or resistance edges.
        """
        if not answer.strip() or answer.lower() in [
            'nothing', 'no', 'nope', 'none', 'n/a', 'not blocked'
        ]:
            logger.info("Standup: no blockers reported.")
            return {
                "nodes_created": 0,
                "nodes_updated": 0,
                "summary": "No blockers today."
            }

        items = await self._extract_items(llm_router, answer, "blockers")
        created = 0

        for item in items:
            from brain.schema import NodeSchema, NodeType, NodeSource, NodeStatus
            from brain.signal_defaults import get_defaults
            defaults = get_defaults(NodeSource.MANUAL)
            node = NodeSchema(
                type        = NodeType.BLOCKER,
                label       = item[:80],
                description = f"Blocker reported in standup: {item}",
                source      = NodeSource.MANUAL,
                status      = NodeStatus.ACTIVE,
                importance  = 0.7,
                attention   = 0.9,
                node_weight = defaults['node_weight'],
            )
            brain_service.create_node(node)
            created += 1
            logger.info("Standup: blocker created — %s", item)

        return {
            "nodes_created": created,
            "nodes_updated": 0,
            "summary": f"Logged {created} blocker(s)."
        }

    async def _extract_items(
        self,
        llm_router,
        answer: str,
        context: str
    ) -> list[str]:
        """
        Extract discrete items from a freeform standup answer.
        Returns list of short item strings.
        """
        prompt = (
            f"Extract discrete {context} from this standup answer. "
            f"Return ONLY a JSON array of short strings (under 80 chars each). "
            f"No markdown, no preamble. Max 5 items.\n\n"
            f"Answer: {answer}"
        )
        try:
            response = await llm_router.route(
                task_type='classification',
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200
            )
            response = response.strip()
            start = response.find('[')
            end   = response.rfind(']')
            if start != -1 and end != -1:
                items = json.loads(response[start:end + 1])
                return [str(i).strip() for i in items if i]
        except Exception as e:
            logger.warning(
                "StandupService: item extraction failed: %s", e
            )
            # Fallback — treat whole answer as one item
            return [answer.strip()[:80]]
        return []

    def mark_complete(self, brain_service) -> None:
        """Mark standup as complete for today."""
        brain_service.db.set_drip_state(
            KEY_LAST_STANDUP,
            date.today().isoformat()
        )
        logger.info("StandupService: standup complete for today.")

    def get_status(self, brain_service) -> dict:
        """Return standup status for today."""
        last = brain_service.db.get_drip_state(KEY_LAST_STANDUP)
        today = date.today().isoformat()
        return {
            "completed_today": last == today,
            "last_standup":    last,
            "should_run":      self.should_run_today(brain_service),
        }


# Module-level singleton
standup_service = StandupService()