"""Shape models for shapes, textboxes, connectors, images, and groups."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union, Tuple
from .style import Fill, Line, Shadow
from .text import TextBlock


@dataclass
class Position:
    """Position and dimension in inches."""
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "width": round(self.width, 3),
            "height": round(self.height, 3),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Position:
        return cls(
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            width=float(d.get("width", 1.0)),
            height=float(d.get("height", 1.0)),
        )


@dataclass
class BaseElement:
    """Base class for all slide elements."""
    id: str = ""
    name: str = ""
    type: str = "shape"
    z_order: int = 0

    def to_dict(self) -> Dict[str, Any]:
        raise NotImplementedError


@dataclass
class ShapeElement(BaseElement):
    """Standard geometric shape or textbox."""
    shape_type: str = "rectangle"  # rectangle, roundRect, ellipse, diamond, arrow, line, etc.
    position: Position = field(default_factory=Position)
    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    fill: Fill = field(default_factory=Fill)
    line: Optional[Line] = None
    shadow: Optional[Shadow] = None
    radius: Optional[float] = None  # roundRect corner radius in px at 96 DPI (converted to OOXML adj on write)
    adjust_values: Dict[str, float] = field(default_factory=dict)
    text: Optional[TextBlock] = None

    def __post_init__(self):
        if not self.type:
            self.type = "shape"

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "shape_type": self.shape_type,
            "position": self.position.to_dict(),
        }
        if self.rotation:
            res["rotation"] = round(self.rotation, 2)
        if self.flip_h:
            res["flip_h"] = self.flip_h
        if self.flip_v:
            res["flip_v"] = self.flip_v
        if self.fill:
            res["fill"] = self.fill.to_dict()
        if self.line:
            res["line"] = self.line.to_dict()
        if self.shadow and self.shadow.enabled:
            res["shadow"] = self.shadow.to_dict()
        if self.radius is not None:
            res["radius"] = self.radius
        if self.adjust_values:
            res["adjust_values"] = self.adjust_values
        if self.text and self.text.content:
            res["text"] = self.text.to_dict()
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ShapeElement:
        elem_id = str(d.get("id", ""))
        elem_name = str(d.get("name", ""))
        elem_type = d.get("type", "shape")
        shape_type = d.get("shape_type", "rectangle")
        position = Position.from_dict(d.get("position", {}))

        fill = Fill.from_dict(d.get("fill", {})) if "fill" in d else Fill(type="none")
        line = Line.from_dict(d.get("line", {})) if "line" in d else None
        shadow = Shadow.from_dict(d.get("shadow", {})) if "shadow" in d else None

        text = None
        if "text" in d and d["text"]:
            text = TextBlock.from_dict(d["text"])

        return cls(
            id=elem_id,
            name=elem_name,
            type=elem_type,
            shape_type=shape_type,
            position=position,
            rotation=float(d.get("rotation", 0.0)),
            flip_h=bool(d.get("flip_h", False)),
            flip_v=bool(d.get("flip_v", False)),
            fill=fill,
            line=line,
            shadow=shadow,
            radius=d.get("radius"),
            adjust_values=d.get("adjust_values", {}),
            text=text
        )


@dataclass
class ConnectorElement(BaseElement):
    """Connector line connecting points or shapes."""
    connector_type: str = "straight"  # straight, bent, curved
    start: Tuple[float, float] = (0.0, 0.0)
    end: Tuple[float, float] = (1.0, 1.0)
    line: Line = field(default_factory=Line)
    arrow_start: Optional[str] = None  # none, triangle, stealth, etc.
    arrow_end: Optional[str] = "triangle"
    start_shape_id: Optional[str] = None
    end_shape_id: Optional[str] = None
    start_site_index: Optional[int] = None
    end_site_index: Optional[int] = None

    def __post_init__(self):
        self.type = "connector"

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": self.id,
            "type": "connector",
            "connector_type": self.connector_type,
            "start": {"x": round(self.start[0], 3), "y": round(self.start[1], 3)},
            "end": {"x": round(self.end[0], 3), "y": round(self.end[1], 3)},
            "line": self.line.to_dict(),
        }
        if self.arrow_end and self.arrow_end != "none":
            res["arrow"] = self.arrow_end
        if self.arrow_start and self.arrow_start != "none":
            res["arrow_start"] = self.arrow_start
        if self.start_shape_id:
            res["start_shape_id"] = self.start_shape_id
        if self.end_shape_id:
            res["end_shape_id"] = self.end_shape_id
        if self.start_site_index is not None:
            res["start_site_index"] = self.start_site_index
        if self.end_site_index is not None:
            res["end_site_index"] = self.end_site_index
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ConnectorElement:
        elem_id = str(d.get("id", ""))
        elem_name = str(d.get("name", ""))
        conn_type = d.get("connector_type", "straight")

        # Parse start
        s = d.get("start", [0.0, 0.0])
        if isinstance(s, dict):
            start = (float(s.get("x", 0.0)), float(s.get("y", 0.0)))
        elif isinstance(s, (list, tuple)):
            start = (float(s[0]), float(s[1]))
        else:
            start = (0.0, 0.0)

        # Parse end
        e = d.get("end", [1.0, 1.0])
        if isinstance(e, dict):
            end = (float(e.get("x", 1.0)), float(e.get("y", 1.0)))
        elif isinstance(e, (list, tuple)):
            end = (float(e[0]), float(e[1]))
        else:
            end = (1.0, 1.0)

        line = Line.from_dict(d.get("line", {})) if "line" in d else Line()
        arrow_end = d.get("arrow", d.get("arrow_end", "triangle"))
        arrow_start = d.get("arrow_start")

        return cls(
            id=elem_id,
            name=elem_name,
            connector_type=conn_type,
            start=start,
            end=end,
            line=line,
            arrow_start=arrow_start,
            arrow_end=arrow_end,
            start_shape_id=d.get("start_shape_id"),
            end_shape_id=d.get("end_shape_id"),
            start_site_index=d.get("start_site_index"),
            end_site_index=d.get("end_site_index")
        )


@dataclass
class ImageElement(BaseElement):
    """Raster or vector image placed on the slide."""
    position: Position = field(default_factory=Position)
    src: str = ""                # Path relative to project root or assets/
    original_name: str = ""      # e.g. image1.png
    media_rel_id: str = ""       # e.g. rId2
    rotation: float = 0.0

    def __post_init__(self):
        self.type = "image"

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": self.id,
            "type": "image",
            "position": self.position.to_dict(),
            "src": self.src,
        }
        if self.original_name:
            res["original_name"] = self.original_name
        if self.rotation:
            res["rotation"] = round(self.rotation, 2)
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ImageElement:
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            position=Position.from_dict(d.get("position", {})),
            src=d.get("src", ""),
            original_name=d.get("original_name", ""),
            rotation=float(d.get("rotation", 0.0))
        )


@dataclass
class GroupElement(BaseElement):
    """Group of multiple elements."""
    position: Position = field(default_factory=Position)
    elements: List[Union[ShapeElement, ConnectorElement, ImageElement, 'GroupElement']] = field(default_factory=list)

    def __post_init__(self):
        self.type = "group"

    def all_children(self) -> List[Union[ShapeElement, ConnectorElement, ImageElement, 'GroupElement']]:
        """Returns all descendants recursively."""
        result = []
        for child in self.elements:
            result.append(child)
            if isinstance(child, GroupElement):
                result.extend(child.all_children())
        return result

    def recompute_bounds(self) -> Position:
        """Computes and updates the bounding box from all child elements."""
        if not self.elements:
            return self.position

        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for child in self.elements:
            if hasattr(child, "position") and child.position:
                p = child.position
                min_x = min(min_x, p.x)
                min_y = min(min_y, p.y)
                max_x = max(max_x, p.x + p.width)
                max_y = max(max_y, p.y + p.height)
            elif isinstance(child, ConnectorElement):
                min_x = min(min_x, child.start[0], child.end[0])
                min_y = min(min_y, child.start[1], child.end[1])
                max_x = max(max_x, child.start[0], child.end[0])
                max_y = max(max_y, child.start[1], child.end[1])

        if min_x != float('inf'):
            self.position.x = round(min_x, 4)
            self.position.y = round(min_y, 4)
            self.position.width = round(max(max_x - min_x, 0.01), 4)
            self.position.height = round(max(max_y - min_y, 0.01), 4)
        return self.position

    def translate(self, dx: float, dy: float) -> None:
        """Translates the group and all its children by dx, dy."""
        self.position.x = round(self.position.x + dx, 4)
        self.position.y = round(self.position.y + dy, 4)
        for child in self.elements:
            if isinstance(child, GroupElement):
                child.translate(dx, dy)
            elif hasattr(child, "position") and child.position:
                child.position.x = round(child.position.x + dx, 4)
                child.position.y = round(child.position.y + dy, 4)
            elif isinstance(child, ConnectorElement):
                child.start = (round(child.start[0] + dx, 4), round(child.start[1] + dy, 4))
                child.end = (round(child.end[0] + dx, 4), round(child.end[1] + dy, 4))

    def scale(self, sx: float, sy: float, origin_x: Optional[float] = None, origin_y: Optional[float] = None) -> None:
        """Scales group and children relative to origin (default group position)."""
        ox = self.position.x if origin_x is None else origin_x
        oy = self.position.y if origin_y is None else origin_y

        self.position.x = round(ox + (self.position.x - ox) * sx, 4)
        self.position.y = round(oy + (self.position.y - oy) * sy, 4)
        self.position.width = round(self.position.width * sx, 4)
        self.position.height = round(self.position.height * sy, 4)

        for child in self.elements:
            if isinstance(child, GroupElement):
                child.scale(sx, sy, origin_x=ox, origin_y=oy)
            elif hasattr(child, "position") and child.position:
                child.position.x = round(ox + (child.position.x - ox) * sx, 4)
                child.position.y = round(oy + (child.position.y - oy) * sy, 4)
                child.position.width = round(child.position.width * sx, 4)
                child.position.height = round(child.position.height * sy, 4)
            elif isinstance(child, ConnectorElement):
                sx_start = round(ox + (child.start[0] - ox) * sx, 4)
                sy_start = round(oy + (child.start[1] - oy) * sy, 4)
                sx_end = round(ox + (child.end[0] - ox) * sx, 4)
                sy_end = round(oy + (child.end[1] - oy) * sy, 4)
                child.start = (sx_start, sy_start)
                child.end = (sx_end, sy_end)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "group",
            "position": self.position.to_dict(),
            "elements": [e.to_dict() for e in self.elements]
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GroupElement:
        children = []
        for item in d.get("elements", []):
            t = item.get("type", "shape")
            if t == "connector":
                children.append(ConnectorElement.from_dict(item))
            elif t == "image":
                children.append(ImageElement.from_dict(item))
            elif t == "group":
                children.append(GroupElement.from_dict(item))
            else:
                children.append(ShapeElement.from_dict(item))
        return cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            position=Position.from_dict(d.get("position", {})),
            elements=children
        )
