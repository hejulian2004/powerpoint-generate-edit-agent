"""Interactive PPTSession representing a stateful, multi-turn editing workspace."""

from __future__ import annotations
import uuid
import copy
import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from ..ir.models import PresentationIR, SlideIR
from ..history.undo_stack import UndoRedoStack
from ..history.command import MutationCommand
from .checkpoint import SessionCheckpoint, CheckpointManager

# Bounded idempotency window for caller-supplied mutation ids. This is a short
# retry/dedup buffer, not a mutation history, so it stays small.
COMPLETED_MUTATION_LIMIT = 256


def _default_agent_memory():
    """Lazily constructs an AgentMemory to avoid an import cycle with backend.agent."""
    from ..agent.memory import AgentMemory
    return AgentMemory()


# Terminal errors for a compare-and-swap whole-document replacement.
STALE_GENERATION = "stale_generation"
DOCUMENT_EPOCH_MISMATCH = "document_epoch_mismatch"
CHECKPOINT_NOT_FOUND = "checkpoint_not_found"
STALE_MUTATION = "stale_mutation"
MISSING_REPLACEMENT_STAMP = "missing_replacement_stamp"


@dataclass
class ReplacementResult:
    """Outcome of a CAS-guarded whole-document replacement."""

    committed: bool
    error: Optional[str] = None
    old_epoch: Optional[str] = None
    old_revision: Optional[int] = None
    document_epoch: Optional[str] = None
    version: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "committed": self.committed,
            "error": self.error,
            "old_epoch": self.old_epoch,
            "old_revision": self.old_revision,
            "document_epoch": self.document_epoch,
            "version": self.version,
        }


@dataclass
class PPTSession:
    """A persistent interactive session with presentation state, history, checkpoints, and dialogue."""
    session_id: str
    pres: PresentationIR
    history: UndoRedoStack = field(default_factory=UndoRedoStack)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    checkpoint_mgr: CheckpointManager = field(init=False)
    iterations: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_target_id: Optional[str] = None
    last_action_type: Optional[str] = None
    pending_confirmations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Session-scoped agent memory: activity/preferences never leak across sessions.
    agent_memory: Any = field(default_factory=_default_agent_memory)
    # Identity of the current document. Rotated whenever the presentation object is
    # wholesale replaced (import / generation / checkpoint restore) so stale pending
    # confirmations can never act on a different deck that happens to share a version.
    document_epoch: str = field(default_factory=lambda: uuid.uuid4().hex)
    mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    # (document_epoch, mutation_id) -> terminal MutationBatchResult. Contract: a
    # given key must denote the SAME logical request; duplicate ids return the
    # first outcome (no payload fingerprint / request hash in this version).
    completed_mutations: "OrderedDict[Any, Any]" = field(default_factory=OrderedDict)

    def __post_init__(self):
        self.checkpoint_mgr = CheckpointManager(session_id=self.session_id)
        # Create initial baseline checkpoint
        self.checkpoint_mgr.create(self.pres, description="Initial session state")

    # ------------------------------------------------------------------
    # Idempotency cache (caller-supplied mutation ids)
    # ------------------------------------------------------------------

    def _mutation_cache_key(
        self,
        mutation_id: str,
        document_epoch: Optional[str] = None,
    ):
        """Effective key; a None epoch resolves to the live document epoch."""
        return (
            document_epoch if document_epoch is not None else self.document_epoch,
            mutation_id,
        )

    def get_cached_mutation_result(
        self,
        mutation_id: str,
        document_epoch: Optional[str] = None,
    ) -> Optional[Any]:
        """Returns a deep copy of a terminal outcome, or None. Refreshes LRU order."""
        key = self._mutation_cache_key(mutation_id, document_epoch)
        result = self.completed_mutations.get(key)
        if result is None:
            return None
        self.completed_mutations.move_to_end(key)
        return copy.deepcopy(result)

    def remember_mutation_result(
        self,
        mutation_id: str,
        result: Any,
        document_epoch: Optional[str] = None,
    ) -> None:
        """Stores a deep-copied terminal outcome, evicting the oldest over the limit."""
        key = self._mutation_cache_key(mutation_id, document_epoch)
        self.completed_mutations[key] = copy.deepcopy(result)
        self.completed_mutations.move_to_end(key)
        while len(self.completed_mutations) > COMPLETED_MUTATION_LIMIT:
            self.completed_mutations.popitem(last=False)

    # ------------------------------------------------------------------
    # Pending confirmation lifecycle (PR6-hardening round 2)
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
        """Stores a blocked call so the user can confirm the *original* invocation."""
        record = {
            "call_id": call_id,
            "tool": tool,
            "arguments": dict(arguments or {}),
            "confidence": confidence,
            "presentation_version": presentation_version,
            "expected_revision": (
                expected_revision if expected_revision is not None else presentation_version
            ),
            "document_epoch": (
                document_epoch if document_epoch is not None else self.document_epoch
            ),
            "target_element_id": target_element_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.pending_confirmations[call_id] = record
        self.updated_at = datetime.now(timezone.utc)
        return record

    def get_pending_confirmation(self, call_id: str) -> Optional[Dict[str, Any]]:
        return self.pending_confirmations.get(call_id)

    def consume_pending_confirmation(self, call_id: str) -> Optional[Dict[str, Any]]:
        record = self.pending_confirmations.pop(call_id, None)
        if record is not None:
            self.updated_at = datetime.now(timezone.utc)
        return record

    def clear_pending_confirmations(self) -> None:
        if self.pending_confirmations:
            self.pending_confirmations.clear()
            self.updated_at = datetime.now(timezone.utc)

    def _unsafe_install_for_bootstrap(
        self,
        pres: PresentationIR,
        *,
        clear_history: bool = True,
        clear_checkpoints: bool = True,
        checkpoint_description: Optional[str] = None,
    ) -> None:
        """PRIVATE, CAS-BYPASSING primitive for bootstrap / test fixtures only.

        Production paths (HTTP routes, agent persistence, store wrappers) MUST use
        `await commit_replacement(...)`, which owns the lock and enforces the
        epoch/revision CAS. This method deliberately skips both. Do not expose it
        as a normal API; a contract test scans production call sites.
        """
        self.pres = pres
        self.document_epoch = uuid.uuid4().hex
        self.clear_pending_confirmations()
        self.completed_mutations.clear()
        self.last_target_id = None
        self.last_action_type = None
        if clear_history:
            self.history.clear()
        if clear_checkpoints:
            self.checkpoint_mgr.clear()
        if checkpoint_description:
            self.checkpoint_mgr.create(pres, description=checkpoint_description)
        self.updated_at = datetime.now(timezone.utc)

    def _finalize_inplace_replacement_locked(
        self,
        *,
        clear_history: bool = True,
        clear_checkpoints: bool = True,
        checkpoint_description: str = "Generated presentation",
    ) -> None:
        """Finalize an in-place whole-document replacement.

        The caller has already built the new deck on the SAME ``self.pres`` object
        (so every held reference stays valid) and MUST already hold
        ``mutation_lock``. This rotates the document identity, resets the target
        /action state, drops stale confirmations and the idempotency cache, clears
        history + checkpoints, and creates a fresh baseline checkpoint so the
        replacement has the same lifecycle as upload / PPTSpec generation.

        It is intentionally private: raw identity rotation must only be reachable
        from the gateway's lock-holding replacement path.
        """
        self.document_epoch = uuid.uuid4().hex
        # A replacement is a new document identity; the revision restarts. The
        # (epoch, revision) pair - never the revision alone - carries identity.
        self.pres.version = 1
        self.clear_pending_confirmations()
        self.completed_mutations.clear()
        self.last_target_id = None
        self.last_action_type = None
        if clear_history:
            self.history.clear()
        if clear_checkpoints:
            self.checkpoint_mgr.clear()
        self.checkpoint_mgr.create(self.pres, description=checkpoint_description)
        self.updated_at = datetime.now(timezone.utc)

    def _replacement_cas_error(
        self,
        expected_epoch: Optional[str],
        expected_revision: Optional[int],
        stale_error: str,
    ) -> Optional[ReplacementResult]:
        """Returns a rejected ReplacementResult, or None when the CAS passes."""
        if expected_epoch is not None and expected_epoch != self.document_epoch:
            return ReplacementResult(
                committed=False,
                error=DOCUMENT_EPOCH_MISMATCH,
                old_epoch=self.document_epoch,
                old_revision=self.pres.version,
                document_epoch=self.document_epoch,
                version=self.pres.version,
            )
        if expected_revision is not None and self.pres.version != expected_revision:
            return ReplacementResult(
                committed=False,
                error=stale_error,
                old_epoch=self.document_epoch,
                old_revision=self.pres.version,
                document_epoch=self.document_epoch,
                version=self.pres.version,
            )
        return None

    async def commit_replacement(
        self,
        pres: PresentationIR,
        *,
        expected_epoch: Optional[str],
        expected_revision: Optional[int],
        clear_history: bool = True,
        clear_checkpoints: bool = True,
        checkpoint_description: Optional[str] = None,
    ) -> ReplacementResult:
        """CAS-guarded whole-document replacement (import / generation / load).

        Owns the mutation lock and both CAS checks so callers cannot forget to
        guard a wholesale overwrite. Both stamps are REQUIRED; passing `None`
        fails closed rather than silently performing an unconditional overwrite.
        """
        async with self.mutation_lock:
            old_epoch = self.document_epoch
            old_revision = self.pres.version
            if expected_epoch is None or expected_revision is None:
                return ReplacementResult(
                    committed=False,
                    error=MISSING_REPLACEMENT_STAMP,
                    old_epoch=old_epoch,
                    old_revision=old_revision,
                    document_epoch=self.document_epoch,
                    version=self.pres.version,
                )
            rejection = self._replacement_cas_error(
                expected_epoch, expected_revision, STALE_GENERATION
            )
            if rejection is not None:
                return rejection
            self._unsafe_install_for_bootstrap(
                pres,
                clear_history=clear_history,
                clear_checkpoints=clear_checkpoints,
                checkpoint_description=checkpoint_description,
            )
            return ReplacementResult(
                committed=True,
                error=None,
                old_epoch=old_epoch,
                old_revision=old_revision,
                document_epoch=self.document_epoch,
                version=self.pres.version,
            )

    @property
    def checkpoints(self) -> List[SessionCheckpoint]:
        return self.checkpoint_mgr.checkpoints

    @property
    def active_slide_id(self) -> Optional[str]:
        return self.pres.active_slide_id

    @active_slide_id.setter
    def active_slide_id(self, val: Optional[str]):
        self.pres.active_slide_id = val

    def get_active_slide(self) -> Optional[SlideIR]:
        return self.pres.get_active_slide()

    def set_active_slide(self, slide_id: str) -> bool:
        slide = self.pres.get_slide(slide_id)
        if slide:
            self.pres.active_slide_id = slide_id
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        vision_critique: Optional[str] = None,
        visual_review: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "tool_calls": tool_calls or [],
            "vision_critique": vision_critique,
            "visual_review": visual_review
        }
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def create_checkpoint(
        self,
        description: str = "",
        score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SessionCheckpoint:
        cp = self.checkpoint_mgr.create(
            pres=self.pres,
            description=description,
            score=score,
            metadata=metadata
        )
        self.updated_at = datetime.now(timezone.utc)
        return cp

    def _restore_checkpoint_unchecked(
        self, checkpoint_id: str, clear_history: bool = True
    ) -> bool:
        """Raw, CAS-free projection rollback.

        Private on purpose: whole-document replacement is only legal through
        `commit_checkpoint_restore`, which owns the mutation lock and enforces the
        epoch/revision CAS. Bootstrap seeding uses `_unsafe_install_for_bootstrap`.
        """
        restored = self.checkpoint_mgr.restore(checkpoint_id)
        if restored:
            self.pres = restored
            # Restoring is a document-level rollback: rotate identity and drop stale
            # confirmations that were bound to the previous revision.
            self.document_epoch = uuid.uuid4().hex
            self.clear_pending_confirmations()
            self.completed_mutations.clear()
            if clear_history:
                self.history.clear()
            else:
                self.history.record(
                    action="restore_checkpoint",
                    description=f"Restored to checkpoint {checkpoint_id}",
                    source="session_checkpoint"
                )
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False

    async def commit_checkpoint_restore(
        self,
        checkpoint_id: str,
        *,
        expected_epoch: Optional[str],
        expected_revision: Optional[int],
        clear_history: bool = True,
    ) -> ReplacementResult:
        """CAS-guarded checkpoint restore. Owns the mutation lock.

        A restore is a whole-document rollback: it must reject when the live
        document moved past the caller's view, instead of blindly overwriting a
        newer revision. Both stamps are REQUIRED and fail closed when missing.
        """
        async with self.mutation_lock:
            old_epoch = self.document_epoch
            old_revision = self.pres.version
            if expected_epoch is None or expected_revision is None:
                return ReplacementResult(
                    committed=False,
                    error=MISSING_REPLACEMENT_STAMP,
                    old_epoch=old_epoch,
                    old_revision=old_revision,
                    document_epoch=self.document_epoch,
                    version=self.pres.version,
                )
            rejection = self._replacement_cas_error(
                expected_epoch, expected_revision, STALE_MUTATION
            )
            if rejection is not None:
                return rejection
            if not self._restore_checkpoint_unchecked(
                checkpoint_id, clear_history=clear_history
            ):
                return ReplacementResult(
                    committed=False,
                    error=CHECKPOINT_NOT_FOUND,
                    old_epoch=old_epoch,
                    old_revision=old_revision,
                    document_epoch=self.document_epoch,
                    version=self.pres.version,
                )
            return ReplacementResult(
                committed=True,
                error=None,
                old_epoch=old_epoch,
                old_revision=old_revision,
                document_epoch=self.document_epoch,
                version=self.pres.version,
            )

    def undo(self) -> Optional[MutationCommand]:
        cmd = self.history.undo(self.pres)
        if cmd:
            self.updated_at = datetime.now(timezone.utc)
        return cmd

    def redo(self) -> Optional[MutationCommand]:
        cmd = self.history.redo(self.pres)
        if cmd:
            self.updated_at = datetime.now(timezone.utc)
        return cmd

    def record_iteration(self, iteration_data: Any):
        if hasattr(iteration_data, "to_dict"):
            self.iterations.append(iteration_data.to_dict())
        else:
            self.iterations.append(iteration_data)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.pres.title,
            "slides_count": len(self.pres.slides),
            "active_slide_id": self.active_slide_id,
            "version": self.pres.version,
            "messages_count": len(self.messages),
            "checkpoints_count": len(self.checkpoints),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "can_undo": self.history.can_undo(),
            "can_redo": self.history.can_redo(),
            "last_target_id": self.last_target_id,
            "pending_confirmations_count": len(self.pending_confirmations),
        }
