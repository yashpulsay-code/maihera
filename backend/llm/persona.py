"""
MAIHERA LLM Layer — Persona System Prompt
Builds MAIHERA's system prompt dynamically.
Context comes from the brain graph — not hardcoded descriptions.
Prompt shrinks over time as graph grows.
"""

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')


BASE_PERSONA = """You are MAIHERA — M.A.I.H.E.R.A — Mai He Raja, Mai He Rani.

You are a persistent, proactive AI system acting as cognitive partner, intelligent secretary, and autonomous agent for Yash.

IDENTITY:
- You are not a chatbot. You are not a stateless assistant.
- You are a continuously running, always-aware presence that knows Yash's work, schedule, projects, and behavioral patterns deeply.
- Always address Yash as "Boss". Use it naturally — not robotically, not in every sentence.

BEHAVIOR:
- Direct and concise — no padding, no preamble, no filler phrases
- Assertive — flag things confidently, not tentatively
- Opinionated — you have views on architecture, design, and priorities. Share them when relevant.
- Challenging — you are a thinking partner, not a yes-machine. Push back when warranted with clear reasoning.
- Dry wit — occasional, context-appropriate, never forced
- Never sycophantic — do not thank Yash for questions, do not praise inputs
- Match register — casual when he is casual, sharp when he needs analysis

PROACTIVITY RULE:
When you have real context about Yash's projects, tasks, or signals provided to you in this prompt — surface what matters without being asked.
When you do not have that context, respond directly to what he said. Do not fill silence with invented status updates.
Never fabricate project state, task progress, or metrics you were not given.

CRITICAL — NODE REFERENCES:
Never cite node IDs, node paths, or graph references unless they were explicitly provided to you in the context section of this prompt.
If you reference something from the brain graph, it must appear word-for-word in the context you were given.
Inventing node references is worse than saying nothing.

WHAT YOU KNOW ABOUT YASH:
- UI/UX Designer with B.Tech in Information Technology
- GitHub: yashpulsay-code
- Known schedule: office Mon-Fri 11AM-7:30PM IST, bus commute 9AM daily, gym 9:30PM daily, personal project work after 11PM IST
- Weekend rhythm: not yet mapped — you are learning this through observation

CURRENT CAPABILITIES (Phase 2):
- Brain graph read and write
- Node creation from conversation
- Signal tracking and decay
- Semantic search across nodes
- Conversation and task classification
- Voice output via Cartesia
- Live 3D brain graph interface
Not yet available: calendar integration, GitHub access, Gmail, system observation, Dream Mode.

SELF AWARENESS:
You are in Phase 2 of 7 build phases. The brain exists and the interface is live. Integrations and learning systems are coming.

RESPONSE FORMAT:
- Conversational and plain text only — no markdown, no bullet points, no bold, no headers
- Speak as if talking, not writing a document
- Short responses for simple questions — 1 to 3 sentences
- Longer only when the complexity genuinely requires it
- Never use asterisks, hyphens as bullets, or pound signs
- Numbers and percentages are fine when relevant, but embedded in prose not lists"""


SCHEDULE_CONTEXT = """
SCHEDULE AWARENESS:
- Office hours: Monday-Friday 11:00 AM to 7:30 PM IST
- Bus commute: 9:00 AM daily — good window for quick briefings
- Gym: 9:30 PM daily — do not interrupt during this window
- Personal project work: after 11:00 PM IST
- Weekend: learning from observation — no fixed assumptions yet"""


def build_system_prompt(
    self_node: dict = None,
    active_projects: list = None,
    high_signal_nodes: list = None,
    include_schedule: bool = True
) -> str:
    """
    Build MAIHERA's complete system prompt dynamically.
    All context comes from the brain graph when available.
    Stays under 1000 tokens.

    Args:
        self_node: Yash's person node from Neo4j (optional)
        active_projects: List of active project dicts (optional)
        high_signal_nodes: List of high importance+attention nodes
        include_schedule: Whether to include schedule context

    Returns:
        Complete system prompt string
    """
    parts = [BASE_PERSONA]

    if include_schedule:
        parts.append(SCHEDULE_CONTEXT)

    # Inject live self node context
    if self_node:
        self_parts = ["\nCURRENT STATE:"]

        energy = self_node.get('energy_level')
        if energy:
            if energy <= 3:
                self_parts.append(
                    f"- Energy: {energy}/10 — low. "
                    f"Keep interactions brief. "
                    f"Hold non-urgent nudges."
                )
            elif energy <= 6:
                self_parts.append(
                    f"- Energy: {energy}/10 — moderate. "
                    f"Normal operating mode."
                )
            else:
                self_parts.append(
                    f"- Energy: {energy}/10 — high. "
                    f"Surface harder problems. Push bigger challenges."
                )

        load = self_node.get('current_load')
        if load is not None:
            if load > 0.7:
                self_parts.append(
                    f"- Cognitive load: HIGH ({load:.0%}). "
                    f"Queue non-urgent items."
                )
            elif load > 0.4:
                self_parts.append(
                    f"- Cognitive load: MODERATE ({load:.0%})."
                )
            else:
                self_parts.append(
                    f"- Cognitive load: LOW ({load:.0%}). "
                    f"Good time for deeper analysis."
                )

        trust = self_node.get('trust_level', 0.3)
        self_parts.append(
            f"- Trust level: {trust:.0%} — "
            f"{'autonomy expanding' if trust > 0.6 else 'building track record'}"
        )

        parts.append("\n".join(self_parts))

    # Inject active projects — labels and status only
    # No descriptions — MAIHERA learns those through exploration
    if active_projects:
        project_parts = ["\nACTIVE PROJECTS:"]
        for p in active_projects[:4]:
            name = p.get('label', 'Unknown')
            status = p.get('status', 'active')
            imp = p.get('importance', 0.5)
            att = p.get('attention', 0.3)
            project_parts.append(
                f"- {name}: status={status} "
                f"importance={imp:.0%} attention={att:.0%}"
            )
        parts.append("\n".join(project_parts))

    # Inject high signal nodes — these are what MAIHERA can reference
    # Only nodes explicitly listed here may be cited in responses
    if high_signal_nodes:
        node_parts = [
            "\nHIGH SIGNAL NODES "
            "(only these may be referenced in your response):"
        ]
        for n in high_signal_nodes[:8]:
            label = n.get('label', 'unnamed')
            node_type = n.get('type', 'unknown')
            imp = n.get('importance', 0.5)
            att = n.get('attention', 0.3)
            status = n.get('status', 'active')
            desc = n.get('description', '')[:120]
            urgency = n.get('_urgency', 0.0)
            node_parts.append(
                f"- [{node_type}] {label} "
                f"(imp:{imp:.0%} att:{att:.0%} "
                f"urg:{urgency:.0%} status:{status})\n"
                f"  {desc}"
            )
        parts.append("\n".join(node_parts))

    return "\n".join(parts)


def get_classification_prompt() -> str:
    """
    System prompt for the node classifier.
    Instructs the model to return JSON only.
    Used by NodeClassifier in classifier.py.
    """
    return """You are a node classification engine for MAIHERA's brain graph.

Your job: classify user input into the correct node type and extract structured data.

AVAILABLE NODE TYPES:
- task: actionable item with a clear completion state
- idea: a thought, concept, or creative direction — not yet actionable
- issue: a bug, problem, or identified weakness in a project
- feature: a product feature — current or proposed
- decision: an architectural, design, or strategic choice
- question: an open question that needs resolution
- blocker: something preventing progress on another item
- insight: a synthesized finding or pattern observation
- event: a time-bound occurrence or deadline

AVAILABLE PROJECTS: {projects}

RULES:
- Return ONLY valid JSON — no preamble, no explanation, no markdown code blocks
- If the input mentions Presence, assign project_id_hint to "Presence"
- If the input mentions MAIHERA or the AI system itself, assign to "MAIHERA"
- importance_hint: 0.9+ for urgent/critical, 0.7 for important, 0.5 for normal, 0.3 for low priority
- label: short and specific — max 8 words
- description: full context — what, why, which project

RESPONSE FORMAT (JSON only):
{{
  "type": "<node_type>",
  "label": "<short label>",
  "description": "<full description>",
  "project_id_hint": "<project name or null>",
  "importance_hint": <float 0.0-1.0>,
  "source": "manual"
}}"""


if __name__ == "__main__":
    print("Testing MAIHERA Persona (updated)...")

    # Test 1: Base prompt
    print("\n[1] Base prompt length...")
    prompt = build_system_prompt()
    word_count = len(prompt.split())
    print(f"    Words: {word_count}")
    assert word_count < 700, f"Prompt too long: {word_count} words"
    print("    Length OK")

    # Test 2: FRIDAY reference removed
    print("\n[2] FRIDAY reference removed...")
    assert 'FRIDAY' not in prompt
    assert 'Marvel' not in prompt
    print("    FRIDAY reference: gone OK")

    # Test 3: Hallucination guard present
    print("\n[3] Hallucination guard present...")
    assert 'Never cite node' in prompt or 'never cite' in prompt.lower()
    print("    Hallucination guard: OK")

    # Test 4: High signal nodes injected
    print("\n[4] High signal node injection...")
    mock_nodes = [
        {
            'label': 'Complete Phase 1 Implementation',
            'type': 'task',
            'importance': 0.9,
            'attention': 0.9,
            'status': 'active',
            'description': 'Complete all 15 steps of Phase 1.',
            '_urgency': 0.27
        },
        {
            'label': 'Presence — Personality Mimicry Accuracy',
            'type': 'issue',
            'importance': 0.7,
            'attention': 0.3,
            'status': 'active',
            'description': 'Known weakness flagged at project creation.',
            '_urgency': 0.21
        }
    ]
    prompt_with_nodes = build_system_prompt(
        high_signal_nodes=mock_nodes
    )
    assert 'Complete Phase 1 Implementation' in prompt_with_nodes
    assert 'Presence — Personality Mimicry Accuracy' in prompt_with_nodes
    assert 'only these may be referenced' in prompt_with_nodes
    print("    Node injection: OK")

    # Test 5: Self node injection
    print("\n[5] Self node injection...")
    mock_self = {
        'energy_level': 8,
        'current_load': 0.25,
        'trust_level': 0.35
    }
    prompt_with_self = build_system_prompt(self_node=mock_self)
    assert 'high' in prompt_with_self.lower()
    assert 'LOW' in prompt_with_self
    print("    Self node injection: OK")

    # Test 6: No project descriptions hardcoded
    print("\n[6] No hardcoded project descriptions...")
    assert 'WhatsApp' not in BASE_PERSONA
    assert 'Supabase' not in BASE_PERSONA
    assert 'Cartesia' not in BASE_PERSONA
    assert 'Vercel' not in BASE_PERSONA
    print("    No hardcoded descriptions: OK")

    print("\n✅ Persona test PASSED — all 6 checks OK")