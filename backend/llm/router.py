"""
MAIHERA LLM Layer — Router
Routes inference requests to optimal model based on task type.
Primary: Ollama Cloud. Fallback: Groq.
Tracks quota per provider and cascades automatically.
Never drops a request silently.
"""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import httpx
from groq import Groq

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """Raised when all providers are exhausted or failing."""
    pass


# ── Provider Configuration ────────────────────────────────────────────

OLLAMA_MODELS = {
    'signal_update':      'gpt-oss:20b-cloud',
    'classification':     'gpt-oss:20b-cloud',
    'conversation':       'gpt-oss:120b-cloud',
    'task_decomposition': 'gpt-oss:120b-cloud',
    'code_analysis':      'qwen3-coder:480b-cloud',
    'dream_mode':         'deepseek-v3.1:671b-cloud',
    'vision':             'qwen3-vl:235b-cloud',
    'default':            'gpt-oss:120b-cloud',
}

GROQ_MODELS = {
    'signal_update':      'llama-3.1-8b-instant',
    'classification':     'llama-3.1-8b-instant',
    'conversation':       'llama-3.3-70b-versatile',
    'task_decomposition': 'llama-3.3-70b-versatile',
    'code_analysis':      'llama-3.3-70b-versatile',
    'dream_mode':         'llama-3.3-70b-versatile',
    'vision':             'llama-3.3-70b-versatile',
    'default':            'llama-3.3-70b-versatile',
}

# Task type → provider order (primary first, fallback second)
ROUTING_TABLE = {
    'signal_update':      ['ollama', 'groq'],
    'classification':     ['ollama', 'groq'],
    'conversation':       ['ollama', 'groq'],
    'task_decomposition': ['ollama', 'groq'],
    'code_analysis':      ['ollama', 'groq'],
    'dream_mode':         ['ollama', 'groq'],
    'vision':             ['ollama', 'groq'],
    'default':            ['ollama', 'groq'],
}


class LLMRouter:
    """
    Routes LLM inference to optimal provider based on task type.
    Tracks quota per provider per session window.
    Cascades to fallback automatically on quota exhaustion or error.
    """

    def __init__(self):
        # Ollama cloud config
        self.ollama_base_url = os.getenv(
            'OLLAMA_CLOUD_BASE_URL', 'https://ollama.com/api'
        )
        self.ollama_api_key = os.getenv('OLLAMA_CLOUD_API_KEY', '')
        self.ollama_session_cap = int(
            os.getenv('OLLAMA_CLOUD_SESSION_CAP', '20')
        )

        # Groq config
        self.groq_client = Groq(
            api_key=os.getenv('GROQ_API_KEY', '')
        )
        self.groq_daily_cap = 200  # conservative — actual is 6000/day

        # Quota tracking — resets on scheduler tick
        self._ollama_session_count = 0
        self._ollama_session_start = datetime.utcnow()
        self._groq_daily_count = 0
        self._groq_day_start = datetime.utcnow().date()

        # Request history for logging
        self._request_log: list[dict] = []

    # ── Quota Management ──────────────────────────────────────────

    def _check_ollama_quota(self) -> bool:
        """
        Check if Ollama cloud has remaining session quota.
        Resets counter every 3 hours (session window).
        """
        now = datetime.utcnow()
        window = timedelta(hours=3)
        if now - self._ollama_session_start > window:
            self._ollama_session_count = 0
            self._ollama_session_start = now
            logger.info("Ollama session quota reset.")

        remaining = self.ollama_session_cap - self._ollama_session_count
        if remaining <= 0:
            logger.warning(
                "Ollama session quota exhausted (%d/%d). "
                "Routing to fallback.",
                self._ollama_session_count,
                self.ollama_session_cap
            )
            return False
        return True

    def _check_groq_quota(self) -> bool:
        """
        Check if Groq has remaining daily quota.
        Resets counter at midnight UTC.
        """
        today = datetime.utcnow().date()
        if today != self._groq_day_start:
            self._groq_daily_count = 0
            self._groq_day_start = today
            logger.info("Groq daily quota reset.")

        if self._groq_daily_count >= self.groq_daily_cap:
            logger.warning(
                "Groq daily quota exhausted (%d/%d).",
                self._groq_daily_count,
                self.groq_daily_cap
            )
            return False
        return True

    def _increment_ollama(self) -> None:
        self._ollama_session_count += 1

    def _increment_groq(self) -> None:
        self._groq_daily_count += 1

    def reset_daily_quotas(self) -> None:
        """Reset all daily counters. Called by scheduler at midnight."""
        self._groq_daily_count = 0
        self._groq_day_start = datetime.utcnow().date()
        logger.info("Daily quotas reset.")

    # ── Provider Calls ────────────────────────────────────────────

    async def _call_ollama(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        task_type: str
    ) -> str:
        """
        Call Ollama cloud API.
        Uses Ollama's native /api/chat format (not OpenAI-compatible).
        """
        model = OLLAMA_MODELS.get(task_type, OLLAMA_MODELS['default'])

        full_messages = []
        if system_prompt:
            full_messages.append({
                'role': 'system',
                'content': system_prompt
            })
        full_messages.extend(messages)

        payload = {
            'model': model,
            'messages': full_messages,
            'stream': False,
            'options': {'num_predict': max_tokens}
        }

        headers = {
            'Authorization': f'Bearer {self.ollama_api_key}',
            'Content-Type': 'application/json'
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f'{self.ollama_base_url}/chat',
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            content = data['message']['content']
            self._increment_ollama()
            logger.debug(
                "Ollama [%s] responded (%d chars).",
                model, len(content)
            )
            return content

    def _call_groq(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        task_type: str
    ) -> str:
        """
        Call Groq API using the official Groq SDK.
        Groq uses OpenAI-compatible format.
        """
        model = GROQ_MODELS.get(task_type, GROQ_MODELS['default'])

        full_messages = []
        if system_prompt:
            full_messages.append({
                'role': 'system',
                'content': system_prompt
            })
        full_messages.extend(messages)

        response = self.groq_client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=0.7
        )
        content = response.choices[0].message.content
        self._increment_groq()
        logger.debug(
            "Groq [%s] responded (%d chars).",
            model, len(content)
        )
        return content

    # ── Main Router ───────────────────────────────────────────────

    async def route(
        self,
        task_type: str,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000
    ) -> str:
        """
        Route an inference request to the optimal provider.
        Checks quota, tries primary, cascades to fallback.
        Raises LLMUnavailableError if all providers fail.
        Logs every request for observability.
        """
        providers = ROUTING_TABLE.get(
            task_type, ROUTING_TABLE['default']
        )
        start_time = datetime.utcnow()
        last_error = None

        for provider in providers:
            try:
                if provider == 'ollama':
                    if not self._check_ollama_quota():
                        logger.info(
                            "Skipping Ollama — quota exhausted. "
                            "Trying next provider."
                        )
                        continue
                    result = await self._call_ollama(
                        messages, system_prompt,
                        max_tokens, task_type
                    )

                elif provider == 'groq':
                    if not self._check_groq_quota():
                        logger.info(
                            "Skipping Groq — quota exhausted. "
                            "Trying next provider."
                        )
                        continue
                    result = self._call_groq(
                        messages, system_prompt,
                        max_tokens, task_type
                    )

                else:
                    continue

                # Log successful request
                elapsed = (datetime.utcnow() - start_time
                           ).total_seconds()
                self._request_log.append({
                    'task_type': task_type,
                    'provider': provider,
                    'elapsed_seconds': elapsed,
                    'timestamp': start_time.isoformat(),
                    'success': True
                })
                logger.info(
                    "LLM route: task=%s provider=%s "
                    "elapsed=%.2fs",
                    task_type, provider, elapsed
                )
                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider '%s' failed for task '%s': %s. "
                    "Trying next provider.",
                    provider, task_type, e
                )
                self._request_log.append({
                    'task_type': task_type,
                    'provider': provider,
                    'error': str(e),
                    'timestamp': start_time.isoformat(),
                    'success': False
                })
                continue

        # All providers failed
        error_msg = (
            f"All LLM providers exhausted for task '{task_type}'. "
            f"Last error: {last_error}. "
            f"Ollama session: {self._ollama_session_count}/"
            f"{self.ollama_session_cap}. "
            f"Groq daily: {self._groq_daily_count}/"
            f"{self.groq_daily_cap}."
        )
        logger.critical(error_msg)
        raise LLMUnavailableError(error_msg)

    def get_quota_status(self) -> dict:
        """Return current quota status for health checks."""
        return {
            'ollama': {
                'session_used': self._ollama_session_count,
                'session_cap': self.ollama_session_cap,
                'session_remaining': max(
                    0,
                    self.ollama_session_cap - self._ollama_session_count
                ),
                'window_started': self._ollama_session_start.isoformat()
            },
            'groq': {
                'daily_used': self._groq_daily_count,
                'daily_cap': self.groq_daily_cap,
                'daily_remaining': max(
                    0,
                    self.groq_daily_cap - self._groq_daily_count
                ),
                'day_started': str(self._groq_day_start)
            }
        }

    def get_request_log(self, last_n: int = 20) -> list[dict]:
        """Return the last N request log entries."""
        return self._request_log[-last_n:]


if __name__ == "__main__":
    import asyncio
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    async def test_router():
        print("Testing MAIHERA LLM Router...")
        router = LLMRouter()

        # Test 1: Quota status
        print("\n[1] Quota status...")
        status = router.get_quota_status()
        print(f"    Ollama remaining: "
              f"{status['ollama']['session_remaining']}")
        print(f"    Groq remaining: "
              f"{status['groq']['daily_remaining']}")

        # Test 2: Groq call (uses Groq quota, not Ollama)
        print("\n[2] Testing Groq provider directly...")
        result = router._call_groq(
            messages=[{
                'role': 'user',
                'content': (
                    'Reply with exactly this text and nothing else: '
                    'MAIHERA router test successful'
                )
            }],
            system_prompt=None,
            max_tokens=20,
            task_type='conversation'
        )
        print(f"    Groq response: {result.strip()}")
        assert len(result) > 0, "Empty response from Groq"
        print("    Groq call: OK")

        # Test 3: Route via Groq by exhausting Ollama quota
        print("\n[3] Testing cascade routing...")
        router._ollama_session_count = router.ollama_session_cap
        result = await router.route(
            task_type='conversation',
            messages=[{
                'role': 'user',
                'content': (
                    'Reply with exactly: cascade test OK'
                )
            }],
            max_tokens=20
        )
        print(f"    Cascade result: {result.strip()}")
        assert len(result) > 0
        print("    Cascade routing: OK")

        # Reset for next test
        router._ollama_session_count = 0

        # Test 4: Request log
        print("\n[4] Request log...")
        log = router.get_request_log()
        print(f"    Log entries: {len(log)}")
        assert len(log) >= 1
        for entry in log:
            print(f"    [{entry['provider']}] "
                  f"task={entry['task_type']} "
                  f"success={entry['success']}")
        print("    Request log: OK")

        print("\n✅ LLM Router test PASSED — all 4 checks OK")
        print("\nFinal quota status:")
        final = router.get_quota_status()
        print(f"  Ollama used: {final['ollama']['session_used']}")
        print(f"  Groq used: {final['groq']['daily_used']}")

    asyncio.run(test_router())