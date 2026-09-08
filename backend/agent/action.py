"""AgentAction: Standardized action contract and semantic resolution for PPT Agent."""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from ..ir.models import PresentationIR, SlideIR, ElementIR


@dataclass
class AgentAction:
    """Standardized action contract bridging High-Level Agent Planning to Low-Level Tool Invocations."""
    action_type: str
    target: str  # "title" | "subtitle" | "card" | "last_target" | exact element_id
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    reason: str = ""
    relative: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target": self.target,
            "parameters": self.parameters,
            "confidence": self.confidence,
            "reason": self.reason,
            "relative": self.relative,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentAction:
        return cls(
            action_type=data.get("action_type", "update_element"),
            target=data.get("target", ""),
            parameters=data.get("parameters", {}),
            confidence=data.get("confidence", 1.0),
            reason=data.get("reason", ""),
            relative=data.get("relative", False)
        )


class ActionResolver:
    """Resolves semantic targets and relative offsets to concrete elements and coordinates."""

    @classmethod
    def resolve_target_element(
        cls,
        target: str,
        slide: Optional[SlideIR],
        last_target_id: Optional[str] = None
    ) -> Optional[ElementIR]:
        if not slide or not slide.elements:
            return None

        # 1. Exact ID match
        for el in slide.elements:
            if el.id == target:
                return el

        # 2. Contextual last_target
        if target in ["last_target", "active_target", "it", "this"]:
            if last_target_id:
                for el in slide.elements:
                    if el.id == last_target_id:
                        return el

        # 3. Semantic "title" resolution
        if "title" in target.lower() or "标题" in target:
            # Check ID
            for el in slide.elements:
                if "title" in el.id.lower():
                    return el
            # Check max font size
            title_candidate = None
            max_font = 0.0
            for el in slide.elements:
                tc = getattr(el, "text_content", None)
                if tc and tc.paragraphs:
                    for p in tc.paragraphs:
                        for r in p.runs:
                            if r.font and r.font.size and r.font.size > max_font:
                                max_font = r.font.size
                                title_candidate = el
            if title_candidate and max_font >= 20.0:
                return title_candidate
            # Top-most text element
            top_text = next((e for e in slide.elements if e.type == "text" and e.y < 180), None)
            if top_text:
                return top_text

        # 4. Semantic "card" / "shape" resolution
        if "card" in target.lower() or "shape" in target.lower() or "卡片" in target:
            cards = [e for e in slide.elements if e.type == "shape"]
            if cards:
                return cards[0]

        # 5. Fallback to last target only if explicitly valid
        if last_target_id:
            for el in slide.elements:
                if el.id == last_target_id:
                    return el
        return None

    @classmethod
    def action_to_tool_call(
        cls,
        action: AgentAction,
        pres: PresentationIR,
        last_target_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Converts an AgentAction into an executable tool call dict."""
        active_slide = pres.get_active_slide()
        target_elem = cls.resolve_target_element(action.target, active_slide, last_target_id)

        # Guard: Relative movement requires a valid target element
        if action.relative:
            if not target_elem:
                return None
            resolved_params = dict(action.parameters)
            if "x" in resolved_params:
                resolved_params["x"] = round(target_elem.x + resolved_params["x"], 1)
            if "y" in resolved_params:
                resolved_params["y"] = round(target_elem.y + resolved_params["y"], 1)
            if "font_size" in resolved_params:
                curr_size = 24.0
                tc = getattr(target_elem, "text_content", None)
                if tc and tc.paragraphs and tc.paragraphs[0].runs:
                    f = tc.paragraphs[0].runs[0].font
                    if f and f.size:
                        curr_size = f.size
                resolved_params["font_size"] = max(12.0, min(72.0, curr_size + resolved_params["font_size"]))

            return {
                "name": "update_element",
                "arguments": {
                    "element_id": target_elem.id,
                    "slide_id": active_slide.id if active_slide else None,
                    **resolved_params
                }
            }

        element_id = target_elem.id if target_elem else action.target

        # 2. Text formatting / resizing
        if action.action_type in ["resize_text", "format_text", "highlight_text"]:
            if not target_elem and action.target:
                return None
            args = {"element_id": element_id}
            if active_slide:
                args["slide_id"] = active_slide.id
            args.update(action.parameters)
            return {
                "name": "format_text",
                "arguments": args
            }

        # 3. Element update / move
        if action.action_type in ["update_element", "move_element", "reposition_element"]:
            if not target_elem and action.target:
                return None
            args = {"element_id": element_id}
            if active_slide:
                args["slide_id"] = active_slide.id
            args.update(action.parameters)
            return {
                "name": "update_element",
                "arguments": args
            }

        # 4. Layout optimization
        if action.action_type == "optimize_layout":
            args = dict(action.parameters)
            if active_slide and "slide_id" not in args:
                args["slide_id"] = active_slide.id
            return {
                "name": "optimize_layout",
                "arguments": args
            }

        # 5. Theme application
        if action.action_type == "apply_theme":
            return {
                "name": "apply_theme",
                "arguments": action.parameters
            }

        # Guard: Other element-specific actions targeting an unknown element should fail cleanly
        if not target_elem and action.target and action.action_type not in ["add_element", "create_element"]:
            return None

        # Generic passthrough
        args = {"element_id": element_id, **action.parameters}
        return {
            "name": action.action_type,
            "arguments": args
        }
