"""
MAIHERA Nudge Service
Evaluates brain graph on a schedule and fires proactive
speech when signal thresholds are breached.
Respects focus mode, energy level, and office hours.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)

# Nudge thresholds
URGENCY_THRESHOLD = 0.7
ATTENTION_THRESHOLD = 0.6
RESISTANCE_THRESHOLD = 0.5
MIN_HOURS_BETWEEN_NUDGES = 2.0

# Low energy mode — set externally when energy <= 3
low_energy_mode: bool = False


class NudgeService:
    """
    Evaluates the brain graph every 5 minutes.
    Fires proactive speech via VoiceService when nodes
    breach signal thresholds.

    Respects:
    - Focus mode (queues to SQLite instead of speaking)
    - Low energy mode (doubles nudge interval)
    - System status (no nudges during dream or speaking)
    - Office hours (no personal project nudges 11am-7:30pm)
    - last_surfaced timestamp (prevents repeated nudging)
    """

    def __init__(self, brain_service, voice_service, db_manager):
        self._brain = brain_service
        self._voice = voice_service
        self._db = db_manager
        self._ws_manager = None
        self._llm_router = None
        self._current_status = "watching"
        logger.info("NudgeService initialized.")

    def set_ws_manager(self, ws_manager) -> None:
        self._ws_manager = ws_manager

    def set_llm_router(self, llm_router) -> None:
        self._llm_router = llm_router

    def set_status(self, status: str) -> None:
        """Called by other services to inform nudge engine of state."""
        self._current_status = status

    # ── Core Evaluation ───────────────────────────────────────────

    async def evaluate(self) -> None:
        """
        Main evaluation loop — called every 5 minutes by scheduler.
        Checks all active nodes against signal thresholds.
        """
        logger.debug("NudgeService: evaluating brain graph...")

        # Skip if MAIHERA is already speaking or in dream mode
        if self._current_status in ("speaking", "dream"):
            logger.debug("NudgeService: skipping — status is %s",
                         self._current_status)
            return

        try:
            nodes = self._brain.list_nodes(status="active")
        except Exception as e:
            logger.error("NudgeService: failed to list nodes: %s", e)
            return

        qualifying = []
        for node in nodes:
            try:
                urgency = self._brain.compute_urgency(node["id"])
                attention = float(node.get("attention", 0.0))
                resistance = float(node.get("resistance", 0.0))

                qualifies_urgency = urgency >= URGENCY_THRESHOLD
                qualifies_resistance = (
                    attention >= ATTENTION_THRESHOLD
                    and resistance >= RESISTANCE_THRESHOLD
                )

                if qualifies_urgency or qualifies_resistance:
                    node["_urgency"] = urgency
                    qualifying.append(node)

            except Exception as e:
                logger.warning(
                    "NudgeService: error evaluating node %s: %s",
                    node.get("id"), e
                )

        if not qualifying:
            logger.debug("NudgeService: no qualifying nodes.")
            return

        # Sort urgent first
        qualifying.sort(key=lambda n: n["_urgency"], reverse=True)
        logger.info(
            "NudgeService: %d qualifying nodes found.",
            len(qualifying)
        )

        for node in qualifying:
            await self._process_node(node)

    async def _process_node(self, node: dict) -> None:
        """Decide whether to nudge, queue, or skip for one node."""
        node_id = node["id"]
        node_label = node.get("label", "unknown")

        # Check last_surfaced — skip if nudged recently
        if not self._should_surface(node):
            return

        # Check office hours for personal workspace nodes
        if self._is_office_hours() and node.get("workspace") == "personal":
            logger.debug(
                "NudgeService: skipping personal node during office hours: %s",
                node_label
            )
            return

        # Generate nudge text via LLM
        nudge_text = await self._generate_nudge(node)
        if not nudge_text:
            return

        priority = "urgent" if node["_urgency"] >= URGENCY_THRESHOLD else "normal"

        nudge_dict = {
            "id": str(uuid.uuid4()),
            "text": nudge_text,
            "node_ids": [node_id],
            "priority": priority,
            "suppressed_at": datetime.now(timezone.utc).isoformat()
        }

        # Check if focus session is active
        active_focus = self._db.get_active_focus_session()
        if active_focus:
            self._db.append_nudge_to_session(
                session_id=active_focus["id"],
                nudge=nudge_dict
            )
            logger.info(
                "NudgeService: queued nudge to focus session for: %s",
                node_label
            )
            # Update frontend nudge queue display
            if self._ws_manager:
                session = self._db.get_active_focus_session()
                if session:
                    import json
                    pending = json.loads(
                        session.get("pending_nudges", "[]")
                    )
                    await self._ws_manager.send_nudge_queue_update(pending)
            return

        # No focus session — speak now
        await self._voice.enqueue_speech(
            text=nudge_text,
            node_ids=[node_id],
            priority=priority
        )

        # Update last_surfaced on node
        self._brain.update_node(
            node_id,
            {"last_surfaced": datetime.utcnow().isoformat()}
        )

        logger.info(
            "NudgeService: nudge fired for node: %s [%s]",
            node_label, priority
        )

    def _should_surface(self, node: dict) -> bool:
        """
        Returns True if enough time has passed since last nudge.
        Doubles interval in low energy mode.
        """
        last_surfaced = node.get("last_surfaced")
        if not last_surfaced:
            return True

        try:
            last = datetime.fromisoformat(last_surfaced)
            now = datetime.utcnow()
            hours_since = (now - last).total_seconds() / 3600

            min_hours = MIN_HOURS_BETWEEN_NUDGES
            if low_energy_mode:
                min_hours *= 2

            return hours_since >= min_hours

        except (ValueError, TypeError):
            return True

    def _is_office_hours(self) -> bool:
        """
        Returns True if current time is within office hours.
        Mon-Fri 11:00 AM - 7:30 PM IST (UTC+5:30).
        """
        now_utc = datetime.now(timezone.utc)
        # IST offset: +5:30
        ist_hour = (now_utc.hour + 5) % 24
        ist_minute = (now_utc.minute + 30) % 60
        if now_utc.minute + 30 >= 60:
            ist_hour = (ist_hour + 1) % 24

        ist_time = ist_hour + ist_minute / 60
        weekday = now_utc.weekday()  # 0=Mon, 6=Sun

        is_weekday = weekday < 5
        is_work_hours = 11.0 <= ist_time <= 19.5
        return is_weekday and is_work_hours

    async def _generate_nudge(self, node: dict) -> Optional[str]:
        """
        Generate natural language nudge via LLM router.
        Falls back to a template string if LLM fails.
        """
        node_label = node.get("label", "a task")
        resistance_reason = node.get("resistance_reason", "")
        last_touched = node.get("last_touched", "")

        # Relative time string for prompt
        time_str = ""
        if last_touched:
            try:
                last = datetime.fromisoformat(last_touched)
                hours = (datetime.utcnow() - last).total_seconds() / 3600
                if hours < 1:
                    time_str = "less than an hour ago"
                elif hours < 24:
                    time_str = f"{int(hours)} hours ago"
                else:
                    time_str = f"{int(hours / 24)} days ago"
            except (ValueError, TypeError):
                time_str = "recently"

        prompt = (
            f"You are MAIHERA, a proactive AI secretary. "
            f"Generate a single short nudge for Boss about this node. "
            f"Be direct and warm. Address him as Boss. "
            f"Maximum 2 sentences. No preamble. "
            f"Node: '{node_label}'. "
            f"Last touched: {time_str}. "
            f"Resistance reason: {resistance_reason or 'none'}. "
            f"Output only the nudge text, nothing else."
        )

        if self._llm_router:
            try:
                response = await self._llm_router.route(
                    task_type="conversation",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=80
                )
                if response and response.strip():
                    return response.strip()
            except Exception as e:
                logger.warning(
                    "NudgeService: LLM nudge generation failed: %s", e
                )

        # Fallback template
        return (
            f"Boss, '{node_label}' has been sitting idle "
            f"{'for ' + time_str if time_str else 'for a while'}. "
            f"Worth a look?"
        )

    # ── Focus Session Delivery ────────────────────────────────────

    async def deliver_focus_session_summary(
        self,
        session_id: str
    ) -> None:
        """
        Called when focus mode ends.
        Reads queued nudges, delivers them sequentially by voice.
        """
        nudges = self._db.end_focus_session(session_id)

        if not nudges:
            await self._voice.enqueue_speech(
                text="Focus session complete, Boss. Nothing urgent came in.",
                node_ids=[],
                priority="normal"
            )
            return

        count = len(nudges)
        intro = (
            f"Focus session complete, Boss. "
            f"{count} item{'s' if count > 1 else ''} came in while you were focused."
        )
        await self._voice.enqueue_speech(
            text=intro,
            node_ids=[],
            priority="normal"
        )

        # Small gap before items
        await asyncio.sleep(0.5)

        for nudge in nudges:
            await self._voice.enqueue_speech(
                text=nudge["text"],
                node_ids=nudge.get("node_ids", []),
                priority=nudge.get("priority", "normal")
            )
            await asyncio.sleep(0.3)

        logger.info(
            "NudgeService: delivered %d focus session nudges.",
            count
        )

    # ── Morning Briefing ──────────────────────────────────────────

    async def trigger_morning_briefing(self) -> None:
        """
        Deliver the morning briefing if not already done today.
        Triggered on session_start WebSocket message.
        """
        if self._db.briefing_delivered_today():
            logger.info(
                "NudgeService: briefing already delivered today."
            )
            return

        logger.info("NudgeService: starting morning briefing...")

        if self._ws_manager:
            await self._ws_manager.send_briefing_start()

        segments = await self._build_briefing_segments()

        # Collect all segments into one display message
        full_briefing_text = " ".join(s["text"] for s in segments)
        all_node_ids = list(set(
            nid for s in segments for nid in s["node_ids"]
        ))

        # One chat message for the entire briefing
        if self._ws_manager:
            await self._ws_manager.send_maihera_speak(
                text=full_briefing_text,
                node_ids=all_node_ids,
                priority="urgent"
            )
            await self._ws_manager.send_briefing_start()

        # Speak each segment sequentially — voice only, no extra chat messages
        for segment in segments:
            await self._voice.enqueue_speech(
                text=segment["text"],
                node_ids=segment["node_ids"],
                priority="urgent",
                silent=True
            )

        if self._ws_manager:
            await self._ws_manager.send_briefing_end()

        if self._ws_manager:
            await self._ws_manager.send_briefing_end()

        self._db.log_briefing_delivered(
            segment_count=len(segments),
            completed=True
        )
        logger.info(
            "NudgeService: morning briefing complete (%d segments).",
            len(segments)
        )

    async def _build_briefing_segments(self) -> list[dict]:
        """Build the ordered list of briefing segments."""
        segments = []
        now = datetime.now(timezone.utc)

        # Segment 0 — Greeting
        day = now.strftime("%A")
        date_str = now.strftime("%-d %B") if os.name != "nt" else now.strftime("%d %B").lstrip("0")
        greeting = (
            f"Good morning Boss. It's {day}, {date_str}. "
            f"I'm online and watching."
        )
        segments.append({"text": greeting, "node_ids": []})

        # Segment 1 — High signal nodes
        try:
            high_signal = self._brain.get_high_signal_nodes(
                importance_threshold=0.5,
                attention_threshold=0.3
            )[:3]

            if high_signal:
                node_ids = [n["id"] for n in high_signal]
                labels = [n["label"] for n in high_signal]

                if len(labels) == 1:
                    node_text = f"'{labels[0]}'"
                elif len(labels) == 2:
                    node_text = f"'{labels[0]}' and '{labels[1]}'"
                else:
                    node_text = (
                        f"'{labels[0]}', '{labels[1]}', "
                        f"and '{labels[2]}'"
                    )

                signal_text = (
                    f"Your top items today are {node_text}. "
                    f"I'll surface more context as the day develops."
                )
                segments.append({
                    "text": signal_text,
                    "node_ids": node_ids
                })
            else:
                segments.append({
                    "text": "Your brain graph is quiet this morning. Good time to load something new.",
                    "node_ids": []
                })

        except Exception as e:
            logger.warning("Briefing: failed to get high signal nodes: %s", e)

        # Segment 2 — Energy check-in (always last)
        segments.append({
            "text": "Before we begin — energy level today, Boss? One to ten.",
            "node_ids": []
        })

        return segments