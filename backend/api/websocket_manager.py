"""
MAIHERA API — WebSocket Manager
Manages all connected WebSocket clients.
Broadcasts brain graph updates to all connections.
"""

import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages active WebSocket connections.
    Broadcasts full graph payload on every brain update.
    Phase 1: broadcast to all clients (no per-client filtering).
    Phase 2: filter by visible project when 3D graph is live.
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

    async def broadcast(self, data: dict) -> None:
        """
        Broadcast a payload to all connected clients.
        Removes dead connections silently.
        """
        if not self.active:
            return

        payload = json.dumps(data)
        dead = []

        for websocket in self.active:
            try:
                await websocket.send_text(payload)
            except Exception:
                dead.append(websocket)

        for websocket in dead:
            self.disconnect(websocket)

        if dead:
            logger.info(
                "Removed %d dead WebSocket connections.",
                len(dead)
            )

    async def broadcast_graph_update(
        self,
        graph: dict,
        event_type: str = "graph_update"
    ) -> None:
        """
        Broadcast a brain graph update.
        Wraps graph in a typed event envelope.
        """
        await self.broadcast({
            "event": event_type,
            "data": graph
        })

    @property
    def connection_count(self) -> int:
        return len(self.active)