"""Slide and Presentation models."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
from .style import Fill
from .shape import (
    BaseElement,
    ShapeElement,
    ConnectorElement,
    ImageElement,
    GroupElement,
    Position
)

# Standard 16:9 widescreen dimensions in inches
DEFAULT_WIDTH = 13.333
DEFAULT_HEIGHT = 7.5


@dataclass
class SlideSize:
    """Slide dimensions in inches."""
    width: float = DEFAULT_WIDTH
    height: float = DEFAULT_HEIGHT

    def to_dict(self) -> Dict[str, float]:
        return {
            "width": round(self.width, 3),
            "height": round(self.height, 3)
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SlideSize:
        return cls(
            width=float(d.get("width", DEFAULT_WIDTH)),
            height=float(d.get("height", DEFAULT_HEIGHT))
        )


@dataclass
class ThemeInfo:
    """Theme color and font scheme."""
    name: str = "Office Theme"
    color_scheme: Dict[str, str] = field(default_factory=dict)
    font_scheme: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "color_scheme": self.color_scheme,
            "font_scheme": self.font_scheme
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ThemeInfo:
        return cls(
            name=d.get("name", "Office Theme"),
            color_scheme=d.get("color_scheme", {}),
            font_scheme=d.get("font_scheme", {})
        )


@dataclass
class Slide:
    """Represents a single slide in a presentation."""
    slide_id: int = 1
    slide_num: int = 1
    size: SlideSize = field(default_factory=SlideSize)
    background: Optional[Fill] = None
    elements: List[Union[ShapeElement, ConnectorElement, ImageElement, GroupElement]] = field(default_factory=list)
    layout_name: Optional[str] = None
    xml_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "slide_id": self.slide_id,
            "size": self.size.to_dict(),
        }
        if self.background:
            res["background"] = self.background.to_dict()
        res["elements"] = [elem.to_dict() for elem in self.elements]
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Slide:
        slide_id = int(d.get("slide_id", 1))
        size = SlideSize.from_dict(d.get("size", {}))
        bg = Fill.from_dict(d["background"]) if "background" in d else None
        
        elements = []
        for elem_data in d.get("elements", []):
            elem_type = elem_data.get("type", "shape")
            if elem_type == "connector":
                elements.append(ConnectorElement.from_dict(elem_data))
            elif elem_type == "image":
                elements.append(ImageElement.from_dict(elem_data))
            elif elem_type == "group":
                elements.append(GroupElement.from_dict(elem_data))
            else:
                elements.append(ShapeElement.from_dict(elem_data))
                
        return cls(
            slide_id=slide_id,
            slide_num=slide_id,
            size=size,
            background=bg,
            elements=elements
        )


@dataclass
class Presentation:
    """Represents an entire presentation."""
    name: str = "Presentation"
    size: SlideSize = field(default_factory=SlideSize)
    theme: ThemeInfo = field(default_factory=ThemeInfo)
    slides: List[Slide] = field(default_factory=list)
    media_files: Dict[str, bytes] = field(default_factory=dict)  # filename -> bytes
    theme_raw_bytes: Optional[bytes] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "presentation_name": self.name,
            "size": self.size.to_dict(),
            "slides_count": len(self.slides),
            "theme": self.theme.to_dict(),
            "slides": [
                {
                    "slide_id": s.slide_id,
                    "slide_file": f"slides/slide_{s.slide_id:02d}.json",
                    "elements_count": len(s.elements)
                }
                for s in self.slides
            ]
        }
