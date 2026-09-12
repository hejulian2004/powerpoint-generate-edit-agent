"""DocumentService: owns one session's PresentationIR, identity, lock, and
the mutation-idempotency cache.

This is the single place that may rotate a document's identity
(``commit_replacement`` / ``commit_checkpoint_restore`` / the private
``_unsafe_install_for_bootstrap`` primitive). It owns the mutation lock and the
CAS checks so callers cannot forget to guard a wholesale overwrite.

Collaborators (history / checkpoints / confirmations) are injected by the
session factory; replacement resets all of them, because a new document
identity invalidates history, checkpoints, and pending confirmations.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ...ir.models import PresentationIR, SlideIR
from .agent_execution import DOCUMENT_FROZEN

# Bounded idempotency window for caller-supplied mutation ids. This is a short
# retry/dedup buffer, not a mutation history, so it stays small. It is
# process-runtime state and is never persisted across a restart (contract P1).
COMPLETED_MUTATION_LIMIT = 256

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
class ExportSnapshot:
    """Immutable deep copy of a document pinned to one epoch/revision.

    Captured under the mutation lock so a long export/render runs against a
    single deterministic revision even if edits commit mid-flight.
    """

    presentation: Any
    document_epoch: str
    version: int


class DocumentService:
    """Owns the presentation, its identity, the mutation lock, and CAS logic."""

    def __init__(
        self,
        session_id: str,
        presentation: PresentationIR,
        *,
        history: Any,
        checkpoints: Any,
        confirmations: Any,
        agent_execution: Any = None,
    ) -> None:
        self.session_id = session_id
        self.presentation: PresentationIR = presentation
        # Identity of the current document. Rotated whenever the presentation
        # object is wholesale replaced (import / generation / checkpoint restore).
        self.epoch: str = uuid.uuid4().hex
        self.mutation_lock: asyncio.Lock = asyncio.Lock()
        self.last_target_id: Optional[str] = None
        self.last_action_type: Optional[str] = None
        # (document_epoch, mutation_id) -> {"result", "payload_hash"}.
        self.completed_mutations: "OrderedDict[Any, Any]" = OrderedDict()
        self._history = history
        self._checkpoints = checkpoints
        self._confirmations = confirmations
        # Session-scoped Agent edit window. Whole-document replacement is checked
        # against this under `mutation_lock` so an Agent freeze is a true
        # session-level write barrier, not just a gateway one.
        self._agent_execution = agent_execution

    # ------------------------------------------------------------------
    # Active slide (a document cursor, not shared navigation authority)
    # ------------------------------------------------------------------

    @property
    def active_slide_id(self) -> Optional[str]:
        return self.presentation.active_slide_id

    @active_slide_id.setter
    def active_slide_id(self, val: Optional[str]):
        self.presentation.active_slide_id = val

    def get_active_slide(self) -> Optional[SlideIR]:
        return self.presentation.get_active_slide()

    def set_active_slide(self, slide_id: str) -> bool:
        slide = self.presentation.get_slide(slide_id)
        if slide:
            self.presentation.active_slide_id = slide_id
            return True
        return False

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
            document_epoch if document_epoch is not None else self.epoch,
            mutation_id,
        )

    def get_cached_mutation_result(
        self,
        mutation_id: str,
        document_epoch: Optional[str] = None,
        payload_hash: Optional[str] = None,
    ) -> Optional[Any]:
        """Returns a deep copy of a terminal outcome, or None. Refreshes LRU order.

        When both the stored and requested payload hashes are present and differ,
        this returns None (a miss); callers that need to surface the protocol
        violation should call `cached_mutation_payload_mismatch` first.
        """
        key = self._mutation_cache_key(mutation_id, document_epoch)
        entry = self.completed_mutations.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict):
            stored_hash = entry.get("payload_hash")
            if payload_hash is not None and stored_hash is not None and stored_hash != payload_hash:
                return None
            result = entry.get("result")
        else:
            result = entry
        self.completed_mutations.move_to_end(key)
        return copy.deepcopy(result)

    def cached_mutation_payload_mismatch(
        self,
        mutation_id: str,
        document_epoch: Optional[str] = None,
        payload_hash: Optional[str] = None,
    ) -> bool:
        """True when the same id was already used with a different logical payload."""
        entry = self.completed_mutations.get(
            self._mutation_cache_key(mutation_id, document_epoch)
        )
        if not isinstance(entry, dict):
            return False
        stored_hash = entry.get("payload_hash")
        return (
            payload_hash is not None
            and stored_hash is not None
            and stored_hash != payload_hash
        )

    def remember_mutation_result(
        self,
        mutation_id: str,
        result: Any,
        document_epoch: Optional[str] = None,
        payload_hash: Optional[str] = None,
    ) -> None:
        """Stores a deep-copied terminal outcome, evicting the oldest over the limit."""
        key = self._mutation_cache_key(mutation_id, document_epoch)
        self.completed_mutations[key] = {
            "result": copy.deepcopy(result),
            "payload_hash": payload_hash,
        }
        self.completed_mutations.move_to_end(key)
        while len(self.completed_mutations) > COMPLETED_MUTATION_LIMIT:
            self.completed_mutations.popitem(last=False)

    # ------------------------------------------------------------------
    # Replacement primitives
    # ------------------------------------------------------------------

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
        self.presentation = pres
        self.epoch = uuid.uuid4().hex
        self._confirmations.clear()
        self.completed_mutations.clear()
        self.last_target_id = None
        self.last_action_type = None
        if clear_history:
            self._history.clear()
        if clear_checkpoints:
            self._checkpoints.clear()
        if checkpoint_description:
            self._checkpoints.create(pres, description=checkpoint_description)

    def _finalize_inplace_replacement_locked(
        self,
        *,
        clear_history: bool = True,
        clear_checkpoints: bool = True,
        checkpoint_description: str = "Generated presentation",
    ) -> None:
        """Finalize an in-place whole-document replacement.

        The caller has already built the new deck on the SAME ``self.presentation``
        object (so every held reference stays valid) and MUST already hold
        ``mutation_lock``. This rotates the document identity, resets the target
        /action state, drops stale confirmations and the idempotency cache, clears
        history + checkpoints, and creates a fresh baseline checkpoint so the
        replacement has the same lifecycle as upload / PPTSpec generation.

        It is intentionally private: raw identity rotation must only be reachable
        from the gateway's lock-holding replacement path.
        """
        self.epoch = uuid.uuid4().hex
        # A replacement is a new document identity; the revision restarts. The
        # (epoch, revision) pair - never the revision alone - carries identity.
        self.presentation.version = 1
        self._confirmations.clear()
        self.completed_mutations.clear()
        self.last_target_id = None
        self.last_action_type = None
        if clear_history:
            self._history.clear()
        if clear_checkpoints:
            self._checkpoints.clear()
        self._checkpoints.create(self.presentation, description=checkpoint_description)

    def _replacement_authorization_error(
        self,
        source: str,
        agent_turn_id: Optional[str],
    ) -> Optional[str]:
        """Returns DOCUMENT_FROZEN when a non-owner may not replace the document.

        Callers MUST hold ``mutation_lock`` when invoking this. The check runs
        BEFORE the CAS and before any IR/epoch/history mutation so a frozen
        replacement has exactly zero side effects.
        """
        execution = self._agent_execution
        if execution is None:
            return None
        if execution.allows(source, agent_turn_id):
            return None
        return DOCUMENT_FROZEN

    def _frozen_replacement_result(self) -> ReplacementResult:
        return ReplacementResult(
            committed=False,
            error=DOCUMENT_FROZEN,
            old_epoch=self.epoch,
            old_revision=self.presentation.version,
            document_epoch=self.epoch,
            version=self.presentation.version,
        )

    def _replacement_cas_error(
        self,
        expected_epoch: Optional[str],
        expected_revision: Optional[int],
        stale_error: str,
    ) -> Optional[ReplacementResult]:
        """Returns a rejected ReplacementResult, or None when the CAS passes."""
        if expected_epoch is not None and expected_epoch != self.epoch:
            return ReplacementResult(
                committed=False,
                error=DOCUMENT_EPOCH_MISMATCH,
                old_epoch=self.epoch,
                old_revision=self.presentation.version,
                document_epoch=self.epoch,
                version=self.presentation.version,
            )
        if expected_revision is not None and self.presentation.version != expected_revision:
            return ReplacementResult(
                committed=False,
                error=stale_error,
                old_epoch=self.epoch,
                old_revision=self.presentation.version,
                document_epoch=self.epoch,
                version=self.presentation.version,
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
        source: str = "system",
        agent_turn_id: Optional[str] = None,
    ) -> ReplacementResult:
        """CAS-guarded whole-document replacement (import / generation / load).

        Owns the mutation lock and both CAS checks so callers cannot forget to
        guard a wholesale overwrite. Both stamps are REQUIRED; passing `None`
        fails closed rather than silently performing an unconditional overwrite.

        While a session has an active Agent turn, only that turn's own
        ``agent``/``remediation`` source (with a matching ``agent_turn_id``) may
        replace the document; every REST/frontend/system replacement is rejected
        with ``DOCUMENT_FROZEN`` before any CAS or write.
        """
        async with self.mutation_lock:
            old_epoch = self.epoch
            old_revision = self.presentation.version
            if self._replacement_authorization_error(source, agent_turn_id):
                return self._frozen_replacement_result()
            if expected_epoch is None or expected_revision is None:
                return ReplacementResult(
                    committed=False,
                    error=MISSING_REPLACEMENT_STAMP,
                    old_epoch=old_epoch,
                    old_revision=old_revision,
                    document_epoch=self.epoch,
                    version=self.presentation.version,
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
                document_epoch=self.epoch,
                version=self.presentation.version,
            )

    async def snapshot_for_export(self) -> "ExportSnapshot":
        """Pin a deep copy of the document to one epoch/revision under the lock.

        The caller renders from the returned copy; subsequent edits cannot alter
        what is written to disk.
        """
        async with self.mutation_lock:
            return ExportSnapshot(
                presentation=copy.deepcopy(self.presentation),
                document_epoch=self.epoch,
                version=self.presentation.version,
            )

    def _restore_checkpoint_unchecked(
        self, checkpoint_id: str, clear_history: bool = True
    ) -> bool:
        """Raw, CAS-free projection rollback.

        Private on purpose: whole-document replacement is only legal through
        `commit_checkpoint_restore`, which owns the mutation lock and enforces the
        epoch/revision CAS. Bootstrap seeding uses `_unsafe_install_for_bootstrap`.
        """
        restored = self._checkpoints.restore(checkpoint_id)
        if restored:
            self.presentation = restored
            # Restoring is a document-level rollback: rotate identity and drop stale
            # confirmations that were bound to the previous revision.
            self.epoch = uuid.uuid4().hex
            self._confirmations.clear()
            self.completed_mutations.clear()
            if clear_history:
                self._history.clear()
            else:
                self._history.record(
                    action="restore_checkpoint",
                    description=f"Restored to checkpoint {checkpoint_id}",
                    source="session_checkpoint",
                )
            return True
        return False

    async def commit_checkpoint_restore(
        self,
        checkpoint_id: str,
        *,
        expected_epoch: Optional[str],
        expected_revision: Optional[int],
        clear_history: bool = True,
        source: str = "system",
        agent_turn_id: Optional[str] = None,
    ) -> ReplacementResult:
        """CAS-guarded checkpoint restore. Owns the mutation lock.

        A restore is a whole-document rollback: it must reject when the live
        document moved past the caller's view, instead of blindly overwriting a
        newer revision. Both stamps are REQUIRED and fail closed when missing.
        A non-owner restore is rejected ``DOCUMENT_FROZEN`` before any CAS/write.
        """
        async with self.mutation_lock:
            old_epoch = self.epoch
            old_revision = self.presentation.version
            if self._replacement_authorization_error(source, agent_turn_id):
                return self._frozen_replacement_result()
            if expected_epoch is None or expected_revision is None:
                return ReplacementResult(
                    committed=False,
                    error=MISSING_REPLACEMENT_STAMP,
                    old_epoch=old_epoch,
                    old_revision=old_revision,
                    document_epoch=self.epoch,
                    version=self.presentation.version,
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
                    document_epoch=self.epoch,
                    version=self.presentation.version,
                )
            return ReplacementResult(
                committed=True,
                error=None,
                old_epoch=old_epoch,
                old_revision=old_revision,
                document_epoch=self.epoch,
                version=self.presentation.version,
            )
