"""
MAIHERA Voice Service — Cartesia TTS
Manages speech synthesis and proactive voice delivery queue.
Audio files written to backend/audio_out/ for Electron pickup.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / '.env')

logger = logging.getLogger(__name__)

CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", "")
AUDIO_OUT_DIR = Path(__file__).parent.parent / "audio_out"


class SpeechItem:
    def __init__(
        self,
        text: str,
        node_ids: list[str],
        priority: str = "normal"
    ):
        self.text = text
        self.node_ids = node_ids
        self.priority = priority
        self.queued_at = datetime.now(timezone.utc).isoformat()
        self.id = str(uuid.uuid4())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "node_ids": self.node_ids,
            "priority": self.priority,
            "queued_at": self.queued_at
        }


class VoiceService:
    """
    Manages Cartesia TTS synthesis and the proactive speech queue.

    Flow:
        enqueue_speech() → queue → drain_queue() background task
        → synthesize() → write audio_out/{uuid}.mp3
        → notify WebSocket → Electron picks up file → plays audio
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ws_manager = None
        self._is_speaking = False
        self._drain_task: Optional[asyncio.Task] = None
        self._client = None
        self._playback_done = asyncio.Event()
        self._playback_done.set()  
        AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("VoiceService initialized. Audio out: %s", AUDIO_OUT_DIR)
    
    def signal_playback_done(self) -> None:
        """Called when Electron reports audio playback finished."""
        self._playback_done.set()

    def set_ws_manager(self, ws_manager) -> None:
        """Inject WebSocket manager after lifespan init."""
        self._ws_manager = ws_manager

    def _get_client(self):
        """Lazy-init Cartesia client."""
        if self._client is None:
            if not CARTESIA_API_KEY:
                raise RuntimeError("CARTESIA_API_KEY not set in .env")
            from cartesia import Cartesia
            self._client = Cartesia(api_key=CARTESIA_API_KEY)
            logger.info("Cartesia client initialized.")
        return self._client

    def _synthesize_blocking(self, text: str) -> bytes:
        """
        Blocking Cartesia TTS call.
        Runs in executor so it doesn't block the event loop.
        """
        client = self._get_client()
        response = client.tts.generate(
            model_id="sonic-2",
            transcript=text,
            voice={"mode": "id", "id": CARTESIA_VOICE_ID},
            output_format={
                "container": "mp3",
                "bit_rate": 128000,
                "sample_rate": 44100,
            },
        )
        return response.read()

    async def synthesize(self, text: str) -> bytes:
        """Async wrapper around blocking Cartesia call."""
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None, self._synthesize_blocking, text
        )
        return audio_bytes

    def _write_audio_file(self, audio_bytes: bytes) -> str:
        """Write audio bytes to audio_out dir. Returns filename."""
        filename = f"{uuid.uuid4()}.mp3"
        filepath = AUDIO_OUT_DIR / filename
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        logger.info("Audio file written: %s", filename)
        return filename

    def _cleanup_old_files(self) -> None:
        """Delete audio files older than 60 seconds."""
        now = datetime.now(timezone.utc).timestamp()
        for f in AUDIO_OUT_DIR.glob("*.mp3"):
            try:
                age = now - f.stat().st_mtime
                if age > 60:
                    f.unlink()
                    logger.debug("Cleaned up audio file: %s", f.name)
            except Exception as e:
                logger.warning("Could not clean up %s: %s", f.name, e)

    async def enqueue_speech(
        self,
        text: str,
        node_ids: list[str],
        priority: str = "normal",
        silent: bool = False
    ) -> None:
        item = SpeechItem(text=text, node_ids=node_ids, priority=priority)
        await self._queue.put(item)
        logger.info("Speech queued [%s]: %.50s...", priority, text)
        if self._ws_manager and not silent:
            await self._ws_manager.send_maihera_speak(
                text=text,
                node_ids=node_ids,
                priority=priority
            )

    async def drain_queue(self) -> None:
        """
        Background task — runs continuously.
        Drains speech queue one item at a time.
        Waits for Electron playback signal before next item.
        """
        logger.info("Voice drain queue started.")
        while True:
            try:
                item: SpeechItem = await self._queue.get()
                self._is_speaking = True

                if self._ws_manager:
                    await self._ws_manager.send_system_status("speaking")

                try:
                    self._playback_done.clear()
                    audio_bytes = await self.synthesize(item.text)
                    filename = self._write_audio_file(audio_bytes)

                    if self._ws_manager:
                        await self._ws_manager.send_maihera_speak(
                            text=item.text,
                            node_ids=item.node_ids,
                            priority=item.priority,
                            audio_file=filename
                        )

                    # Wait for Electron to signal playback complete
                    # Timeout after 30 seconds as safety net
                    try:
                        await asyncio.wait_for(
                            self._playback_done.wait(),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Playback timeout — moving to next item.")

                    self._cleanup_old_files()

                except Exception as e:
                    logger.error("Speech synthesis failed: %s", e)
                    self._playback_done.set()  # unblock on error

                finally:
                    self._is_speaking = False
                    self._queue.task_done()
                    if self._ws_manager and self._queue.empty():
                        await self._ws_manager.send_system_status("watching")

            except asyncio.CancelledError:
                logger.info("Voice drain queue cancelled.")
                break
            except Exception as e:
                logger.error("Drain queue error: %s", e)
                await asyncio.sleep(1)

    def start(self) -> None:
        """Start the drain queue as a background asyncio task."""
        self._drain_task = asyncio.create_task(self.drain_queue())
        logger.info("Voice drain task started.")

    def stop(self) -> None:
        """Cancel the drain task on shutdown."""
        if self._drain_task:
            self._drain_task.cancel()
            logger.info("Voice drain task stopped.")

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def get_stats(self) -> dict:
        return {
            "is_speaking": self._is_speaking,
            "queue_size": self._queue.qsize(),
            "audio_out_dir": str(AUDIO_OUT_DIR),
            "cartesia_configured": bool(CARTESIA_API_KEY and CARTESIA_VOICE_ID)
        }