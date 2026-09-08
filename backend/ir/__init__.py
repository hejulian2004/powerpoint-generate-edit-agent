"""PPT-IR Core module exports."""

from .models import (
    PresentationIR,
    SlideIR,
    ElementIR,
    ShapeElementIR,
    TextElementIR,
    ConnectorElementIR,
    ImageElementIR,
    TableElementIR,
    ElementStyleIR,
    FillStyle,
    BorderStyle,
    ShadowStyle,
    GradientFill,
    GradientStop,
    TextContentIR,
    ParagraphIR,
    RunIR,
    FontIR,
)
from .converter import PPTIRConverter
from .patch import PatchRecord, HistoryManager
from .svg_renderer import SVGRenderer

__all__ = [
    "PresentationIR",
    "SlideIR",
    "ElementIR",
    "ShapeElementIR",
    "TextElementIR",
    "ConnectorElementIR",
    "ImageElementIR",
    "TableElementIR",
    "ElementStyleIR",
    "FillStyle",
    "BorderStyle",
    "ShadowStyle",
    "GradientFill",
    "GradientStop",
    "TextContentIR",
    "ParagraphIR",
    "RunIR",
    "FontIR",
    "PPTIRConverter",
    "PatchRecord",
    "HistoryManager",
    "SVGRenderer",
]
