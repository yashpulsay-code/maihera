"""
MAIHERA System Observer Worker
Async consumer that drains ContextEvents from the observer queue.
Writes behavioral signals to the brain graph.
Runs in the FastAPI event loop — no threading needed here.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# How long (seconds) a dwell event must be to spike attention
DWELL_MIN_SECONDS = 120

# Attention spike values by context
ATTENTION_SPIKE = {
    "coding":   0.75,
    "design":   0.75,
    "browsing": 0.45,
    "general":  0.30,
}

# How much to boost attention on focus_gained (lighter than dwell)
FOCUS_GAINED_BOOST = 0.15


class SystemObserverWorker:
    """
    Consumes ContextEvents from the system observer queue.
    Translates behavioral signals into brain graph updates.

    Three event types handled:
    - focus_gained: Yash switched to a whitelisted app
    - dwell: Yash has been in the same app for 2+ minutes
    - focus_lost: Yash left a whitelisted app

    Signal writes:
    - dwell in coding/design context → spike attention on
      matching project nodes
    - focus_lost after long dwell → update last_active on
      self node
    - All events → update current_context on self node
    """

    def __init__(self, event_queue: asyncio.Queue, brain_service):
        self._queue = event_queue
        self._brain = brain_service
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Track session-level context
        self._current_context: Optional[str] = None
        self._current_label: Optional[str] = None
        self._session_start: Optional[str] = None

        logger.info("SystemObserverWorker initialized.")

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Schedule the consumer coroutine on the running event loop."""
        self._running = True
        self._task = asyncio.create_task(
            self._consume_loop(),
            name="SystemObserverWorker"
        )
        logger.info("SystemObserverWorker started.")

    def stop(self) -> None:
        """Cancel the consumer task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("SystemObserverWorker stopped.")

    # ── Consumer Loop ─────────────────────────────────────────────

    async def _consume_loop(self) -> None:
        """Drain events from the queue as they arrive."""
        logger.info("SystemObserverWorker: consumer loop running.")
        while self._running:
            try:
                # Wait up to 5s for an event then loop
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
                await self._handle_event(event)
                self._queue.task_done()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info(
                    "SystemObserverWorker: consumer cancelled."
                )
                break
            except Exception as e:
                logger.error(
                    "SystemObserverWorker: error handling event: %s", e
                )

    # ── Event Handling ────────────────────────────────────────────

    async def _handle_event(self, event) -> None:
        """Route event to the correct handler."""
        logger.debug(
            "ObserverWorker: %s — %s (%s)",
            event.event_type, event.process_label, event.context
        )

        if event.event_type == "focus_gained":
            await self._on_focus_gained(event)
        elif event.event_type == "dwell":
            await self._on_dwell(event)
        elif event.event_type == "focus_lost":
            await self._on_focus_lost(event)

    async def _on_focus_gained(self, event) -> None:
        """
        Yash switched to a whitelisted app.
        Update self node current context.
        Light attention boost on matching project nodes.
        """
        self._current_context = event.context
        self._current_label   = event.process_label
        self._session_start   = event.timestamp

        # Update self node with current context
        self._update_self_context(event.context, event.process_label)

        # Light attention boost on projects matching this context
        if event.context in ("coding", "design"):
            await self._boost_project_attention(
                context=event.context,
                boost=FOCUS_GAINED_BOOST,
                source_label=event.process_label
            )

    async def _on_dwell(self, event) -> None:
        """
        Yash has been in the same app for 2+ minutes.
        Stronger attention spike on matching project nodes.
        This is the primary 'active work' signal.
        """
        if event.dwell_seconds < DWELL_MIN_SECONDS:
            return

        spike = ATTENTION_SPIKE.get(event.context, 0.30)

        if event.context in ("coding", "design"):
            await self._boost_project_attention(
                context=event.context,
                boost=spike,
                source_label=event.process_label
            )
            logger.info(
                "ObserverWorker: dwell signal — %s context, "
                "attention spike %.2f on matching projects.",
                event.context, spike
            )

    async def _on_focus_lost(self, event) -> None:
        """
        Yash left a whitelisted app.
        Update self node last_active timestamp.
        Record session duration for pattern learning.
        """
        self._update_self_last_active(
            context=event.context,
            dwell_seconds=event.dwell_seconds
        )

        if event.dwell_seconds >= DWELL_MIN_SECONDS:
            logger.info(
                "ObserverWorker: focus_lost after %.0fs in %s.",
                event.dwell_seconds, event.process_label
            )

        self._current_context = None
        self._current_label   = None

    # ── Brain Writes ──────────────────────────────────────────────

    def _update_self_context(
        self, context: str, label: str
    ) -> None:
        """Write current activity context to the self node."""
        try:
            with self._brain.driver.session() as session:
                session.run("""
                    MATCH (n:Node {type: 'self'})
                    SET n.current_context = $context,
                        n.current_app     = $label,
                        n.last_touched    = $now
                """,
                    context=context,
                    label=label,
                    now=datetime.utcnow().isoformat()
                )
        except Exception as e:
            logger.error(
                "ObserverWorker: failed to update self context: %s", e
            )

    def _update_self_last_active(
        self, context: str, dwell_seconds: float
    ) -> None:
        """Update last_active and session log on self node."""
        try:
            with self._brain.driver.session() as session:
                session.run("""
                    MATCH (n:Node {type: 'self'})
                    SET n.last_active   = $now,
                        n.last_context  = $context,
                        n.last_touched  = $now
                """,
                    now=datetime.utcnow().isoformat(),
                    context=context
                )
        except Exception as e:
            logger.error(
                "ObserverWorker: failed to update self last_active: %s",
                e
            )

    async def _boost_project_attention(
        self,
        context: str,
        boost: float,
        source_label: str
    ) -> None:
        """
        Boost attention on active project nodes that match
        the current work context.

        Context mapping:
        - coding  → MAIHERA project (active build)
        - design  → Presence project (UI/design work)
        - both    → both projects get a lighter boost

        Attention is clamped to 1.0. Never decays below floor.
        """
        try:
            projects = self._brain.list_nodes(
                node_type="project", status="active"
            )

            for project in projects:
                label_lower = project.get("label", "").lower()
                project_id  = project.get("id")
                if not project_id:
                    continue

                # Determine if this project matches the context
                is_match = False
                if context == "coding" and "maihera" in label_lower:
                    is_match = True
                elif context == "design" and "presence" in label_lower:
                    is_match = True
                elif context == "browsing":
                    # Browsing gets a light boost on both — research signal
                    boost = min(boost, 0.15)
                    is_match = True

                if not is_match:
                    continue

                # Read current attention — live from Neo4j
                node = self._brain.get_node(project_id)
                if not node:
                    continue

                current = float(node.get("attention", 0.0))
                new_val = min(1.0, current + boost)

                self._brain.update_signal(
                    project_id, "attention", new_val
                )
                logger.debug(
                    "ObserverWorker: attention %s → %.3f (via %s, +%.2f)",
                    project.get("label"), new_val, source_label, boost
                )

        except Exception as e:
            logger.error(
                "ObserverWorker: attention boost failed: %s", e
            )

    # ── State Access ──────────────────────────────────────────────

    @property
    def current_context(self) -> Optional[str]:
        """Current detected work context — coding | design | browsing | None."""
        return self._current_context

    @property
    def current_label(self) -> Optional[str]:
        """Current whitelisted app label."""
        return self._current_label