"""
MAIHERA API — WebSocket Manager
Manages all connected WebSocket clients.
Typed message schema for Phase 2+.
"""

import json
import logging
from datetime import datetime, timezone
from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _envelope(msg_type: str, payload: dict) -> str:
    """Wrap any payload in the standard MAIHERA WS envelope."""
    return json.dumps({
        "type": msg_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


class WebSocketManager:
    """
    Manages active WebSocket connections.
    All outbound messages use the typed envelope:
        { type, payload, timestamp }

    Outbound types:
        full_sync, node_upsert, node_delete,
        edge_upsert, edge_delete, signal_update,
        maihera_speak, briefing_start, briefing_segment,
        briefing_end, focus_mode_change, nudge_queue_update,
        system_status

    Inbound types handled in main.py:
        session_start, chat, energy_checkin,
        focus_mode, speech_next
    """

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)
        logger.info(
            "WebSocket connected. Active connections: %d",
            len(self.active)
        )

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)
        logger.info(
            "WebSocket disconnected. Active connections: %d",
            len(self.active)
        )

    async def _send(self, msg_type: str, payload: dict) -> None:
        """Broadcast a typed message to all connected clients."""
        if not self.active:
            return
        text = _envelope(msg_type, payload)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)
        if dead:
            logger.info("Removed %d dead connections.", len(dead))

    # ── Outbound: Graph ───────────────────────────────────────────

    async def send_full_sync(self, graph: dict) -> None:
        """Send complete graph snapshot. Only on connect/reconnect."""
        await self._send("full_sync", {
            "nodes": graph.get("nodes", []),
            "edges": graph.get("edges", [])
        })

    async def send_node_upsert(self, node: dict) -> None:
        await self._send("node_upsert", node)

    async def send_node_delete(self, node_id: str) -> None:
        await self._send("node_delete", {"id": node_id})

    async def send_edge_upsert(self, edge: dict) -> None:
        await self._send("edge_upsert", edge)

    async def send_edge_delete(self, edge_id: str) -> None:
        await self._send("edge_delete", {"id": edge_id})

    async def send_signal_update(
        self,
        node_id: str,
        signals: dict
    ) -> None:
        await self._send("signal_update", {
            "id": node_id,
            "signals": signals
        })

    # ── Outbound: Voice ───────────────────────────────────────────

    async def send_maihera_speak(
        self,
        text: str,
        node_ids: list[str],
        priority: str = "normal",
        audio_file: str | None = None
    ) -> None:
        payload = {
            "text": text,
            "node_ids": node_ids,
            "priority": priority
        }
        if audio_file:
            payload["audio_file"] = audio_file
        await self._send("maihera_speak", payload)

    # ── Outbound: Briefing ────────────────────────────────────────

    async def send_briefing_start(self) -> None:
        await self._send("briefing_start", {})

    async def send_briefing_segment(
        self,
        text: str,
        node_ids: list[str],
        segment_index: int
    ) -> None:
        await self._send("briefing_segment", {
            "text": text,
            "node_ids": node_ids,
            "segment_index": segment_index
        })

    async def send_briefing_end(self) -> None:
        await self._send("briefing_end", {})

    # ── Outbound: Session & Focus ─────────────────────────────────

    async def send_focus_mode_change(
        self,
        active: bool,
        session_id: str | None = None
    ) -> None:
        await self._send("focus_mode_change", {
            "active": active,
            "session_id": session_id
        })

    async def send_nudge_queue_update(
        self,
        nudges: list[dict]
    ) -> None:
        await self._send("nudge_queue_update", {"nudges": nudges})

    async def send_system_status(self, status: str) -> None:
        """
        status: 'watching' | 'thinking' | 'speaking' | 'dream'
        """
        await self._send("system_status", {"status": status})

    # ── Legacy compat (used by brain routes in Phase 1) ───────────

    async def broadcast(self, data: dict) -> None:
        """Raw broadcast — kept for Phase 1 route compatibility."""
        if not self.active:
            return
        text = json.dumps(data)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_graph_update(
        self,
        graph: dict,
        event_type: str = "graph_update"
    ) -> None:
        """Kept for Phase 1 route compatibility. Wraps as full_sync."""
        await self.send_full_sync(graph)

    @property
    def connection_count(self) -> int:
        return len(self.active)