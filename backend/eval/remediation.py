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
    # PR6 Fidelity Repair Action Types
    FIX_FONT = "fix_font"
    FIX_COLOR = "fix_color"
    FIX_GEOMETRY = "fix_geometry"
    FIX_THEME_REF = "fix_theme_ref"
    FIX_ALIGNMENT = "fix_alignment"


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


class FidelityRemediationGenerator:
    """Generates structured fidelity FixActions by comparing slides against baseline/template design."""

    @classmethod
    def generate_plan(cls, orig_slide: Any, current_slide: Any) -> RemediationPlan:
        actions: List[FixAction] = []
        orig_elements = {el.id: el for el in orig_slide.all_elements(recursive=True)}
        curr_elements = {el.id: el for el in current_slide.all_elements(recursive=True)}

        for eid, o_el in orig_elements.items():
            c_el = curr_elements.get(eid)
            if not c_el:
                continue

            # 1. Geometry drift check (> 2px)
            dx = abs(c_el.x - o_el.x)
            dy = abs(c_el.y - o_el.y)
            dw = abs(c_el.width - o_el.width)
            dh = abs(c_el.height - o_el.height)
            if max(dx, dy, dw, dh) > 2.0:
                actions.append(FixAction(
                    action_type=FixActionType.FIX_GEOMETRY,
                    category=DefectCategory.CRITICAL,
                    target_ids=[eid],
                    parameters={
                        "element_id": eid,
                        "x": o_el.x,
                        "y": o_el.y,
                        "width": o_el.width,
                        "height": o_el.height
                    },
                    reason=f"Element '{eid}' geometric drift {max(dx, dy, dw, dh):.1f}px exceeds 2px threshold",
                    priority=9,
                    confidence=0.98,
                    source="fidelity_engine"
                ))

            # 2. Typography check
            o_tc = getattr(o_el, "text_content", None)
            c_tc = getattr(c_el, "text_content", None)
            if o_tc and c_tc:
                o_font = cls._extract_first_font(o_tc)
                c_font = cls._extract_first_font(c_tc)
                if o_font and c_font:
                    font_params: Dict[str, Any] = {"element_id": eid}
                    needs_font_fix = False
                    if o_font.name and c_font.name and o_font.name.lower() != c_font.name.lower():
                        font_params["font_family"] = o_font.name
                        needs_font_fix = True
                    if o_font.size and c_font.size and abs(o_font.size - c_font.size) > 2.0:
                        font_params["font_size"] = o_font.size
                        needs_font_fix = True

                    if needs_font_fix:
                        actions.append(FixAction(
                            action_type=FixActionType.FIX_FONT,
                            category=DefectCategory.CRITICAL,
                            target_ids=[eid],
                            parameters=font_params,
                            reason=f"Element '{eid}' typography deviated from baseline font specification",
                            priority=8,
                            confidence=0.95,
                            source="fidelity_engine"
                        ))

            # 3. Styling / Color check
            o_style = getattr(o_el, "style", None)
            c_style = getattr(c_el, "style", None)
            if o_style and c_style:
                o_fill = getattr(o_style, "fill", None)
                c_fill = getattr(c_style, "fill", None)
                if o_fill and c_fill and getattr(o_fill, "color", None) and getattr(c_fill, "color", None):
                    if o_fill.color != c_fill.color:
                        actions.append(FixAction(
                            action_type=FixActionType.FIX_COLOR,
                            category=DefectCategory.CRITICAL,
                            target_ids=[eid],
                            parameters={
                                "element_id": eid,
                                "fill_color": o_fill.color
                            },
                            reason=f"Element '{eid}' fill color deviated ({c_fill.color} != {o_fill.color})",
                            priority=7,
                            confidence=0.92,
                            source="fidelity_engine"
                        ))

        return RemediationPlan(
            actions=actions,
            has_critical=any(a.category == DefectCategory.CRITICAL for a in actions),
            summary=f"Fidelity remediation generated {len(actions)} repair actions"
        )

    @staticmethod
    def _extract_first_font(tc: Any):
        if tc and tc.paragraphs:
            for p in tc.paragraphs:
                for r in p.runs:
                    if r.font:
                        return r.font
        return None
