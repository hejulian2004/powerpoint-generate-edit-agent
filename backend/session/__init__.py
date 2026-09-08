"""Session management module for persistent, stateful interactive PPT editing."""

from .checkpoint import SessionCheckpoint, CheckpointManager
from .session import PPTSession
from .manager import SessionManager, session_manager

__all__ = [
    "SessionCheckpoint",
    "CheckpointManager",
    "PPTSession",
    "SessionManager",
    "session_manager"
]
