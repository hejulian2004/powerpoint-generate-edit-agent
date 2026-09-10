"""ActionRiskPolicy: per-action-type semantic resolution risk thresholds (PR6.1).

Different operations carry different risk. A low-confidence resolution should gate
high-risk mutations (delete / move / resize) harder than low-risk styling changes.

    DELETE  -> requires confidence >= 0.95
    MOVE    -> requires confidence >= 0.85
    RESIZE  -> requires confidence >= 0.85
    STYLE   -> requires confidence >= 0.75
    default -> requires confidence >= 0.80

ActionResolver uses these thresholds to compute `_needs_confirmation` per action.
"""

from __future__ import annotations
from typing import Dict, Optional

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


class ConfirmationGate:
    """Execution-level gate that blocks unconfirmed low-confidence mutations.

    `ActionResolver.action_to_tool_call` only *flags* `_needs_confirmation`; this gate is
    the enforcement point consulted by the agent runtime before any tool handler runs.
    A tool call is only allowed through when:
      - it carries no `_needs_confirmation` flag (direct LLM / deterministic planning), or
      - it carries `_needs_confirmation=False`, or
      - its call id (`id`) is present in the explicit user-confirmed id set.
    """

    @staticmethod
    def is_blocked(tool_call: Dict[str, Any], confirmed_ids: Optional[set] = None) -> bool:
        if tool_call.get("_needs_confirmation") is not True:
            return False
        if confirmed_ids and tool_call.get("id") in confirmed_ids:
            return False
        return True

    @staticmethod
    def blocked_result(tool_call: Dict[str, Any]) -> Dict[str, Any]:
        name = tool_call.get("name", "unknown")
        confidence = tool_call.get("_resolution_confidence")
        conf_txt = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "unknown"
        return {
            "success": False,
            "blocked": True,
            "requires_confirmation": True,
            "resolution_confidence": confidence,
            "message": (
                f"操作 '{name}' 语义解析置信度 {conf_txt} 低于安全阈值，已被 RiskPolicy 拦截。"
                f"请明确确认后重试（确认方式：二次确认同一指令或提供更精确的目标描述）。"
            ),
            "error": "requires_user_confirmation",
        }
