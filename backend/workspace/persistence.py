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

from ..session.snapshot import SessionSnapshot

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
        # Monotonic per-session mutation generation. ``schedule`` bumps it; a
        # flush captures the generation before saving and only clears the dirty
        # marker if no newer mutation landed while the save was in flight.
        # Correctness is derived from this dict, never from task liveness.
        self._dirty_generation: Dict[str, int] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    @property
    def dirty_session_ids(self) -> Set[str]:
        return set(self._dirty_generation)

    def schedule(self, session) -> None:
        sid = session.session_id
        self._dirty_generation[sid] = self._dirty_generation.get(sid, 0) + 1
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
        if sid not in self._dirty_generation:
            return
        generation = self._dirty_generation[sid]
        session = self._resolver(sid)
        if session is None:
            self._dirty_generation.pop(sid, None)
            return
        snapshot: SessionSnapshot = await session.snapshot_for_persistence()
        await self._repo.save(snapshot)
        # Only clear dirty if no newer mutation arrived during the save. If the
        # generation advanced, the schedule() that bumped it already queued a
        # follow-up flush (or a sync caller awaits flush_all), so the newer
        # state is not lost.
        if self._dirty_generation.get(sid) == generation:
            self._dirty_generation.pop(sid, None)

    async def flush_all(self) -> None:
        for sid in list(self._dirty_generation):
            await self.flush_session_id(sid)

    async def close(self) -> None:
        await self.flush_all()
        # A save in flight may have been superseded; drain once more so the
        # final committed generation reaches the repository on graceful close.
        await self.flush_all()
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        self._tasks.clear()
