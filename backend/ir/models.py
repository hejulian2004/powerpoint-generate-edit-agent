"""PPT-IR (Presentation Intermediate Representation) Data Models.

The canonical representation used across Agent reasoning, SVG/HTML rendering,
Web editing, and bi-directional OOXML conversion.
Standard canvas dimensions: 1280 x 720 (16:9 ViewBox).
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field
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
    type: Literal["none", "solid", "gradient"] = "solid"
    color: Optional[str] = Field("#3B82F6", description="Hex color")
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    gradient: Optional[GradientFill] = None


class BorderStyle(BaseModel):
    color: Optional[str] = Field("#1E293B", description="Border color")
    width: float = Field(1.0, ge=0.0, description="Border width in px")
    style: Literal["solid", "dashed", "dotted", "none"] = "solid"
    alpha: float = Field(1.0, ge=0.0, le=1.0)


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


class RunIR(BaseModel):
    text: str = ""
    font: Optional[FontIR] = None


class ParagraphIR(BaseModel):
    align: Literal["left", "center", "right", "justify"] = "left"
    vertical_align: Literal["top", "middle", "bottom"] = "top"
    line_spacing: float = Field(1.2, description="Line height multiplier")
    space_before: float = 0.0
    space_after: float = 0.0
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
    def from_plain_text(cls, text: str, font: Optional[FontIR] = None, align: Literal["left", "center", "right", "justify"] = "left") -> TextContentIR:
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
    z_index: int = Field(0, description="Stacking order")
    locked: bool = False
    style: ElementStyleIR = Field(default_factory=ElementStyleIR)


class ShapeElementIR(BaseElementIR):
    type: Literal["shape"] = "shape"
    shape_type: str = Field("roundRect", description="rectangle, roundRect, ellipse, diamond, triangle, rightArrow, callout, star")
    text_content: Optional[TextContentIR] = None


class TextElementIR(BaseElementIR):
    type: Literal["text"] = "text"
    text_content: TextContentIR = Field(default_factory=TextContentIR)


class ConnectorElementIR(BaseElementIR):
    type: Literal["connector"] = "connector"
    start_x: float = 0.0
    start_y: float = 0.0
    end_x: float = 100.0
    end_y: float = 100.0
    arrow_start: Literal["none", "triangle", "stealth", "oval"] = "none"
    arrow_end: Literal["none", "triangle", "stealth", "oval"] = "triangle"
    line_type: Literal["straight", "elbow", "curved"] = "straight"


class ImageElementIR(BaseElementIR):
    type: Literal["image"] = "image"
    src: str = Field("", description="Asset URL, relative path or data:image/*;base64")
    asset_id: Optional[str] = None
    alt_text: Optional[str] = None


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


# Union type for polymorphic elements
ElementIR = Union[
    ShapeElementIR,
    TextElementIR,
    ConnectorElementIR,
    ImageElementIR,
    TableElementIR,
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

    def get_element(self, element_id: str) -> Optional[ElementIR]:
        for el in self.elements:
            if el.id == element_id:
                return el
        return None

    def add_element(self, element: ElementIR) -> ElementIR:
        self.elements.append(element)
        return element

    def remove_element(self, element_id: str) -> bool:
        init_len = len(self.elements)
        self.elements = [el for el in self.elements if el.id != element_id]
        return len(self.elements) < init_len


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
        "font_body": "Segoe UI"
    })
    slides: List[SlideIR] = Field(default_factory=list)
    active_slide_id: Optional[str] = None
    version: int = 1
    assets: Dict[str, str] = Field(default_factory=dict, description="asset_id -> base64 or path")

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
