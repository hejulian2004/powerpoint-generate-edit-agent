"""Interactive PPTSession: a thin aggregate over isolated session services.

State ownership (S2/S3) lives in the services:

    PPTSession
        document:        DocumentService        (IR, epoch, lock, CAS, idempotency)
        history_service: HistoryService         (undo/redo command stack)
        checkpoint_service: CheckpointService   (retained snapshots)
        memory:          MemoryService          (messages, agent/subagent memory)
        confirmations:   ConfirmationService    (pending low-confidence calls)
        agent_execution: AgentExecutionService  (exclusive Agent edit window)
        connection:      ConnectionService      (single writable frontend)

For backward compatibility this class still exposes delegating properties and
methods (``pres``, ``document_epoch``, ``history``, ``messages``, ...). New code
must use the service APIs; a contract test forbids *new* direct mutation of the
legacy surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..ir.models import PresentationIR, SlideIR
from .services.document import (
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
from .services.agent_execution import AgentExecutionService
from .services.checkpoint import CheckpointService
from .services.confirmation import ConfirmationService
from .services.connection import ConnectionService
from .services.history import HistoryService
from .services.memory import MemoryService

__all__ = [
    "CHECKPOINT_NOT_FOUND",
    "COMPLETED_MUTATION_LIMIT",
    "DOCUMENT_EPOCH_MISMATCH",
    "ExportSnapshot",
    "MISSING_REPLACEMENT_STAMP",
    "PPTSession",
    "ReplacementResult",
    "STALE_GENERATION",
    "STALE_MUTATION",
]


class PPTSession:
    """A persistent interactive session with isolated presentation state."""

    def __init__(
        self,
        session_id: str,
        pres: Optional[PresentationIR] = None,
        *,
        init_baseline: bool = True,
    ):
        self.session_id = session_id
        if pres is None:
            pres = PresentationIR(title="Untitled Presentation")

        self.history_service = HistoryService()
        self.checkpoint_service = CheckpointService(session_id=session_id)
        self.memory = MemoryService()
        self.confirmations = ConfirmationService()

        # DocumentService needs the history/checkpoint/confirmation collaborators
        # so a replacement can reset all of them atomically.
        self.document = DocumentService(
            session_id,
            pres,
            history=self.history_service,
            checkpoints=self.checkpoint_service,
            confirmations=self.confirmations,
        )

        self.agent_execution = AgentExecutionService()
        self.connection = ConnectionService()
        self.iterations: List[Dict[str, Any]] = []
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        # Attached by WorkspaceManager; marks committed state dirty for debounced
        # durable persistence (contract P3).
        self.persistence: Any = None

        if init_baseline:
            self.checkpoint_service.create(pres, description="Initial session state")

    # ------------------------------------------------------------------
    # Compatibility surface (delegating). New code should use services.
    # ------------------------------------------------------------------

    @property
    def pres(self) -> PresentationIR:
        return self.document.presentation

    @pres.setter
    def pres(self, val: PresentationIR) -> None:
        self.document.presentation = val

    @property
    def document_epoch(self) -> str:
        return self.document.epoch

    @document_epoch.setter
    def document_epoch(self, val: str) -> None:
        self.document.epoch = val

    @property
    def mutation_lock(self) -> Any:
        return self.document.mutation_lock

    @property
    def completed_mutations(self) -> Any:
        return self.document.completed_mutations

    @property
    def last_target_id(self) -> Optional[str]:
        return self.document.last_target_id

    @last_target_id.setter
    def last_target_id(self, val: Optional[str]) -> None:
        self.document.last_target_id = val

    @property
    def last_action_type(self) -> Optional[str]:
        return self.document.last_action_type

    @last_action_type.setter
    def last_action_type(self, val: Optional[str]) -> None:
        self.document.last_action_type = val

    @property
    def messages(self) -> List[Dict[str, Any]]:
        return self.memory.messages

    @property
    def agent_memory(self) -> Any:
        return self.memory.agent_memory

    @agent_memory.setter
    def agent_memory(self, val: Any) -> None:
        self.memory.agent_memory = val

    @property
    def pending_confirmations(self) -> Dict[str, Dict[str, Any]]:
        return self.confirmations.pending

    @property
    def history(self) -> Any:
        return self.history_service.stack

    @history.setter
    def history(self, val: Any) -> None:
        self.history_service.stack = val

    @property
    def checkpoints(self) -> List[Any]:
        return self.checkpoint_service.items

    @property
    def active_slide_id(self) -> Optional[str]:
        return self.document.active_slide_id

    @active_slide_id.setter
    def active_slide_id(self, val: Optional[str]) -> None:
        self.document.active_slide_id = val

    # ------------------------------------------------------------------
    # Idempotency cache (delegates to DocumentService)
    # ------------------------------------------------------------------

    def get_cached_mutation_result(self, *args: Any, **kwargs: Any) -> Any:
        return self.document.get_cached_mutation_result(*args, **kwargs)

    def cached_mutation_payload_mismatch(self, *args: Any, **kwargs: Any) -> Any:
        return self.document.cached_mutation_payload_mismatch(*args, **kwargs)

    def remember_mutation_result(self, *args: Any, **kwargs: Any) -> Any:
        return self.document.remember_mutation_result(*args, **kwargs)

    # ------------------------------------------------------------------
    # Pending confirmation lifecycle (delegates to ConfirmationService)
    # ------------------------------------------------------------------

    def register_pending_confirmation(
        self,
        call_id: str,
        tool: str,
        arguments: Dict[str, Any],
        confidence: Optional[float],
        presentation_version: int,
        target_element_id: Optional[str] = None,
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        if document_epoch is None:
            document_epoch = self.document.epoch
        record = self.confirmations.register(
            call_id=call_id,
            tool=tool,
            arguments=arguments,
            confidence=confidence,
            presentation_version=presentation_version,
            target_element_id=target_element_id,
            document_epoch=document_epoch,
            expected_revision=expected_revision,
        )
        self.updated_at = datetime.now(timezone.utc)
        return record

    def get_pending_confirmation(self, call_id: str) -> Optional[Dict[str, Any]]:
        return self.confirmations.get(call_id)

    def consume_pending_confirmation(self, call_id: str) -> Optional[Dict[str, Any]]:
        record = self.confirmations.consume(call_id)
        if record is not None:
            self.updated_at = datetime.now(timezone.utc)
        return record

    def clear_pending_confirmations(self) -> None:
        if self.confirmations.clear():
            self.updated_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Document lifecycle (delegates to DocumentService)
    # ------------------------------------------------------------------

    def _unsafe_install_for_bootstrap(self, *args: Any, **kwargs: Any) -> None:
        self.document._unsafe_install_for_bootstrap(*args, **kwargs)
        self.updated_at = datetime.now(timezone.utc)

    def _finalize_inplace_replacement_locked(self, *args: Any, **kwargs: Any) -> None:
        self.document._finalize_inplace_replacement_locked(*args, **kwargs)
        self.updated_at = datetime.now(timezone.utc)

    def _restore_checkpoint_unchecked(self, *args: Any, **kwargs: Any) -> bool:
        result = self.document._restore_checkpoint_unchecked(*args, **kwargs)
        if result:
            self.updated_at = datetime.now(timezone.utc)
        return result

    async def commit_replacement(self, *args: Any, **kwargs: Any) -> ReplacementResult:
        result = await self.document.commit_replacement(*args, **kwargs)
        self.updated_at = datetime.now(timezone.utc)
        self.schedule_persist()
        return result

    async def commit_checkpoint_restore(self, *args: Any, **kwargs: Any) -> ReplacementResult:
        result = await self.document.commit_checkpoint_restore(*args, **kwargs)
        self.updated_at = datetime.now(timezone.utc)
        self.schedule_persist()
        return result

    async def snapshot_for_export(self) -> ExportSnapshot:
        return await self.document.snapshot_for_export()

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    def get_active_slide(self) -> Optional[SlideIR]:
        return self.document.get_active_slide()

    def set_active_slide(self, slide_id: str) -> bool:
        ok = self.document.set_active_slide(slide_id)
        if ok:
            self.updated_at = datetime.now(timezone.utc)
        return ok

    # ------------------------------------------------------------------
    # History / checkpoints
    # ------------------------------------------------------------------

    def undo(self) -> Any:
        cmd = self.history_service.undo(self.document.presentation)
        if cmd:
            self.updated_at = datetime.now(timezone.utc)
        return cmd

    def redo(self) -> Any:
        cmd = self.history_service.redo(self.document.presentation)
        if cmd:
            self.updated_at = datetime.now(timezone.utc)
        return cmd

    def create_checkpoint(
        self,
        description: str = "",
        score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        cp = self.checkpoint_service.create(
            pres=self.document.presentation,
            description=description,
            score=score,
            metadata=metadata,
        )
        self.updated_at = datetime.now(timezone.utc)
        return cp

    # ------------------------------------------------------------------
    # Conversation / iterations
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        vision_critique: Optional[str] = None,
        visual_review: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        msg = self.memory.add_message(
            role=role,
            content=content,
            tool_calls=tool_calls,
            vision_critique=vision_critique,
            visual_review=visual_review,
        )
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def record_iteration(self, iteration_data: Any) -> None:
        if hasattr(iteration_data, "to_dict"):
            self.iterations.append(iteration_data.to_dict())
        else:
            self.iterations.append(iteration_data)
        self.updated_at = datetime.now(timezone.utc)

    def schedule_persist(self) -> None:
        """Marks committed state dirty for debounced durable persistence.

        No-op when no persistence service is attached (unit tests, pure IR use).
        """
        if self.persistence is not None:
            self.persistence.schedule(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.document.presentation.title,
            "slides_count": len(self.document.presentation.slides),
            "active_slide_id": self.active_slide_id,
            "version": self.document.presentation.version,
            "messages_count": len(self.memory.messages),
            "checkpoints_count": len(self.checkpoints),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "can_undo": self.history_service.can_undo(),
            "can_redo": self.history_service.can_redo(),
            "last_target_id": self.document.last_target_id,
            "pending_confirmations_count": len(self.confirmations.pending),
        }
