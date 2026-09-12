"""Workspace persistence package (Phase 3).

Owns durable storage for the single-user workspace: per-session snapshots plus
the workspace-level ``last_active_session_id`` pointer.
"""

from .snapshot import (
    SessionSnapshot,
    WorkspaceSnapshot,
    session_to_snapshot,
    snapshot_to_session,
)

__all__ = [
    "SessionSnapshot",
    "WorkspaceSnapshot",
    "session_to_snapshot",
    "snapshot_to_session",
]
