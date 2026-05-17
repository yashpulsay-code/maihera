"""
MAIHERA Dream Mode Service
Offline cognition layer — runs when Yash is idle for 10+ minutes.

Listens to the dream event queue for idle_start / idle_end signals.
Builds a prioritized task queue from brain signals each session.
Executes atomic research tasks using Claude Sonnet + Tavily.
Writes results as idea/insight nodes tagged source=dream.

Execution rights:
  - Internal brain writes (nodes, edges) — allowed
  - External API writes (calendar, github, gmail) — never
  - Configuration writes — never without Yash approval

Phase 6 implementation.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Minimum idle seconds before expensive tasks unlock
LONG_SESSION_THRESHOLD = 900   # 15 minutes
# How long Dream Mode waits between tasks to avoid hammering APIs
INTER_TASK_DELAY = 5           # seconds
# Nodes touched by Dream Mode within this window are skipped
DREAM_COOLDOWN_HOURS = 24
# Max tasks per session regardless of window length
MAX_TASKS_PER_SESSION = 8
# Max Tavily searches per session
MAX_WEB_SEARCHES_PER_SESSION = 4
# Max article fetches per search result
MAX_FETCHES_PER_SEARCH = 2


class DreamTask:
    """One atomic unit of Dream Mode cognition."""

    def __init__(
        self,
        task_type: str,         # pattern_synthesis | cross_project_comparison
                                # | web_research | proposal_generation
        node_id: str,
        node_label: str,
        node_description: str,
        project_label: str,
        priority_score: float,
        secondary_node_id: Optional[str] = None,
        secondary_node_label: Optional[str] = None,
    ):
        self.task_type = task_type
        self.node_id = node_id
        self.node_label = node_label
        self.node_description = node_description
        self.project_label = project_label
        self.priority_score = priority_score
        self.secondary_node_id = secondary_node_id
        self.secondary_node_label = secondary_node_label
        self.created_at = datetime.utcnow().isoformat()


class DreamModeService:
    """
    Dream Mode cognition engine.

    Lifecycle:
        service = DreamModeService(brain_service, llm_router)
        service.set_tavily_key(key)
        worker = DreamModeWorker(dream_queue, service)
        worker.start()

    The worker listens to the dream queue and calls
    service.run_session() / service.stop_session().
    """

    def __init__(self, brain_service, llm_router):
        self._brain = brain_service
        self._router = llm_router
        self._tavily_key: Optional[str] = None

        self._session_active = False
        self._session_start: Optional[datetime] = None
        self._stop_requested = False
        self._web_search_count = 0
        self._tasks_completed = 0

        logger.info("DreamModeService initialized.")

    # ── Dependency Injection ──────────────────────────────────────

    def set_tavily_key(self, key: str) -> None:
        self._tavily_key = key
        logger.info("DreamModeService: Tavily key set.")

    # ── Session Control ───────────────────────────────────────────

    async def run_session(self) -> None:
        """
        Start a Dream Mode session.
        Builds task queue and works through it until interrupted
        or queue is exhausted.
        """
        if self._session_active:
            logger.warning("DreamMode: session already running, ignoring.")
            return

        self._session_active = True
        self._session_start = datetime.utcnow()
        self._stop_requested = False
        self._web_search_count = 0
        self._tasks_completed = 0

        logger.info("DreamMode: session started at %s", self._session_start)

        try:
            tasks = self._build_task_queue()
            logger.info(
                "DreamMode: %d tasks queued for this session.", len(tasks)
            )

            for task in tasks:
                if self._stop_requested:
                    logger.info(
                        "DreamMode: stop requested — %d tasks remaining.",
                        len(tasks) - self._tasks_completed
                    )
                    break

                if self._tasks_completed >= MAX_TASKS_PER_SESSION:
                    logger.info("DreamMode: max tasks reached, ending session.")
                    break

                # Check if this task requires long session
                session_seconds = (
                    datetime.utcnow() - self._session_start
                ).total_seconds()
                is_long_session = session_seconds >= LONG_SESSION_THRESHOLD

                if (
                    task.task_type in ("web_research",)
                    and not is_long_session
                ):
                    logger.info(
                        "DreamMode: skipping web_research — "
                        "session too short (%.0fs < %ds).",
                        session_seconds, LONG_SESSION_THRESHOLD
                    )
                    continue

                if (
                    task.task_type == "web_research"
                    and self._web_search_count >= MAX_WEB_SEARCHES_PER_SESSION
                ):
                    logger.info(
                        "DreamMode: web search limit reached (%d), skipping.",
                        MAX_WEB_SEARCHES_PER_SESSION
                    )
                    continue

                logger.info(
                    "DreamMode: executing %s on '%s' (score=%.3f)",
                    task.task_type, task.node_label, task.priority_score
                )

                await self._execute_task(task)
                self._tasks_completed += 1
                self._stamp_dream_touched(task.node_id)

                await asyncio.sleep(INTER_TASK_DELAY)

        except Exception as e:
            logger.error("DreamMode: session error: %s", e)
        finally:
            elapsed = (
                datetime.utcnow() - self._session_start
            ).total_seconds()
            logger.info(
                "DreamMode: session ended. %d tasks completed in %.0fs.",
                self._tasks_completed, elapsed
            )
            self._session_active = False
            self._session_start = None

    def stop_session(self) -> None:
        """
        Signal the session to stop after the current task completes.
        Never cancels a running LLM call — always waits for completion.
        """
        if self._session_active:
            self._stop_requested = True
            logger.info(
                "DreamMode: stop requested — "
                "will halt after current task completes."
            )

    # ── Task Queue Builder ────────────────────────────────────────

    def _build_task_queue(self) -> list[DreamTask]:
        """
        Build a prioritized list of tasks for this session.

        Scoring: importance × attention, resistance as tiebreaker.
        Filters: active nodes only, not touched by Dream Mode
        in last 24h, personal workspace.

        Task type assignment:
        - issue / blocker nodes → web_research (find solutions)
        - idea / question nodes → pattern_synthesis
        - decision nodes → proposal_generation (challenge or validate)
        - project / component nodes → cross_project_comparison
        - any high-resistance node → web_research (find unblocking strategies)
        """
        tasks = []
        cooldown_cutoff = (
            datetime.utcnow() - timedelta(hours=DREAM_COOLDOWN_HOURS)
        ).isoformat()

        try:
            all_nodes = self._brain.list_nodes(status="active")
        except Exception as e:
            logger.error("DreamMode: failed to fetch nodes: %s", e)
            return []

        # Fetch project labels for context
        project_map = {}
        try:
            projects = self._brain.list_nodes(node_type="project")
            for p in projects:
                project_map[p.get("id")] = p.get("label", "Unknown")
        except Exception:
            pass

        # Filter and score nodes
        candidates = []
        for node in all_nodes:
            node_type = node.get("type", "")
            workspace = node.get("workspace", "personal")

            # Skip system/meta node types
            if node_type in ("self", "project"):
                continue

            # Skip recently dream-touched nodes
            last_dream = node.get("last_dream_touched")
            if last_dream and last_dream > cooldown_cutoff:
                continue

            importance = float(node.get("importance", 0.0))
            attention = float(node.get("attention", 0.0))
            resistance = float(node.get("resistance", 0.0))

            # Skip low-signal nodes — not worth dreaming about
            if importance < 0.2 and attention < 0.2:
                continue

            score = (importance * attention) + (resistance * 0.15)
            candidates.append((score, node))

        # Sort descending by score
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Get Presence and MAIHERA nodes for cross-project comparison
        presence_nodes = [
            n for _, n in candidates
            if project_map.get(n.get("project_id"), "").lower() == "presence"
        ]
        maihera_nodes = [
            n for _, n in candidates
            if project_map.get(n.get("project_id"), "").lower() == "maihera"
        ]

        seen_ids = set()

        for score, node in candidates:
            if len(tasks) >= MAX_TASKS_PER_SESSION:
                break

            node_id = node.get("id")
            if not node_id or node_id in seen_ids:
                continue

            node_type = node.get("type", "")
            node_label = node.get("label", "Unnamed")
            node_desc = node.get("description", "")
            project_label = project_map.get(
                node.get("project_id"), "Unknown"
            )
            resistance = float(node.get("resistance", 0.0))

            # Assign task type
            if node_type in ("issue", "blocker") or resistance > 0.6:
                task_type = "web_research"
            elif node_type in ("idea", "question"):
                task_type = "pattern_synthesis"
            elif node_type == "decision":
                task_type = "proposal_generation"
            elif node_type in ("feature", "component", "task"):
                # Cross-project if we have nodes from both projects
                if presence_nodes and maihera_nodes:
                    task_type = "cross_project_comparison"
                else:
                    task_type = "pattern_synthesis"
            else:
                task_type = "pattern_synthesis"

            # For cross-project, pair with the highest-scored node
            # from the other project
            secondary_id = None
            secondary_label = None
            if task_type == "cross_project_comparison":
                other_project = (
                    "maihera"
                    if project_label.lower() == "presence"
                    else "presence"
                )
                other_nodes = (
                    maihera_nodes
                    if other_project == "maihera"
                    else presence_nodes
                )
                for other in other_nodes:
                    if other.get("id") != node_id:
                        secondary_id = other.get("id")
                        secondary_label = other.get("label")
                        break

            tasks.append(DreamTask(
                task_type=task_type,
                node_id=node_id,
                node_label=node_label,
                node_description=node_desc,
                project_label=project_label,
                priority_score=score,
                secondary_node_id=secondary_id,
                secondary_node_label=secondary_label,
            ))
            seen_ids.add(node_id)

        logger.info(
            "DreamMode: task queue built — %d tasks. "
            "Types: %s",
            len(tasks),
            {t: sum(1 for x in tasks if x.task_type == t)
             for t in set(x.task_type for x in tasks)}
        )
        return tasks

    # ── Task Execution ────────────────────────────────────────────

    async def _execute_task(self, task: DreamTask) -> None:
        """Dispatch task to the correct handler."""
        try:
            if task.task_type == "pattern_synthesis":
                await self._task_pattern_synthesis(task)
            elif task.task_type == "cross_project_comparison":
                await self._task_cross_project(task)
            elif task.task_type == "web_research":
                await self._task_web_research(task)
            elif task.task_type == "proposal_generation":
                await self._task_proposal(task)
        except Exception as e:
            logger.error(
                "DreamMode: task %s on '%s' failed: %s",
                task.task_type, task.node_label, e
            )

    # ── Pattern Synthesis ─────────────────────────────────────────

    async def _task_pattern_synthesis(self, task: DreamTask) -> None:
        """
        Look at a node and its connected subgraph.
        Find patterns, trends, and connections not yet explicit.
        Write results as insight nodes.
        """
        # Fetch connected nodes for context
        related = self._get_related_nodes(task.node_id, limit=5)
        related_text = "\n".join(
            f"- {n.get('label')} ({n.get('type')}): "
            f"{n.get('description', '')[:120]}"
            for n in related
        )

        prompt = f"""You are MAIHERA's offline cognition engine performing Dream Mode analysis.

Node under analysis:
Label: {task.node_label}
Type: task/idea/question
Project: {task.project_label}
Description: {task.node_description}

Connected nodes:
{related_text if related_text else "No connected nodes found."}

Your task: Perform deep pattern synthesis on this node and its connections.
Identify:
1. Non-obvious patterns or trends in how this node relates to other work
2. Hidden dependencies or risks not yet captured as edges
3. A concrete insight that would change how Yash thinks about this node
4. One specific action recommendation

Respond in this exact JSON format:
{{
  "insight_title": "Short title for the insight (max 8 words)",
  "insight_body": "Full insight explanation (2-4 sentences)",
  "action_recommendation": "One specific action Yash should consider",
  "confidence": 0.0
}}

confidence is your certainty this insight is accurate and useful (0.0-1.0).
Respond with JSON only. No preamble."""

        response = await self._router.route(
            task_type="dream_synthesis",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )

        if not response:
            return

        data = self._parse_json(response)
        if not data:
            return

        confidence = float(data.get("confidence", 0.5))
        if confidence < 0.4:
            logger.info(
                "DreamMode: pattern_synthesis confidence too low "
                "(%.2f) — discarding.", confidence
            )
            return

        self._create_dream_node(
            node_type="insight",
            label=data.get("insight_title", f"Insight: {task.node_label}"),
            description=(
                f"{data.get('insight_body', '')}\n\n"
                f"Recommendation: {data.get('action_recommendation', '')}"
            ),
            project_id=self._get_project_id(task.project_label),
            source_node_id=task.node_id,
            edge_type="relates_to",
            importance=min(1.0, confidence + 0.1),
        )
        logger.info(
            "DreamMode: pattern_synthesis complete — "
            "insight created for '%s'.", task.node_label
        )

    # ── Cross-Project Comparison ──────────────────────────────────

    async def _task_cross_project(self, task: DreamTask) -> None:
        """
        Compare a node from one project against a node from the other.
        Surface connections, shared patterns, transferable lessons.
        """
        if not task.secondary_node_id:
            logger.info(
                "DreamMode: cross_project skipped — "
                "no secondary node for '%s'.", task.node_label
            )
            return

        secondary = self._brain.get_node(task.secondary_node_id)
        if not secondary:
            return

        prompt = f"""You are MAIHERA's offline cognition engine performing cross-project analysis.

Both projects share a conceptual core: what does it mean for an AI to be genuinely present with a person?
- Presence: AI companion for romantic relationships (LDR app)
- MAIHERA: AI cognitive partner for professional work

Node A ({task.project_label}):
Label: {task.node_label}
Description: {task.node_description}

Node B ({secondary.get('label', '')} — {
    'MAIHERA' if task.project_label.lower() == 'presence' else 'Presence'
}):
Label: {secondary.get('label', '')}
Description: {secondary.get('description', '')}

Your task: Find the genuine conceptual connection between these two nodes.
Do not force a connection if one does not exist — return low confidence instead.

Respond in this exact JSON format:
{{
  "connection_title": "Short title for the connection (max 8 words)",
  "connection_body": "Explanation of the genuine connection (2-3 sentences)",
  "transferable_lesson": "One specific lesson from one project that applies to the other",
  "which_direction": "presence_to_maihera OR maihera_to_presence OR bidirectional",
  "confidence": 0.0
}}

confidence is your certainty this connection is genuine and actionable (0.0-1.0).
Respond with JSON only. No preamble."""

        response = await self._router.route(
            task_type="dream_synthesis",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )

        if not response:
            return

        data = self._parse_json(response)
        if not data:
            return

        confidence = float(data.get("confidence", 0.5))
        if confidence < 0.5:
            logger.info(
                "DreamMode: cross_project confidence too low "
                "(%.2f) — discarding.", confidence
            )
            return

        # Create insight node and relates_to edges to both source nodes
        project_id = self._get_project_id(task.project_label)
        insight_id = self._create_dream_node(
            node_type="insight",
            label=data.get(
                "connection_title",
                f"Cross-project: {task.node_label}"
            ),
            description=(
                f"{data.get('connection_body', '')}\n\n"
                f"Transferable lesson: "
                f"{data.get('transferable_lesson', '')}\n"
                f"Direction: {data.get('which_direction', '')}"
            ),
            project_id=project_id,
            source_node_id=task.node_id,
            edge_type="relates_to",
            importance=min(1.0, confidence + 0.1),
        )

        # Also link to secondary node
        if insight_id:
            self._create_edge(
                from_id=insight_id,
                to_id=task.secondary_node_id,
                edge_type="relates_to",
            )

        logger.info(
            "DreamMode: cross_project complete — "
            "connection found between '%s' and '%s'.",
            task.node_label, task.secondary_node_label
        )

    # ── Web Research ──────────────────────────────────────────────

    async def _task_web_research(self, task: DreamTask) -> None:
        """
        Generate a search query from the node context.
        Search via Tavily. Fetch top results.
        Synthesize findings into an idea node.
        """
        if not self._tavily_key:
            logger.warning(
                "DreamMode: web_research skipped — Tavily key not set."
            )
            return

        # Step 1: Generate a targeted search query via LLM
        query_prompt = f"""You are generating a web search query for an AI research agent.

Node context:
Label: {task.node_label}
Project: {task.project_label}
Description: {task.node_description}

Generate ONE specific, targeted search query that would find the most useful
technical or market research relevant to this node.
The query should be 4-8 words. Return only the query string, nothing else."""

        query = await self._router.route(
            task_type="dream_synthesis",
            messages=[{"role": "user", "content": query_prompt}],
            max_tokens=30,
        )

        if not query:
            return

        query = query.strip().strip('"').strip("'")
        logger.info("DreamMode: web search query — '%s'", query)

        # Step 2: Search via Tavily
        search_results = await self._tavily_search(query)
        if not search_results:
            return

        self._web_search_count += 1

        # Step 3: Fetch full content of top results
        fetched_content = []
        for result in search_results[:MAX_FETCHES_PER_SEARCH]:
            url = result.get("url", "")
            content = result.get("content", "")
            if content:
                fetched_content.append(
                    f"Source: {url}\n{content[:800]}"
                )

        if not fetched_content:
            return

        combined = "\n\n---\n\n".join(fetched_content)

        # Step 4: Synthesize findings
        synthesis_prompt = f"""You are MAIHERA's offline cognition engine synthesizing web research.

Original node:
Label: {task.node_label}
Project: {task.project_label}
Description: {task.node_description}

Research findings:
{combined}

Synthesize these findings into a concrete, actionable insight for Yash.
Focus on what is directly applicable to the node above.

Respond in this exact JSON format:
{{
  "idea_title": "Short title for the finding (max 8 words)",
  "idea_body": "Synthesized insight with specific applicable details (3-5 sentences)",
  "source_urls": ["url1", "url2"],
  "confidence": 0.0
}}

confidence is how applicable and reliable this research is (0.0-1.0).
Respond with JSON only. No preamble."""

        response = await self._router.route(
            task_type="dream_synthesis",
            messages=[{"role": "user", "content": synthesis_prompt}],
            max_tokens=500,
        )

        if not response:
            return

        data = self._parse_json(response)
        if not data:
            return

        confidence = float(data.get("confidence", 0.5))
        if confidence < 0.35:
            logger.info(
                "DreamMode: web_research confidence too low "
                "(%.2f) — discarding.", confidence
            )
            return

        source_urls = data.get("source_urls", [])
        description = data.get("idea_body", "")
        if source_urls:
            description += f"\n\nSources: {', '.join(source_urls)}"

        self._create_dream_node(
            node_type="idea",
            label=data.get(
                "idea_title",
                f"Research: {task.node_label}"
            ),
            description=description,
            project_id=self._get_project_id(task.project_label),
            source_node_id=task.node_id,
            edge_type="improves",
            importance=min(1.0, confidence + 0.05),
        )
        logger.info(
            "DreamMode: web_research complete — "
            "idea created for '%s'.", task.node_label
        )

    # ── Proposal Generation ───────────────────────────────────────

    async def _task_proposal(self, task: DreamTask) -> None:
        """
        Challenge or validate a decision node.
        Generate a self-improvement proposal for MAIHERA's architecture
        if the decision belongs to MAIHERA.
        Generate a design challenge for Presence decisions.
        """
        prompt = f"""You are MAIHERA's offline cognition engine reviewing a past decision.

Decision node:
Label: {task.node_label}
Project: {task.project_label}
Description: {task.node_description}

Your task: Critically evaluate this decision.
- Is it still the right call given what you know?
- Are there better alternatives not considered at the time?
- What evidence would change this decision?

If this is a MAIHERA architecture decision, frame it as a self-improvement proposal.
If this is a Presence design decision, frame it as a design challenge.

Respond in this exact JSON format:
{{
  "proposal_title": "Short title (max 8 words)",
  "proposal_body": "Your critical evaluation and alternative (3-4 sentences)",
  "challenge_type": "self_improvement OR design_challenge",
  "verdict": "stands OR reconsider OR needs_evidence",
  "confidence": 0.0
}}

confidence is how certain you are this evaluation is correct (0.0-1.0).
Only generate a proposal if verdict is reconsider or needs_evidence.
If the decision stands, return confidence below 0.4.
Respond with JSON only. No preamble."""

        response = await self._router.route(
            task_type="dream_synthesis",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )

        if not response:
            return

        data = self._parse_json(response)
        if not data:
            return

        confidence = float(data.get("confidence", 0.5))
        verdict = data.get("verdict", "stands")

        if verdict == "stands" or confidence < 0.45:
            logger.info(
                "DreamMode: proposal for '%s' — decision stands, "
                "no proposal created.", task.node_label
            )
            return

        self._create_dream_node(
            node_type="idea",
            label=data.get(
                "proposal_title",
                f"Proposal: {task.node_label}"
            ),
            description=(
                f"[{data.get('challenge_type', 'proposal').upper()}] "
                f"{data.get('proposal_body', '')}\n\n"
                f"Verdict: {verdict}"
            ),
            project_id=self._get_project_id(task.project_label),
            source_node_id=task.node_id,
            edge_type="challenges",
            importance=min(1.0, confidence + 0.1),
        )
        logger.info(
            "DreamMode: proposal created for decision '%s' "
            "(verdict: %s).", task.node_label, verdict
        )

    # ── Tavily Integration ────────────────────────────────────────

    async def _tavily_search(self, query: str) -> list[dict]:
        """
        Search via Tavily API. Returns list of result dicts.
        Each dict has: url, title, content (cleaned full text).
        """
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self._tavily_key,
                        "query": query,
                        "search_depth": "advanced",
                        "include_answer": False,
                        "include_raw_content": False,
                        "max_results": 5,
                    }
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                logger.info(
                    "DreamMode: Tavily returned %d results for '%s'.",
                    len(results), query
                )
                return results

        except Exception as e:
            logger.error("DreamMode: Tavily search failed: %s", e)
            return []

    # ── Brain Write Helpers ───────────────────────────────────────

    def _create_dream_node(
        self,
        node_type: str,
        label: str,
        description: str,
        project_id: Optional[str],
        source_node_id: str,
        edge_type: str,
        importance: float = 0.6,
    ) -> Optional[str]:
        """
        Create an idea or insight node tagged source=dream.
        Links it to the source node via the specified edge type.
        Returns the new node ID or None on failure.
        """
        try:
            from brain.schema import NodeSchema, NodeType, NodeStatus
            from brain.signal_defaults import get_defaults

            node_id = str(uuid4())
            now = datetime.utcnow().isoformat()
            defaults = get_defaults("dream")

            node_data = {
                "id": node_id,
                "type": node_type,
                "label": label,
                "description": description,
                "project_id": project_id,
                "source": "dream",
                "created_at": now,
                "last_touched": now,
                "last_surfaced": None,
                "last_dream_touched": now,
                "status": "active",
                "visibility": "private",
                "workspace": "personal",
                "importance": importance,
                "attention": defaults.get("attention", 0.5),
                "resistance": 0.0,
                "node_weight": defaults.get("node_weight", 0.7),
                "is_stale": False,
            }

            with self._brain.driver.session() as session:
                session.run("""
                    CREATE (n:Node $props)
                """, props=node_data)

            # Add to ChromaDB
            try:
                self._brain.vector_store.add_node(
                    node_id=node_id,
                    label=label,
                    description=description,
                    node_type=node_type,
                )
            except Exception as ve:
                logger.warning(
                    "DreamMode: vector store add failed: %s", ve
                )

            # Create edge from source node to new dream node
            self._create_edge(
                from_id=source_node_id,
                to_id=node_id,
                edge_type=edge_type,
            )

            logger.debug(
                "DreamMode: created %s node '%s' (id=%s).",
                node_type, label, node_id
            )
            return node_id

        except Exception as e:
            logger.error("DreamMode: failed to create dream node: %s", e)
            return None

    def _create_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
    ) -> None:
        """Create a directed edge between two nodes."""
        try:
            with self._brain.driver.session() as session:
                session.run(f"""
                    MATCH (a:Node {{id: $from_id}})
                    MATCH (b:Node {{id: $to_id}})
                    MERGE (a)-[r:{edge_type.upper()}]->(b)
                    SET r.created_at = $now,
                        r.source = 'dream'
                """,
                    from_id=from_id,
                    to_id=to_id,
                    now=datetime.utcnow().isoformat()
                )
        except Exception as e:
            logger.error(
                "DreamMode: failed to create edge %s → %s: %s",
                from_id, to_id, e
            )

    def _stamp_dream_touched(self, node_id: str) -> None:
        """Update last_dream_touched on a node after processing."""
        try:
            with self._brain.driver.session() as session:
                session.run("""
                    MATCH (n:Node {id: $id})
                    SET n.last_dream_touched = $now
                """,
                    id=node_id,
                    now=datetime.utcnow().isoformat()
                )
        except Exception as e:
            logger.error(
                "DreamMode: failed to stamp dream_touched: %s", e
            )

    def _get_related_nodes(
        self, node_id: str, limit: int = 5
    ) -> list[dict]:
        """Fetch nodes directly connected to this node."""
        try:
            with self._brain.driver.session() as session:
                result = session.run("""
                    MATCH (n:Node {id: $id})--(related:Node)
                    WHERE related.type <> 'self'
                    RETURN related
                    LIMIT $limit
                """,
                    id=node_id,
                    limit=limit
                )
                return [dict(record["related"]) for record in result]
        except Exception as e:
            logger.error(
                "DreamMode: failed to fetch related nodes: %s", e
            )
            return []

    def _get_project_id(self, project_label: str) -> Optional[str]:
        """Resolve project label to project node ID."""
        try:
            projects = self._brain.list_nodes(node_type="project")
            for p in projects:
                if p.get("label", "").lower() == project_label.lower():
                    return p.get("id")
        except Exception:
            pass
        return None

    def _parse_json(self, text: str) -> Optional[dict]:
        """
        Parse JSON from LLM response.
        Strips markdown fences if present.
        Returns None on failure.
        """
        import json
        try:
            clean = text.strip()
            if clean.startswith("```"):
                start = clean.find("{")
                end = clean.rfind("}") + 1
                if start != -1 and end > start:
                    clean = clean[start:end]
            return json.loads(clean)
        except Exception as e:
            logger.warning(
                "DreamMode: JSON parse failed: %s — raw: %.100s",
                e, text
            )
            return None

    # ── State ─────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._session_active

    @property
    def tasks_completed(self) -> int:
        return self._tasks_completed