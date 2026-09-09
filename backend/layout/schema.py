"""Layout & Geometry Intermediate Representation (LayoutSpec) Schema (PR10).

Defines the spatial and geometric contracts between the Slide Semantic IR (SlideSpec)
and the PPTX Renderer.

Decoupling Principle:
SlideSpec (Semantic visual intent, no coords)
  -> Layout Engine / Synthesis (PR10: computes geometry & constraints)
  -> LayoutSpec (Deterministic coordinates, typography, safe zones)
  -> PPTX Renderer (PR11: shapes, tables, pictures, theme)
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..slidespec.schema import BlockRole, VisualIntent


class Canvas(BaseModel):
    """Normalized slide canvas dimensions (default: 16:9 ViewBox)."""

    width: float = Field(1280.0, ge=100.0, description="Canvas width in px")
    height: float = Field(720.0, ge=100.0, description="Canvas height in px")


class Rect(BaseModel):
    """Bounding box geometry on the normalized canvas."""

    x: float = Field(..., description="Horizontal offset from left")
    y: float = Field(..., description="Vertical offset from top")
    width: float = Field(..., ge=0.0, description="Bounding box width")
    height: float = Field(..., ge=0.0, description="Bounding box height")

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height if self.height > 0 else 0.0

    def intersects(self, other: "Rect", eps: float = 1e-4) -> bool:
        """Check if this rectangle intersects with another rectangle."""
        if (
            self.right <= other.x + eps
            or other.right <= self.x + eps
            or self.bottom <= other.y + eps
            or other.bottom <= self.y + eps
        ):
            return False
        return True

    def contains(self, other: "Rect", eps: float = 1e-4) -> bool:
        """Check if this rectangle completely contains another rectangle."""
        return (
            self.x <= other.x + eps
            and self.y <= other.y + eps
            and self.right >= other.right - eps
            and self.bottom >= other.bottom - eps
        )

    def intersection(self, other: "Rect") -> Optional["Rect"]:
        """Return the intersection rectangle if any, else None."""
        if not self.intersects(other):
            return None
        ix = max(self.x, other.x)
        iy = max(self.y, other.y)
        iw = min(self.right, other.right) - ix
        ih = min(self.bottom, other.bottom) - iy
        return Rect(x=ix, y=iy, width=iw, height=ih)


class ElementType(str, Enum):
    """Type of concrete element on the canvas."""

    TEXT = "TEXT"
    FIGURE = "FIGURE"
    TABLE = "TABLE"
    BADGE = "BADGE"
    CONTAINER = "CONTAINER"


class TextStyle(BaseModel):
    """Typography specification for textual elements."""

    font_size: float = Field(18.0, ge=6.0, description="Font size in points")
    font_weight: Literal["normal", "bold"] = "normal"
    font_family: str = Field("Calibri", description="Font family name")
    alignment: Literal["left", "center", "right", "justify"] = "left"
    vertical_alignment: Literal["top", "middle", "bottom"] = "top"
    line_height: float = Field(1.2, description="Line spacing multiplier")
    color: Optional[str] = Field(None, description="Hex color '#RRGGBB' or theme reference")
    italic: bool = False


class ElementStyle(BaseModel):
    """Visual presentation styling for elements and containers."""

    text: Optional[TextStyle] = None
    background_color: Optional[str] = Field(None, description="Background fill hex color")
    border_color: Optional[str] = Field(None, description="Border hex color")
    border_width: float = Field(0.0, ge=0.0, description="Border stroke width in px")
    corner_radius: float = Field(0.0, ge=0.0, description="Border radius in px")
    padding: float = Field(0.0, ge=0.0, description="Internal content padding in px")
    opacity: float = Field(1.0, ge=0.0, le=1.0, description="Element opacity")


class LayoutElement(BaseModel):
    """A positioned, rendered element placed onto the slide canvas."""

    element_id: str = Field(..., description="Unique element identifier within the slide")
    source_block_id: Optional[str] = Field(
        None, description="Reference ID back to SlideSpec content block or synthetic role"
    )
    source_evidence_ids: List[str] = Field(
        default_factory=list, description="Associated evidence IDs propagated from SlideSpec"
    )
    element_type: ElementType = Field(..., description="Element category")
    role: Optional[BlockRole] = Field(None, description="Semantic role propagated from SlideSpec")
    geometry: Rect = Field(..., description="Explicit bounding rectangle on canvas")
    style: ElementStyle = Field(default_factory=ElementStyle, description="Visual style properties")
    content: Any = Field(default=None, description="Element payload (text, figure ref, table ref, or badge data)")
    z_index: int = Field(0, description="Stacking order")
    parent_id: Optional[str] = Field(None, description="Optional parent container ID")


class LayoutConstraint(BaseModel):
    """A geometric or relational layout constraint rule."""

    constraint_type: str = Field(..., description="Constraint identifier (e.g. CANVAS_BOUNDS, NO_OVERLAP)")
    target_element_ids: List[str] = Field(default_factory=list, description="IDs of elements subject to constraint")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Constraint threshold parameters")
    satisfied: bool = Field(True, description="Whether constraint is currently satisfied")
    message: Optional[str] = Field(None, description="Diagnostic violation details if not satisfied")


class LayoutSpec(BaseModel):
    """Fully resolved geometry and layout specification for a single slide."""

    slide_id: str = Field(..., description="Slide identifier")
    slide_index: int = Field(..., ge=1, description="1-based slide index")
    visual_intent: VisualIntent = Field(..., description="Original visual intent")
    canvas: Canvas = Field(default_factory=Canvas, description="Canvas dimension")
    elements: List[LayoutElement] = Field(default_factory=list, description="Positioned layout elements")
    constraints: List[LayoutConstraint] = Field(default_factory=list, description="Recorded layout constraints")
    speaker_notes: Optional[str] = Field(None, description="Speaker notes propagated from SlideSpec")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Supplementary layout metadata")

    def get_element(self, element_id: str) -> Optional[LayoutElement]:
        """Find element by element_id."""
        for el in self.elements:
            if el.element_id == element_id:
                return el
        return None

    def get_elements_by_type(self, element_type: ElementType) -> List[LayoutElement]:
        """Return all elements matching element_type."""
        return [el for el in self.elements if el.element_type == element_type]


class DeckLayoutSpec(BaseModel):
    """Structured collection of slide layouts representing a full presentation."""

    title: str = Field(..., description="Presentation title")
    canvas: Canvas = Field(default_factory=Canvas, description="Presentation canvas dimension")
    slides: List[LayoutSpec] = Field(default_factory=list, description="Ordered slide layout specs")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Deck-level metadata")

    @property
    def slide_count(self) -> int:
        return len(self.slides)

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        """Serialize deck layout spec to dictionary."""
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        """Deterministically write DeckLayoutSpec to JSON file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "DeckLayoutSpec":
        """Deserialize DeckLayoutSpec from JSON file."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
