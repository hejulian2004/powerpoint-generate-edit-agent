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
        self._debounce_tasks: Dict[str, asyncio.Task] = {}
        self._session_locks: Dict[str, asyncio.Lock] = {}

    @property
    def dirty_session_ids(self) -> Set[str]:
        return set(self._dirty_generation)

    @property
    def _tasks(self) -> Dict[str, asyncio.Task]:
        return self._debounce_tasks

    def _get_lock(self, sid: str) -> asyncio.Lock:
        lock = self._session_locks.get(sid)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[sid] = lock
        return lock

    def schedule(self, session) -> None:
        sid = session.session_id
        self._dirty_generation[sid] = self._dirty_generation.get(sid, 0) + 1
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop (sync context): remain dirty; close()/flush_all() persist it.
            return
        task = self._debounce_tasks.get(sid)
        if task is None or task.done():
            self._debounce_tasks[sid] = asyncio.create_task(
                self._debounced(sid), name=f"persist_debounce:{sid}"
            )

    async def _debounced(self, sid: str) -> None:
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            return
        finally:
            if self._debounce_tasks.get(sid) is asyncio.current_task():
                self._debounce_tasks.pop(sid, None)
        await self.flush_session_id(sid)

    async def flush(self, session) -> None:
        await self.flush_session_id(session.session_id)

    async def persist_session_now(self, sid: str) -> None:
        """Immediately captures a durable snapshot and writes to repository.

        Cancels any pending debounce sleep timer, but never cancels active
        repository writes. Serializes behind per-session write lock so in-flight
        writes finish cleanly before capturing and persisting the latest state.
        """
        current = asyncio.current_task()
        timer = self._debounce_tasks.pop(sid, None)
        if timer is not None and timer is not current and not timer.done():
            timer.cancel()

        lock = self._get_lock(sid)
        async with lock:
            generation = self._dirty_generation.get(sid, 0)
            session = self._resolver(sid)
            if session is None:
                self._dirty_generation.pop(sid, None)
                return
            snap_res = await session.snapshot_for_persistence(with_pending_tombstones=True)
            if isinstance(snap_res, tuple):
                snapshot, pending_tombstones = snap_res
            else:
                snapshot, pending_tombstones = snap_res, None

            await self._repo.save(snapshot, pending_tombstones)
            if pending_tombstones and hasattr(session, "ack_persisted_tombstones"):
                session.ack_persisted_tombstones([t.request_id for t in pending_tombstones])

            if self._dirty_generation.get(sid, 0) <= generation:
                self._dirty_generation.pop(sid, None)

    async def flush_session_id(self, sid: str) -> None:
        current = asyncio.current_task()
        timer = self._debounce_tasks.pop(sid, None)
        if timer is not None and timer is not current and not timer.done():
            timer.cancel()

        if sid not in self._dirty_generation:
            return

        lock = self._get_lock(sid)
        async with lock:
            if sid not in self._dirty_generation:
                return
            generation = self._dirty_generation[sid]
            session = self._resolver(sid)
            if session is None:
                self._dirty_generation.pop(sid, None)
                return
            snap_res = await session.snapshot_for_persistence(with_pending_tombstones=True)
            if isinstance(snap_res, tuple):
                snapshot, pending_tombstones = snap_res
            else:
                snapshot, pending_tombstones = snap_res, None

            await self._repo.save(snapshot, pending_tombstones)
            if pending_tombstones and hasattr(session, "ack_persisted_tombstones"):
                session.ack_persisted_tombstones([t.request_id for t in pending_tombstones])
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
        for task in list(self._debounce_tasks.values()):
            if not task.done():
                task.cancel()
        self._debounce_tasks.clear()
        await self.flush_all()
        # A save in flight may have been superseded; drain once more so the
        # final committed generation reaches the repository on graceful close.
        await self.flush_all()
