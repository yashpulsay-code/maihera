"""
MAIHERA Weekly Review Service
Runs every Sunday. Replaces the daily standup.
Delivers a structured voice briefing covering the week:
- What moved forward
- What stalled
- Behavioral patterns observed
- Resistance trends
- One clear recommendation
Sends summary to Yash via Gmail after delivery.
"""

import sys
import json
import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

KEY_LAST_WEEKLY_REVIEW = "weekly_review_last_date"


class WeeklyReviewService:

    def should_run_today(self, brain_service) -> bool:
        """Return True if today is Sunday and review not yet done."""
        today = date.today()
        if today.weekday() != 6:  # 6 = Sunday
            return False

        last = brain_service.db.get_drip_state(KEY_LAST_WEEKLY_REVIEW)
        return last != today.isoformat()

    async def run(
        self,
        brain_service,
        llm_router,
        voice_service,
        ws_manager
    ) -> None:
        """
        Deliver the weekly review by voice and send summary email.
        Called from morning briefing on Sundays.
        """
        logger.info("WeeklyReviewService: starting weekly review...")

        summary_text = await self._generate_summary(
            brain_service, llm_router
        )
        segments     = self._split_into_segments(summary_text)

        # Deliver by voice
        full_text  = " ".join(segments)
        all_ids: list[str] = []

        if ws_manager:
            await ws_manager.send_maihera_speak(
                text=full_text,
                node_ids=all_ids,
                priority="normal"
            )

        for segment in segments:
            await voice_service.enqueue_speech(
                text=segment,
                node_ids=[],
                priority="normal",
                silent=True
            )

        # Send email summary
        try:
            from services.gmail_service import gmail_service
            await gmail_service.send_weekly_summary(summary_text)
            logger.info("WeeklyReviewService: summary email sent.")
        except Exception as e:
            logger.warning(
                "WeeklyReviewService: email send failed — %s", e
            )

        # Mark complete
        brain_service.db.set_drip_state(
            KEY_LAST_WEEKLY_REVIEW,
            date.today().isoformat()
        )
        logger.info("WeeklyReviewService: weekly review complete.")

    async def _generate_summary(
        self,
        brain_service,
        llm_router
    ) -> str:
        """
        Generate the weekly review summary via LLM.
        Pulls brain data to give the LLM real context.
        """
        brain_context = self._build_brain_context(brain_service)

        prompt = f"""You are MAIHERA delivering the Sunday weekly review to Boss.
Speak directly to him in second person. Address him as Boss.
Be honest, specific, and useful. Not generic.

Here is the current brain state:
{brain_context}

Generate a weekly review covering:
1. What moved forward this week (completed or high-attention active tasks)
2. What stalled (high importance, low attention, or resistant nodes)
3. One behavioral pattern you noticed
4. One clear recommendation for next week

Keep it under 200 words. Conversational. Voice-friendly — no bullet points,
no headers. Flowing prose only. Start with 'Boss,' """

        try:
            response = await llm_router.route(
                task_type='dream_mode',
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400
            )
            if response and response.strip():
                return response.strip()
        except Exception as e:
            logger.error(
                "WeeklyReviewService: LLM generation failed — %s", e
            )

        # Fallback — structured summary from raw data
        return self._fallback_summary(brain_service)

    def _build_brain_context(self, brain_service) -> str:
        """Build a compact brain state string for the LLM prompt."""
        lines = []

        try:
            # Completed nodes this week
            all_nodes = brain_service.list_nodes(status='completed')
            week_ago  = (datetime.utcnow() - timedelta(days=7)).isoformat()
            completed = [
                n for n in all_nodes
                if n.get('last_touched', '') >= week_ago
            ]
            if completed:
                labels = [n['label'] for n in completed[:5]]
                lines.append(f"Completed this week: {', '.join(labels)}")

            # High resistance nodes
            active = brain_service.list_nodes(status='active')
            resistant = [
                n for n in active
                if float(n.get('resistance', 0)) >= 0.4
            ]
            if resistant:
                labels = [n['label'] for n in resistant[:3]]
                lines.append(f"Showing resistance: {', '.join(labels)}")

            # High importance stalled nodes
            stalled = [
                n for n in active
                if float(n.get('importance', 0)) >= 0.6
                and float(n.get('attention', 0)) <= 0.2
            ]
            if stalled:
                labels = [n['label'] for n in stalled[:3]]
                lines.append(f"High importance but stalled: {', '.join(labels)}")

            # Stale nodes
            stale = [n for n in active if n.get('is_stale')]
            if stale:
                lines.append(f"Stale nodes needing re-evaluation: {len(stale)}")

            # Top active nodes by signal
            high_signal = brain_service.get_high_signal_nodes(
                importance_threshold=0.5,
                attention_threshold=0.3
            )[:5]
            if high_signal:
                labels = [n['label'] for n in high_signal]
                lines.append(f"Top active items: {', '.join(labels)}")

        except Exception as e:
            logger.warning(
                "WeeklyReviewService: brain context error — %s", e
            )
            lines.append("Brain context unavailable.")

        return "\n".join(lines) if lines else "No significant activity this week."

    def _fallback_summary(self, brain_service) -> str:
        """Plain text fallback when LLM fails."""
        try:
            stats = brain_service.get_stats()
            total = stats.get('node_count', 0)
            return (
                f"Boss, here's your weekly review. "
                f"Your brain currently has {total} nodes across all projects. "
                f"I wasn't able to generate a full analysis this week — "
                f"check the logs for details. "
                f"I recommend spending a few minutes reviewing your active tasks "
                f"and updating any that have changed status."
            )
        except Exception:
            return (
                "Boss, I wasn't able to generate your weekly review this week. "
                "Check the logs and try again."
            )

    def _split_into_segments(self, text: str) -> list[str]:
        """
        Split review text into voice-friendly segments.
        Split on sentence boundaries, max ~150 chars per segment.
        """
        sentences = []
        for part in text.replace('!', '.').replace('?', '.').split('.'):
            part = part.strip()
            if part:
                sentences.append(part + '.')

        segments = []
        current  = ""
        for sentence in sentences:
            if len(current) + len(sentence) > 150 and current:
                segments.append(current.strip())
                current = sentence
            else:
                current += " " + sentence

        if current.strip():
            segments.append(current.strip())

        return segments if segments else [text]

    def get_status(self, brain_service) -> dict:
        """Return weekly review status."""
        last  = brain_service.db.get_drip_state(KEY_LAST_WEEKLY_REVIEW)
        today = date.today()
        return {
            "last_review":    last,
            "is_sunday":      today.weekday() == 6,
            "should_run":     self.should_run_today(brain_service),
            "completed_today": last == today.isoformat(),
        }


# Module-level singleton
weekly_review_service = WeeklyReviewService()