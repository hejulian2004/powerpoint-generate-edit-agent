"""Subagent Session Memory & History Management.

Provides isolated, dedicated history tracking for each subagent in the orchestration pipeline.
Key Principles:
1. Strict Isolation: Subagents NEVER share each other's memories or the main conversational history.
2. Continuity across Rework / Loop-backs:
   When a review rejects and the pipeline loops back to Planner or Executor, the Subagent
   retains its own prior audit trail. On the next review round, the Subagent can contrast
   with its previous findings to verify whether previous issues were addressed.
3. Structured Records:
   Tracks round number, audit inputs, verdict, scores, critique points, and recommendations.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SubagentHistoryEntry:
    """A single audit or execution record in a subagent's private history."""
    round_index: int
    timestamp: float = field(default_factory=time.time)
    input_digest: str = ""
    approved: Optional[bool] = None
    score: Optional[float] = None
    critique_summary: str = ""
    defects_or_risks: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_index": self.round_index,
            "timestamp": self.timestamp,
            "input_digest": self.input_digest,
            "approved": self.approved,
            "score": self.score,
            "critique_summary": self.critique_summary,
            "defects_or_risks": self.defects_or_risks,
            "recommendations": self.recommendations,
            "metadata": self.metadata
        }


class SubagentSessionMemory:
    """Dedicated, isolated memory manager for a specific subagent."""

    def __init__(self, subagent_name: str):
        self.subagent_name = subagent_name
        self.entries: List[SubagentHistoryEntry] = []

    def record_audit(
        self,
        input_digest: str,
        approved: Optional[bool],
        score: Optional[float],
        critique_summary: str,
        defects_or_risks: Optional[List[str]] = None,
        recommendations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SubagentHistoryEntry:
        """Records a new audit round into the subagent's private history."""
        entry = SubagentHistoryEntry(
            round_index=len(self.entries) + 1,
            input_digest=input_digest,
            approved=approved,
            score=score,
            critique_summary=critique_summary,
            defects_or_risks=list(defects_or_risks or []),
            recommendations=list(recommendations or []),
            metadata=dict(metadata or {})
        )
        self.entries.append(entry)
        return entry

    def get_last_entry(self) -> Optional[SubagentHistoryEntry]:
        """Returns the most recent audit entry if available."""
        return self.entries[-1] if self.entries else None

    def get_rework_context_summary(self) -> str:
        """Generates a concise summary of prior audit rounds for rework context."""
        if not self.entries:
            return "（首次评审，无历史记录）"

        lines = [f"【{self.subagent_name} 历史专属审查记录（共 {len(self.entries)} 轮）】:"]
        for e in self.entries:
            verdict = "通过" if e.approved else "未通过/需修正"
            lines.append(f"- 第 {e.round_index} 轮评审: 结论={verdict}, 得分={e.score if e.score is not None else 'N/A'}")
            if e.defects_or_risks:
                lines.append(f"  历史指出问题: {'; '.join(e.defects_or_risks[:2])}")
            if e.recommendations:
                lines.append(f"  历史整改建议: {'; '.join(e.recommendations[:2])}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subagent_name": self.subagent_name,
            "entries_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentSessionMemory":
        mem = cls(subagent_name=data.get("subagent_name", "UnknownSubagent"))
        for ed in data.get("entries", []):
            entry = SubagentHistoryEntry(
                round_index=ed.get("round_index", 1),
                timestamp=ed.get("timestamp", 0.0),
                input_digest=ed.get("input_digest", ""),
                approved=ed.get("approved"),
                score=ed.get("score"),
                critique_summary=ed.get("critique_summary", ""),
                defects_or_risks=ed.get("defects_or_risks", []),
                recommendations=ed.get("recommendations", []),
                metadata=ed.get("metadata", {})
            )
            mem.entries.append(entry)
        return mem
