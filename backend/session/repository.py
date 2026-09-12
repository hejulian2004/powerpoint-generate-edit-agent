"""SessionRepository protocol: durable storage for ``SessionSnapshot`` objects.

The protocol is async so a synchronous backend (stdlib ``sqlite3``) can be
offloaded with ``asyncio.to_thread``. Implementations MUST be single-writer:
callers may issue concurrent saves, and the repository (not the caller) owns
serialization.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, runtime_checkable

from .snapshot import SessionSnapshot


@runtime_checkable
class SessionRepository(Protocol):
    async def save(self, snapshot: SessionSnapshot) -> None: ...

    async def load(self, session_id: str) -> Optional[SessionSnapshot]: ...

    async def delete(self, session_id: str) -> None: ...

    async def list_ids(self) -> List[str]: ...

    async def close(self) -> None: ...


class InMemorySessionRepository:
    """Test/default repository that keeps snapshots in a dict (no durability)."""

    def __init__(self) -> None:
        self._snapshots: Dict[str, SessionSnapshot] = {}

    async def save(self, snapshot: SessionSnapshot) -> None:
        self._snapshots[snapshot.session_id] = snapshot

    async def load(self, session_id: str) -> Optional[SessionSnapshot]:
        return self._snapshots.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._snapshots.pop(session_id, None)

    async def list_ids(self) -> List[str]:
        return list(self._snapshots.keys())

    async def close(self) -> None:
        return None
