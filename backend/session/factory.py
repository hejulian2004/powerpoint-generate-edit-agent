"""SessionFactory: the single production boundary that creates a ``PPTSession``.

Ownership (S2): a session receives its own ``PresentationIR``. Persistence
(``restore``) reconstructs a session from a durable snapshot with an explicit
epoch and optional baseline suppression so a restart never appends a phantom
baseline checkpoint.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Optional

from ..ir.models import PresentationIR
from .session import PPTSession
from .snapshot import SessionSnapshot


class SessionFactory:
    """Creates and restores isolated ``PPTSession`` aggregates."""

    @staticmethod
    def new_session_id() -> str:
        return f"sess_{uuid.uuid4().hex[:8]}"

    @classmethod
    def create(
        cls,
        pres: Optional[PresentationIR] = None,
        session_id: Optional[str] = None,
        *,
        init_baseline: bool = True,
    ) -> PPTSession:
        """Creates a session that exclusively owns a fresh copy of ``pres``.

        The incoming presentation is deep-copied so two sessions can never share
        the same ``PresentationIR`` object (S2). Callers that need by-reference
        replacement semantics use ``session.commit_replacement`` instead.
        """
        sid = session_id or cls.new_session_id()
        owned = copy.deepcopy(pres) if pres is not None else PresentationIR(
            title="Untitled Presentation"
        )
        return PPTSession(session_id=sid, pres=owned, init_baseline=init_baseline)

    @classmethod
    def restore(cls, snapshot: SessionSnapshot, *, init_baseline: bool = False) -> PPTSession:
        """Reconstructs a session from a durable snapshot.

        ``init_baseline`` defaults to False: checkpoints are restored exactly as
        persisted, so the constructor's synthetic "Initial session state" baseline
        is suppressed.
        """
        pres = PresentationIR.model_validate(snapshot.presentation)
        session = cls.create(pres, session_id=snapshot.session_id, init_baseline=init_baseline)
        # Restore the persisted identity explicitly; the constructor would mint a
        # fresh epoch for a new document.
        session.document.epoch = snapshot.document_epoch
        return session
