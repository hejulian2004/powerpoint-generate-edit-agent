"""WebSocket endpoint for ultra-low latency real-time streaming and synchronization.

Re-exports router and handlers from backend.server.websocket for full backward compatibility.
"""

from __future__ import annotations
from ..server.websocket import ws_router, websocket_endpoint, build_preview_update

__all__ = ["ws_router", "websocket_endpoint", "build_preview_update"]
