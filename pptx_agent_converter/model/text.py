"""Text models for runs, paragraphs, and text blocks."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from .style import Font, ParagraphStyle


@dataclass
class Run:
    """A text run with uniform formatting."""
    text: str = ""
    font: Font = field(default_factory=Font)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "font": self.font.to_dict()
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Run:
        return cls(
            text=d.get("text", ""),
            font=Font.from_dict(d.get("font", {}))
        )


@dataclass
class Paragraph:
    """A paragraph consisting of runs and styling."""
    runs: List[Run] = field(default_factory=list)
    style: ParagraphStyle = field(default_factory=ParagraphStyle)
    bullet: Optional[str] = None

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "runs": [r.to_dict() for r in self.runs],
            "style": self.style.to_dict()
        }
        if self.bullet:
            res["bullet"] = self.bullet
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Paragraph:
        runs = [Run.from_dict(r) for r in d.get("runs", [])]
        style = ParagraphStyle.from_dict(d.get("style", {}))
        return cls(runs=runs, style=style, bullet=d.get("bullet"))


@dataclass
class TextBlock:
    """Represents the complete text content of a shape or textbox."""
    paragraphs: List[Paragraph] = field(default_factory=list)
    vertical_align: str = "middle"  # "top", "middle", "bottom"
    word_wrap: bool = True
    margin_left: float = 0.1   # inches
    margin_right: float = 0.1  # inches
    margin_top: float = 0.05   # inches
    margin_bottom: float = 0.05 # inches

    @property
    def content(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def primary_font(self) -> Font:
        for p in self.paragraphs:
            for r in p.runs:
                if r.font:
                    return r.font
        return Font()

    @property
    def primary_paragraph_style(self) -> ParagraphStyle:
        if self.paragraphs:
            style = self.paragraphs[0].style
            style.vertical = self.vertical_align
            return style
        return ParagraphStyle(vertical=self.vertical_align)

    def to_dict(self) -> Dict[str, Any]:
        """Output clean format aligned with prompt requirement."""
        res: Dict[str, Any] = {
            "content": self.content,
            "font": self.primary_font.to_dict(),
            "paragraph": self.primary_paragraph_style.to_dict(),
        }
        # If there are multiple paragraphs or multiple runs with differing styles, include rich structure
        if len(self.paragraphs) > 1 or any(len(p.runs) > 1 for p in self.paragraphs):
            res["paragraphs"] = [p.to_dict() for p in self.paragraphs]
        return res

    @classmethod
    def from_dict(cls, d: Dict[str, Any] | str) -> TextBlock:
        if isinstance(d, str):
            tb = TextBlock()
            tb.paragraphs = [Paragraph(runs=[Run(text=d, font=Font())])]
            return tb

        paragraphs: List[Paragraph] = []
        if "paragraphs" in d and isinstance(d["paragraphs"], list):
            paragraphs = [Paragraph.from_dict(p) for p in d["paragraphs"]]
        elif "content" in d:
            content = d["content"]
            font_data = d.get("font", {})
            font = Font.from_dict(font_data)
            para_data = d.get("paragraph", {})
            para_style = ParagraphStyle.from_dict(para_data)
            
            lines = content.split("\n")
            for line in lines:
                p = Paragraph(runs=[Run(text=line, font=font)], style=para_style)
                paragraphs.append(p)

        vertical = "middle"
        if "paragraph" in d and "vertical" in d["paragraph"]:
            vertical = d["paragraph"]["vertical"]

        return cls(
            paragraphs=paragraphs,
            vertical_align=vertical,
            word_wrap=d.get("word_wrap", True)
        )

    @classmethod
    def from_simple_text(
        cls,
        text: str,
        font_name: str = "Calibri",
        font_size: float = 14.0,
        font_color: str = "#000000",
        bold: bool = False,
        italic: bool = False,
        align: str = "left",
        vertical: str = "middle"
    ) -> TextBlock:
        font = Font(name=font_name, size=font_size, color=font_color, bold=bold, italic=italic)
        style = ParagraphStyle(align=align, vertical=vertical)
        paragraphs = [Paragraph(runs=[Run(text=line, font=font)], style=style) for line in text.split("\n")]
        return cls(paragraphs=paragraphs, vertical_align=vertical)
