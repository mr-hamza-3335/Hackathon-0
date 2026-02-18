"""WebSocket connection manager for real-time updates."""

import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("silver.ws")


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WS connected — {len(self.active_connections)} active")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WS disconnected — {len(self.active_connections)} active")

    async def broadcast(self, event_type: str, data: Any) -> None:
        """Send an event to all connected clients."""
        message = json.dumps({"event": event_type, "data": data})
        disconnected = []
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)


manager = ConnectionManager()
