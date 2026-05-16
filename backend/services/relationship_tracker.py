"""
MAIHERA Relationship Tracker
Updates last_interacted timestamps on person nodes from
three sources: Calendar, GitHub, and Gmail.

Cold detection runs every 6 hours via APScheduler.
Two tiers:
  - frequent:   contacts seen weekly → cold after 14 days
  - occasional: contacts seen less often → cold after 45 days

Tier is inferred from interaction history after 4+ weeks of data.
Before that, all contacts default to occasional tier.

Unresponsive tracking is deferred to Phase 7.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import json

logger = logging.getLogger(__name__)

# Tier thresholds in days
COLD_THRESHOLD_FREQUENT   = 14
COLD_THRESHOLD_OCCASIONAL = 45

# Minimum interactions to classify as frequent
FREQUENT_MIN_INTERACTIONS = 4
# Minimum days of history before tier classification kicks in
TIER_CLASSIFICATION_MIN_DAYS = 28


class RelationshipTracker:
    """
    Tracks interaction recency for all person nodes.
    Writes cold_contact nudges when relationships go quiet.

    Sources that update last_interacted:
    - Calendar: event attendees
    - GitHub: PR reviewers, issue assignees, commit authors
    - Gmail: email senders (already handled by GmailReaderWorker —
      this service reads the result, not the source)

    Cold detection: runs every 6 hours, surfaces nudge for
    person nodes that have gone quiet beyond their tier threshold.
    """

    def __init__(self, brain_service, voice_service=None):
        self._brain  = brain_service
        self._voice  = voice_service
        self._ws_manager = None
        logger.info("RelationshipTracker initialized.")

    def set_voice_service(self, voice_service) -> None:
        self._voice = voice_service

    def set_ws_manager(self, ws_manager) -> None:
        self._ws_manager = ws_manager

    # ── Interaction Updates ───────────────────────────────────────

    def record_interaction(
        self,
        person_node_id: str,
        source: str,
        detail: str = "",
    ) -> None:
        """
        Update last_interacted and increment interaction_count
        on a person node.

        source: 'calendar' | 'github' | 'gmail'
        detail: brief description e.g. 'attended meeting X'
        """
        try:
            node = self._brain.get_node(person_node_id)
            if not node:
                return

            now = datetime.now(timezone.utc).isoformat()
            current_count = int(node.get("interaction_count", 0))

            self._brain.update_node(person_node_id, {
                "last_interacted":   now,
                "interaction_count": current_count + 1,
                "last_interaction_source": source,
                "last_interaction_detail": detail[:120],
            })

            logger.debug(
                "RelationshipTracker: interaction recorded — "
                "%s via %s.",
                node.get("label"), source
            )

        except Exception as e:
            logger.error(
                "RelationshipTracker: record_interaction failed: %s",
                e
            )

    def update_from_calendar_event(self, event_node: dict) -> None:
        """
        Called by CalendarWorker when a new event node is created.
        Finds attendee person nodes and records interactions.
        event_node: the calendar event node dict from Neo4j.
        """
        event_id    = event_node.get("id")
        event_label = event_node.get("label", "a meeting")
        if not event_id:
            return

        try:
            # Find person nodes linked to this event via ASSIGNED_TO
            # or RELATES_TO edges
            edges = self._brain.get_edges(event_id, direction="both")
            for edge in edges:
                other_id = (
                    edge["to_id"]
                    if edge["from_id"] == event_id
                    else edge["from_id"]
                )
                other_node = self._brain.get_node(other_id)
                if other_node and other_node.get("type") == "person":
                    self.record_interaction(
                        person_node_id=other_id,
                        source="calendar",
                        detail=f"attended {event_label}",
                    )

        except Exception as e:
            logger.error(
                "RelationshipTracker: calendar update failed: %s", e
            )

    def update_from_github_event(
        self,
        person_label: str,
        detail: str,
    ) -> None:
        """
        Called when a GitHub event involves a known person.
        Looks up the person node by label and records interaction.
        """
        try:
            persons = self._brain.list_nodes(node_type="person")
            for person in persons:
                if person.get("label", "").lower() == person_label.lower():
                    self.record_interaction(
                        person_node_id=person["id"],
                        source="github",
                        detail=detail,
                    )
                    return
        except Exception as e:
            logger.error(
                "RelationshipTracker: github update failed: %s", e
            )

    def update_from_gmail_event(self, person_node_id: str) -> None:
        """
        Called when GmailReaderWorker creates or updates a person node
        from an incoming email. Simply records the interaction.
        """
        self.record_interaction(
            person_node_id=person_node_id,
            source="gmail",
            detail="email received",
        )

    # ── Tier Classification ───────────────────────────────────────

    def _classify_tier(self, node: dict) -> str:
        """
        Classify a person node as 'frequent' or 'occasional'
        based on interaction history.

        Frequent: 4+ interactions AND node is older than 28 days.
        Before 28 days of history, everyone is occasional.
        """
        created_at = node.get("created_at")
        if created_at:
            try:
                created = datetime.fromisoformat(created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = (
                    datetime.now(timezone.utc) - created
                ).days
                if age_days < TIER_CLASSIFICATION_MIN_DAYS:
                    return "occasional"
            except (ValueError, TypeError):
                pass

        count = int(node.get("interaction_count", 0))
        if count >= FREQUENT_MIN_INTERACTIONS:
            return "frequent"
        return "occasional"

    def _cold_threshold_days(self, node: dict) -> int:
        """Return cold threshold in days for a person node."""
        tier = self._classify_tier(node)
        if tier == "frequent":
            return COLD_THRESHOLD_FREQUENT
        return COLD_THRESHOLD_OCCASIONAL

    # ── Cold Detection ────────────────────────────────────────────

    async def evaluate_cold_contacts(self) -> None:
        """
        Main cold detection evaluation.
        Called every 6 hours by APScheduler.
        Surfaces nudges for contacts that have gone quiet.
        """
        logger.debug("RelationshipTracker: evaluating cold contacts...")

        try:
            persons = self._brain.list_nodes(node_type="person")
        except Exception as e:
            logger.error(
                "RelationshipTracker: failed to list persons: %s", e
            )
            return

        # Exclude Yash himself
        persons = [
            p for p in persons
            if p.get("label", "").lower() not in ("yash", "self")
        ]

        cold_contacts = []
        for person in persons:
            try:
                if self._is_cold(person):
                    cold_contacts.append(person)
            except Exception as e:
                logger.error(
                    "RelationshipTracker: error checking %s: %s",
                    person.get("label"), e
                )

        if not cold_contacts:
            logger.debug("RelationshipTracker: no cold contacts.")
            return

        logger.info(
            "RelationshipTracker: %d cold contact(s) detected.",
            len(cold_contacts)
        )

        # Surface at most 2 cold contacts per evaluation
        # to avoid flooding Yash with relationship nudges
        for person in cold_contacts[:2]:
            await self._surface_cold_contact(person)

    def _is_cold(self, node: dict) -> bool:
        """
        Returns True if a person node has gone quiet
        beyond their tier threshold.
        Skips nodes with no interaction history — they were
        never warm so cannot be cold.
        """
        last_interacted = node.get("last_interacted")
        if not last_interacted:
            return False  # Never interacted — not cold, just new

        # Skip if surfaced as cold recently (within 7 days)
        last_surfaced = node.get("last_surfaced")
        if last_surfaced:
            try:
                last = datetime.fromisoformat(last_surfaced)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                days_since_surface = (
                    datetime.now(timezone.utc) - last
                ).days
                if days_since_surface < 7:
                    return False
            except (ValueError, TypeError):
                pass

        try:
            last = datetime.fromisoformat(last_interacted)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)

            days_since = (
                datetime.now(timezone.utc) - last
            ).days
            threshold = self._cold_threshold_days(node)
            return days_since >= threshold

        except (ValueError, TypeError):
            return False

    async def _surface_cold_contact(self, person: dict) -> None:
        """
        Surface a nudge for a cold contact via voice and WebSocket.
        Updates last_surfaced on the person node.
        """
        label           = person.get("label", "someone")
        last_interacted = person.get("last_interacted", "")
        threshold       = self._cold_threshold_days(person)
        tier            = self._classify_tier(person)

        # Compute days since last interaction for nudge text
        try:
            last = datetime.fromisoformat(last_interacted)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - last).days
            time_str = f"{days_since} days"
        except (ValueError, TypeError):
            time_str = "a while"

        nudge_text = (
            f"Boss, you haven't been in touch with {label} "
            f"for {time_str}. "
            f"Worth a quick check-in?"
        )

        logger.info(
            "RelationshipTracker: cold contact nudge — %s "
            "(%s tier, %d day threshold).",
            label, tier, threshold
        )

        # Update last_surfaced on person node
        self._brain.update_node(person["id"], {
            "last_surfaced": datetime.now(timezone.utc).isoformat()
        })

        if self._voice:
            await self._voice.enqueue_speech(
                text=nudge_text,
                node_ids=[person["id"]],
                priority="normal",
            )

        if self._ws_manager:
            await self._ws_manager.send_maihera_speak(
                text=nudge_text,
                node_ids=[person["id"]],
                priority="normal",
            )

    # ── Stats ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return relationship tracking statistics."""
        try:
            persons = self._brain.list_nodes(node_type="person")
            persons = [
                p for p in persons
                if p.get("label", "").lower()
                not in ("yash", "self")
            ]
            total        = len(persons)
            with_history = sum(
                1 for p in persons if p.get("last_interacted")
            )
            cold         = sum(
                1 for p in persons
                if p.get("last_interacted") and self._is_cold(p)
            )
            return {
                "total_contacts":  total,
                "with_history":    with_history,
                "cold_contacts":   cold,
            }
        except Exception as e:
            logger.error(
                "RelationshipTracker: stats failed: %s", e
            )
            return {}