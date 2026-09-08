"""PPT-IR (Presentation Intermediate Representation) Data Models - v2.

The canonical representation used across Agent reasoning, SVG/HTML rendering,
Web editing, and bi-directional OOXML conversion.
Standard canvas dimensions: 1280 x 720 (16:9 ViewBox).

Features in v2:
- True hierarchical GroupElementIR with recursive children and transform nesting
- TransformIR with flip_h, flip_v, scale_x, scale_y and matrix representation
- Rich ParagraphIR (bullet styles, line spacing, space before/after, indent level)
- Rich RunIR (hyperlink, highlight, theme color reference)
- Shape custom geometry and adjust values
- Connector shape-binding (start_shape_id, end_shape_id)
- Master and theme color slot references
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field, model_validator
import uuid


# =====================================================================
# Style & Visual Models
# =====================================================================

class GradientStop(BaseModel):
    position: float = Field(0.0, description="Stop position from 0.0 to 1.0")
    color: str = Field("#3B82F6", description="Hex color '#RRGGBB'")
    alpha: float = Field(1.0, description="Opacity from 0.0 to 1.0")


class GradientFill(BaseModel):
    type: Literal["linear", "radial"] = "linear"
    angle: float = Field(90.0, description="Gradient angle in degrees")
    stops: List[GradientStop] = Field(default_factory=list)


class FillStyle(BaseModel):
    type: Literal["none", "solid", "gradient", "theme"] = "solid"
    color: Optional[str] = Field("#3B82F6", description="Hex color")
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    gradient: Optional[GradientFill] = None
    theme_color: Optional[str] = Field(None, description="OOXML theme token: accent1-6, dk1, lt1, etc.")


class BorderStyle(BaseModel):
    color: Optional[str] = Field("#1E293B", description="Border color")
    width: float = Field(1.0, ge=0.0, description="Border width in px")
    style: Literal["solid", "dashed", "dotted", "none"] = "solid"
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    theme_color: Optional[str] = None


class ShadowStyle(BaseModel):
    enabled: bool = False
    color: str = "#000000"
    blur: float = Field(4.0, ge=0.0)
    angle: float = Field(45.0, description="Shadow angle in degrees")
    distance: float = Field(3.0, ge=0.0)
    alpha: float = Field(0.25, ge=0.0, le=1.0)


class FontIR(BaseModel):
    name: str = "Segoe UI"
    size: float = Field(18.0, ge=6.0, description="Font size in px")
    color: str = "#1E293B"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    highlight: Optional[str] = None
    theme_color: Optional[str] = None


class RunIR(BaseModel):
    text: str = ""
    font: Optional[FontIR] = None
    hyperlink: Optional[str] = None


class ParagraphIR(BaseModel):
    align: Literal["left", "center", "right", "justify"] = "left"
    vertical_align: Literal["top", "middle", "bottom"] = "top"
    line_spacing: float = Field(1.2, description="Line height multiplier")
    space_before: float = 0.0
    space_after: float = 0.0
    bullet: Optional[str] = Field(None, description="Bullet symbol, 'none', 'disc', or numbering")
    indent_level: int = Field(0, ge=0, le=9, description="0-based paragraph nesting level")
    margin_left: float = Field(0.0, description="Left indentation margin in px")
    runs: List[RunIR] = Field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "".join(r.text for r in self.runs)


class TextContentIR(BaseModel):
    paragraphs: List[ParagraphIR] = Field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "\n".join(p.plain_text for p in self.paragraphs)

    @classmethod
    def from_plain_text(
        cls,
        text: str,
        font: Optional[FontIR] = None,
        align: Literal["left", "center", "right", "justify"] = "left"
    ) -> TextContentIR:
        paragraphs = []
        for line in text.split("\n"):
            paragraphs.append(ParagraphIR(align=align, runs=[RunIR(text=line, font=font)]))
        return cls(paragraphs=paragraphs)


class ElementStyleIR(BaseModel):
    fill: Optional[FillStyle] = None
    border: Optional[BorderStyle] = None
    shadow: Optional[ShadowStyle] = None
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    radius: float = Field(0.0, description="Normalized border radius 0.0 - 0.5 or px")
    padding: float = Field(8.0, description="Internal padding in px")


# =====================================================================
# Transform & Geometry Models
# =====================================================================

class TransformIR(BaseModel):
    """Canonical geometric transformation on the 1280x720 canvas."""
    x: float = Field(0.0, description="Left position in px")
    y: float = Field(0.0, description="Top position in px")
    width: float = Field(100.0, ge=0.0, description="Width in px")
    height: float = Field(50.0, ge=0.0, description="Height in px")
    rotation: float = Field(0.0, description="Clockwise rotation in degrees")
    flip_h: bool = Field(False, description="Horizontal flip")
    flip_v: bool = Field(False, description="Vertical flip")
    scale_x: float = Field(1.0, description="Local horizontal scale")
    scale_y: float = Field(1.0, description="Local vertical scale")


# =====================================================================
# Element IR Models
# =====================================================================

class BaseElementIR(BaseModel):
    id: str = Field(default_factory=lambda: f"elem_{uuid.uuid4().hex[:8]}")
    type: str
    name: Optional[str] = None
    x: float = Field(0.0, description="Left position in px (1280x720 canvas)")
    y: float = Field(0.0, description="Top position in px")
    width: float = Field(100.0, ge=0.0, description="Width in px")
    height: float = Field(50.0, ge=0.0, description="Height in px")
    rotation: float = Field(0.0, description="Clockwise rotation in degrees")
    transform: Optional[TransformIR] = None
    z_index: int = Field(0, description="Stacking order")
    locked: bool = False
    style: ElementStyleIR = Field(default_factory=ElementStyleIR)
    children: List[ElementIR] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_transform_and_coords(self) -> BaseElementIR:
        """Keep top-level coordinates and transform object bidirectional."""
        if self.transform is None:
            self.transform = TransformIR(
                x=self.x,
                y=self.y,
                width=self.width,
                height=self.height,
                rotation=self.rotation,
            )
        else:
            # Sync to flat fields for backwards compatibility with PR1 code
            self.x = self.transform.x
            self.y = self.transform.y
            self.width = self.transform.width
            self.height = self.transform.height
            self.rotation = self.transform.rotation
        return self


class ShapeElementIR(BaseElementIR):
    type: Literal["shape"] = "shape"
    shape_type: str = Field("roundRect", description="rectangle, roundRect, ellipse, diamond, triangle, rightArrow, callout, star")
    text_content: Optional[TextContentIR] = None
    flip_h: bool = False
    flip_v: bool = False
    adjust_values: Dict[str, float] = Field(default_factory=dict, description="OOXML shape adjustment values (e.g. corner radius)")
    custom_geometry: Optional[str] = Field(None, description="Optional SVG path data for custom shapes")


class TextElementIR(BaseElementIR):
    type: Literal["text"] = "text"
    text_content: TextContentIR = Field(default_factory=TextContentIR)


class ConnectorElementIR(BaseElementIR):
    type: Literal["connector"] = "connector"
    start_x: float = 0.0
    start_y: float = 0.0
    end_x: float = 100.0
    end_y: float = 100.0
    start_shape_id: Optional[str] = Field(None, description="Bound shape ID at start point")
    end_shape_id: Optional[str] = Field(None, description="Bound shape ID at end point")
    start_site_index: Optional[int] = Field(None, description="Connection site anchor index on start shape")
    end_site_index: Optional[int] = Field(None, description="Connection site anchor index on end shape")
    arrow_start: Literal["none", "triangle", "stealth", "oval"] = "none"
    arrow_end: Literal["none", "triangle", "stealth", "oval"] = "triangle"
    line_type: Literal["straight", "elbow", "curved"] = "straight"


class ImageElementIR(BaseElementIR):
    type: Literal["image"] = "image"
    src: str = Field("", description="Asset URL, relative path or data:image/*;base64")
    asset_id: Optional[str] = None
    alt_text: Optional[str] = None
    crop: Optional[Dict[str, float]] = Field(None, description="Normalized crop margins: {left, top, right, bottom}")


class TableCellIR(BaseModel):
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text_content: TextContentIR = Field(default_factory=TextContentIR)
    style: Optional[ElementStyleIR] = None


class TableElementIR(BaseElementIR):
    type: Literal["table"] = "table"
    rows: int = 2
    cols: int = 2
    cells: List[List[TableCellIR]] = Field(default_factory=list)


class GroupElementIR(BaseElementIR):
    """Hierarchical Group container preserving nested structure and coordinate system."""
    type: Literal["group"] = "group"
    children: List[ElementIR] = Field(default_factory=list)

    def add_child(self, child: ElementIR) -> ElementIR:
        self.children.append(child)
        return child

    def get_child(self, child_id: str) -> Optional[ElementIR]:
        for child in self.children:
            if child.id == child_id:
                return child
            if isinstance(child, GroupElementIR):
                sub = child.get_child(child_id)
                if sub:
                    return sub
        return None

    def all_children(self) -> List[ElementIR]:
        result = []
        for child in self.children:
            result.append(child)
            if isinstance(child, GroupElementIR):
                result.extend(child.all_children())
        return result

    @property
    def text_content(self) -> Optional[TextContentIR]:
        """Aggregate text content from children if any child has text."""
        child_paras = []
        for c in self.children:
            tc = getattr(c, "text_content", None)
            if tc and tc.paragraphs:
                child_paras.extend(tc.paragraphs)
        if child_paras:
            return TextContentIR(paragraphs=child_paras)
        return None


# Union type for polymorphic elements (including GroupElementIR)
ElementIR = Union[
    ShapeElementIR,
    TextElementIR,
    ConnectorElementIR,
    ImageElementIR,
    TableElementIR,
    GroupElementIR,
]


# =====================================================================
# Slide & Presentation Models
# =====================================================================

class SlideIR(BaseModel):
    id: str = Field(default_factory=lambda: f"slide_{uuid.uuid4().hex[:6]}")
    slide_num: int = 1
    title: Optional[str] = None
    width: int = Field(1280, description="Standard canvas width in px")
    height: int = Field(720, description="Standard canvas height in px")
    background: FillStyle = Field(default_factory=lambda: FillStyle(type="solid", color="#FFFFFF", alpha=1.0))
    elements: List[ElementIR] = Field(default_factory=list)
    notes: str = ""
    master: Optional[Dict[str, Any]] = Field(None, description="Master slide layout metadata")
    theme: Optional[Dict[str, Any]] = Field(None, description="Slide-level theme override")
    theme_ref: Optional[str] = Field(None, description="Reference to presentation theme")
    layout_name: Optional[str] = Field(None, description="OOXML layout name, e.g. Title and Content")

    def get_element(self, element_id: str) -> Optional[ElementIR]:
        """Search element by ID recursively across top-level elements and groups."""
        def _search(items: List[ElementIR]) -> Optional[ElementIR]:
            for el in items:
                if el.id == element_id:
                    return el
                if isinstance(el, GroupElementIR):
                    found = _search(el.children)
                    if found:
                        return found
            return None
        return _search(self.elements)

    def all_elements(self, recursive: bool = True) -> List[ElementIR]:
        """Return all elements. If recursive=True, includes children inside groups."""
        if not recursive:
            return list(self.elements)
        result: List[ElementIR] = []
        for el in self.elements:
            result.append(el)
            if isinstance(el, GroupElementIR):
                result.extend(el.all_children())
        return result

    def leaf_elements(self) -> List[ElementIR]:
        """Return only leaf elements (non-groups) across the entire hierarchy."""
        return [el for el in self.all_elements(recursive=True) if not isinstance(el, GroupElementIR)]

    def add_element(self, element: ElementIR) -> ElementIR:
        self.elements.append(element)
        return element

    def remove_element(self, element_id: str) -> bool:
        """Remove an element by ID, searching top-level elements and inside groups."""
        init_len = len(self.elements)
        self.elements = [el for el in self.elements if el.id != element_id]
        if len(self.elements) < init_len:
            return True

        # Search recursively within groups
        for el in self.elements:
            if isinstance(el, GroupElementIR):
                child_init = len(el.children)
                el.children = [c for c in el.children if c.id != element_id]
                if len(el.children) < child_init:
                    return True
                # Recursive group search
                for child in el.children:
                    if isinstance(child, GroupElementIR):
                        if self._remove_from_group(child, element_id):
                            return True
        return False

    def _remove_from_group(self, group: GroupElementIR, element_id: str) -> bool:
        child_init = len(group.children)
        group.children = [c for c in group.children if c.id != element_id]
        if len(group.children) < child_init:
            return True
        for child in group.children:
            if isinstance(child, GroupElementIR):
                if self._remove_from_group(child, element_id):
                    return True
        return False


class PresentationIR(BaseModel):
    id: str = Field(default_factory=lambda: f"pres_{uuid.uuid4().hex[:8]}")
    title: str = "PPT-Agent-Studio Presentation"
    width: int = 1280
    height: int = 720
    theme: Dict[str, Any] = Field(default_factory=lambda: {
        "name": "Modern Clean",
        "primary_color": "#2563EB",
        "secondary_color": "#0F172A",
        "background_color": "#FFFFFF",
        "card_background": "#F8FAFC",
        "font_heading": "Segoe UI",
        "font_body": "Segoe UI",
        "color_scheme": {
            "accent1": "#2563EB",
            "accent2": "#0EA5E9",
            "accent3": "#10B981",
            "accent4": "#F59E0B",
            "accent5": "#EF4444",
            "accent6": "#8B5CF6",
            "dk1": "#0F172A",
            "lt1": "#FFFFFF",
            "dk2": "#334155",
            "lt2": "#F8FAFC",
            "hlink": "#2563EB",
            "folHlink": "#7C3AED",
        },
        "font_scheme": {
            "major_font": "Segoe UI",
            "minor_font": "Segoe UI"
        }
    })
    master: Optional[Dict[str, Any]] = Field(None, description="Presentation-level master layout definitions")
    slides: List[SlideIR] = Field(default_factory=list)
    active_slide_id: Optional[str] = None
    version: int = 1
    assets: Dict[str, str] = Field(default_factory=dict, description="asset_id -> base64 or path")
    asset_metadata: Dict[str, Any] = Field(default_factory=dict, description="asset_id -> {mime_type, width, height, hash}")

    def get_slide(self, slide_id_or_num: Union[str, int]) -> Optional[SlideIR]:
        if isinstance(slide_id_or_num, int):
            for s in self.slides:
                if s.slide_num == slide_id_or_num:
                    return s
            if 0 <= slide_id_or_num < len(self.slides):
                return self.slides[slide_id_or_num]
        else:
            for s in self.slides:
                if s.id == slide_id_or_num:
                    return s
        return None

    def get_active_slide(self) -> Optional[SlideIR]:
        if self.active_slide_id:
            slide = self.get_slide(self.active_slide_id)
            if slide:
                return slide
        return self.slides[0] if self.slides else None


# Rebuild recursive models in Pydantic v2
BaseElementIR.model_rebuild()
GroupElementIR.model_rebuild()
SlideIR.model_rebuild()
PresentationIR.model_rebuild()
