"""SQLite-backed workspace repository.

One process owns one connection to ``data/workspace.db``. All access is
serialized behind an internal ``asyncio.Lock`` and offloaded with
``asyncio.to_thread``; ``check_same_thread=False`` only lifts sqlite3's thread
guard - the lock, not sqlite3, is what guarantees a single writer.

A session switch (flush a session + move ``last_active_session_id``) runs in one
transaction so the workspace can never point at a session row that was not
written.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Protocol, runtime_checkable

from ..session.session import RequestTombstone
from ..session.snapshot import SessionSnapshot, WorkspaceSnapshot

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "workspace.db"
IDEMPOTENCY_RETENTION_SECONDS = 7 * 86400  # 7 days authoritative retention

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    last_active_session_id TEXT,
    session_ids            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_tombstones (
    session_id          TEXT NOT NULL,
    request_id          TEXT NOT NULL,
    fingerprint         TEXT NOT NULL,
    admitted_generation INTEGER NOT NULL,
    completed_at        REAL NOT NULL,
    PRIMARY KEY (session_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_request_tombstones_expiry ON request_tombstones(completed_at);
"""


@runtime_checkable
class WorkspaceRepository(Protocol):
    async def save(
        self,
        snapshot: SessionSnapshot,
        pending_tombstones: Optional[List[RequestTombstone]] = None,
    ) -> None: ...

    async def load(self, session_id: str) -> Optional[SessionSnapshot]: ...

    async def delete(self, session_id: str) -> None: ...

    async def list_ids(self) -> List[str]: ...

    async def load_workspace(self) -> WorkspaceSnapshot: ...

    async def save_workspace(self, snapshot: WorkspaceSnapshot) -> None: ...

    async def switch_session(
        self,
        session_snapshot: SessionSnapshot,
        workspace_snapshot: WorkspaceSnapshot,
    ) -> None: ...

    async def get_request_tombstone(
        self, session_id: str, request_id: str
    ) -> Optional[RequestTombstone]: ...


class SQLiteRepository:
    """Single-writer SQLite store implementing both session and workspace storage."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB_PATH
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- sync primitives (must be called under self._lock via to_thread) --

    def _save_sync(
        self,
        snapshot: SessionSnapshot,
        pending_tombstones: Optional[List[RequestTombstone]] = None,
    ) -> None:
        payload = json.dumps(asdict(snapshot), ensure_ascii=False)
        now = time.time()
        expiry_cutoff = now - IDEMPOTENCY_RETENTION_SECONDS
        with self._conn:
            # 1. Atomic UPSERT session snapshot
            self._conn.execute(
                "INSERT INTO sessions(session_id, payload, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (snapshot.session_id, payload, snapshot.updated_at),
            )
            # 2. Atomic UPSERT pending tombstones in the same transaction
            if pending_tombstones:
                for t in pending_tombstones:
                    try:
                        c_at = float(t.completed_at) if t.completed_at else now
                    except (ValueError, TypeError):
                        c_at = now
                    self._conn.execute(
                        "INSERT INTO request_tombstones(session_id, request_id, fingerprint, admitted_generation, completed_at) "
                        "VALUES(?,?,?,?,?) "
                        "ON CONFLICT(session_id, request_id) DO UPDATE SET "
                        "fingerprint=excluded.fingerprint, "
                        "admitted_generation=excluded.admitted_generation, "
                        "completed_at=excluded.completed_at",
                        (snapshot.session_id, t.request_id, t.fingerprint, t.admitted_generation, c_at),
                    )
            # 3. Clean up tombstones older than 7 days
            self._conn.execute(
                "DELETE FROM request_tombstones WHERE completed_at < ?",
                (expiry_cutoff,),
            )

    def _get_request_tombstone_sync(
        self, session_id: str, request_id: str
    ) -> Optional[RequestTombstone]:
        now = time.time()
        expiry_cutoff = now - IDEMPOTENCY_RETENTION_SECONDS
        row = self._conn.execute(
            "SELECT request_id, fingerprint, admitted_generation, completed_at "
            "FROM request_tombstones "
            "WHERE session_id=? AND request_id=? AND completed_at >= ?",
            (session_id, request_id, expiry_cutoff),
        ).fetchone()
        if row is None:
            return None
        return RequestTombstone(
            request_id=row[0],
            fingerprint=row[1],
            admitted_generation=row[2],
            completed_at=str(row[3]),
        )

    def _load_sync(self, session_id: str) -> Optional[SessionSnapshot]:
        row = self._conn.execute(
            "SELECT payload FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return SessionSnapshot(**json.loads(row[0]))

    def _delete_sync(self, session_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))

    def _list_ids_sync(self) -> List[str]:
        return [r[0] for r in self._conn.execute("SELECT session_id FROM sessions").fetchall()]

    def _load_workspace_sync(self) -> WorkspaceSnapshot:
        row = self._conn.execute(
            "SELECT last_active_session_id, session_ids FROM workspace WHERE id=1"
        ).fetchone()
        if row is None:
            return WorkspaceSnapshot()
        return WorkspaceSnapshot(
            last_active_session_id=row[0],
            session_ids=list(json.loads(row[1] or "[]")),
        )

    def _write_workspace_sync(self, snapshot: WorkspaceSnapshot) -> None:
        self._conn.execute(
            "INSERT INTO workspace(id, last_active_session_id, session_ids) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "last_active_session_id=excluded.last_active_session_id, "
            "session_ids=excluded.session_ids",
            (snapshot.last_active_session_id, json.dumps(snapshot.session_ids, ensure_ascii=False)),
        )

    def _switch_sync(
        self,
        session_snapshot: SessionSnapshot,
        workspace_snapshot: WorkspaceSnapshot,
    ) -> None:
        payload = json.dumps(asdict(session_snapshot), ensure_ascii=False)
        with self._conn:
            self._conn.execute(
                "INSERT INTO sessions(session_id, payload, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (session_snapshot.session_id, payload, session_snapshot.updated_at),
            )
            self._write_workspace_sync(workspace_snapshot)

    # -- async API (single writer, cancellation-safe) --

    async def _run_exclusive(self, func, *args):
        async with self._lock:
            loop = asyncio.get_running_loop()
            fut = loop.run_in_executor(None, func, *args)
            cancelled = False
            while not fut.done():
                try:
                    await asyncio.shield(fut)
                except asyncio.CancelledError:
                    cancelled = True
                    continue
            result = fut.result()
            if cancelled:
                raise asyncio.CancelledError()
            return result

    async def save(
        self,
        snapshot: SessionSnapshot,
        pending_tombstones: Optional[List[RequestTombstone]] = None,
    ) -> None:
        if pending_tombstones is not None:
            await self._run_exclusive(self._save_sync, snapshot, pending_tombstones)
        else:
            await self._run_exclusive(self._save_sync, snapshot)

    async def get_request_tombstone(
        self, session_id: str, request_id: str
    ) -> Optional[RequestTombstone]:
        return await self._run_exclusive(
            self._get_request_tombstone_sync, session_id, request_id
        )

    async def load(self, session_id: str) -> Optional[SessionSnapshot]:
        return await self._run_exclusive(self._load_sync, session_id)

    async def delete(self, session_id: str) -> None:
        await self._run_exclusive(self._delete_sync, session_id)

    async def list_ids(self) -> List[str]:
        return await self._run_exclusive(self._list_ids_sync)

    async def load_workspace(self) -> WorkspaceSnapshot:
        return await self._run_exclusive(self._load_workspace_sync)

    async def save_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        await self._run_exclusive(self._write_workspace, snapshot)

    def _write_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        with self._conn:
            self._write_workspace_sync(snapshot)

    async def switch_session(
        self,
        session_snapshot: SessionSnapshot,
        workspace_snapshot: WorkspaceSnapshot,
    ) -> None:
        await self._run_exclusive(self._switch_sync, session_snapshot, workspace_snapshot)

    async def close(self) -> None:
        await self._run_exclusive(self._conn.close)
