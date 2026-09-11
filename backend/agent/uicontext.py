"""Request-scoped UI context for deictic ("这个 / 它") Agent targeting.

A UIContext is NOT document state: it never enters the PresentationIR. It tells
the Agent which slide and element(s) the *requesting client* had selected when
the natural-language request was made, so deictic references bind to explicit
element ids instead of being guessed from `last_target_id` or text semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Tokens that make a request dependent on the caller's selection.
DEFERENCE_TOKENS = (
    "这个",
    "这个框",
    "当前这个",
    "选中的",
    "这些",
    "它们",
    "这几个",
    "它",
)


@dataclass
class UIContext:
    client_id: Optional[str] = None
    ui_context_revision: int = 0
    active_slide_id: Optional[str] = None
    selected_element_ids: List[str] = field(default_factory=list)
    primary_selected_element_id: Optional[str] = None
    selection_scope: List[str] = field(default_factory=list)
    editing_element_id: Optional[str] = None

    @classmethod
    def from_any(cls, data: Any) -> "UIContext":
        """Coerces a dict / existing UIContext / None into a UIContext."""
        if data is None:
            return cls()
        if isinstance(data, cls):
            return data
        if isinstance(data, dict):
            try:
                revision = int(data.get("ui_context_revision") or 0)
            except (TypeError, ValueError):
                revision = 0
            return cls(
                client_id=data.get("client_id"),
                ui_context_revision=revision,
                active_slide_id=data.get("active_slide_id"),
                selected_element_ids=list(data.get("selected_element_ids") or []),
                primary_selected_element_id=data.get("primary_selected_element_id"),
                selection_scope=list(data.get("selection_scope") or []),
                editing_element_id=data.get("editing_element_id"),
            )
        return cls()

    @property
    def has_selection(self) -> bool:
        return bool(self.selected_element_ids)

    @property
    def resolution_primary(self) -> Optional[str]:
        """The element a singular deictic reference should bind to."""
        if self.primary_selected_element_id:
            return self.primary_selected_element_id
        return self.selected_element_ids[0] if self.selected_element_ids else None

    def is_deictic(self, text: str) -> bool:
        return any(token in (text or "") for token in DEFERENCE_TOKENS)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "ui_context_revision": self.ui_context_revision,
            "active_slide_id": self.active_slide_id,
            "selected_element_ids": list(self.selected_element_ids),
            "primary_selected_element_id": self.primary_selected_element_id,
            "selection_scope": list(self.selection_scope),
            "editing_element_id": self.editing_element_id,
        }
