"""Remediation protocol defining abstract fix actions and plans decoupled from agent tools."""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


class DefectCategory(str, Enum):
    """Categorization of layout defects governing auto-remediation safety policies."""
    CRITICAL = "critical"      # Viewport clipping, collision overlap, text overflow. Eligible for auto-correction.
    STRUCTURAL = "structural"  # Alignment, margin intrusion, card distribution. Advisory; safe auto-fix only if opted-in.
    AESTHETIC = "aesthetic"    # Whitespace balance, color choice, thematic style. Strictly advisory. Never auto-fix.


class FixActionType(str, Enum):
    """Domain-level semantic fix action types decoupled from concrete tool names."""
    CLAMP_VIEWPORT = "clamp_viewport"
    SEPARATE_ELEMENTS = "separate_elements"
    ARRANGE_CARDS = "arrange_cards"
    RESIZE_CONTAINER = "resize_container"
    ENHANCE_CONTRAST = "enhance_contrast"
    ALIGN_ELEMENTS = "align_elements"


@dataclass
class FixAction:
    """An abstract, tool-agnostic remediation operation."""
    action_type: FixActionType
    category: DefectCategory
    target_ids: List[str]
    parameters: Dict[str, Any]
    reason: str
    priority: int = 1
    confidence: float = 1.0
    source: str = "geometry_rule"  # geometry_rule, llm_vision, heuristic

    @property
    def is_auto_applicable(self) -> bool:
        """Safe execution policy: CRITICAL defects with confidence >= 0.9 auto-execute in loop."""
        return self.category == DefectCategory.CRITICAL and self.confidence >= 0.9

    @property
    def execution_mode(self) -> str:
        """Execution mode: 'auto' (>=0.9 critical), 'review' (0.6-0.9), 'advisory' (<0.6 or non-critical)."""
        if self.category == DefectCategory.CRITICAL and self.confidence >= 0.9:
            return "auto"
        elif self.confidence >= 0.6:
            return "review"
        return "advisory"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "category": self.category.value,
            "target_ids": self.target_ids,
            "parameters": self.parameters,
            "reason": self.reason,
            "priority": self.priority,
            "confidence": round(self.confidence, 2),
            "source": self.source,
            "execution_mode": self.execution_mode,
            "is_auto_applicable": self.is_auto_applicable
        }


@dataclass
class RemediationPlan:
    """Structured plan composed of prioritized fix actions."""
    actions: List[FixAction] = field(default_factory=list)
    has_critical: bool = False
    summary: str = ""

    @property
    def auto_executable_actions(self) -> List[FixAction]:
        """Actions meeting confidence (>=0.9) and criticality threshold for automatic execution."""
        return [a for a in self.actions if a.is_auto_applicable]

    @property
    def review_actions(self) -> List[FixAction]:
        """Actions requiring user confirmation/review (confidence 0.6 - 0.9)."""
        return [a for a in self.actions if a.execution_mode == "review"]

    @property
    def advisory_actions(self) -> List[FixAction]:
        """Advisory suggestions (<0.6 confidence or aesthetic)."""
        return [a for a in self.actions if a.execution_mode == "advisory"]

    @property
    def critical_actions(self) -> List[FixAction]:
        return [a for a in self.actions if a.category == DefectCategory.CRITICAL]

    @property
    def structural_actions(self) -> List[FixAction]:
        return [a for a in self.actions if a.category == DefectCategory.STRUCTURAL]

    @property
    def aesthetic_actions(self) -> List[FixAction]:
        return [a for a in self.actions if a.category == DefectCategory.AESTHETIC]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "has_critical": self.has_critical,
            "auto_executable_count": len(self.auto_executable_actions),
            "review_count": len(self.review_actions),
            "advisory_count": len(self.advisory_actions),
            "critical_count": len(self.critical_actions),
            "structural_count": len(self.structural_actions),
            "summary": self.summary
        }
