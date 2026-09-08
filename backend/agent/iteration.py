"""AgentIteration: Multi-turn visual feedback and quantitative layout score tracking."""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class AgentIteration:
    """Records one turn of visual feedback, score progression, and applied changes."""
    iteration: int
    score_before: float
    score_after: float
    changes: List[Dict[str, Any]] = field(default_factory=list)
    critique: Optional[str] = None
    applied_fixes: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    delta: float = 0.0

    def __post_init__(self):
        self.delta = round(self.score_after - self.score_before, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "delta": self.delta,
            "changes": self.changes,
            "critique": self.critique,
            "applied_fixes": self.applied_fixes,
            "timestamp": self.timestamp,
        }
