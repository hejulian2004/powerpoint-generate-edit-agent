"""Domain Mutation History Event Protocol.

Tracks detailed semantic state transitions before and after each mutation.
Supports undo, redo, replay, LLM audit, and visual diffing.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class MutationEvent:
    """Represents a discrete structural or style mutation applied to a presentation element."""
    action: str
    element_id: str
    before: Dict[str, Any] = field(default_factory=dict)
    after: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: str(time.time()))
    source: str = "agent_tool"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "element_id": self.element_id,
            "before": self.before,
            "after": self.after,
            "timestamp": self.timestamp,
            "source": self.source
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MutationEvent:
        return cls(
            action=data.get("action", "unknown"),
            element_id=data.get("element_id", ""),
            before=data.get("before") or {},
            after=data.get("after") or {},
            timestamp=str(data.get("timestamp", time.time())),
            source=data.get("source", "agent_tool")
        )
