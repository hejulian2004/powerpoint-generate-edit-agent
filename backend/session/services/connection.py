"""ConnectionService: session-scoped frontend ownership.

Filled in by Phase 5. For Phase 1 it is introduced as part of the session
aggregate so the single-writable-connection invariant (S1) has a stable home.
"""

from __future__ import annotations

from typing import Optional


class ConnectionService:
    """Owns the single writable frontend for one session (Phase 5)."""

    def __init__(self) -> None:
        self.websocket: Optional[object] = None
        self.frontend_instance_id: Optional[str] = None
        self.connection_generation: int = 0
