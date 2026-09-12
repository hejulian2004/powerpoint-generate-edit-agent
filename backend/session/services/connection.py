"""ConnectionService: single writable frontend ownership (S1).

The newest tab wins: when a second frontend attaches to the same session, the
previous socket is notified (``SESSION_TAKEN_OVER``) and closed with a dedicated
code so it can suppress auto-reconnect instead of ping-ponging.

Every mutation/chat/confirmation dispatch must verify the originating socket is
still the current owner. ``connection_generation`` is issued and bound by the
server at attach; client-reported values are never trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

SESSION_TAKEN_OVER = "session_taken_over"
STALE_CONNECTION = "stale_connection"
WS_TAKEN_OVER_CODE = 4001


@dataclass
class TransportOwnership:
    """Server-issued proof of which socket owns a session.

    Created by the transport at ``attach`` time from the server-bound
    ``connection_generation``. A client-reported generation is never trusted.
    """

    websocket: object
    connection_generation: int


class ConnectionTakenOver(Exception):
    """Raised when a superseded socket attempts to mutate a session."""


class ConnectionService:
    """Owns the single writable frontend for one session."""

    def __init__(self) -> None:
        self.websocket: Optional[object] = None
        self.frontend_instance_id: Optional[str] = None
        self.connection_generation: int = 0

    def attach(
        self,
        websocket: object,
        frontend_instance_id: Optional[str] = None,
    ) -> Tuple[Optional[object], int]:
        """Binds ``websocket`` as the sole owner; returns the superseded socket."""
        previous = self.websocket
        self.websocket = websocket
        self.frontend_instance_id = frontend_instance_id
        self.connection_generation += 1
        return previous, self.connection_generation

    def detach(self, websocket: object) -> None:
        if self.websocket is websocket:
            self.websocket = None
            self.frontend_instance_id = None

    def is_current(self, websocket: object, generation: Optional[int] = None) -> bool:
        if websocket is None or self.websocket is not websocket:
            return False
        if generation is not None and int(generation) != self.connection_generation:
            return False
        return True

    def assert_current(self, websocket: object, generation: Optional[int] = None) -> None:
        if not self.is_current(websocket, generation):
            raise ConnectionTakenOver("frontend connection has been superseded")
