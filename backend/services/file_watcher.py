"""
MAIHERA File Watcher
Watches configured folders for file changes using watchdog.
Publishes FileChangeEvents to an asyncio.Queue.
Config reloads from observer_config.json every 60 seconds —
adding or removing folders takes effect without restart.
Runs in a daemon thread alongside the system observer.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "observer_config.json"
CONFIG_RELOAD_INTERVAL_SECONDS = 60

# File extensions MAIHERA cares about
# Everything else (cache files, temp files, .git internals) is ignored
WATCHED_EXTENSIONS = {
    # Code
    ".py", ".ts", ".tsx", ".js", ".jsx", ".html", ".css",
    ".json", ".yaml", ".yml", ".toml", ".env",
    # Design exports / assets
    ".svg", ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".fig",
    # Docs
    ".md", ".txt", ".csv",
}

# Paths to always ignore regardless of config
IGNORED_FRAGMENTS = {
    "__pycache__", ".git", "node_modules", ".pytest_cache",
    "venv", ".venv", "dist", "build", "chroma_data",
    "audio_out", ".next", ".nuxt",
}


@dataclass
class FileChangeEvent:
    """Published when a watched file is created or modified."""
    timestamp: str
    path: str
    filename: str
    extension: str
    event_type: str          # created | modified
    folder: str              # which watched root triggered this


class _MAIHERAFileHandler(FileSystemEventHandler):
    """
    watchdog event handler.
    Filters events and puts FileChangeEvents onto the queue.
    Bridged to asyncio via loop.call_soon_threadsafe.
    """

    def __init__(self, queue, loop, folder_root: str):
        super().__init__()
        self._queue = queue
        self._loop = loop
        self._folder_root = folder_root

    def _should_process(self, path: str) -> bool:
        """Return True if this file change is worth surfacing."""
        p = Path(path)

        # Ignore hidden files
        if any(part.startswith(".") for part in p.parts
               if part not in (".", "..")):
            # Allow .env files explicitly
            if p.name != ".env":
                return False

        # Ignore fragments
        for fragment in IGNORED_FRAGMENTS:
            if fragment in p.parts:
                return False

        # Only care about known extensions
        if p.suffix.lower() not in WATCHED_EXTENSIONS:
            return False

        return True

    def _publish(self, event_type: str, src_path: str) -> None:
        if not self._should_process(src_path):
            return

        p = Path(src_path)
        event = FileChangeEvent(
            timestamp=datetime.utcnow().isoformat(),
            path=src_path,
            filename=p.name,
            extension=p.suffix.lower(),
            event_type=event_type,
            folder=self._folder_root,
        )

        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, event
            )

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._publish("created", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._publish("modified", event.src_path)


class FileWatcherService:
    """
    Manages watchdog observers for all configured folders.
    Supports hot-reload of watched_folders from config —
    new folders start being watched within 60 seconds,
    removed folders stop being watched at the next reload.
    """

    def __init__(self, event_queue, loop):
        """
        event_queue: asyncio.Queue shared with FileWatcherWorker.
        loop: the running asyncio event loop.
        """
        self._queue = event_queue
        self._loop = loop
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # folder_path → watchdog Observer
        self._observers: dict[str, Observer] = {}
        self._config_loaded_at: float = 0.0
        self._watched_folders: list[str] = []

        logger.info("FileWatcherService initialized.")

    # ── Config ────────────────────────────────────────────────────

    def _load_config(self) -> list[str]:
        """Load watched_folders from observer_config.json."""
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            folders = config.get("watched_folders", [])
            self._config_loaded_at = time.monotonic()
            return [str(Path(f)) for f in folders]
        except FileNotFoundError:
            logger.warning(
                "FileWatcher: observer_config.json not found."
            )
            return []
        except json.JSONDecodeError as e:
            logger.error(
                "FileWatcher: config malformed: %s. "
                "Keeping current folders.",
                e
            )
            return self._watched_folders

    def _maybe_reload_config(self) -> None:
        """Check if config has changed and reconcile observers."""
        if (time.monotonic() - self._config_loaded_at
                <= CONFIG_RELOAD_INTERVAL_SECONDS):
            return

        new_folders = self._load_config()
        current = set(self._watched_folders)
        updated = set(new_folders)

        # Start watching newly added folders
        for folder in updated - current:
            self._start_observer(folder)
            logger.info("FileWatcher: added folder — %s", folder)

        # Stop watching removed folders
        for folder in current - updated:
            self._stop_observer(folder)
            logger.info("FileWatcher: removed folder — %s", folder)

        self._watched_folders = new_folders

    def _start_observer(self, folder: str) -> None:
        """Start a watchdog observer for a single folder."""
        p = Path(folder)
        if not p.exists():
            logger.warning(
                "FileWatcher: folder does not exist, skipping — %s",
                folder
            )
            return

        if folder in self._observers:
            return  # Already watching

        handler = _MAIHERAFileHandler(
            queue=self._queue,
            loop=self._loop,
            folder_root=folder,
        )
        observer = Observer()
        observer.schedule(handler, path=folder, recursive=True)
        observer.start()
        self._observers[folder] = observer
        logger.info("FileWatcher: watching — %s", folder)

    def _stop_observer(self, folder: str) -> None:
        """Stop the watchdog observer for a single folder."""
        observer = self._observers.pop(folder, None)
        if observer:
            observer.stop()
            observer.join(timeout=3)

    # ── Main Loop ─────────────────────────────────────────────────

    def _watch_loop(self) -> None:
        """
        Main thread loop.
        Starts initial observers then polls for config changes.
        """
        logger.info("FileWatcherService watch loop started.")

        # Initial load
        self._watched_folders = self._load_config()
        for folder in self._watched_folders:
            self._start_observer(folder)

        while not self._stop_event.is_set():
            self._maybe_reload_config()
            time.sleep(10)  # Check config every 10s inside the loop

        # Shutdown all observers cleanly
        for folder in list(self._observers.keys()):
            self._stop_observer(folder)

        logger.info("FileWatcherService watch loop stopped.")

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Start the daemon thread."""
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="FileWatcher",
            daemon=True,
        )
        self._thread.start()
        logger.info("FileWatcherService started.")

    def stop(self) -> None:
        """Signal thread to stop and wait."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("FileWatcherService stopped.")

    @property
    def watched_folders(self) -> list[str]:
        return list(self._watched_folders)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()