"""
MAIHERA Drip Service
Surfaces Presence codebase analysis findings 2-3 per day.
Findings are surfaced in priority order (importance descending).
Tracks which findings have been surfaced via SQLite.
Never re-surfaces a finding that has already been delivered.
"""

import sys
import json
import logging
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# How many findings to surface per day
DRIP_PER_DAY = 2

# SQLite keys
KEY_SURFACED    = "drip_surfaced_node_ids"   # JSON list of surfaced node IDs
KEY_LAST_DRIP   = "drip_last_date"           # ISO date of last drip


class DripService:
    """
    Manages daily drip of Presence analysis findings.
    Called during morning briefing — surfaces next N unsurfaced findings.
    """

    def get_todays_findings(self, brain_service) -> list[dict]:
        """
        Return up to DRIP_PER_DAY unsurfaced findings for today.
        Findings are sorted by importance descending (priority 1 first).
        Returns empty list if already dripped today or no findings remain.
        """
        # Check if already dripped today
        last_drip = brain_service.db.get_drip_state(KEY_LAST_DRIP)
        today     = date.today().isoformat()

        if last_drip == today:
            logger.debug("DripService: already dripped today.")
            return []

        # Get all analysis finding nodes from brain
        all_findings = self._get_all_finding_nodes(brain_service)
        if not all_findings:
            logger.debug("DripService: no analysis findings in brain.")
            return []

        # Get already surfaced node IDs
        surfaced_raw = brain_service.db.get_drip_state(KEY_SURFACED)
        surfaced_ids = set(json.loads(surfaced_raw) if surfaced_raw else [])

        # Filter to unsurfaced findings
        unsurfaced = [
            f for f in all_findings
            if f['id'] not in surfaced_ids
        ]

        if not unsurfaced:
            logger.info("DripService: all findings have been surfaced.")
            return []

        # Sort by importance descending — highest priority first
        unsurfaced.sort(key=lambda n: n.get('importance', 0), reverse=True)

        # Take next batch
        batch = unsurfaced[:DRIP_PER_DAY]

        # Mark as surfaced
        new_surfaced = surfaced_ids | {f['id'] for f in batch}
        brain_service.db.set_drip_state(
            KEY_SURFACED,
            json.dumps(list(new_surfaced))
        )
        brain_service.db.set_drip_state(KEY_LAST_DRIP, today)

        # Update last_surfaced timestamp on each node
        now = datetime.utcnow().isoformat()
        for finding in batch:
            brain_service.update_node(
                finding['id'],
                {'last_surfaced': now}
            )

        logger.info(
            "DripService: surfacing %d finding(s) today.", len(batch)
        )
        return batch

    def _get_all_finding_nodes(self, brain_service) -> list[dict]:
        """
        Fetch all analysis finding nodes from brain.
        These are nodes with source_ref = github:yashpulsay-code/Presence
        and type in decision, feature, insight.
        """
        finding_types = ['decision', 'feature', 'insight']
        all_nodes = []
        for node_type in finding_types:
            nodes = brain_service.list_nodes(node_type=node_type)
            for n in nodes:
                if n.get('source_ref') == 'github:yashpulsay-code/Presence':
                    all_nodes.append(n)
        return all_nodes

    def format_finding_for_briefing(self, finding: dict) -> str:
        """
        Format a finding node as a voice briefing segment.
        Kept concise — 2-3 sentences max for voice delivery.
        """
        node_type = finding.get('type', 'insight')
        label     = finding.get('label', 'Unnamed finding')
        desc      = finding.get('description', '')

        type_prefix = {
            'decision': "Boss, I have a challenge to raise about Presence.",
            'feature':  "Boss, I have an improvement proposal for Presence.",
            'insight':  "Boss, I noticed something in the Presence codebase.",
        }.get(node_type, "Boss, I have a finding about Presence.")

        # Truncate description to first 2 sentences for voice
        sentences = desc.replace('!', '.').replace('?', '.').split('.')
        short_desc = '. '.join(
            s.strip() for s in sentences[:2] if s.strip()
        )
        if short_desc and not short_desc.endswith('.'):
            short_desc += '.'

        return f"{type_prefix} {label}. {short_desc}"

    def get_drip_status(self, brain_service) -> dict:
        """Return current drip status for API endpoint."""
        all_findings  = self._get_all_finding_nodes(brain_service)
        surfaced_raw  = brain_service.db.get_drip_state(KEY_SURFACED)
        surfaced_ids  = set(json.loads(surfaced_raw) if surfaced_raw else [])
        last_drip     = brain_service.db.get_drip_state(KEY_LAST_DRIP)

        return {
            'total_findings':     len(all_findings),
            'surfaced':           len(surfaced_ids),
            'remaining':          len(all_findings) - len(surfaced_ids),
            'last_drip_date':     last_drip,
            'dripped_today':      last_drip == date.today().isoformat(),
            'drip_per_day':       DRIP_PER_DAY,
        }

    def reset(self, brain_service) -> None:
        """
        Reset drip state — all findings become unsurfaced again.
        Use when a new analysis pass creates fresh findings.
        """
        brain_service.db.set_drip_state(KEY_SURFACED, json.dumps([]))
        brain_service.db.set_drip_state(KEY_LAST_DRIP, '')
        logger.info("DripService: drip state reset.")


# Module-level singleton
drip_service = DripService()