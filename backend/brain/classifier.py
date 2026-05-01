"""
MAIHERA Brain Layer — Node Classifier
Classifies raw user input into the correct node type
for the brain graph using LLM inference.
Zero Ollama quota used in tests — Groq only.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)

# Fallback classification when LLM is unavailable
FALLBACK_CLASSIFICATION = {
    'type': 'task',
    'label': 'Unclassified item',
    'description': '',
    'project_id_hint': None,
    'importance_hint': 0.5,
    'source': 'manual'
}

# Keyword hints for lightweight pre-classification
TYPE_KEYWORDS = {
    'issue': [
        'bug', 'broken', 'fix', 'error', 'problem',
        'wrong', 'failing', 'crash', 'not working'
    ],
    'idea': [
        'idea', 'what if', 'maybe', 'could we', 'thinking about',
        'consider', 'explore', 'concept', 'imagine'
    ],
    'feature': [
        'feature', 'add', 'build', 'implement', 'create',
        'integrate', 'support', 'enable', 'allow'
    ],
    'question': [
        'how do', 'should we', 'which', 'why is',
        'what is', 'wondering', 'unclear', 'not sure'
    ],
    'decision': [
        'decided', 'going with', 'choosing', 'we will use',
        'architecture', 'decided to', 'final choice'
    ],
    'blocker': [
        'blocked', 'waiting on', 'cannot proceed',
        'stuck on', 'dependency', 'need before'
    ],
}

PROJECT_KEYWORDS = {
    'Presence': [
        'presence', 'companion', 'girlfriend', 'whatsapp',
        'cartesia', 'supabase', 'voice clone', 'personality'
    ],
    'MAIHERA': [
        'maihera', 'brain', 'graph', 'neo4j', 'signal',
        'decay', 'orchestrator', 'phase', 'llm router'
    ],
}


class NodeClassifier:
    """
    Classifies raw user input into structured node data
    for the MAIHERA brain graph.

    Two-stage classification:
    1. Keyword pre-scan — fast, zero API cost
    2. LLM classification — accurate, uses Groq fallback

    The LLM stage uses Groq directly (not Ollama) to preserve
    Ollama quota for higher-value tasks.
    """

    def __init__(self, llm_router=None):
        self.router = llm_router

    def _keyword_prescan(
        self,
        text: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Fast keyword scan to get type and project hints.
        Returns (type_hint, project_hint) — either can be None.
        Used to validate or seed the LLM classification.
        """
        text_lower = text.lower()

        type_hint = None
        for node_type, keywords in TYPE_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                type_hint = node_type
                break

        project_hint = None
        for project, keywords in PROJECT_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                project_hint = project
                break

        return type_hint, project_hint

    def _parse_llm_response(self, response: str) -> Optional[dict]:
        """
        Parse JSON from LLM response.
        Handles responses with or without markdown code fences.
        Returns None if parsing fails.
        """
        # Strip markdown code fences if present
        clean = re.sub(r'```(?:json)?\s*', '', response)
        clean = clean.replace('```', '').strip()

        # Find JSON object in response
        start = clean.find('{')
        end = clean.rfind('}')
        if start == -1 or end == -1:
            logger.warning(
                "No JSON object found in LLM response: %s",
                response[:100]
            )
            return None

        try:
            parsed = json.loads(clean[start:end + 1])
            return parsed
        except json.JSONDecodeError as e:
            logger.warning("JSON parse error: %s", e)
            return None

    def _validate_classification(self, data: dict) -> dict:
        """
        Validate and sanitize a classification result.
        Ensures all required fields exist with valid values.
        """
        valid_types = {
            'task', 'idea', 'issue', 'feature', 'decision',
            'question', 'blocker', 'insight', 'event'
        }

        node_type = data.get('type', 'task')
        if node_type not in valid_types:
            node_type = 'task'

        importance = float(data.get('importance_hint', 0.5))
        importance = max(0.0, min(1.0, importance))

        return {
            'type': node_type,
            'label': str(data.get('label', 'Unnamed item'))[:80],
            'description': str(data.get('description', '')),
            'project_id_hint': data.get('project_id_hint'),
            'importance_hint': importance,
            'source': 'manual'
        }

    async def classify(
        self,
        user_input: str,
        available_projects: list[str]
    ) -> dict:
        """
        Classify raw user input into structured node data.

        Args:
            user_input: Raw text from Yash
            available_projects: List of project names from brain

        Returns:
            Dict with: type, label, description,
                       project_id_hint, importance_hint, source
        """
        if not user_input or not user_input.strip():
            return FALLBACK_CLASSIFICATION.copy()

        # Stage 1: Keyword prescan
        type_hint, project_hint = self._keyword_prescan(user_input)
        logger.debug(
            "Prescan hints — type: %s, project: %s",
            type_hint, project_hint
        )

        # Stage 2: LLM classification
        if self.router:
            try:
                from llm.persona import get_classification_prompt

                projects_str = ', '.join(available_projects) \
                    if available_projects else 'Presence, MAIHERA'

                system_prompt = get_classification_prompt().format(
                    projects=projects_str
                )

                messages = [{
                    'role': 'user',
                    'content': (
                        f'Classify this input from Yash:\n\n'
                        f'"{user_input}"\n\n'
                        f'Keyword hints (use as guidance, not gospel):\n'
                        f'- Likely type: {type_hint or "unknown"}\n'
                        f'- Likely project: {project_hint or "unknown"}'
                    )
                }]

                # Force Groq by temporarily maxing Ollama counter
                original_count = self.router._ollama_session_count
                self.router._ollama_session_count = (
                    self.router.ollama_session_cap
                )

                response = await self.router.route(
                    task_type='classification',
                    messages=messages,
                    system_prompt=system_prompt,
                    max_tokens=300
                )

                # Restore Ollama counter
                self.router._ollama_session_count = original_count

                parsed = self._parse_llm_response(response)
                if parsed:
                    result = self._validate_classification(parsed)
                    logger.info(
                        "Classified '%s...' as %s under %s",
                        user_input[:30],
                        result['type'],
                        result['project_id_hint']
                    )
                    return result

            except Exception as e:
                logger.warning(
                    "LLM classification failed, "
                    "falling back to keyword hints: %s", e
                )

        # Stage 3: Keyword-only fallback
        fallback = FALLBACK_CLASSIFICATION.copy()
        fallback['description'] = user_input
        fallback['label'] = user_input[:60]
        if type_hint:
            fallback['type'] = type_hint
        if project_hint:
            fallback['project_id_hint'] = project_hint

        logger.info(
            "Keyword fallback classification: type=%s project=%s",
            fallback['type'], fallback['project_id_hint']
        )
        return fallback


if __name__ == "__main__":
    import asyncio
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    async def test_classifier():
        print("Testing MAIHERA NodeClassifier...")

        # Test 1: Keyword prescan only (no LLM)
        print("\n[1] Keyword prescan test...")
        classifier = NodeClassifier(llm_router=None)

        type_hint, project_hint = classifier._keyword_prescan(
            "there is a bug in the Presence personality system"
        )
        assert type_hint == 'issue', f"Expected issue, got {type_hint}"
        assert project_hint == 'Presence', \
            f"Expected Presence, got {project_hint}"
        print(f"    Type hint: {type_hint} OK")
        print(f"    Project hint: {project_hint} OK")

        # Test 2: Fallback classification (no LLM)
        print("\n[2] Fallback classification (no LLM)...")
        result = await classifier.classify(
            "Fix the memory leak in Presence Supabase connection",
            available_projects=['Presence', 'MAIHERA']
        )
        print(f"    Type: {result['type']}")
        print(f"    Project hint: {result['project_id_hint']}")
        print(f"    Importance: {result['importance_hint']}")
        assert result['type'] in {
            'task', 'issue', 'feature', 'idea',
            'decision', 'question', 'blocker'
        }
        print("    Fallback classification OK")

        # Test 3: JSON parsing
        print("\n[3] JSON parsing test...")
        raw_json = '''{
            "type": "issue",
            "label": "Supabase memory leak",
            "description": "Memory leak in Presence Supabase connection",
            "project_id_hint": "Presence",
            "importance_hint": 0.8,
            "source": "manual"
        }'''
        parsed = classifier._parse_llm_response(raw_json)
        assert parsed is not None
        assert parsed['type'] == 'issue'
        print(f"    Parsed type: {parsed['type']} OK")

        # Test 4: JSON parsing with markdown fences
        print("\n[4] Markdown fence stripping...")
        fenced = '```json\n' + raw_json + '\n```'
        parsed_fenced = classifier._parse_llm_response(fenced)
        assert parsed_fenced is not None
        assert parsed_fenced['type'] == 'issue'
        print("    Fence stripping OK")

        # Test 5: Validation sanitization
        print("\n[5] Validation sanitization...")
        bad_data = {
            'type': 'invalid_type',
            'importance_hint': 1.5,
            'label': 'x' * 200
        }
        validated = classifier._validate_classification(bad_data)
        assert validated['type'] == 'task'
        assert validated['importance_hint'] <= 1.0
        assert len(validated['label']) <= 80
        print("    Sanitization OK")

        # Test 6: LLM classification via Groq
        print("\n[6] LLM classification via Groq...")
        from llm.router import LLMRouter
        router = LLMRouter()
        classifier_with_llm = NodeClassifier(llm_router=router)

        result_llm = await classifier_with_llm.classify(
            "I need to fix the personality mimicry accuracy "
            "problem in Presence — the AI does not sound like me",
            available_projects=['Presence', 'MAIHERA']
        )
        print(f"    Type: {result_llm['type']}")
        print(f"    Label: {result_llm['label']}")
        print(f"    Project: {result_llm['project_id_hint']}")
        print(f"    Importance: {result_llm['importance_hint']}")
        assert result_llm['type'] in {
            'task', 'issue', 'feature', 'idea',
            'decision', 'question', 'blocker'
        }
        assert len(result_llm['label']) > 0
        print("    LLM classification OK")

        print("\n✅ NodeClassifier test PASSED — all 6 checks OK")

    asyncio.run(test_classifier())