"""Pipeline Output Result Protocol and Consolidated Telemetry."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from ..ir.history_event import MutationEvent


@dataclass
class PipelineResult:
    """Consolidated outcome of the end-to-end PPT editing pipeline."""
    input_path: Optional[str]
    output_path: str
    user_instruction: str
    success: bool
    validation_valid: bool
    initial_score: float
    final_score: float
    tools_executed: List[Dict[str, Any]]
    agent_summary: str
    slide_count: int
    presentation_title: str
    snapshot_uri: Optional[str] = None
    mutation_history: List[MutationEvent] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "user_instruction": self.user_instruction,
            "success": self.success,
            "validation_valid": self.validation_valid,
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "score_diff": round(self.final_score - self.initial_score, 2),
            "tools_executed": self.tools_executed,
            "agent_summary": self.agent_summary,
            "slide_count": self.slide_count,
            "presentation_title": self.presentation_title,
            "snapshot_uri": self.snapshot_uri,
            "mutation_history": [
                m.to_dict() if hasattr(m, "to_dict") else m
                for m in self.mutation_history
            ],
            "error": self.error
        }
