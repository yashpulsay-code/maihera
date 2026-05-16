"""
MAIHERA System Observer
Polls the foreground window every 2 seconds using psutil.
Matches against the app whitelist in observer_config.json.
Publishes ContextEvent objects to an asyncio.Queue.
Runs in a daemon thread — never blocks the FastAPI event loop.
Config file is reloaded every 60 seconds — no restart needed.
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


@dataclass
class ContextEvent:
    """
    Published to the asyncio.Queue when foreground app changes
    or a meaningful dwell time is reached.
    """
    timestamp: str
    process_name: str
    process_label: str
    context: str                        # coding | design | browsing
    window_title: str
    event_type: str                     # focus_gained | dwell | focus_lost
    dwell_seconds: float = 0.0
    extra: dict = field(default_factory=dict)


class SystemObserverService:
    """
    Daemon thread that watches the foreground window.
    Publishes ContextEvents to a queue for async consumption.

    Usage:
        observer = SystemObserverService(event_queue)
        observer.start()
        # later:
        observer.stop()
    """

    def __init__(self, event_queue):
        """
        event_queue: asyncio.Queue — shared with the async consumer.
        Events are put via loop.call_soon_threadsafe to bridge
        the thread boundary safely.
        """
        self._queue = event_queue
        self._loop = None               # set by caller before start()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Config state
        self._whitelist: dict[str, dict] = {}   # process_name → entry
        self._config_loaded_at: float = 0.0

        # Tracking state
        self._current_process: Optional[str] = None
        self._current_context: Optional[str] = None
        self._current_label: Optional[str] = None
        self._current_title: Optional[str] = None
        self._focus_gained_at: Optional[float] = None

        # Dwell event fires after this many seconds in same app
        self._dwell_threshold_seconds = 120     # 2 minutes

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
        Uses psutil to find the process owning the foreground window.
        Returns None if detection fails.
        """
        try:
            import ctypes
            # Get foreground window handle
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return None

            # Get PID from window handle
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid)
            )
            if not pid.value:
                return None

            # Get window title
            title_buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.user32.GetWindowTextW(
                hwnd, title_buf, 512
            )
            title = title_buf.value.strip()

            # Get process name from PID
            try:
                proc = psutil.Process(pid.value)
                return proc.name(), title
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None

        except Exception as e:
            logger.debug("Foreground window detection failed: %s", e)
            return None

    def _match_whitelist(
        self, process_name: str
    ) -> Optional[dict]:
        """
        Match a process name against the whitelist.
        Case-insensitive. Returns whitelist entry or None.
        """
        return self._whitelist.get(process_name.lower())

    # ── Event Publishing ──────────────────────────────────────────

    def _publish(self, event: ContextEvent) -> None:
        """
        Thread-safe publish to the asyncio queue.
        Uses call_soon_threadsafe to bridge thread → event loop.
        """
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

                if result is None:
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue

                process_name, title = result
                entry = self._match_whitelist(process_name)

                now = time.monotonic()
                now_iso = datetime.utcnow().isoformat()

                if entry:
                    context = entry["context"]
                    label   = entry["label"]

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
                        self._current_context = context
                        self._current_label   = label
                        self._current_title   = title
                        self._focus_gained_at = now
                        dwell_fired           = False

                        self._publish(ContextEvent(
                            timestamp=now_iso,
                            process_name=process_name,
                            process_label=label,
                            context=context,
                            window_title=title,
                            event_type="focus_gained",
                        ))
                        logger.debug(
                            "Observer: focus_gained — %s (%s)",
                            label, context
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
                                process_label=label,
                                context=context,
                                window_title=title,
                                event_type="dwell",
                                dwell_seconds=dwell,
                            ))
                            dwell_fired = True
                            logger.debug(
                                "Observer: dwell fired — %s (%.0fs)",
                                label, dwell
                            )

                else:
                    # Not a whitelisted app — treat as focus_lost
                    # if we were previously tracking one
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