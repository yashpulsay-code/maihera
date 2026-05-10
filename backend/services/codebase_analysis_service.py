"""
MAIHERA Codebase Analysis Service
Analyzes Presence GitHub repository and generates architectural assessment findings.
Creates brain nodes for challenges, improvements, and insights.
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.schema import NodeSchema, NodeType, NodeSource, NodeStatus, NodeVisibility
from llm.router import LLMRouter
from services.github_service import github_service
from brain.signal_defaults import get_defaults, analysis_importance

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 48
MAX_FINDINGS = 10
MAX_TOKENS = 6000
CHAR_CAP = MAX_TOKENS * 3

MAIHERA_PERSONA = """You are MAIHERA — Mai He Raja, Mai He Rani.
An assertive, technical AI built to understand and improve the systems she analyzes.
You are direct, specific, and actionable. You base all findings on actual code you can see.
Never give generic advice. Every finding must be tied to a specific file or pattern."""


class CodebaseAnalysisService:
    """Analyzes Presence codebase and creates brain nodes for findings."""

    async def run_first_analysis(
        self,
        brain_service,
        llm_router: LLMRouter
    ) -> dict:
        """
        One-time full analysis of Presence codebase.
        Fetches repo tree, reads key files, generates findings via LLM,
        creates brain nodes for findings.
        Returns summary: {"nodes_created": N, "findings": [...]}
        """
        if not self._check_cooldown(brain_service):
            last_run = self._get_last_run_timestamp(brain_service)
            next_allowed = (
                datetime.fromisoformat(last_run) + timedelta(hours=COOLDOWN_HOURS)
                if last_run else None
            )
            return {
                "status": "cooldown",
                "message": (
                    f"Cooldown active. Next run available at "
                    f"{next_allowed.isoformat() if next_allowed else 'unknown'}"
                )
            }

        presence_project_id = self._get_presence_project_id(brain_service)
        if not presence_project_id:
            return {
                "status": "error",
                "message": "Presence project node not found in brain"
            }

        codebase_summary = await self._fetch_codebase_summary()
        findings = await self._generate_findings(codebase_summary, llm_router)

        nodes_created = await self._create_finding_nodes(
            findings, brain_service, presence_project_id
        )

        self._store_analysis_timestamp(brain_service)

        return {
            "status": "success",
            "nodes_created": nodes_created,
            "findings": findings
        }

    async def _fetch_codebase_summary(self) -> str:
        """
        Build a structured summary of the Presence codebase for LLM analysis.
        1. Get repo tree — all code files
        2. Read key architectural files: index.html, any main JS/TS entry points,
           package.json, any supabase config, any main API files
        3. Cap total content at 8000 tokens (approx 32000 chars) — truncate
           less important files if needed
        4. Return as structured string with file paths and contents
        """
        tree = await github_service.get_repo_tree()

        key_files = [
            'index.html',
            'package.json',
            'src/main.js',
            'src/App.js',
            'src/App.jsx',
            'src/main.ts',
            'src/App.tsx',
            'src/index.js',
            'src/index.tsx',
            'src/config.js',
            'src/config.ts',
            'supabase/index.js',
            'supabase/client.js',
            'api/index.js',
            'api/server.js',
        ]

        prioritized = []
        for f in tree:
            path = f['path']
            if any(path.startswith(kf) for kf in key_files):
                prioritized.insert(0, f)
            else:
                prioritized.append(f)

        summary_parts = []
        total_chars = 0

        for f in prioritized:
            if total_chars >= CHAR_CAP:
                break

            path = f['path']
            try:
                content = await github_service.get_file_content(path)

                if total_chars + len(path) + len(content) > CHAR_CAP:
                    remaining = CHAR_CAP - total_chars - len(path) - 100
                    if remaining > 500:
                        content = content[:remaining] + "\n\n[truncated]"
                    else:
                        continue

                summary_parts.append(f"=== {path} ===\n{content}\n")
                total_chars += len(path) + len(content)

            except Exception as e:
                logger.warning(f"Could not read {path}: {e}")
                continue

        return "\n".join(summary_parts)

    async def _generate_findings(
        self,
        codebase_summary: str,
        llm_router: LLMRouter
    ) -> list[dict]:
        """
        Send codebase summary to LLM with analysis prompt.
        Returns list of findings, each:
        {
            "type": "challenge" | "improvement" | "insight",
            "label": str,
            "description": str,
            "evidence": [str],
            "priority": int,
            "confidence": float
        }
        Parse LLM response as JSON. Strip markdown fences.
        Cap at 10 findings total.
        """
        user_prompt = f"""You are analyzing the Presence codebase — a personal AI companion app built with HTML/CSS/JS frontend and Supabase backend.

Here is the codebase:
{codebase_summary}

Generate exactly 10 findings as a JSON array. Each finding must be:
- Specific to actual code you can see, not generic advice
- Tied to a specific file or pattern
- Actionable — what exactly should change and why

Finding types:
- "challenge": An architectural or design decision that is flawed or has a better alternative
- "improvement": A concrete enhancement that would meaningfully improve the product
- "insight": A pattern or observation worth tracking

Return ONLY a JSON array, no markdown, no preamble:
[
  {{
    "type": "challenge|improvement|insight",
    "label": "Short title under 60 chars",
    "description": "One paragraph. What is the issue, why it matters, what to do instead.",
    "evidence": ["specific/file/path.js", "another observation tied to code"],
    "priority": 1,
    "confidence": 0.85
  }}
]
Priority 1 = most important architectural concern. Priority 10 = lowest."""

        try:
            response = await llm_router.route(
                task_type="code_analysis",
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=MAIHERA_PERSONA,
                max_tokens=4000
            )

            # Strip markdown fences
            response = response.strip()
            for fence in ['```json', '```']:
                if response.startswith(fence):
                    response = response[len(fence):]
            if response.endswith('```'):
                response = response[:-3]
            response = response.strip()

            # Extract JSON array — find first [ and last ]
            # Handles cases where LLM adds text before or after
            start_idx = response.find('[')
            end_idx   = response.rfind(']')
            if start_idx == -1 or end_idx == -1:
                logger.error(
                    "No JSON array found in LLM response. "
                    "Raw: %.200s", response
                )
                return []
            response = response[start_idx:end_idx + 1]

            findings = json.loads(response)

            validated = []
            for f in findings:
                if not all(k in f for k in ["type", "label", "description", "evidence", "priority", "confidence"]):
                    continue
                if f["type"] not in ["challenge", "improvement", "insight"]:
                    continue
                if not (1 <= f["priority"] <= 10):
                    continue
                if not (0.0 <= f["confidence"] <= 1.0):
                    continue
                validated.append(f)

            return validated[:MAX_FINDINGS]

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Raw response: {response[:500] if response else 'empty'}")
            return []
        except Exception as e:
            logger.error(f"Error generating findings: {e}")
            return []

    async def _create_finding_nodes(
        self,
        findings: list[dict],
        brain_service,
        presence_project_id: str
    ) -> int:
        """
        Create brain nodes from findings list.
        - "challenge" → NodeType.DECISION with status=CHALLENGED
        - "improvement" → NodeType.FEATURE with status=ACTIVE
        - "insight" → NodeType.INSIGHT with status=ACTIVE
        - All nodes: source=NodeSource.DREAM, node_weight=0.8,
          source_ref="github:yashpulsay-code/Presence",
          importance scales with priority (priority 1 → 0.8, priority 10 → 0.4),
          attention=0.7, project_id=presence_project_id
        - Sort by priority before creating — highest priority nodes first
        - Create BELONGS_TO edge from each finding node to Presence project node
        - Return count of nodes created
        """
        sorted_findings = sorted(findings, key=lambda f: f["priority"])

        count = 0
        for finding in sorted_findings:
            ftype = finding["type"]

            if ftype == "challenge":
                node_type = NodeType.DECISION
                node_status = NodeStatus.CHALLENGED
            elif ftype == "improvement":
                node_type = NodeType.FEATURE
                node_status = NodeStatus.ACTIVE
            else:
                node_type = NodeType.INSIGHT
                node_status = NodeStatus.ACTIVE

            priority = finding["priority"]
            importance = analysis_importance(priority)

            defaults = get_defaults(NodeSource.DREAM)

            node = NodeSchema(
                type        = node_type,
                label       = finding["label"][:60],
                description = finding["description"],
                project_id  = presence_project_id,
                source      = NodeSource.DREAM,
                status      = node_status,
                visibility  = NodeVisibility.PRIVATE,
                source_ref  = "github:yashpulsay-code/Presence",
                node_weight = defaults['node_weight'],
                importance  = importance,
                attention   = defaults['attention'],
                evidence    = finding["evidence"]
            )

            try:
                node_id = brain_service.create_node(node)

                brain_service.create_edge(
                    from_id=node_id,
                    to_id=presence_project_id,
                    edge_type="BELONGS_TO"
                )

                count += 1
                logger.info(f"Created {ftype} node: {finding['label']}")

            except Exception as e:
                logger.error(f"Failed to create node for {finding['label']}: {e}")

        return count

    def _get_presence_project_id(self, brain_service) -> str | None:
        """Find Presence project node ID from Neo4j."""
        try:
            projects = brain_service.list_nodes(node_type="project")
            for p in projects:
                label = p.get("label", "").lower()
                if "presence" in label or "github" in label:
                    return p.get("id")
            return None
        except Exception as e:
            logger.error(f"Failed to find Presence project: {e}")
            return None

    def _check_cooldown(self, brain_service) -> bool:
        """
        Return True if analysis is allowed (cooldown passed or never run).
        Reads 'presence_analysis_last_run' from github_state SQLite table.
        48 hour cooldown.
        """
        try:
            cursor = brain_service.db.connection.execute(
                "SELECT value FROM github_state WHERE key = ?",
                ("presence_analysis_last_run",)
            )
            row = cursor.fetchone()

            if not row:
                return True

            last_run = datetime.fromisoformat(row[0])
            next_allowed = last_run + timedelta(hours=COOLDOWN_HOURS)

            return datetime.utcnow() >= next_allowed

        except Exception as e:
            logger.error(f"Failed to check cooldown: {e}")
            return True

    def _get_last_run_timestamp(self, brain_service) -> str | None:
        """Get last analysis timestamp from github_state."""
        try:
            cursor = brain_service.db.connection.execute(
                "SELECT value FROM github_state WHERE key = ?",
                ("presence_analysis_last_run",)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get last run timestamp: {e}")
            return None

    def _store_analysis_timestamp(self, brain_service) -> None:
        """Store current UTC timestamp to github_state as presence_analysis_last_run."""
        try:
            now = datetime.utcnow().isoformat()
            brain_service.db.connection.execute("""
                INSERT INTO github_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, ("presence_analysis_last_run", now))
            brain_service.db.connection.commit()
            logger.info(f"Stored analysis timestamp: {now}")
        except Exception as e:
            logger.error(f"Failed to store analysis timestamp: {e}")


codebase_analysis_service = CodebaseAnalysisService()