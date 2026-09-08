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

        # 3. High-Fidelity Semantic Element Graph resolution
        try:
            from ..semantic.element_graph import SemanticElementGraph
            graph = SemanticElementGraph(slide)
            target_norm = target.lower().strip()

            # Title
            if target_norm in ["title", "slide_title", "header"] or "标题" in target:
                title_elem = graph.get_title()
                if title_elem:
                    return title_elem

            # Subtitle
            if target_norm in ["subtitle", "sub_title", "subheading"] or "副标题" in target:
                subs = graph.find_by_role("subtitle")
                if subs:
                    return subs[0]

            # Cards / Containers
            if target_norm in ["card", "cards", "container"] or "卡片" in target or "容器" in target:
                cards = graph.get_containers()
                if cards:
                    return cards[0]

            # Metrics / KPIs
            if target_norm in ["metric", "kpi", "number", "stat"] or "指标" in target or "数据" in target:
                metrics = graph.find_by_role("metric")
                if metrics:
                    return metrics[0]

            # Body / Paragraphs
            if target_norm in ["body", "content", "paragraph", "text"] or "正文" in target:
                bodies = graph.find_by_role("body")
                if bodies:
                    return bodies[0]

            # Images
            if target_norm in ["image", "picture", "photo", "pic"] or "图片" in target or "图" in target:
                images = graph.find_by_role("image")
                if images:
                    return images[0]

            # Footers
            if target_norm in ["footer", "footnote", "page_number"] or "页脚" in target:
                footers = graph.find_by_role("footer")
                if footers:
                    return footers[0]
        except Exception:
            pass

        # 4. Fallback heuristic for "title" resolution
        if "title" in target.lower() or "标题" in target:
            for el in slide.elements:
                if "title" in el.id.lower():
                    return el
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
            top_text = next((e for e in slide.elements if e.type == "text" and e.y < 180), None)
            if top_text:
                return top_text

        # 5. Fallback heuristic for "card" / "shape"
        if "card" in target.lower() or "shape" in target.lower() or "卡片" in target:
            cards = [e for e in slide.elements if e.type == "shape"]
            if cards:
                return cards[0]

        # 6. Fallback to last target only if explicitly valid
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

        # Resolve any theme color tokens in parameters (e.g. accent1, theme:accent1)
        theme_engine = None
        for k in ["color", "font_color", "fill_color", "border_color"]:
            if k in action.parameters:
                val = str(action.parameters[k]).strip()
                if val.lower() in ["accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "dk1", "lt1", "dk2", "lt2"] or val.lower().startswith("theme:"):
                    token = val[6:] if val.lower().startswith("theme:") else val
                    if theme_engine is None:
                        from ..fidelity.theme_engine import ThemeEngine
                        t_data = getattr(pres, "theme", None)
                        scheme = getattr(t_data, "color_scheme", None) if t_data else None
                        theme_engine = ThemeEngine(color_scheme=scheme)
                    action.parameters[k] = theme_engine.resolve_color(token)

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
