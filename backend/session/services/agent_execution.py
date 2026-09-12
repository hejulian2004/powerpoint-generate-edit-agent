"""AgentExecutionService: session-scoped exclusive Agent edit window.

Filled in by Phase 6. For Phase 1 it is introduced as part of the session
aggregate so the freeze lease has a stable, session-owned home.
"""

from __future__ import annotations

from typing import Optional


class AgentExecutionService:
    """Owns the active Agent turn lease for one session (Phase 6)."""

    def __init__(self) -> None:
        self.active_turn: Optional[object] = None

    @property
    def is_frozen(self) -> bool:
        return self.active_turn is not None
