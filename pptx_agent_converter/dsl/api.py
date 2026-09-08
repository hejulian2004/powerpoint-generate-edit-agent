"""DSL API for defining PPTX shapes, connectors, text, and slides."""

from __future__ import annotations
from typing import Optional, Tuple, Dict, Any, Union, List

from ..model.slide import Slide, SlideSize
from ..model.shape import (
    Position,
    ShapeElement,
    ConnectorElement,
    ImageElement,
    GroupElement
)
from ..model.style import Fill, Line, Shadow, Font, ParagraphStyle
from ..model.text import TextBlock, Paragraph, Run


class Shape:
    """DSL Shape definition."""

    def __init__(
        self,
        type: str = "roundRect",
        x: float = 0.0,
        y: float = 0.0,
        width: float = 2.0,
        height: float = 1.0,
        rotation: float = 0.0,
        radius: Optional[float] = None,
        style: Optional[Dict[str, Any]] = None,
        fill: Optional[Union[str, Dict[str, Any]]] = None,
        border: Optional[Union[str, Dict[str, Any], float]] = None,
        line: Optional[Union[str, Dict[str, Any], float]] = None,
        shadow: Optional[Union[bool, Dict[str, Any]]] = None,
        text: Optional[Union[str, Dict[str, Any], TextBlock]] = None,
        font: Optional[Dict[str, Any]] = None,
        paragraph: Optional[Dict[str, Any]] = None,
        name: str = ""
    ):
        self.type = type
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.rotation = rotation
        self.radius = radius
        self.style = style or {}
        self.name = name

        # Resolve fill
        raw_fill = fill or self.style.get("fill")
        if isinstance(raw_fill, str):
            self.fill = Fill(type="solid", color=raw_fill)
        elif isinstance(raw_fill, dict):
            self.fill = Fill.from_dict(raw_fill)
        elif raw_fill is None:
            self.fill = Fill(type="none")
        else:
            self.fill = Fill(type="none")

        # Resolve line / border
        raw_line = line or border or self.style.get("border") or self.style.get("line")
        if raw_line is not None:
            self.line = Line.from_dict(raw_line)
        else:
            self.line = None

        # Resolve shadow
        raw_shadow = shadow if shadow is not None else self.style.get("shadow")
        if raw_shadow is not None:
            self.shadow = Shadow.from_dict(raw_shadow)
        else:
            self.shadow = None

        # Resolve text
        self.text_block = None
        if isinstance(text, TextBlock):
            self.text_block = text
        elif isinstance(text, dict):
            self.text_block = TextBlock.from_dict(text)
        elif isinstance(text, str) and text:
            f = Font.from_dict(font or {}) if font else Font()
            p = ParagraphStyle.from_dict(paragraph or {}) if paragraph else ParagraphStyle()
            paragraphs = [Paragraph(runs=[Run(text=line_str, font=f)], style=p) for line_str in text.split("\n")]
            self.text_block = TextBlock(paragraphs=paragraphs, vertical_align=p.vertical)

    def to_element(self) -> ShapeElement:
        return ShapeElement(
            name=self.name,
            type="shape",
            shape_type=self.type,
            position=Position(x=self.x, y=self.y, width=self.width, height=self.height),
            rotation=self.rotation,
            fill=self.fill,
            line=self.line,
            shadow=self.shadow,
            radius=self.radius,
            text=self.text_block
        )


class Connector:
    """DSL Connector definition."""

    def __init__(
        self,
        start: Tuple[float, float] = (0.0, 0.0),
        end: Tuple[float, float] = (1.0, 1.0),
        arrow: str = "triangle",
        arrow_start: Optional[str] = None,
        arrow_end: Optional[str] = None,
        type: str = "straight",
        connector_type: Optional[str] = None,
        line: Optional[Union[Dict[str, Any], Line, str]] = None,
        color: str = "#333333",
        width: float = 1.5,
        start_shape_id: Optional[str] = None,
        end_shape_id: Optional[str] = None,
        name: str = ""
    ):
        self.start = (float(start[0]), float(start[1]))
        self.end = (float(end[0]), float(end[1]))
        self.arrow_end = arrow_end or arrow
        self.arrow_start = arrow_start
        self.connector_type = connector_type or type
        self.start_shape_id = start_shape_id
        self.end_shape_id = end_shape_id
        self.name = name

        if isinstance(line, Line):
            self.line = line
        elif isinstance(line, dict):
            self.line = Line.from_dict(line)
        elif isinstance(line, str):
            self.line = Line(color=line, width=width)
        else:
            self.line = Line(color=color, width=width)

    def to_element(self) -> ConnectorElement:
        return ConnectorElement(
            name=self.name,
            connector_type=self.connector_type,
            start=self.start,
            end=self.end,
            line=self.line,
            arrow_start=self.arrow_start,
            arrow_end=self.arrow_end,
            start_shape_id=self.start_shape_id,
            end_shape_id=self.end_shape_id
        )


class TextBox:
    """DSL TextBox definition."""

    def __init__(
        self,
        text: str,
        x: float = 0.0,
        y: float = 0.0,
        width: float = 3.0,
        height: float = 1.0,
        font_name: str = "Calibri",
        font_size: float = 14.0,
        color: str = "#000000",
        bold: bool = False,
        italic: bool = False,
        align: str = "left",
        vertical: str = "middle",
        name: str = ""
    ):
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.name = name
        self.text_block = TextBlock.from_simple_text(
            text=text,
            font_name=font_name,
            font_size=font_size,
            font_color=color,
            bold=bold,
            italic=italic,
            align=align,
            vertical=vertical
        )

    def to_element(self) -> ShapeElement:
        return ShapeElement(
            name=self.name,
            type="textbox",
            shape_type="rectangle",
            position=Position(x=self.x, y=self.y, width=self.width, height=self.height),
            fill=Fill(type="none"),
            line=None,
            text=self.text_block
        )


class Image:
    """DSL Image definition."""

    def __init__(
        self,
        src: str,
        x: float = 0.0,
        y: float = 0.0,
        width: float = 3.0,
        height: float = 2.0,
        rotation: float = 0.0,
        name: str = ""
    ):
        self.src = src
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.rotation = rotation
        self.name = name

    def to_element(self) -> ImageElement:
        return ImageElement(
            name=self.name,
            position=Position(x=self.x, y=self.y, width=self.width, height=self.height),
            src=self.src,
            rotation=self.rotation
        )


def add_shape(slide: Slide, shape: Union[Shape, ShapeElement]) -> ShapeElement:
    """Adds a shape to a slide."""
    elem = shape.to_element() if isinstance(shape, Shape) else shape
    slide.elements.append(elem)
    return elem


def add_connector(
    slide: Slide,
    connector: Optional[Union[Connector, ConnectorElement]] = None,
    **kwargs
) -> ConnectorElement:
    """Adds a connector to a slide. Supports passing Connector instance or direct kwargs."""
    if connector is not None:
        elem = connector.to_element() if isinstance(connector, Connector) else connector
    else:
        conn_obj = Connector(**kwargs)
        elem = conn_obj.to_element()
    slide.elements.append(elem)
    return elem


def add_textbox(
    slide: Slide,
    textbox: Optional[Union[TextBox, ShapeElement]] = None,
    **kwargs
) -> ShapeElement:
    """Adds a textbox to a slide."""
    if textbox is not None:
        elem = textbox.to_element() if isinstance(textbox, TextBox) else textbox
    else:
        tb_obj = TextBox(**kwargs)
        elem = tb_obj.to_element()
    slide.elements.append(elem)
    return elem


def add_image(
    slide: Slide,
    image: Optional[Union[Image, ImageElement]] = None,
    **kwargs
) -> ImageElement:
    """Adds an image to a slide."""
    if image is not None:
        elem = image.to_element() if isinstance(image, Image) else image
    else:
        img_obj = Image(**kwargs)
        elem = img_obj.to_element()
    slide.elements.append(elem)
    return elem


def create_slide(slide_id: int = 1, width: float = 13.333, height: float = 7.5) -> Slide:
    """Creates a new empty Slide."""
    return Slide(slide_id=slide_id, slide_num=slide_id, size=SlideSize(width=width, height=height))
