"""Process-wide WorkspaceManager lifecycle.

Created on FastAPI startup (``lifespan``) and closed on shutdown so a graceful
restart flushes all dirty sessions. Exposed via ``get_workspace_manager`` for
transport layers.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from ..session.manager import session_manager
from .manager import WorkspaceManager
from .repository import DEFAULT_DB_PATH, SQLiteRepository

logger = logging.getLogger(__name__)

_workspace_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> Optional[WorkspaceManager]:
    return _workspace_manager


def set_workspace_manager(manager: Optional[WorkspaceManager]) -> None:
    global _workspace_manager
    _workspace_manager = manager


def _resolve_db_path(db_path: Optional[Path]) -> Path:
    if db_path is not None:
        return Path(db_path)
    env_path = os.environ.get("WORKSPACE_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


async def startup_workspace(db_path: Optional[Path] = None) -> WorkspaceManager:
    repository = SQLiteRepository(_resolve_db_path(db_path))
    manager = WorkspaceManager(session_manager, repository)
    set_workspace_manager(manager)
    restored = await manager.restore_last_active()
    if restored is not None:
        logger.info("Restored last active session '%s'", restored.session_id)
    return manager


async def shutdown_workspace() -> None:
    manager = get_workspace_manager()
    if manager is None:
        return
    await manager.close()
    set_workspace_manager(None)
