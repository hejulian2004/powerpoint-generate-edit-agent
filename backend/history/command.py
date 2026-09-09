"""MutationCommand architecture implementing the Command Pattern for PPT-IR edits.

Supports reversible execution:
- execute(): apply mutation to PresentationIR
- undo(): revert mutation on PresentationIR
- redo(): re-apply mutation on PresentationIR
- to_event(): export as standardized MutationEvent
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import time
import copy
import uuid
from typing import Dict, Any, Optional, List, Type

from ..ir.models import (
    PresentationIR, SlideIR, ElementIR,
    ShapeElementIR, TextElementIR, ConnectorElementIR,
    ImageElementIR, TableElementIR, GroupElementIR
)
from ..ir.history_event import MutationEvent

_ELEMENT_CLASS_MAP: Dict[str, Type[ElementIR]] = {
    "shape": ShapeElementIR,
    "text": TextElementIR,
    "connector": ConnectorElementIR,
    "image": ImageElementIR,
    "table": TableElementIR,
    "group": GroupElementIR,
}


def _deserialize_element(data: Dict[str, Any]) -> ElementIR:
    elem_type = data.get("type", "shape")
    cls = _ELEMENT_CLASS_MAP.get(elem_type, ShapeElementIR)
    return cls.model_validate(data)


def _renumber_slides(pres: PresentationIR) -> None:
    """Renumbers every slide in order to keep slide_num consistent after insertion/removal."""
    for idx, s in enumerate(pres.slides):
        s.slide_num = idx + 1


def _insert_slide(pres: PresentationIR, slide_data: Dict[str, Any], position: int) -> SlideIR:
    """Inserts a slide (deserialized from slide_data) at the given 0-based position."""
    slide = SlideIR.model_validate(slide_data)
    if not any(s.id == slide.id for s in pres.slides):
        idx = max(0, min(position, len(pres.slides)))
        pres.slides.insert(idx, slide)
        _renumber_slides(pres)
    return slide


def _remove_slide(pres: PresentationIR, slide_id: str) -> bool:
    """Removes the slide with the given id and renumbers the remaining slides."""
    idx = next((i for i, s in enumerate(pres.slides) if s.id == slide_id), None)
    if idx is None:
        return False
    pres.slides.pop(idx)
    _renumber_slides(pres)
    return True


class MutationCommand(ABC):
    """Abstract Base Class for all reversible PPT-IR mutation commands."""

    def __init__(
        self,
        command_id: Optional[str] = None,
        action: str = "mutation",
        description: str = "",
        timestamp: Optional[float] = None,
        source: str = "agent_tool",
        slide_id: Optional[str] = None,
        element_id: Optional[str] = None
    ):
        self.id = command_id or f"cmd_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
        self.action = action
        self.description = description
        self.timestamp = timestamp or time.time()
        self.source = source
        self.slide_id = slide_id
        self.element_id = element_id

    @abstractmethod
    def execute(self, pres: PresentationIR) -> bool:
        """Applies the mutation to the presentation."""
        pass

    @abstractmethod
    def undo(self, pres: PresentationIR) -> bool:
        """Reverts the mutation on the presentation."""
        pass

    @abstractmethod
    def redo(self, pres: PresentationIR) -> bool:
        """Re-applies the mutation on the presentation."""
        pass

    @abstractmethod
    def to_event(self) -> MutationEvent:
        """Serializes command into standardized MutationEvent."""
        pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "description": self.description,
            "timestamp": self.timestamp,
            "source": self.source,
            "slide_id": self.slide_id,
            "element_id": self.element_id,
        }

    def model_dump(self) -> Dict[str, Any]:
        """Pydantic-compatible serialization alias."""
        return self.to_dict()


class UpdateElementCommand(MutationCommand):
    """Command that updates coordinates, styling, or text of an existing element."""

    def __init__(
        self,
        slide_id: str,
        element_id: str,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        action: str = "update_element",
        description: str = "",
        source: str = "agent_tool",
        command_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ):
        super().__init__(
            command_id=command_id,
            action=action,
            description=description,
            timestamp=timestamp,
            source=source,
            slide_id=slide_id,
            element_id=element_id
        )
        self.before = copy.deepcopy(before) if before else {}
        self.after = copy.deepcopy(after) if after else {}

    def execute(self, pres: PresentationIR) -> bool:
        return self._apply_state(pres, self.after)

    def undo(self, pres: PresentationIR) -> bool:
        return self._apply_state(pres, self.before)

    def redo(self, pres: PresentationIR) -> bool:
        return self._apply_state(pres, self.after)

    def _apply_state(self, pres: PresentationIR, state: Dict[str, Any]) -> bool:
        if not self.slide_id or not state:
            return False
        slide = pres.get_slide(self.slide_id)
        if not slide:
            return False

        for idx, el in enumerate(slide.elements):
            if el.id == self.element_id:
                # Merge target state with full validation
                current_dump = el.model_dump()
                current_dump.update(state)
                # Ensure transform sub-object is synchronized with updated coordinates
                if "transform" in current_dump and isinstance(current_dump["transform"], dict):
                    t = current_dump["transform"]
                    for coord in ["x", "y", "width", "height", "rotation"]:
                        if coord in state:
                            t[coord] = state[coord]
                slide.elements[idx] = _deserialize_element(current_dump)
                return True
        return False

    def to_event(self) -> MutationEvent:
        return MutationEvent(
            action=self.action,
            element_id=self.element_id or "",
            before=self.before,
            after=self.after,
            timestamp=str(self.timestamp),
            source=self.source
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["before"] = self.before
        d["after"] = self.after
        return d


class AddElementCommand(MutationCommand):
    """Command that adds a new element to a slide."""

    def __init__(
        self,
        slide_id: str,
        element_data: Dict[str, Any],
        action: str = "add_element",
        description: str = "",
        source: str = "agent_tool",
        command_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ):
        elem_id = element_data.get("id", f"el_{uuid.uuid4().hex[:6]}")
        super().__init__(
            command_id=command_id,
            action=action,
            description=description,
            timestamp=timestamp,
            source=source,
            slide_id=slide_id,
            element_id=elem_id
        )
        self.element_data = copy.deepcopy(element_data)
        self.before = {}
        self.after = self.element_data

    def execute(self, pres: PresentationIR) -> bool:
        slide = pres.get_slide(self.slide_id) if self.slide_id else None
        if not slide:
            return False
        elem = _deserialize_element(self.element_data)
        # Avoid duplicate addition if element already exists
        if not any(e.id == self.element_id for e in slide.elements):
            slide.elements.append(elem)
        return True

    def undo(self, pres: PresentationIR) -> bool:
        slide = pres.get_slide(self.slide_id) if self.slide_id else None
        if not slide or not self.element_id:
            return False
        return slide.remove_element(self.element_id)

    def redo(self, pres: PresentationIR) -> bool:
        return self.execute(pres)

    def to_event(self) -> MutationEvent:
        return MutationEvent(
            action=self.action,
            element_id=self.element_id or "",
            before={},
            after=self.element_data,
            timestamp=str(self.timestamp),
            source=self.source
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["after"] = self.element_data
        return d


class DeleteElementCommand(MutationCommand):
    """Command that deletes an existing element from a slide, preserving its snapshot."""

    def __init__(
        self,
        slide_id: str,
        element_id: str,
        before_data: Dict[str, Any],
        action: str = "delete_element",
        description: str = "",
        source: str = "agent_tool",
        command_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ):
        super().__init__(
            command_id=command_id,
            action=action,
            description=description,
            timestamp=timestamp,
            source=source,
            slide_id=slide_id,
            element_id=element_id
        )
        self.before_data = copy.deepcopy(before_data)
        self.before = self.before_data
        self.after = {}

    def execute(self, pres: PresentationIR) -> bool:
        slide = pres.get_slide(self.slide_id) if self.slide_id else None
        if not slide or not self.element_id:
            return False
        return slide.remove_element(self.element_id)

    def undo(self, pres: PresentationIR) -> bool:
        slide = pres.get_slide(self.slide_id) if self.slide_id else None
        if not slide or not self.before_data:
            return False
        elem = _deserialize_element(self.before_data)
        if not any(e.id == self.element_id for e in slide.elements):
            slide.elements.append(elem)
        return True

    def redo(self, pres: PresentationIR) -> bool:
        return self.execute(pres)

    def to_event(self) -> MutationEvent:
        return MutationEvent(
            action=self.action,
            element_id=self.element_id or "",
            before=self.before_data,
            after={},
            timestamp=str(self.timestamp),
            source=self.source
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["before"] = self.before_data
        return d


class AddSlideCommand(MutationCommand):
    """Command that adds a new slide to a presentation (create_slide / duplicate_slide)."""

    def __init__(
        self,
        slide_id: str,
        slide_data: Dict[str, Any],
        position: int = 0,
        prev_active_slide_id: Optional[str] = None,
        action: str = "create_slide",
        description: str = "",
        source: str = "agent_tool",
        command_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ):
        super().__init__(
            command_id=command_id,
            action=action,
            description=description,
            timestamp=timestamp,
            source=source,
            slide_id=slide_id
        )
        self.slide_data = copy.deepcopy(slide_data)
        self.position = position
        self.prev_active_slide_id = prev_active_slide_id
        self.before = {"active_slide_id": prev_active_slide_id}
        self.after = self.slide_data

    def execute(self, pres: PresentationIR) -> bool:
        _insert_slide(pres, self.slide_data, self.position)
        pres.active_slide_id = self.slide_id
        return True

    def undo(self, pres: PresentationIR) -> bool:
        ok = _remove_slide(pres, self.slide_id)
        if ok:
            pres.active_slide_id = self.prev_active_slide_id
        return ok

    def redo(self, pres: PresentationIR) -> bool:
        return self.execute(pres)

    def to_event(self) -> MutationEvent:
        return MutationEvent(
            action=self.action,
            element_id=self.slide_id or "",
            before=self.before,
            after=self.after,
            timestamp=str(self.timestamp),
            source=self.source
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["before"] = self.before
        d["after"] = self.after
        d["position"] = self.position
        return d


class DeleteSlideCommand(MutationCommand):
    """Command that deletes a slide, preserving its snapshot for undo/redo."""

    def __init__(
        self,
        slide_id: str,
        slide_data: Dict[str, Any],
        position: int = 0,
        active_after_delete: Optional[str] = None,
        action: str = "delete_slide",
        description: str = "",
        source: str = "agent_tool",
        command_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ):
        super().__init__(
            command_id=command_id,
            action=action,
            description=description,
            timestamp=timestamp,
            source=source,
            slide_id=slide_id
        )
        self.slide_data = copy.deepcopy(slide_data)
        self.position = position
        self.active_after_delete = active_after_delete
        self.before = {"slide": self.slide_data, "active_slide_id": active_after_delete}
        self.after = {}

    def execute(self, pres: PresentationIR) -> bool:
        ok = _remove_slide(pres, self.slide_id)
        if ok:
            pres.active_slide_id = self.active_after_delete
        return ok

    def undo(self, pres: PresentationIR) -> bool:
        _insert_slide(pres, self.slide_data, self.position)
        pres.active_slide_id = self.slide_id
        return True

    def redo(self, pres: PresentationIR) -> bool:
        return self.execute(pres)

    def to_event(self) -> MutationEvent:
        return MutationEvent(
            action=self.action,
            element_id=self.slide_id or "",
            before=self.before,
            after=self.after,
            timestamp=str(self.timestamp),
            source=self.source
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["before"] = self.before
        d["after"] = self.after
        d["position"] = self.position
        return d


class BatchMutationCommand(MutationCommand):
    """Atomic composite command executing multiple mutation commands."""

    def __init__(
        self,
        commands: List[MutationCommand],
        description: str = "Batch mutation",
        source: str = "agent_tool",
        command_id: Optional[str] = None,
        timestamp: Optional[float] = None
    ):
        super().__init__(
            command_id=command_id,
            action="batch_update",
            description=description,
            timestamp=timestamp,
            source=source
        )
        self.commands = commands
        self.before = {}
        self.after = {}

    def execute(self, pres: PresentationIR) -> bool:
        executed: List[MutationCommand] = []
        for cmd in self.commands:
            if not cmd.execute(pres):
                # Rollback already executed sub-commands in reverse order to ensure atomicity
                for prev_cmd in reversed(executed):
                    prev_cmd.undo(pres)
                return False
            executed.append(cmd)
        return True

    def undo(self, pres: PresentationIR) -> bool:
        success = True
        # Revert in reverse order
        for cmd in reversed(self.commands):
            if not cmd.undo(pres):
                success = False
        return success

    def redo(self, pres: PresentationIR) -> bool:
        redone: List[MutationCommand] = []
        for cmd in self.commands:
            if not cmd.redo(pres):
                # Rollback already redone sub-commands in reverse order to ensure atomicity
                for prev_cmd in reversed(redone):
                    prev_cmd.undo(pres)
                return False
            redone.append(cmd)
        return True

    def to_event(self) -> MutationEvent:
        combined_before = {}
        combined_after = {}
        for c in self.commands:
            ev = c.to_event()
            if ev.before:
                combined_before[ev.element_id] = ev.before
            if ev.after:
                combined_after[ev.element_id] = ev.after

        return MutationEvent(
            action=self.action,
            element_id=self.commands[0].element_id if self.commands else "",
            before=combined_before,
            after=combined_after,
            timestamp=str(self.timestamp),
            source=self.source
        )

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["sub_commands"] = [c.to_dict() for c in self.commands]
        return d
