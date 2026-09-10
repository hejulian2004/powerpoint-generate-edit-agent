"""ActionRiskPolicy: per-action-type semantic resolution risk thresholds (PR6.1).

Different operations carry different risk. A low-confidence resolution should gate
high-risk mutations (delete / move / resize) harder than low-risk styling changes.

    DELETE  -> requires confidence >= 0.95
    MOVE    -> requires confidence >= 0.85
    RESIZE  -> requires confidence >= 0.85
    STYLE   -> requires confidence >= 0.75
    default -> requires confidence >= 0.80

`ActionResolver` flags resolver-generated calls, and `RiskEnricher` applies the same
policy to *every* tool call (including raw live-LLM tool calls) before the
`ConfirmationGate` decides whether execution is allowed.
"""

from __future__ import annotations
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..ir.models import PresentationIR

# Risk levels -> minimum semantic resolution confidence before a mutation proceeds.
RISK_LEVELS: Dict[str, float] = {
    "DELETE": 0.95,
    "MOVE": 0.85,
    "RESIZE": 0.85,
    "STYLE": 0.75,
}

DEFAULT_THRESHOLD: float = 0.80

# action_type -> risk level.
ACTION_RISK: Dict[str, str] = {
    # Destructive mutations: highest bar
    "delete_element": "DELETE",
    "delete_slide": "DELETE",
    "clear_slide_elements": "DELETE",
    "remove_element": "DELETE",
    "remove_shape": "DELETE",
    "remove_text": "DELETE",
    # Geometry mutations
    "move_element": "MOVE",
    "reposition_element": "MOVE",
    "move": "MOVE",
    # Sizing mutations
    "resize_text": "RESIZE",
    "resize_element": "RESIZE",
    "resize": "RESIZE",
    # Styling / text formatting: lowest risk
    "format_text": "STYLE",
    "highlight_text": "STYLE",
    "update_element": "STYLE",
    "update_style": "STYLE",
    "apply_style": "STYLE",
    "set_font": "STYLE",
    "set_color": "STYLE",
    "change_color": "STYLE",
}


class ActionRiskPolicy:
    """Computes the minimum semantic confidence required for a given action type."""

    @classmethod
    def risk_level(cls, action_type: str) -> str:
        return ACTION_RISK.get(action_type, "DEFAULT")

    @classmethod
    def threshold(cls, action_type: str) -> float:
        """Returns the minimum resolution confidence for an action type."""
        level = cls.risk_level(action_type)
        return RISK_LEVELS.get(level, DEFAULT_THRESHOLD)

    @classmethod
    def needs_confirmation(cls, confidence: Optional[float], action_type: str) -> bool:
        """True when a resolution confidence is missing or below the action's threshold."""
        if confidence is None:
            return True
        return confidence < cls.threshold(action_type)


class RiskEnricher:
    """Normalizes any tool call (live LLM or heuristic) into a risk-assessed call.

    The live LLM path builds raw `{"name", "arguments", "id"}` calls and previously
    bypassed risk policy entirely. `tools_node` now runs every call through this
    enricher before `ConfirmationGate`, so the gate sees a `_needs_confirmation`
    decision regardless of which planner produced the call.

    Existing resolver metadata is never overwritten (ActionResolver has more precise
    semantic intent than name/arg heuristics).
    """

    # Tool name -> action_type whose risk level should be consulted.
    RISKY_TOOLS = {
        "delete_element": "delete_element",
        "delete_slide": "delete_slide",
        "clear_slide_elements": "clear_slide_elements",
        "format_text": "format_text",
        "update_element": "update_element",
    }

    # Slide-scoped tools resolve a slide reference instead of an element reference.
    SLIDE_SCOPED_TOOLS = {"delete_slide", "clear_slide_elements"}

    @classmethod
    def _infer_action_type(cls, name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """Maps a tool invocation to the semantic action type used for risk tiers."""
        base = cls.RISKY_TOOLS.get(name)
        if base is None:
            return None
        if name == "update_element":
            if "x" in arguments or "y" in arguments:
                return "move_element"
            if "width" in arguments or "height" in arguments:
                return "resize_element"
            return "update_element"
        return base

    @classmethod
    def _exact_element_match(cls, slide: Any, target: str) -> bool:
        if slide is None or not target:
            return False
        for el in slide.all_elements(recursive=True):
            if el.id == target:
                return True
        return False

    @classmethod
    def _resolve_confidence(
        cls,
        name: str,
        arguments: Dict[str, Any],
        pres: Optional["PresentationIR"],
    ) -> Optional[float]:
        """Semantic resolution confidence for a raw call (None = unresolved)."""
        if pres is None:
            return None

        if name in cls.SLIDE_SCOPED_TOOLS:
            slide_ref = arguments.get("slide_id_or_num", arguments.get("slide_id"))
            if slide_ref is None:
                return None
            slide = pres.get_slide(slide_ref)
            if slide is None:
                return None
            if isinstance(slide_ref, str) and slide_ref == slide.id:
                return 1.0
            return 0.95

        target = arguments.get("element_id") or arguments.get("target")
        if target is None:
            return None
        slide = pres.get_active_slide()
        if cls._exact_element_match(slide, str(target)):
            return 1.0
        # Allow the semantic resolver (unique names, positional refs) to weigh in.
        from .action import ActionResolver
        try:
            _, confidence = ActionResolver.resolve_target_element_with_confidence(
                str(target), slide, arguments.get("last_target_id")
            )
            return confidence
        except Exception:
            return None

    @classmethod
    def enrich_tool_call(
        cls,
        tool_call: Dict[str, Any],
        pres: Optional["PresentationIR"],
    ) -> Dict[str, Any]:
        """Adds `_resolution_confidence` / `_needs_confirmation` to a tool call in place."""
        if not isinstance(tool_call, dict) or tool_call.get("_risk_enriched"):
            return tool_call
        if "_needs_confirmation" in tool_call or "_resolution_confidence" in tool_call:
            # ActionResolver already assessed this call with finer semantic intent.
            tool_call["_risk_enriched"] = True
            return tool_call

        name = tool_call.get("name", "")
        arguments = tool_call.get("arguments") or {}
        action_type = cls._infer_action_type(name, arguments)
        tool_call["_risk_enriched"] = True
        if action_type is None:
            return tool_call

        confidence = cls._resolve_confidence(name, arguments, pres)
        tool_call["_resolution_confidence"] = (
            round(confidence, 2) if isinstance(confidence, (int, float)) else None
        )
        tool_call["_needs_confirmation"] = ActionRiskPolicy.needs_confirmation(
            confidence, action_type
        )
        tool_call["_risk_action_type"] = action_type
        return tool_call


class ConfirmationGate:
    """Execution-level gate that blocks unconfirmed low-confidence mutations.

    `ActionResolver.action_to_tool_call` only *flags* `_needs_confirmation`; `RiskEnricher`
    extends that flag to raw live-LLM calls; this gate is the enforcement point consulted
    by the agent runtime before any tool handler runs.

    Fail-closed contract: a risky action whose risk was never assessed (no
    `_needs_confirmation` metadata after enrichment) is blocked rather than allowed.
    A call is only allowed through when:
      - its call id (`id`) is present in the explicit user-confirmed id set, or
      - it carries `_needs_confirmation=False`, or
      - it is not a risk-mapped action (e.g. create/generate/undo tools).
    """

    @staticmethod
    def is_blocked(tool_call: Dict[str, Any], confirmed_ids: Optional[set] = None) -> bool:
        if confirmed_ids and tool_call.get("id") in confirmed_ids:
            return False
        flag = tool_call.get("_needs_confirmation")
        if flag is False:
            return False
        if flag is True:
            return True
        # No risk assessment present: fail closed for risk-mapped actions.
        action_type = RiskEnricher._infer_action_type(
            tool_call.get("name", ""), tool_call.get("arguments") or {}
        )
        return action_type is not None

    @staticmethod
    def blocked_result(tool_call: Dict[str, Any]) -> Dict[str, Any]:
        name = tool_call.get("name", "unknown")
        call_id = tool_call.get("id")
        confidence = tool_call.get("_resolution_confidence")
        conf_txt = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unknown"
        return {
            "success": False,
            "blocked": True,
            "requires_confirmation": True,
            "call_id": call_id,
            "resolution_confidence": confidence,
            "message": (
                f"操作 '{name}' 语义解析置信度 {conf_txt} 低于安全阈值，已被 RiskPolicy 拦截。"
                f"请显式确认后执行该挂起调用（call_id: {call_id}）。"
            ),
            "error": "requires_user_confirmation",
        }
