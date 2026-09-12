"""Session service layer.

A ``PPTSession`` is a thin aggregate that owns one isolated instance of each
service below. Services own the actual state; ``PPTSession`` only exposes
delegating compatibility properties/methods so existing call sites keep working
while new code uses the service API directly.

Isolation invariant (S2/S3): a ``PresentationIR`` object, its history, its
checkpoints, its conversation/memory, and its pending confirmations belong to
exactly one session.
"""

from .agent_execution import AgentExecutionService
from .checkpoint import CheckpointService
from .confirmation import ConfirmationService
from .connection import ConnectionService
from .document import (
    COMPLETED_MUTATION_LIMIT,
    CHECKPOINT_NOT_FOUND,
    DOCUMENT_EPOCH_MISMATCH,
    MISSING_REPLACEMENT_STAMP,
    STALE_GENERATION,
    STALE_MUTATION,
    DocumentService,
    ExportSnapshot,
    ReplacementResult,
)
from .history import HistoryService
from .memory import MemoryService

__all__ = [
    "AgentExecutionService",
    "CHECKPOINT_NOT_FOUND",
    "COMPLETED_MUTATION_LIMIT",
    "CheckpointService",
    "ConfirmationService",
    "ConnectionService",
    "DOCUMENT_EPOCH_MISMATCH",
    "DocumentService",
    "ExportSnapshot",
    "HistoryService",
    "MISSING_REPLACEMENT_STAMP",
    "MemoryService",
    "ReplacementResult",
    "STALE_GENERATION",
    "STALE_MUTATION",
]
