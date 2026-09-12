"""SessionManager managing registry, lifecycle, and isolation of PPTSession workspaces."""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List

from ..ir.models import PresentationIR
from .factory import SessionFactory
from .session import PPTSession

logger = logging.getLogger(__name__)


class SessionManager:
    """Registry maintaining active PPTSession instances.

    Sessions are created through ``SessionFactory`` so each one owns an
    independent ``PresentationIR`` (S2). ``DEFAULT_SESSION_ID`` is retained only
    for explicit bootstrap/test use; production paths must supply a real id (S4).
    """

    DEFAULT_SESSION_ID = "default"

    def __init__(self):
        self._sessions: Dict[str, PPTSession] = {}

    def create_session(
        self,
        pres: Optional[PresentationIR] = None,
        session_id: Optional[str] = None,
    ) -> PPTSession:
        session = SessionFactory.create(pres, session_id=session_id)
        self._sessions[session.session_id] = session
        logger.info(
            "Created session '%s' with presentation '%s'",
            session.session_id,
            session.pres.title,
        )
        return session

    def get_session(self, session_id: str) -> Optional[PPTSession]:
        return self._sessions.get(session_id)

    def get_or_create(
        self,
        session_id: Optional[str] = None,
        pres_factory: Optional[callable] = None,
    ) -> PPTSession:
        sid = session_id or self.DEFAULT_SESSION_ID
        if sid in self._sessions:
            return self._sessions[sid]

        pres = pres_factory() if pres_factory else None
        return self.create_session(pres=pres, session_id=sid)

    def get_or_create_default(self, pres: Optional[PresentationIR] = None) -> PPTSession:
        return self.get_or_create(self.DEFAULT_SESSION_ID, pres_factory=lambda: pres)

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Deleted session '%s'", session_id)
            return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [sess.to_dict() for sess in self._sessions.values()]

    def clear(self):
        self._sessions.clear()


# Global singleton instance
session_manager = SessionManager()
