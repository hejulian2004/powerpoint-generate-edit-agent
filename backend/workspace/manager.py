"""WorkspaceManager: the durable single-user workspace.

Composes ``SessionManager`` (in-memory live sessions) with a repository (durable
snapshots) and a ``SessionPersistenceService`` (debounced writes). It owns the
workspace-level ``last_active_session_id`` pointer (S5/S6).
"""

from __future__ import annotations

import logging
from typing import Optional

from ..ir.models import PresentationIR
from ..session.manager import SessionManager
from ..session.snapshot import WorkspaceSnapshot, session_to_snapshot, snapshot_to_session
from .persistence import SessionPersistenceService

logger = logging.getLogger(__name__)


class WorkspaceManager:
    def __init__(
        self,
        session_manager: SessionManager,
        repository,
        *,
        debounce_seconds: float = 0.5,
    ) -> None:
        self._sessions = session_manager
        self._repo = repository
        self._persistence = SessionPersistenceService(
            repository, self._sessions.get_session, debounce_seconds=debounce_seconds
        )
        self._last_active_session_id: Optional[str] = None

    @property
    def persistence(self) -> SessionPersistenceService:
        return self._persistence

    @property
    def last_active_session_id(self) -> Optional[str]:
        return self._last_active_session_id

    def _bind(self, session) -> None:
        session.persistence = self._persistence

    async def _save_session(self, session) -> None:
        await self._repo.save(session_to_snapshot(session))

    async def _save_workspace(self, *, last_active_session_id: Optional[str] = None) -> None:
        session_ids = await self._repo.list_ids()
        snapshot = WorkspaceSnapshot(
            last_active_session_id=(
                last_active_session_id
                if last_active_session_id is not None
                else self._last_active_session_id
            ),
            session_ids=session_ids,
        )
        saver = getattr(self._repo, "save_workspace", None)
        if saver is not None:
            await saver(snapshot)

    async def create_session(
        self,
        pres: Optional[PresentationIR] = None,
        session_id: Optional[str] = None,
    ):
        session = self._sessions.create_session(pres, session_id=session_id)
        self._bind(session)
        await self._save_session(session)
        self._last_active_session_id = session.session_id
        await self._save_workspace(last_active_session_id=session.session_id)
        return session

    async def restore_session(self, session_id: str):
        snapshot = await self._repo.load(session_id)
        if snapshot is None:
            return None
        session = snapshot_to_session(snapshot)
        self._bind(session)
        self._sessions.register(session)
        return session

    async def activate(self, session_id: str):
        """Restores (if needed) and marks ``session_id`` as the active workspace.

        Flushes the session and moves the pointer in one repository transaction so
        the workspace can never reference an unwritten session row.
        """
        session = self._sessions.get_session(session_id)
        if session is None:
            session = await self.restore_session(session_id)
        if session is None:
            return None
        self._bind(session)
        await self._persistence.flush_session_id(session_id)
        snapshot = session_to_snapshot(session)
        session_ids = await self._repo.list_ids()
        if session_id not in session_ids:
            session_ids.append(session_id)
        workspace = WorkspaceSnapshot(
            last_active_session_id=session_id, session_ids=session_ids
        )
        switcher = getattr(self._repo, "switch_session", None)
        if switcher is not None:
            await switcher(snapshot, workspace)
        else:
            await self._repo.save(snapshot)
            await self._save_workspace(last_active_session_id=session_id)
        self._last_active_session_id = session_id
        return session

    async def restore_last_active(self):
        workspace = await self._repo.load_workspace()
        self._last_active_session_id = workspace.last_active_session_id
        if not workspace.last_active_session_id:
            return None
        return await self.restore_session(workspace.last_active_session_id)

    async def close(self) -> None:
        await self._persistence.close()
        await self._repo.close()
