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