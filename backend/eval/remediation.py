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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "category": self.category.value,
            "target_ids": self.target_ids,
            "parameters": self.parameters,
            "reason": self.reason,
            "priority": self.priority
        }


@dataclass
class RemediationPlan:
    """Structured plan composed of prioritized fix actions."""
    actions: List[FixAction] = field(default_factory=list)
    has_critical: bool = False
    summary: str = ""

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
            "critical_count": len(self.critical_actions),
            "structural_count": len(self.structural_actions),
            "summary": self.summary
        }
