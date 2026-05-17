"""
MAIHERA System Observer
Polls the foreground window every 2 seconds using psutil.
Matches against the app whitelist in observer_config.json.
Publishes ContextEvent objects to an asyncio.Queue.
Runs in a daemon thread — never blocks the FastAPI event loop.
Config file is reloaded every 60 seconds — no restart needed.

Phase 6: adds idle_start / idle_end events for Dream Mode triggering.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "observer_config.json"
POLL_INTERVAL_SECONDS = 2
CONFIG_RELOAD_INTERVAL_SECONDS = 60
IDLE_THRESHOLD_SECONDS = 600  # 10 minutes


@dataclass
class ContextEvent:
    """
    Published to the asyncio.Queue when foreground app changes,
    a meaningful dwell time is reached, or idle state changes.

    event_type values:
        focus_gained  — whitelisted app gained focus
        dwell         — stayed in same whitelisted app 2+ minutes
        focus_lost    — left a whitelisted app
        idle_start    — no whitelisted app active for 10+ minutes
        idle_end      — whitelisted app regained focus after idle
    """
    timestamp: str
    process_name: str
    process_label: str
    context: str
    window_title: str
    event_type: str
    dwell_seconds: float = 0.0
    extra: dict = field(default_factory=dict)


class SystemObserverService:
    """
    Daemon thread that watches the foreground window.
    Publishes ContextEvents to a queue for async consumption.

    Usage:
        observer = SystemObserverService(event_queue)
        observer.set_event_loop(loop)
        observer.start()
        # later:
        observer.stop()
    """

    def __init__(self, event_queue):
        self._queue = event_queue
        self._loop = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Config state
        self._whitelist: dict[str, dict] = {}
        self._config_loaded_at: float = 0.0

        # Foreground tracking state
        self._current_process: Optional[str] = None
        self._current_context: Optional[str] = None
        self._current_label: Optional[str] = None
        self._current_title: Optional[str] = None
        self._focus_gained_at: Optional[float] = None

        # Idle tracking state
        self._idle_since: Optional[float] = None
        self._idle_fired: bool = False

        # Dwell event fires after this many seconds in same app
        self._dwell_threshold_seconds = 120  # 2 minutes

        self._load_config()
        logger.info("SystemObserverService initialized.")

    # ── Config ────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Load or reload observer_config.json."""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)

            whitelist = {}
            for entry in config.get("app_whitelist", []):
                process = entry.get("process", "").lower()
                if process:
                    whitelist[process] = {
                        "context": entry.get("context", "general"),
                        "label":   entry.get("label", process),
                    }

            self._whitelist = whitelist
            self._config_loaded_at = time.monotonic()
            logger.debug(
                "Observer config loaded — %d whitelisted apps.",
                len(self._whitelist)
            )

        except FileNotFoundError:
            logger.warning(
                "observer_config.json not found at %s. "
                "Observer running with empty whitelist.",
                CONFIG_PATH
            )
        except json.JSONDecodeError as e:
            logger.error(
                "observer_config.json is malformed: %s. "
                "Using previous config.",
                e
            )

    def _maybe_reload_config(self) -> None:
        """Reload config if 60 seconds have passed."""
        if (time.monotonic() - self._config_loaded_at
                > CONFIG_RELOAD_INTERVAL_SECONDS):
            self._load_config()

    # ── Foreground Window Detection ───────────────────────────────

    def _get_foreground_process(self) -> Optional[tuple[str, str]]:
        """
        Returns (process_name, window_title) of the foreground window.
        Returns None if detection fails.
        """
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None

            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid)
            )
            if not pid.value:
                return None

            title_buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(hwnd, title_buf, 512)
            title = title_buf.value.strip()

            try:
                proc = psutil.Process(pid.value)
                return proc.name(), title
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None

        except Exception as e:
            logger.debug("Foreground window detection failed: %s", e)
            return None

    def _match_whitelist(self, process_name: str) -> Optional[dict]:
        """Match a process name against the whitelist. Case-insensitive."""
        return self._whitelist.get(process_name.lower())

    # ── Event Publishing ──────────────────────────────────────────

    def _publish(self, event: ContextEvent) -> None:
        """Thread-safe publish to the asyncio queue."""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, event
            )
        else:
            logger.debug(
                "Observer: event loop not available, dropping event."
            )

    # ── Main Poll Loop ────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """Main loop — runs in daemon thread."""
        logger.info("SystemObserver poll loop started.")
        dwell_fired = False

        while not self._stop_event.is_set():
            try:
                self._maybe_reload_config()

                result = self._get_foreground_process()
                now = time.monotonic()
                now_iso = datetime.utcnow().isoformat()

                if result is None:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                process_name, title = result
                entry = self._match_whitelist(process_name)

                if entry:
                    # ── Whitelisted app is in focus ───────────────

                    # Reset idle state if we were idle
                    if self._idle_fired:
                        self._publish(ContextEvent(
                            timestamp=now_iso,
                            process_name=process_name,
                            process_label=entry["label"],
                            context=entry["context"],
                            window_title=title,
                            event_type="idle_end",
                            dwell_seconds=(
                                now - self._idle_since
                                if self._idle_since else 0.0
                            ),
                        ))
                        logger.info(
                            "Observer: idle_end fired — %s returned after %.0fs.",
                            entry["label"],
                            now - self._idle_since if self._idle_since else 0.0,
                        )

                    self._idle_since = None
                    self._idle_fired = False

                    # App changed
                    if process_name != self._current_process:
                        # Fire focus_lost for previous app
                        if self._current_process and self._current_context:
                            dwell = (
                                now - self._focus_gained_at
                                if self._focus_gained_at else 0.0
                            )
                            self._publish(ContextEvent(
                                timestamp=now_iso,
                                process_name=self._current_process,
                                process_label=self._current_label or "",
                                context=self._current_context,
                                window_title=self._current_title or "",
                                event_type="focus_lost",
                                dwell_seconds=dwell,
                            ))

                        # Record new app
                        self._current_process = process_name
                        self._current_context = entry["context"]
                        self._current_label   = entry["label"]
                        self._current_title   = title
                        self._focus_gained_at = now
                        dwell_fired           = False

                        self._publish(ContextEvent(
                            timestamp=now_iso,
                            process_name=process_name,
                            process_label=entry["label"],
                            context=entry["context"],
                            window_title=title,
                            event_type="focus_gained",
                        ))
                        logger.debug(
                            "Observer: focus_gained — %s (%s)",
                            entry["label"], entry["context"]
                        )

                    else:
                        # Same app — check for dwell
                        if (
                            not dwell_fired
                            and self._focus_gained_at
                            and (now - self._focus_gained_at)
                                >= self._dwell_threshold_seconds
                        ):
                            dwell = now - self._focus_gained_at
                            self._publish(ContextEvent(
                                timestamp=now_iso,
                                process_name=process_name,
                                process_label=entry["label"],
                                context=entry["context"],
                                window_title=title,
                                event_type="dwell",
                                dwell_seconds=dwell,
                            ))
                            dwell_fired = True
                            logger.debug(
                                "Observer: dwell fired — %s (%.0fs)",
                                entry["label"], dwell
                            )

                else:
                    # ── Non-whitelisted app or desktop ───────────

                    # Fire focus_lost for the last tracked app
                    if self._current_process:
                        dwell = (
                            now - self._focus_gained_at
                            if self._focus_gained_at else 0.0
                        )
                        self._publish(ContextEvent(
                            timestamp=now_iso,
                            process_name=self._current_process,
                            process_label=self._current_label or "",
                            context=self._current_context or "",
                            window_title=self._current_title or "",
                            event_type="focus_lost",
                            dwell_seconds=dwell,
                        ))
                        self._current_process = None
                        self._current_context = None
                        self._current_label   = None
                        self._current_title   = None
                        self._focus_gained_at = None
                        dwell_fired           = False

                    # Start or continue idle timer
                    if self._idle_since is None:
                        self._idle_since = now

                    # Fire idle_start if threshold crossed
                    if (
                        not self._idle_fired
                        and (now - self._idle_since) >= IDLE_THRESHOLD_SECONDS
                    ):
                        self._idle_fired = True
                        self._publish(ContextEvent(
                            timestamp=now_iso,
                            process_name="",
                            process_label="idle",
                            context="idle",
                            window_title="",
                            event_type="idle_start",
                            dwell_seconds=now - self._idle_since,
                        ))
                        logger.info(
                            "Observer: idle_start fired (%.0fs idle).",
                            now - self._idle_since,
                        )

            except Exception as e:
                logger.error("SystemObserver poll error: %s", e)

            time.sleep(POLL_INTERVAL_SECONDS)

        logger.info("SystemObserver poll loop stopped.")

    # ── Lifecycle ─────────────────────────────────────────────────

    def set_event_loop(self, loop) -> None:
        """Must be called before start() with the running event loop."""
        self._loop = loop

    def start(self) -> None:
        """Start the daemon thread."""
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="SystemObserver",
            daemon=True
        )
        self._thread.start()
        logger.info("SystemObserverService started.")

    def stop(self) -> None:
        """Signal the thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("SystemObserverService stopped.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()