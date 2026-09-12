"""Re-exports the canonical snapshot value objects / converters.

The value objects live in ``backend.session.snapshot`` so the session package can
depend on them without importing the workspace package (which depends on
sessions). This module gives the workspace package a stable public surface.
"""

from ..session.snapshot import (
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
