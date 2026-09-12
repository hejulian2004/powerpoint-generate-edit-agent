"""Debounced durable persistence for live sessions.

``SessionPersistenceService`` coalesces writes: callers ``schedule(session)`` on a
committed change, and the service flushes at most once per debounce window. A
graceful shutdown calls ``close()`` which flushes every dirty session
(contract P3: normal close/refresh/restart loses zero committed state; only a
hard crash can lose up to one debounce window).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict, Optional, Set

from ..session.snapshot import SessionSnapshot, session_to_snapshot

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECONDS = 0.5


class SessionPersistenceService:
    def __init__(
        self,
        repository,
        resolver: Callable[[str], object],
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    ) -> None:
        self._repo = repository
        self._resolver = resolver
        self._debounce = debounce_seconds
        self._dirty: Set[str] = set()
        self._tasks: Dict[str, asyncio.Task] = {}

    @property
    def dirty_session_ids(self) -> Set[str]:
        return set(self._dirty)

    def schedule(self, session) -> None:
        sid = session.session_id
        self._dirty.add(sid)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop (sync context): remain dirty; close()/flush_all() persist it.
            return
        task = self._tasks.get(sid)
        if task is None or task.done():
            self._tasks[sid] = asyncio.create_task(
                self._debounced(sid), name=f"persist:{sid}"
            )

    async def _debounced(self, sid: str) -> None:
        await asyncio.sleep(self._debounce)
        await self.flush_session_id(sid)

    async def flush(self, session) -> None:
        await self.flush_session_id(session.session_id)

    async def flush_session_id(self, sid: str) -> None:
        current = asyncio.current_task()
        task = self._tasks.pop(sid, None)
        if task is not None and task is not current and not task.done():
            task.cancel()
        if sid not in self._dirty:
            return
        session = self._resolver(sid)
        if session is None:
            self._dirty.discard(sid)
            return
        snapshot: SessionSnapshot = session_to_snapshot(session)
        await self._repo.save(snapshot)
        self._dirty.discard(sid)

    async def flush_all(self) -> None:
        for sid in list(self._dirty):
            await self.flush_session_id(sid)

    async def close(self) -> None:
        await self.flush_all()
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._tasks.clear()
