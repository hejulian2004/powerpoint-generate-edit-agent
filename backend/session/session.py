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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from collections import OrderedDict
import asyncio
import json
import logging
import time

logger = logging.getLogger(__name__)

from ..ir.models import PresentationIR, SlideIR
from .snapshot import SessionSnapshot, session_to_snapshot
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
from .services.plan_confirmation import PlanConfirmationService

MAX_COMPLETED_REQUESTS = 32
MAX_COMPLETED_REQUEST_BYTES = 32 * 1024 * 1024  # 32 MiB
MAX_COMPLETED_REQUEST_RECORD_BYTES = 16 * 1024 * 1024  # 16 MiB
MAX_COMPLETED_TOMBSTONES = 1024


@dataclass
class RequestOutcome:
    ok: bool
    response: Optional[Dict[str, Any]] = None
    status_code: Optional[int] = None
    detail: Any = None


class RequestExecution:
    def __init__(self, fingerprint: str, future: asyncio.Future, admitted_generation: int):
        self.fingerprint = fingerprint
        self.future = future
        self.admitted_generation = admitted_generation


@dataclass
class CompletedRequestRecord:
    request_id: str
    fingerprint: str
    response: Dict[str, Any]
    admitted_generation: int
    size_bytes: int = 0
    durable: bool = False


@dataclass
class RequestTombstone:
    request_id: str
    fingerprint: str
    admitted_generation: int
    completed_at: str = ""


@dataclass
class FailedRequestRecord:
    request_id: str
    fingerprint: str
    conversation_generation: int
    outcome: RequestOutcome
    expire_at: float


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
    "RequestOutcome",
    "RequestExecution",
    "CompletedRequestRecord",
    "RequestTombstone",
    "FailedRequestRecord",
    "MAX_COMPLETED_REQUESTS",
    "MAX_COMPLETED_REQUEST_BYTES",
    "MAX_COMPLETED_REQUEST_RECORD_BYTES",
    "MAX_COMPLETED_TOMBSTONES",
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
        self.plan_confirmations = PlanConfirmationService()
        # Session-level interaction mode: "auto" (plan and execute in one turn) or
        # "plan" (pause after the plan critic approves for explicit user approval).
        # Ephemeral like confirmations; never persisted (contract P2).
        self.interaction_mode: str = "auto"

        # The Agent edit window must exist before the DocumentService so it can be
        # injected as the replacement authorization collaborator.
        self.agent_execution = AgentExecutionService()

        # DocumentService needs the history/checkpoint/confirmation collaborators
        # so a replacement can reset all of them atomically.
        self.document = DocumentService(
            session_id,
            pres,
            history=self.history_service,
            checkpoints=self.checkpoint_service,
            confirmations=self.confirmations,
            agent_execution=self.agent_execution,
        )

        self.connection = ConnectionService()
        self.iterations: List[Dict[str, Any]] = []
        self.committed_turns: Dict[str, Dict[str, Any]] = {}  # request_id -> turn DTO
        self.conversation_generation: int = 0
        self.completed_requests: OrderedDict[str, CompletedRequestRecord] = OrderedDict()
        self.completed_tombstones: OrderedDict[str, RequestTombstone] = OrderedDict()
        self.pending_tombstones: Dict[str, RequestTombstone] = {}  # uncommitted write-set for atomic SQLite commit
        self.failed_requests: OrderedDict[str, FailedRequestRecord] = OrderedDict()
        self.in_flight_requests: Dict[str, RequestExecution] = {}
        self._request_journal_lock: Optional[asyncio.Lock] = None
        self._request_journal_lock_loop: Optional[Any] = None

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
    # Pending plan lifecycle (delegates to PlanConfirmationService)
    # ------------------------------------------------------------------

    @property
    def pending_plans(self) -> Dict[str, Dict[str, Any]]:
        return self.plan_confirmations.pending

    def register_pending_plan(
        self,
        plan_id: str,
        plan: str,
        plan_review: Optional[Dict[str, Any]] = None,
        user_query: str = "",
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
        active_slide_id: Optional[str] = None,
        ui_context: Optional[Dict[str, Any]] = None,
        ui_context_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        if document_epoch is None:
            document_epoch = self.document.epoch
        record = self.plan_confirmations.register(
            plan_id=plan_id,
            plan=plan,
            plan_review=plan_review,
            user_query=user_query,
            document_epoch=document_epoch,
            expected_revision=expected_revision,
            active_slide_id=active_slide_id,
            ui_context=ui_context,
            ui_context_revision=ui_context_revision,
        )
        self.updated_at = datetime.now(timezone.utc)
        return record

    def get_pending_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        return self.plan_confirmations.get(plan_id)

    def consume_pending_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        record = self.plan_confirmations.consume(plan_id)
        if record is not None:
            self.updated_at = datetime.now(timezone.utc)
        return record

    def clear_pending_plans(self) -> None:
        if self.plan_confirmations.clear():
            self.updated_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Document lifecycle (delegates to DocumentService)
    # ------------------------------------------------------------------

    def _unsafe_install_for_bootstrap(self, *args: Any, **kwargs: Any) -> None:
        self.document._unsafe_install_for_bootstrap(*args, **kwargs)
        self.plan_confirmations.clear()
        self.updated_at = datetime.now(timezone.utc)

    def _finalize_inplace_replacement_locked(self, *args: Any, **kwargs: Any) -> None:
        self.document._finalize_inplace_replacement_locked(*args, **kwargs)
        self.plan_confirmations.clear()
        self.updated_at = datetime.now(timezone.utc)

    def _restore_checkpoint_unchecked(self, *args: Any, **kwargs: Any) -> bool:
        result = self.document._restore_checkpoint_unchecked(*args, **kwargs)
        if result:
            self.updated_at = datetime.now(timezone.utc)
        return result

    async def commit_replacement(self, *args: Any, **kwargs: Any) -> ReplacementResult:
        result = await self.document.commit_replacement(*args, **kwargs)
        if result.committed:
            self.plan_confirmations.clear()
            self.updated_at = datetime.now(timezone.utc)
            self.schedule_persist()
        return result

    async def commit_checkpoint_restore(self, *args: Any, **kwargs: Any) -> ReplacementResult:
        result = await self.document.commit_checkpoint_restore(*args, **kwargs)
        if result.committed:
            self.plan_confirmations.clear()
            self.updated_at = datetime.now(timezone.utc)
            self.schedule_persist()
        return result

    async def snapshot_for_export(self) -> ExportSnapshot:
        return await self.document.snapshot_for_export()

    async def snapshot_for_persistence(
        self, with_pending_tombstones: bool = False
    ) -> Union[SessionSnapshot, Tuple[SessionSnapshot, List[RequestTombstone]]]:
        """Atomically captures durable state under the strict lock hierarchy:

        conversation_lock -> document.mutation_lock -> request_journal_lock.
        A persistence flush must observe a consistent revision, complete conversational
        turn, and consistent completed replay journal state at the exact same moment.
        """
        async with self.memory.conversation_lock:
            async with self.document.mutation_lock:
                async with self.request_journal_lock:
                    snapshot = session_to_snapshot(self)
                    if with_pending_tombstones:
                        pending = list(self.pending_tombstones.values())
                        return snapshot, pending
                    return snapshot

    def ack_persisted_tombstones(self, committed_ids: List[str]) -> None:
        """Removes committed request IDs from pending_tombstones after DB transaction succeeds."""
        for req_id in committed_ids:
            self.pending_tombstones.pop(req_id, None)

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

    @property
    def request_journal_lock(self) -> asyncio.Lock:
        """The request-journal mutex, lazily bound to the caller's running loop."""
        try:
            loop: Optional[Any] = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._request_journal_lock is None or self._request_journal_lock_loop is not loop:
            self._request_journal_lock = asyncio.Lock()
            self._request_journal_lock_loop = loop
        return self._request_journal_lock

    def get_completed_request(self, request_id: str) -> Optional[CompletedRequestRecord]:
        return self.completed_requests.get(request_id)

    def get_request_tombstone(self, request_id: str) -> Optional[RequestTombstone]:
        return self.completed_tombstones.get(request_id)

    def record_completed_request(
        self,
        request_id: str,
        fingerprint: str,
        response: Dict[str, Any],
        admitted_generation: int,
        durable: bool = False,
        schedule_persist: bool = True,
    ) -> CompletedRequestRecord:
        """Records a completed request into two tiers:

        Tier 1: Bounded response cache (count <= 32, bytes <= 32 MiB).
        Tier 2: Compact durable tombstones (count <= 1024) to reject expired replay side-effects.
        """
        if not request_id:
            raise ValueError("request_id is required")
        try:
            size_bytes = len(
                json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except Exception:
            size_bytes = 1024

        if size_bytes > MAX_COMPLETED_REQUEST_RECORD_BYTES:
            raise RuntimeError(
                f"COMPACT_REPLAY_RESPONSE_INVARIANT_VIOLATION: Response for {request_id} "
                f"exceeds limit ({size_bytes} > {MAX_COMPLETED_REQUEST_RECORD_BYTES} bytes)"
            )

        assert size_bytes <= MAX_COMPLETED_REQUEST_RECORD_BYTES, (
            f"Compact response for {request_id} must not exceed {MAX_COMPLETED_REQUEST_RECORD_BYTES} bytes"
        )

        record = CompletedRequestRecord(
            request_id=request_id,
            fingerprint=fingerprint,
            response=response,
            admitted_generation=admitted_generation,
            size_bytes=size_bytes,
            durable=durable,
        )

        # Tier 2: Record durable compact tombstone in memory LRU cache and uncommitted write-set
        tombstone = RequestTombstone(
            request_id=request_id,
            fingerprint=fingerprint,
            admitted_generation=admitted_generation,
            completed_at=str(time.time()),
        )
        while len(self.completed_tombstones) >= MAX_COMPLETED_TOMBSTONES:
            self.completed_tombstones.popitem(last=False)
        self.completed_tombstones[request_id] = tombstone
        self.pending_tombstones[request_id] = tombstone

        # Tier 1: Evict oldest if count exceeds MAX_COMPLETED_REQUESTS
        while len(self.completed_requests) >= MAX_COMPLETED_REQUESTS:
            self.completed_requests.popitem(last=False)

        # Tier 1: Evict oldest if total bytes exceed MAX_COMPLETED_REQUEST_BYTES
        current_bytes = sum(r.size_bytes for r in self.completed_requests.values()) + size_bytes
        while current_bytes > MAX_COMPLETED_REQUEST_BYTES and self.completed_requests:
            evicted = self.completed_requests.popitem(last=False)[1]
            current_bytes -= evicted.size_bytes

        self.completed_requests[request_id] = record
        self.updated_at = datetime.now(timezone.utc)
        if schedule_persist:
            self.schedule_persist()
        return record

    def record_failed_request(
        self,
        request_id: str,
        fingerprint: str,
        outcome: RequestOutcome,
        ttl_seconds: float = 5.0,
    ) -> None:
        """Records a short-lived terminal failure in memory, bound to conversation_generation."""
        if not request_id:
            return
        # Lazy eviction of expired
        now = time.monotonic()
        for k in list(self.failed_requests.keys()):
            if self.failed_requests[k].expire_at <= now:
                self.failed_requests.pop(k, None)

        while len(self.failed_requests) >= 64:
            self.failed_requests.popitem(last=False)

        self.failed_requests[request_id] = FailedRequestRecord(
            request_id=request_id,
            fingerprint=fingerprint,
            conversation_generation=self.conversation_generation,
            outcome=outcome,
            expire_at=now + ttl_seconds,
        )

    async def commit_conversation_turn(
        self,
        request_id: str,
        user_content: str,
        assistant_content: str,
        provenance: Optional[List[Dict[str, Any]]] = None,
        admitted_generation: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Atomically commits a single canonical conversation turn (User + Assistant).

        Idempotent by request_id: retrying with the same request_id returns the exact
        same committed turn DTO without creating duplicate messages in memory.
        If admitted_generation is provided, rejects commit if conversation was reset.
        """
        async with self.memory.conversation_lock:
            if admitted_generation is not None and admitted_generation != self.conversation_generation:
                raise RuntimeError("CONVERSATION_RESET_DURING_REQUEST")

            if request_id and request_id in self.committed_turns:
                return self.committed_turns[request_id]

            user_msg = self.add_message(role="user", content=user_content)
            asst_msg = self.add_message(role="assistant", content=assistant_content)

            import time
            turn_dto = {
                "turn_id": f"turn_{int(time.time() * 1000)}_{len(self.memory.messages)}",
                "request_id": request_id or "",
                "user": user_msg,
                "assistant": asst_msg,
                "provenance": provenance or [],
            }
            if request_id:
                # Bounded cache of recently committed turns
                if len(self.committed_turns) >= 200:
                    oldest = next(iter(self.committed_turns))
                    self.committed_turns.pop(oldest, None)
                self.committed_turns[request_id] = turn_dto

            self.updated_at = datetime.now(timezone.utc)
            self.schedule_persist()
            return turn_dto

    def record_iteration(self, iteration_data: Any) -> None:
        if hasattr(iteration_data, "to_dict"):
            self.iterations.append(iteration_data.to_dict())
        else:
            self.iterations.append(iteration_data)
        self.updated_at = datetime.now(timezone.utc)

    async def reset_conversation(self) -> None:
        """Starts a brand-new conversation while preserving the deck and history.

        Clears the transcript, Agent memory, subagent memories and any manual
        compression anchor, and also drops pending confirmations/plans so no
        orphaned server-side actions survive the reset. The presentation,
        document epoch, checkpoints and interaction mode are preserved.
        """
        async with self.memory.conversation_lock:
            async with self.request_journal_lock:
                self.conversation_generation += 1
                self.committed_turns.clear()
                self.completed_requests.clear()
                # Contract: completed_tombstones & pending_tombstones are session-scoped and 7-day durable;
                # reset_conversation() NEVER deletes tombstones, preserving idempotency across resets.
                self.failed_requests.clear()
            self.memory.clear_conversation()
            self.confirmations.clear()
            self.plan_confirmations.clear()
        self.updated_at = datetime.now(timezone.utc)
        self.schedule_persist()

    def set_interaction_mode(self, mode: str) -> str:
        self.interaction_mode = "plan" if mode == "plan" else "auto"
        self.updated_at = datetime.now(timezone.utc)
        return self.interaction_mode

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
            "pending_plans_count": len(self.plan_confirmations.pending),
            "interaction_mode": self.interaction_mode,
        }
