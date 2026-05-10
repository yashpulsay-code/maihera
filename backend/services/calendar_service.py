"""
MAIHERA Service — Google Calendar Integration
Fetches events from Google Calendar and creates brain nodes.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import datetime, timedelta
from typing import Optional
import asyncio

# Try to import rapidfuzz, provide clear error if missing
try:
    from rapidfuzz import fuzz
except ImportError:
    raise ImportError(
        "rapidfuzz is required for calendar service. "
        "Install with: pip install rapidfuzz"
    )

from brain.schema import NodeSchema, NodeType, NodeSource, NodeStatus, WorkspaceType
from services.google_auth_service import google_auth
from services.secrets_service import secrets
from brain.signal_defaults import get_defaults, calendar_attention

logger = logging.getLogger(__name__)

class CalendarService:
    """Service for syncing Google Calendar events to the brain graph."""

    def get_service(self):
        """Return authenticated Google Calendar API service object."""
        return google_auth.get_calendar_service()

    async def fetch_upcoming_events(self, days_ahead: int = 14) -> list[dict]:
        """Fetch events from now until days_ahead from primary calendar."""
        service = self.get_service()
        now = datetime.utcnow()
        end_time = now + timedelta(days=days_ahead)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now.isoformat() + 'Z',
            timeMax=end_time.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        return events_result.get('items', [])

    async def sync_to_brain(self, brain_service) -> dict:
        """
        Full sync — fetch upcoming events, create/update brain nodes.
        Returns summary: {"created": N, "updated": N, "linked": N, "unlinked": N}
        """
        from brain.brain_service import BrainService

        if not isinstance(brain_service, BrainService):
            raise ValueError("brain_service must be a BrainService instance")

        events = await self.fetch_upcoming_events()

        summary = {
            "created": 0,
            "updated": 0,
            "linked": 0,
            "unlinked": 0
        }

        for event in events:
            try:
                result = await self._process_event(event, brain_service)
                for key in summary:
                    summary[key] += result.get(key, 0)
            except Exception as e:
                logger.error(f"Error processing event {event.get('id')}: {e}")
                continue

        logger.info(f"Calendar sync complete: {summary}")
        return summary

    async def _process_event(self, event: dict, brain_service) -> dict:
        """Process a single calendar event and sync to brain."""
        event_id = event['id']
        source_ref = f"gcal:{event_id}"

        # Deduplicate — query Neo4j directly by source_ref
        existing = brain_service.find_node_by_source_ref(source_ref)

        if existing:
            # Update attention and last_touched only
            attention = self._compute_attention(event)
            brain_service.update_node_signals(
                node_id=existing['id'],
                attention=attention
            )
            return {"updated": 1, "linked": 0, "unlinked": 0}
        else:
            # Create new node
            node_schema = self._build_node_schema(event, source_ref)
            node_id = brain_service.create_node(node_schema)
            result = {"created": 1, "updated": 0}

        # Link to persons and projects
        link_result = await self._link_event(event, node_id, brain_service)
        result.update(link_result)
        return result

    def _build_node_schema(self, event: dict, source_ref: str) -> NodeSchema:
        """Build a NodeSchema from a Google Calendar event."""
        label       = event.get('summary', 'Untitled Event')
        description = self._extract_event_description(event)
        start       = event.get('start', {})
        start_dt    = self._parse_datetime(start)

        # Compute attention from proximity
        if start_dt:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            # Make start_dt timezone-aware if naive
            if start_dt.tzinfo is None:
                from datetime import timezone
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            hours_until = (start_dt - now).total_seconds() / 3600
            attention = calendar_attention(hours_until)
        else:
            attention = 0.6

        defaults = get_defaults(NodeSource.CALENDAR)

        return NodeSchema(
            type        = NodeType.EVENT,
            label       = label,
            description = description,
            source      = NodeSource.CALENDAR,
            source_ref  = source_ref,
            importance  = defaults['importance'],
            attention   = attention,
            node_weight = defaults['node_weight'],
            workspace   = WorkspaceType.PERSONAL,
            status      = NodeStatus.ACTIVE,
            evidence    = [],
        )

    async def _link_event(self, event: dict, node_id: str, brain_service) -> dict:
        """Link event node to persons and projects."""
        result = {"linked": 0, "unlinked": 0}

        # Link to persons
        person_links = await self._link_to_persons(event, node_id, brain_service)
        result["linked"] += person_links

        # Link to projects
        project_links = await self._link_to_projects(event, node_id, brain_service)
        if project_links == 0:
            # No project links, mark as unlinked
            brain_service.update_node(node_id, {
                "status": NodeStatus.ACTIVE.value,
                "evidence": ["unlinked"]
            })
            result["unlinked"] = 1
        else:
            result["linked"] += project_links

        return result

    async def _link_to_persons(self, event: dict, node_id: str, brain_service) -> int:
        """Link event to person nodes using fuzzy matching."""
        attendees = event.get('attendees', [])
        links = 0

        for attendee in attendees:
            name = attendee.get('displayName')
            if not name:
                continue

            # Search for person nodes with similar names
            person_nodes = brain_service.search_nodes(
                query=name,
                node_type=NodeType.PERSON.value
            )

            # Find best match with high similarity
            best_match = None
            best_score = 0

            for person_node in person_nodes:
                score = fuzz.ratio(name, person_node.get('label', ''))
                if score > 80 and score > best_score:
                    best_match = person_node
                    best_score = score

            if best_match:
                brain_service.create_edge(
                    from_id=node_id,
                    to_id=best_match['id'],
                    edge_type='RELATES_TO'
                )
                links += 1

        return links

    async def _link_to_projects(self, event: dict, node_id: str, brain_service) -> int:
        """Link event to project nodes using semantic search."""
        title = event.get('summary', '')
        description = event.get('description', '')
        search_query = f"{title} {description}".strip()

        if not search_query:
            return 0

        # Search for related projects using semantic similarity
        project_results = brain_service.search_nodes(
            query=search_query,
            node_type=NodeType.PROJECT.value
        )

        # Link to top matches with high similarity
        links = 0
        for result in project_results[:2]:  # Limit to top 2
            if result.get('_search_distance', 1.0) < 0.25:  # High similarity threshold
                brain_service.create_edge(
                    from_id=node_id,
                    to_id=result['id'],
                    edge_type='BELONGS_TO'
                )
                links += 1

        return links

    async def get_todays_events(self) -> list[dict]:
        """Return today's events as raw Google Calendar dicts."""
        service = self.get_service()
        now = datetime.utcnow()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_of_day.isoformat() + 'Z',
            timeMax=end_of_day.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        return events_result.get('items', [])

    def _compute_attention(self, event: dict) -> float:
        """Compute attention signal based on proximity to now."""
        start = self._parse_datetime(event.get('start', {}))
        if not start:
            return 0.4
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        hours_until = (start - now).total_seconds() / 3600
        return calendar_attention(hours_until)

    def _parse_datetime(self, time_dict: dict) -> Optional[datetime]:
        """Parse datetime from Google Calendar time dictionary."""
        if 'dateTime' in time_dict:
            dt_str = time_dict['dateTime']
        elif 'date' in time_dict:
            # All-day event, treat as start of day
            dt_str = time_dict['date'] + 'T00:00:00'
        else:
            return None

        try:
            # Handle timezone if present
            if 'Z' in dt_str or '+' in dt_str:
                return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            else:
                # Assume UTC if no timezone
                return datetime.fromisoformat(dt_str)
        except ValueError:
            logger.warning(f"Could not parse datetime: {dt_str}")
            return None

    def _extract_event_description(self, event: dict) -> str:
        """Build a meaningful description string from a Google Calendar event dict."""
        parts = []

        # Add summary/title
        if event.get('summary'):
            parts.append(event['summary'])

        # Add description
        if event.get('description'):
            parts.append(event['description'])

        # Add location
        if event.get('location'):
            parts.append(f"Location: {event['location']}")

        # Add attendees
        attendees = event.get('attendees', [])
        if attendees:
            attendee_names = [a.get('displayName', a.get('email', ''))
                              for a in attendees[:3]]  # Limit to first 3
            if attendee_names:
                parts.append(f"Attendees: {', '.join(attendee_names)}")

        # Add time
        start = event.get('start')
        if start:
            start_dt = self._parse_datetime(start)
            if start_dt:
                parts.append(f"Start: {start_dt.strftime('%Y-%m-%d %H:%M')}")

        return " | ".join(parts) if parts else "No description"


# Module-level singleton
calendar_service = CalendarService()