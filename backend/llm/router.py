"""
MAIHERA LLM Layer — Router
Routes inference requests to optimal model based on task type.
Providers: Ollama Cloud, Groq, Gemini 2.5 Flash, Gemini 2.0 Flash, OpenRouter.
Tracks daily quota and per-minute rate limits per provider.
Cascades automatically. Never drops a request silently.
"""

import os
import logging
import time
from collections import deque
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


# ── Model Tables ──────────────────────────────────────────────────────

OLLAMA_MODELS = {
    'signal_update':      'gpt-oss:20b-cloud',
    'classification':     'gpt-oss:20b-cloud',
    'conversation':       'gpt-oss:120b-cloud',
    'task_decomposition': 'gpt-oss:120b-cloud',
    'code_analysis':      'qwen3-coder:480b-cloud',
    'dream_mode':         'deepseek-v3.1:671b-cloud',
    'vision':             'qwen3-vl:235b-cloud',
    'nudge':              'gpt-oss:20b-cloud',
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
    'nudge':              'llama-3.1-8b-instant',
    'default':            'llama-3.3-70b-versatile',
}

# Gemini 2.5 Flash — primary Gemini tier (10 RPM, 500 RPD)
GEMINI_FLASH_MODELS = {
    'signal_update':      'gemini-2.5-flash-preview-05-20',
    'classification':     'gemini-2.5-flash-preview-05-20',
    'conversation':       'gemini-2.5-flash-preview-05-20',
    'task_decomposition': 'gemini-2.5-flash-preview-05-20',
    'code_analysis':      'gemini-2.5-flash-preview-05-20',
    'dream_mode':         'gemini-2.5-flash-preview-05-20',
    'vision':             'gemini-2.5-flash-preview-05-20',
    'nudge':              'gemini-2.5-flash-preview-05-20',
    'default':            'gemini-2.5-flash-preview-05-20',
}

# Gemini 2.0 Flash — high-volume overflow tier (10 RPM, 1500 RPD)
GEMINI_FLASH_LITE_MODELS = {
    'signal_update':      'gemini-2.0-flash',
    'classification':     'gemini-2.0-flash',
    'conversation':       'gemini-2.0-flash',
    'task_decomposition': 'gemini-2.0-flash',
    'code_analysis':      'gemini-2.0-flash',
    'dream_mode':         'gemini-2.0-flash',
    'vision':             'gemini-2.0-flash',
    'nudge':              'gemini-2.0-flash',
    'default':            'gemini-2.0-flash',
}

OPENROUTER_MODELS = {
    'signal_update':      'meta-llama/llama-3.1-8b-instruct:free',
    'classification':     'meta-llama/llama-3.1-8b-instruct:free',
    'nudge':              'meta-llama/llama-3.1-8b-instruct:free',
    'conversation':       'mistralai/mistral-7b-instruct:free',
    'default':            'mistralai/mistral-7b-instruct:free',
}

# ── Routing Table ─────────────────────────────────────────────────────
# Left = highest priority. Cascades right on quota exhaustion or error.

ROUTING_TABLE = {
    'signal_update':      ['ollama', 'groq', 'gemini_flash_lite', 'openrouter'],
    'classification':     ['ollama', 'groq', 'gemini_flash', 'openrouter'],
    'conversation':       ['ollama', 'gemini_flash', 'groq', 'openrouter'],
    'task_decomposition': ['ollama', 'gemini_flash', 'groq', 'gemini_flash_lite'],
    'code_analysis':      ['ollama', 'groq', 'gemini_flash', 'gemini_flash_lite'],
    'dream_mode':         ['ollama', 'gemini_flash', 'groq', 'gemini_flash_lite'],
    'vision':             ['ollama', 'gemini_flash', 'groq'],
    'nudge':              ['groq', 'ollama', 'gemini_flash_lite', 'openrouter'],
    'default':            ['ollama', 'groq', 'gemini_flash', 'openrouter'],
}

# ── Quota Config ──────────────────────────────────────────────────────

QUOTA_CONFIG = {
    'ollama': {
        'daily':        None,
        'rpm':          10,
        'window_hours': 3,
    },
    'groq': {
        'daily':        14400,
        'rpm':          60,
        'window_hours': None,
    },
    'gemini_flash': {
        'daily':        500,
        'rpm':          10,
        'window_hours': None,
    },
    'gemini_flash_lite': {
        'daily':        1500,
        'rpm':          10,
        'window_hours': None,
    },
    'openrouter': {
        'daily':        None,
        'rpm':          20,
        'window_hours': None,
    },
}


# ── Quota Tracker ─────────────────────────────────────────────────────

class ProviderQuota:
    """
    Tracks daily quota and per-minute rate limit for one provider.
    Uses a sliding window deque for RPM tracking.
    """

    def __init__(self, provider: str, config: dict, session_cap: int = None):
        self.provider    = provider
        self.daily_cap   = config.get('daily')
        self.rpm_cap     = config.get('rpm', 60)
        self.window_hours = config.get('window_hours')
        self.session_cap = session_cap

        self._daily_count   = 0
        self._day_start     = datetime.utcnow().date()
        self._session_count = 0
        self._session_start = datetime.utcnow()
        self._request_times: deque = deque()

    def _reset_daily_if_needed(self):
        today = datetime.utcnow().date()
        if today != self._day_start:
            self._daily_count = 0
            self._day_start   = today

    def _reset_session_if_needed(self):
        if self.window_hours:
            now = datetime.utcnow()
            if now - self._session_start > timedelta(hours=self.window_hours):
                self._session_count = 0
                self._session_start = now

    def _clean_rpm_window(self):
        cutoff = time.monotonic() - 60.0
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    def has_quota(self) -> tuple[bool, str]:
        self._reset_daily_if_needed()
        self._reset_session_if_needed()
        self._clean_rpm_window()

        if self.daily_cap is not None:
            if self._daily_count >= self.daily_cap:
                return False, f"daily cap {self._daily_count}/{self.daily_cap}"

        if self.session_cap is not None:
            if self._session_count >= self.session_cap:
                return False, (
                    f"session cap {self._session_count}/{self.session_cap}"
                )

        if len(self._request_times) >= self.rpm_cap:
            return False, (
                f"rpm limit {len(self._request_times)}/{self.rpm_cap}"
            )

        return True, "ok"

    def record_request(self):
        self._daily_count   += 1
        self._session_count += 1
        self._request_times.append(time.monotonic())

    def status(self) -> dict:
        self._reset_daily_if_needed()
        self._reset_session_if_needed()
        self._clean_rpm_window()
        return {
            'daily_used':   self._daily_count,
            'daily_cap':    self.daily_cap,
            'session_used': self._session_count,
            'session_cap':  self.session_cap,
            'rpm_current':  len(self._request_times),
            'rpm_cap':      self.rpm_cap,
        }

    def reset_daily(self):
        self._daily_count = 0
        self._day_start   = datetime.utcnow().date()


# ── Router ────────────────────────────────────────────────────────────

class LLMRouter:
    """
    Routes LLM inference to optimal provider based on task type.
    Cascades to fallback automatically on quota exhaustion or error.
    """

    def __init__(self):
        ollama_session_cap      = int(os.getenv('OLLAMA_CLOUD_SESSION_CAP', '20'))
        self.ollama_base_url    = os.getenv('OLLAMA_CLOUD_BASE_URL', 'https://ollama.com/api')
        self.ollama_api_key     = os.getenv('OLLAMA_CLOUD_API_KEY', '')
        self.gemini_api_key     = os.getenv('GEMINI_API_KEY', '')
        self.openrouter_api_key = os.getenv('OPENROUTER_API_KEY', '')

        self.groq_client = Groq(api_key=os.getenv('GROQ_API_KEY', ''))

        self._quotas: dict[str, ProviderQuota] = {
            'ollama':           ProviderQuota('ollama',           QUOTA_CONFIG['ollama'],
                                              session_cap=ollama_session_cap),
            'groq':             ProviderQuota('groq',             QUOTA_CONFIG['groq']),
            'gemini_flash':     ProviderQuota('gemini_flash',     QUOTA_CONFIG['gemini_flash']),
            'gemini_flash_lite':ProviderQuota('gemini_flash_lite',QUOTA_CONFIG['gemini_flash_lite']),
            'openrouter':       ProviderQuota('openrouter',       QUOTA_CONFIG['openrouter']),
        }

        self._request_log: list[dict] = []

    # ── Provider Calls ────────────────────────────────────────────

    async def _call_ollama(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        task_type: str
    ) -> str:
        model = OLLAMA_MODELS.get(task_type, OLLAMA_MODELS['default'])
        full_messages = []
        if system_prompt:
            full_messages.append({'role': 'system', 'content': system_prompt})
        full_messages.extend(messages)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f'{self.ollama_base_url}/chat',
                json={
                    'model':   model,
                    'messages': full_messages,
                    'stream':  False,
                    'options': {'num_predict': max_tokens}
                },
                headers={
                    'Authorization': f'Bearer {self.ollama_api_key}',
                    'Content-Type':  'application/json'
                }
            )
            response.raise_for_status()
            content = response.json()['message']['content']
            logger.debug("Ollama [%s] %d chars.", model, len(content))
            return content

    def _call_groq(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        task_type: str
    ) -> str:
        model = GROQ_MODELS.get(task_type, GROQ_MODELS['default'])
        full_messages = []
        if system_prompt:
            full_messages.append({'role': 'system', 'content': system_prompt})
        full_messages.extend(messages)

        response = self.groq_client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=0.7
        )
        content = response.choices[0].message.content
        logger.debug("Groq [%s] %d chars.", model, len(content))
        return content

    async def _call_gemini(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        task_type: str,
        tier: str = 'flash'
    ) -> str:
        model_table = (
            GEMINI_FLASH_MODELS if tier == 'flash'
            else GEMINI_FLASH_LITE_MODELS
        )
        model = model_table.get(task_type, model_table['default'])

        contents = []
        for msg in messages:
            role = 'user' if msg['role'] == 'user' else 'model'
            contents.append({
                'role':  role,
                'parts': [{'text': msg['content']}]
            })

        payload: dict = {
            'contents': contents,
            'generationConfig': {
                'maxOutputTokens': max_tokens,
                'temperature':     0.7,
            }
        }
        if system_prompt:
            payload['system_instruction'] = {
                'parts': [{'text': system_prompt}]
            }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.gemini_api_key}"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        try:
            content = data['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError) as e:
            raise ValueError(
                f"Unexpected Gemini response format: {data}"
            ) from e

        logger.debug(
            "Gemini-%s [%s] %d chars.", tier, model, len(content)
        )
        return content

    async def _call_openrouter(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        task_type: str
    ) -> str:
        model = OPENROUTER_MODELS.get(task_type, OPENROUTER_MODELS['default'])
        full_messages = []
        if system_prompt:
            full_messages.append({'role': 'system', 'content': system_prompt})
        full_messages.extend(messages)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                'https://openrouter.ai/api/v1/chat/completions',
                json={
                    'model':      model,
                    'messages':   full_messages,
                    'max_tokens': max_tokens,
                },
                headers={
                    'Authorization': f'Bearer {self.openrouter_api_key}',
                    'Content-Type':  'application/json',
                    'HTTP-Referer':  'https://github.com/yashpulsay-code/MAIHERA',
                    'X-Title':       'MAIHERA',
                }
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            logger.debug("OpenRouter [%s] %d chars.", model, len(content))
            return content

    # ── Main Router ───────────────────────────────────────────────

    async def route(
        self,
        task_type: str,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000
    ) -> str:
        providers  = ROUTING_TABLE.get(task_type, ROUTING_TABLE['default'])
        start_time = datetime.utcnow()
        last_error = None

        for provider in providers:
            quota = self._quotas.get(provider)
            if quota is None:
                continue

            available, reason = quota.has_quota()
            if not available:
                logger.info(
                    "Skipping %s — %s. Trying next.", provider, reason
                )
                continue

            try:
                if provider == 'ollama':
                    result = await self._call_ollama(
                        messages, system_prompt, max_tokens, task_type
                    )
                elif provider == 'groq':
                    result = self._call_groq(
                        messages, system_prompt, max_tokens, task_type
                    )
                elif provider == 'gemini_flash':
                    result = await self._call_gemini(
                        messages, system_prompt, max_tokens, task_type,
                        tier='flash'
                    )
                elif provider == 'gemini_flash_lite':
                    result = await self._call_gemini(
                        messages, system_prompt, max_tokens, task_type,
                        tier='flash_lite'
                    )
                elif provider == 'openrouter':
                    result = await self._call_openrouter(
                        messages, system_prompt, max_tokens, task_type
                    )
                else:
                    continue

                quota.record_request()
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                self._request_log.append({
                    'task_type': task_type,
                    'provider':  provider,
                    'elapsed_seconds': elapsed,
                    'timestamp': start_time.isoformat(),
                    'success':   True
                })
                logger.info(
                    "LLM route: task=%s provider=%s elapsed=%.2fs",
                    task_type, provider, elapsed
                )
                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider '%s' failed for task '%s': %s. Trying next.",
                    provider, task_type, e
                )
                self._request_log.append({
                    'task_type': task_type,
                    'provider':  provider,
                    'error':     str(e),
                    'timestamp': start_time.isoformat(),
                    'success':   False
                })

        status_summary = {
            p: self._quotas[p].status()
            for p in providers if p in self._quotas
        }
        error_msg = (
            f"All LLM providers exhausted for task '{task_type}'. "
            f"Last error: {last_error}. "
            f"Quota status: {status_summary}"
        )
        logger.critical(error_msg)
        raise LLMUnavailableError(error_msg)

    # ── Quota Management ──────────────────────────────────────────

    def reset_daily_quotas(self) -> None:
        for quota in self._quotas.values():
            quota.reset_daily()
        logger.info("All daily quotas reset.")

    def get_quota_status(self) -> dict:
        return {
            provider: quota.status()
            for provider, quota in self._quotas.items()
        }

    def get_request_log(self, last_n: int = 20) -> list[dict]:
        return self._request_log[-last_n:]


if __name__ == "__main__":
    import asyncio
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    async def test_router():
        print("Testing MAIHERA LLM Router — Phase 3 expanded...")
        router = LLMRouter()

        print("\n[1] Quota status — all providers...")
        status = router.get_quota_status()
        for provider, s in status.items():
            print(f"    {provider}: "
                  f"daily={s['daily_used']}/{s['daily_cap']} "
                  f"rpm={s['rpm_current']}/{s['rpm_cap']}")

        print("\n[2] Groq direct call...")
        result = router._call_groq(
            messages=[{
                'role': 'user',
                'content': 'Reply with exactly two words: groq ok'
            }],
            system_prompt=None,
            max_tokens=10,
            task_type='classification'
        )
        print(f"    Response: {result.strip()}")
        assert len(result) > 0
        print("    Groq: OK")

        print("\n[3] Gemini 2.5 Flash direct call...")
        try:
            result = await router._call_gemini(
                messages=[{
                    'role': 'user',
                    'content': 'Reply with exactly two words: gemini ok'
                }],
                system_prompt=None,
                max_tokens=10,
                task_type='classification',
                tier='flash'
            )
            print(f"    Response: {result.strip()}")
            print("    Gemini 2.5 Flash: OK")
        except Exception as e:
            print(f"    Gemini 2.5 Flash: FAILED — {e}")

        print("\n[4] Gemini 2.0 Flash direct call...")
        try:
            result = await router._call_gemini(
                messages=[{
                    'role': 'user',
                    'content': 'Reply with exactly two words: gemini lite ok'
                }],
                system_prompt=None,
                max_tokens=10,
                task_type='classification',
                tier='flash_lite'
            )
            print(f"    Response: {result.strip()}")
            print("    Gemini 2.0 Flash: OK")
        except Exception as e:
            print(f"    Gemini 2.0 Flash: FAILED — {e}")

        print("\n[5] Cascade — exhaust Ollama, confirm fallback...")
        router._quotas['ollama']._session_count = 9999
        result = await router.route(
            task_type='classification',
            messages=[{'role': 'user', 'content': 'Reply with: cascade ok'}],
            max_tokens=20
        )
        print(f"    Cascade result: {result.strip()}")
        assert len(result) > 0
        print("    Cascade: OK")

        print("\n[6] Request log...")
        for entry in router.get_request_log():
            status_str = (
                "ok" if entry['success']
                else f"FAIL:{entry.get('error','?')[:40]}"
            )
            print(f"    [{entry['provider']}] "
                  f"{entry['task_type']} — {status_str}")

        print("\n✅ Router test complete.")

    asyncio.run(test_router())