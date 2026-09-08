"""Style models for PPTX shapes, lines, fills, fonts, and effects."""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class Color:
    """Represents a color with optional alpha transparency and theme scheme mapping."""
    hex: str = "#000000"  # e.g. #3366FF
    alpha: float = 100.0   # 0 to 100 percent
    scheme_name: Optional[str] = None  # e.g. 'accent1', 'tx1', 'bg1'

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"hex": self.hex, "alpha": self.alpha}
        if self.scheme_name:
            data["scheme_name"] = self.scheme_name
        return data

    @classmethod
    def from_dict(cls, d: Dict[str, Any] | str) -> Color:
        if isinstance(d, str):
            return cls(hex=d)
        return cls(
            hex=d.get("hex", d.get("color", "#000000")),
            alpha=float(d.get("alpha", 100.0)),
            scheme_name=d.get("scheme_name")
        )


@dataclass
class GradientStop:
    position: float  # 0.0 to 1.0
    color: str       # Hex color
    alpha: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {"position": self.position, "color": self.color, "alpha": self.alpha}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GradientStop:
        return cls(
            position=float(d.get("position", 0.0)),
            color=d.get("color", "#000000"),
            alpha=float(d.get("alpha", 100.0))
        )


@dataclass
class Fill:
    """Fill style: solid, gradient, none, or picture."""
    type: str = "solid"  # "solid", "gradient", "none", "pattern", "picture"
    color: Optional[str] = None  # Hex color for solid
    alpha: float = 100.0  # Transparency: 100 = opaque, 0 = fully transparent
    angle: Optional[float] = None  # Gradient angle in degrees
    stops: List[GradientStop] = field(default_factory=list)  # For gradient
    scheme_color: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"type": self.type}
        if self.color is not None:
            res["color"] = self.color
        if self.alpha != 100.0:
            res["alpha"] = round(self.alpha, 2)
        if self.angle is not None:
            res["angle"] = self.angle
        if self.stops:
            res["stops"] = [s.to_dict() for s in self.stops]
        if self.scheme_color:
            res["scheme_color"] = self.scheme_color
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any] | str) -> Fill:
        if isinstance(d, str):
            return cls(type="solid", color=d)
        stops = [GradientStop.from_dict(s) for s in d.get("stops", [])]
        return cls(
            type=d.get("type", "solid"),
            color=d.get("color"),
            alpha=float(d.get("alpha", 100.0)),
            angle=float(d.get("angle")) if d.get("angle") is not None else None,
            stops=stops,
            scheme_color=d.get("scheme_color")
        )


@dataclass
class Line:
    """Border or connector stroke style."""
    color: Optional[str] = "#000000"
    width: float = 1.0  # in pt
    alpha: float = 100.0
    style: str = "solid"  # "solid", "dash", "dot", "dashDot"
    arrow_start: Optional[str] = None  # "none", "triangle", "stealth", "oval", "diamond"
    arrow_end: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {}
        if self.color:
            res["color"] = self.color
        res["width"] = round(self.width, 2)
        if self.alpha != 100.0:
            res["alpha"] = round(self.alpha, 2)
        if self.style != "solid":
            res["style"] = self.style
        if self.arrow_start:
            res["arrow_start"] = self.arrow_start
        if self.arrow_end:
            res["arrow_end"] = self.arrow_end
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any] | str | float) -> Line:
        if isinstance(d, (int, float)):
            return cls(width=float(d))
        if isinstance(d, str):
            return cls(color=d)
        return cls(
            color=d.get("color", "#000000"),
            width=float(d.get("width", 1.0)),
            alpha=float(d.get("alpha", 100.0)),
            style=d.get("style", "solid"),
            arrow_start=d.get("arrow_start"),
            arrow_end=d.get("arrow_end")
        )


@dataclass
class Shadow:
    """Shadow effect."""
    enabled: bool = False
    color: str = "#000000"
    alpha: float = 40.0
    blur: float = 4.0        # pt
    distance: float = 3.0    # pt
    direction: float = 45.0  # degrees

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"enabled": self.enabled}
        if self.enabled:
            res["color"] = self.color
            res["alpha"] = round(self.alpha, 2)
            res["blur"] = round(self.blur, 2)
            res["distance"] = round(self.distance, 2)
            res["direction"] = round(self.direction, 2)
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any] | bool) -> Shadow:
        if isinstance(d, bool):
            return cls(enabled=d)
        return cls(
            enabled=d.get("enabled", True),
            color=d.get("color", "#000000"),
            alpha=float(d.get("alpha", 40.0)),
            blur=float(d.get("blur", 4.0)),
            distance=float(d.get("distance", 3.0)),
            direction=float(d.get("direction", 45.0))
        )


@dataclass
class Font:
    """Font styling."""
    name: str = "Calibri"
    size: float = 14.0  # pt
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    color: str = "#000000"
    alpha: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "size": round(self.size, 1),
            "bold": self.bold,
            "italic": self.italic,
            "color": self.color,
            **( {"underline": True} if self.underline else {} ),
            **( {"strike": True} if self.strike else {} ),
            **( {"alpha": round(self.alpha, 2)} if self.alpha != 100.0 else {} )
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Font:
        return cls(
            name=d.get("name", "Calibri"),
            size=float(d.get("size", 14.0)),
            bold=bool(d.get("bold", False)),
            italic=bool(d.get("italic", False)),
            underline=bool(d.get("underline", False)),
            strike=bool(d.get("strike", False)),
            color=d.get("color", "#000000"),
            alpha=float(d.get("alpha", 100.0))
        )


@dataclass
class ParagraphStyle:
    """Paragraph alignment and spacing."""
    align: str = "left"        # "left", "center", "right", "justify"
    vertical: str = "middle"   # "top", "middle", "bottom"
    line_spacing: Optional[float] = None
    space_before: Optional[float] = None
    space_after: Optional[float] = None
    margin_left: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"align": self.align, "vertical": self.vertical}
        if self.line_spacing is not None:
            res["line_spacing"] = self.line_spacing
        if self.space_before is not None:
            res["space_before"] = self.space_before
        if self.space_after is not None:
            res["space_after"] = self.space_after
        if self.margin_left is not None:
            res["margin_left"] = self.margin_left
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ParagraphStyle:
        return cls(
            align=d.get("align", "left"),
            vertical=d.get("vertical", "middle"),
            line_spacing=d.get("line_spacing"),
            space_before=d.get("space_before"),
            space_after=d.get("space_after"),
            margin_left=d.get("margin_left")
        )
