"""Patch and Version Control engine for PPT-IR.

Generates reversible patch records for every modification, supporting:
- Undo
- Redo
- Rollback
- Visual history inspection
"""

from __future__ import annotations
import time
import copy
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from .models import PresentationIR, SlideIR, ElementIR


class PatchRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"patch_{int(time.time()*1000)}")
    timestamp: float = Field(default_factory=time.time)
    action: str = "update"  # create_slide, delete_slide, add_element, update_element, delete_element, batch_update
    description: str = ""
    slide_id: Optional[str] = None
    element_id: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None


class HistoryManager:
    """Manages Undo/Redo and version rollback for a PresentationIR."""

    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.undo_stack: List[PatchRecord] = []
        self.redo_stack: List[PatchRecord] = []

    def record(
        self,
        action: str,
        description: str,
        slide_id: Optional[str] = None,
        element_id: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None
    ) -> PatchRecord:
        record = PatchRecord(
            action=action,
            description=description,
            slide_id=slide_id,
            element_id=element_id,
            before=copy.deepcopy(before),
            after=copy.deepcopy(after)
        )
        self.undo_stack.append(record)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        # Clear redo stack on new branch of edits
        self.redo_stack.clear()
        return record

    def undo(self, presentation: PresentationIR) -> Optional[PatchRecord]:
        if not self.undo_stack:
            return None
        patch = self.undo_stack.pop()
        self._apply_state_delta(presentation, patch, reverse=True)
        self.redo_stack.append(patch)
        presentation.version += 1
        return patch

    def redo(self, presentation: PresentationIR) -> Optional[PatchRecord]:
        if not self.redo_stack:
            return None
        patch = self.redo_stack.pop()
        self._apply_state_delta(presentation, patch, reverse=False)
        self.undo_stack.append(patch)
        presentation.version += 1
        return patch

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def get_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": p.id,
                "timestamp": p.timestamp,
                "action": p.action,
                "description": p.description,
                "slide_id": p.slide_id,
                "element_id": p.element_id,
            }
            for p in self.undo_stack
        ]

    def _apply_state_delta(self, pres: PresentationIR, patch: PatchRecord, reverse: bool = False):
        state_to_apply = patch.before if reverse else patch.after
        action = patch.action

        if action in ["add_element", "create_element"]:
            slide = pres.get_slide(patch.slide_id) if patch.slide_id else None
            if not slide:
                return
            if reverse:
                # Reversing add -> remove element
                slide.remove_element(patch.element_id)
            else:
                # Redoing add -> re-insert element
                if patch.after:
                    from .models import ShapeElementIR, TextElementIR, ConnectorElementIR, ImageElementIR, TableElementIR
                    elem_type = patch.after.get("type", "shape")
                    cls_map = {
                        "shape": ShapeElementIR,
                        "text": TextElementIR,
                        "connector": ConnectorElementIR,
                        "image": ImageElementIR,
                        "table": TableElementIR
                    }
                    cls = cls_map.get(elem_type, ShapeElementIR)
                    slide.elements.append(cls.model_validate(patch.after))

        elif action == "delete_element":
            slide = pres.get_slide(patch.slide_id) if patch.slide_id else None
            if not slide:
                return
            if reverse:
                # Reversing delete -> restore element from before
                if patch.before:
                    from .models import ShapeElementIR, TextElementIR, ConnectorElementIR, ImageElementIR, TableElementIR
                    elem_type = patch.before.get("type", "shape")
                    cls_map = {
                        "shape": ShapeElementIR,
                        "text": TextElementIR,
                        "connector": ConnectorElementIR,
                        "image": ImageElementIR,
                        "table": TableElementIR
                    }
                    cls = cls_map.get(elem_type, ShapeElementIR)
                    slide.elements.append(cls.model_validate(patch.before))
            else:
                # Redoing delete -> delete again
                slide.remove_element(patch.element_id)

        elif action in ["update_element", "move_element", "resize_element", "style_element"]:
            slide = pres.get_slide(patch.slide_id) if patch.slide_id else None
            if not slide:
                return
            target_state = patch.before if reverse else patch.after
            if not target_state:
                return
            
            # Find and replace element
            for idx, el in enumerate(slide.elements):
                if el.id == patch.element_id:
                    from .models import ShapeElementIR, TextElementIR, ConnectorElementIR, ImageElementIR, TableElementIR
                    elem_type = target_state.get("type", el.type)
                    cls_map = {
                        "shape": ShapeElementIR,
                        "text": TextElementIR,
                        "connector": ConnectorElementIR,
                        "image": ImageElementIR,
                        "table": TableElementIR
                    }
                    cls = cls_map.get(elem_type, ShapeElementIR)
                    slide.elements[idx] = cls.model_validate(target_state)
                    break
