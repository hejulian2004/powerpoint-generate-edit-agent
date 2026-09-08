"""Bidirectional converter between PPT-IR and pptx_agent_converter models.

Enables seamless lossless translation between:
- Standard 1280x720 ViewBox Pixel Canvas (PPT-IR)
- Physical Inch/EMU/OOXML Representation (pptx_agent_converter.model)
"""

from __future__ import annotations
import base64
from typing import Optional, Dict, Any, List, Tuple
from pptx_agent_converter.model.slide import (
    Presentation, Slide, SlideSize, ThemeInfo,
    DEFAULT_WIDTH, DEFAULT_HEIGHT
)
from pptx_agent_converter.model.shape import (
    ShapeElement, ConnectorElement, ImageElement, GroupElement, Position
)
from pptx_agent_converter.model.style import (
    Fill, Line, Shadow, GradientStop as OOXMLGradientStop
)
from pptx_agent_converter.model.text import (
    TextBlock, Paragraph as OOXMLParagraph, Run as OOXMLRun, Font as OOXMLFont, ParagraphStyle
)

from .models import (
    PresentationIR, SlideIR, ElementIR,
    ShapeElementIR, TextElementIR, ConnectorElementIR, ImageElementIR, TableElementIR,
    ElementStyleIR, FillStyle, BorderStyle, ShadowStyle, GradientFill, GradientStop,
    TextContentIR, ParagraphIR, RunIR, FontIR
)


# Standard 96 DPI coordinate scaling factors
# 1280 / 13.33333333 ≈ 96.0 px/inch; 720 / 7.5 = 96.0 px/inch
DPI = 96.0
PT_TO_PX = 96.0 / 72.0  # 1.333333
PX_TO_PT = 72.0 / 96.0  # 0.75


class PPTIRConverter:
    """High-fidelity bidirectional converter."""

    # -----------------------------------------------------------------
    # OOXML Model -> PPT-IR
    # -----------------------------------------------------------------

    @classmethod
    def presentation_to_ir(cls, pres: Presentation) -> PresentationIR:
        w_in = pres.size.width if pres.size.width > 0 else DEFAULT_WIDTH
        h_in = pres.size.height if pres.size.height > 0 else DEFAULT_HEIGHT
        
        # Calculate scale ratio to map to 1280x720 standard canvas
        scale_x = 1280.0 / w_in
        scale_y = 720.0 / h_in

        slides_ir: List[SlideIR] = []
        for s in pres.slides:
            slides_ir.append(cls.slide_to_ir(s, scale_x, scale_y))

        # Transfer media assets
        assets: Dict[str, str] = {}
        for fname, bdata in pres.media_files.items():
            b64_str = base64.b64encode(bdata).decode("utf-8")
            ext = fname.split(".")[-1].lower() if "." in fname else "png"
            mime = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
            assets[fname] = f"data:{mime};base64,{b64_str}"

        theme_data = pres.theme.to_dict() if pres.theme else {}

        return PresentationIR(
            id=f"pres_{abs(hash(pres.name)) % 1000000:06d}",
            title=pres.name or "Converted Presentation",
            width=1280,
            height=720,
            theme=theme_data,
            slides=slides_ir,
            active_slide_id=slides_ir[0].id if slides_ir else None,
            version=1,
            assets=assets
        )

    @classmethod
    def slide_to_ir(cls, slide: Slide, scale_x: float = DPI, scale_y: float = DPI) -> SlideIR:
        elements_ir: List[ElementIR] = []
        for el in slide.elements:
            if isinstance(el, GroupElement):
                cls._flatten_group_to_ir(el, elements_ir, scale_x, scale_y)
            else:
                ir_el = cls.element_to_ir(el, scale_x, scale_y)
                if ir_el:
                    elements_ir.append(ir_el)

        bg_style = FillStyle(type="solid", color="#FFFFFF", alpha=1.0)
        if slide.background:
            bg_style = cls._fill_to_ir(slide.background)

        return SlideIR(
            id=f"slide_{slide.slide_id:02d}",
            slide_num=slide.slide_num,
            title=f"Slide {slide.slide_num}",
            width=1280,
            height=720,
            background=bg_style,
            elements=elements_ir
        )

    @classmethod
    def element_to_ir(cls, elem: Any, scale_x: float = DPI, scale_y: float = DPI) -> Optional[ElementIR]:
        if isinstance(elem, ConnectorElement):
            sx = round(elem.start[0] * scale_x, 2)
            sy = round(elem.start[1] * scale_y, 2)
            ex = round(elem.end[0] * scale_x, 2)
            ey = round(elem.end[1] * scale_y, 2)
            
            x = min(sx, ex)
            y = min(sy, ey)
            w = max(abs(ex - sx), 1.0)
            h = max(abs(ey - sy), 1.0)

            border = cls._line_to_ir(elem.line)

            return ConnectorElementIR(
                id=elem.id or f"conn_{uuid_short()}",
                name=elem.name or "Connector",
                x=x,
                y=y,
                width=w,
                height=h,
                start_x=sx,
                start_y=sy,
                end_x=ex,
                end_y=ey,
                arrow_start=elem.arrow_start if elem.arrow_start in ["none", "triangle", "stealth", "oval"] else "none",
                arrow_end=elem.arrow_end if elem.arrow_end in ["none", "triangle", "stealth", "oval"] else "triangle",
                line_type=elem.connector_type if elem.connector_type in ["straight", "elbow", "curved"] else "straight",
                style=ElementStyleIR(border=border)
            )

        elif isinstance(elem, ImageElement):
            x = round(elem.position.x * scale_x, 2)
            y = round(elem.position.y * scale_y, 2)
            w = round(elem.position.width * scale_x, 2)
            h = round(elem.position.height * scale_y, 2)

            return ImageElementIR(
                id=elem.id or f"img_{uuid_short()}",
                name=elem.name or "Image",
                x=x,
                y=y,
                width=w,
                height=h,
                rotation=elem.rotation,
                src=elem.src,
                asset_id=elem.original_name,
                style=ElementStyleIR()
            )

        elif isinstance(elem, ShapeElement):
            x = round(elem.position.x * scale_x, 2)
            y = round(elem.position.y * scale_y, 2)
            w = round(elem.position.width * scale_x, 2)
            h = round(elem.position.height * scale_y, 2)

            fill = cls._fill_to_ir(elem.fill) if elem.fill else None
            border = cls._line_to_ir(elem.line) if elem.line else None
            shadow = cls._shadow_to_ir(elem.shadow) if elem.shadow else None

            text_content = None
            if elem.text and elem.text.content:
                text_content = cls._text_block_to_ir(elem.text)

            # Distinguish pure textbox vs shape
            if elem.shape_type in ["textbox", "text"] or (not fill and not border and text_content):
                return TextElementIR(
                    id=elem.id or f"txt_{uuid_short()}",
                    name=elem.name or "TextBox",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    rotation=elem.rotation,
                    text_content=text_content or TextContentIR(),
                    style=ElementStyleIR(fill=fill, border=border, shadow=shadow)
                )

            return ShapeElementIR(
                id=elem.id or f"shape_{uuid_short()}",
                name=elem.name or "Shape",
                shape_type=elem.shape_type or "roundRect",
                x=x,
                y=y,
                width=w,
                height=h,
                rotation=elem.rotation,
                text_content=text_content,
                style=ElementStyleIR(
                    fill=fill,
                    border=border,
                    shadow=shadow,
                    radius=elem.radius if elem.radius is not None else 0.0
                )
            )

        elif isinstance(elem, GroupElement):
            # Flatten group elements for simple IR manipulation
            # or treat as grouped shape
            children = []
            for child in elem.elements:
                ir_child = cls.element_to_ir(child, scale_x, scale_y)
                if ir_child:
                    children.append(ir_child)
            # return first child or shape
            return children[0] if children else None

        return None

    @classmethod
    def _flatten_group_to_ir(cls, grp: GroupElement, acc: List[ElementIR], scale_x: float, scale_y: float):
        """Recursively unwraps group elements into flat IR elements."""
        for child in grp.elements:
            if isinstance(child, GroupElement):
                cls._flatten_group_to_ir(child, acc, scale_x, scale_y)
            else:
                ir_child = cls.element_to_ir(child, scale_x, scale_y)
                if ir_child:
                    acc.append(ir_child)

    # -----------------------------------------------------------------
    # PPT-IR -> OOXML Model
    # -----------------------------------------------------------------

    @classmethod
    def ir_to_presentation(cls, pres_ir: PresentationIR) -> Presentation:
        w_in = DEFAULT_WIDTH  # 13.333
        h_in = DEFAULT_HEIGHT  # 7.5
        scale_x = 1280.0 / w_in
        scale_y = 720.0 / h_in

        slides: List[Slide] = []
        for idx, s_ir in enumerate(pres_ir.slides):
            slides.append(cls.ir_to_slide(s_ir, idx + 1, scale_x, scale_y))

        # Media files reconstruction from assets dict
        media_files: Dict[str, bytes] = {}
        for aid, data_uri in pres_ir.assets.items():
            if "," in data_uri:
                b64_part = data_uri.split(",", 1)[1]
                try:
                    media_files[aid] = base64.b64decode(b64_part)
                except Exception:
                    pass

        return Presentation(
            name=pres_ir.title,
            size=SlideSize(width=w_in, height=h_in),
            theme=ThemeInfo.from_dict(pres_ir.theme),
            slides=slides,
            media_files=media_files
        )

    @classmethod
    def ir_to_slide(cls, s_ir: SlideIR, slide_num: int = 1, scale_x: float = DPI, scale_y: float = DPI) -> Slide:
        elements: List[Any] = []
        for el in s_ir.elements:
            elem = cls.ir_to_element(el, scale_x, scale_y)
            if elem:
                elements.append(elem)

        bg = cls._ir_to_fill(s_ir.background) if s_ir.background else None

        return Slide(
            slide_id=slide_num,
            slide_num=slide_num,
            size=SlideSize(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT),
            background=bg,
            elements=elements
        )

    @classmethod
    def ir_to_element(cls, el: ElementIR, scale_x: float = DPI, scale_y: float = DPI) -> Optional[Any]:
        if isinstance(el, ConnectorElementIR):
            return ConnectorElement(
                id=el.id,
                name=el.name or "Connector",
                connector_type=el.line_type,
                start=(el.start_x / scale_x, el.start_y / scale_y),
                end=(el.end_x / scale_x, el.end_y / scale_y),
                line=cls._ir_to_line(el.style.border) if el.style.border else Line(),
                arrow_start=el.arrow_start if el.arrow_start != "none" else None,
                arrow_end=el.arrow_end if el.arrow_end != "none" else None
            )

        elif isinstance(elem := el, ImageElementIR):
            return ImageElement(
                id=elem.id,
                name=elem.name or "Image",
                position=Position(
                    x=elem.x / scale_x,
                    y=elem.y / scale_y,
                    width=elem.width / scale_x,
                    height=elem.height / scale_y
                ),
                src=elem.src,
                original_name=elem.asset_id or "image.png",
                rotation=elem.rotation
            )

        elif isinstance(elem := el, TextElementIR):
            text_block = cls._ir_to_text_block(elem.text_content)
            return ShapeElement(
                id=elem.id,
                name=elem.name or "TextBox",
                shape_type="textbox",
                position=Position(
                    x=elem.x / scale_x,
                    y=elem.y / scale_y,
                    width=elem.width / scale_x,
                    height=elem.height / scale_y
                ),
                rotation=elem.rotation,
                fill=cls._ir_to_fill(elem.style.fill) if elem.style.fill else Fill(type="none"),
                line=cls._ir_to_line(elem.style.border) if elem.style.border else None,
                shadow=cls._ir_to_shadow(elem.style.shadow) if elem.style.shadow else None,
                text=text_block
            )

        elif isinstance(elem := el, ShapeElementIR):
            text_block = cls._ir_to_text_block(elem.text_content) if elem.text_content else None
            return ShapeElement(
                id=elem.id,
                name=elem.name or "Shape",
                shape_type=elem.shape_type,
                position=Position(
                    x=elem.x / scale_x,
                    y=elem.y / scale_y,
                    width=elem.width / scale_x,
                    height=elem.height / scale_y
                ),
                rotation=elem.rotation,
                fill=cls._ir_to_fill(elem.style.fill) if elem.style.fill else Fill(type="solid", color="#3B82F6"),
                line=cls._ir_to_line(elem.style.border) if elem.style.border else None,
                shadow=cls._ir_to_shadow(elem.style.shadow) if elem.style.shadow else None,
                radius=elem.style.radius if elem.style.radius > 0 else None,
                text=text_block
            )

        return None

    # -----------------------------------------------------------------
    # Helper mapping functions
    # -----------------------------------------------------------------

    @classmethod
    def _fill_to_ir(cls, fill: Fill) -> FillStyle:
        if fill.type == "gradient" and fill.stops:
            stops = [
                GradientStop(
                    position=s.position,
                    color=s.color,
                    alpha=s.alpha / 100.0
                )
                for s in fill.stops
            ]
            return FillStyle(
                type="gradient",
                alpha=fill.alpha / 100.0,
                gradient=GradientFill(
                    type="linear",
                    angle=fill.angle if fill.angle is not None else 90.0,
                    stops=stops
                )
            )
        elif fill.type == "solid":
            return FillStyle(
                type="solid",
                color=fill.color or "#3B82F6",
                alpha=fill.alpha / 100.0
            )
        else:
            return FillStyle(type="none", alpha=0.0)

    @classmethod
    def _ir_to_fill(cls, f_ir: FillStyle) -> Fill:
        if f_ir.type == "gradient" and f_ir.gradient:
            stops = [
                OOXMLGradientStop(
                    position=s.position,
                    color=s.color,
                    alpha=s.alpha * 100.0
                )
                for s in f_ir.gradient.stops
            ]
            return Fill(
                type="gradient",
                alpha=f_ir.alpha * 100.0,
                angle=f_ir.gradient.angle,
                stops=stops
            )
        elif f_ir.type == "solid":
            return Fill(
                type="solid",
                color=f_ir.color or "#3B82F6",
                alpha=f_ir.alpha * 100.0
            )
        return Fill(type="none")

    @classmethod
    def _line_to_ir(cls, line: Line) -> BorderStyle:
        return BorderStyle(
            color=line.color or "#1E293B",
            width=round(line.width * PT_TO_PX, 1) if line.width else 1.0,
            style=line.style if line.style in ["solid", "dashed", "dotted", "none"] else "solid",
            alpha=line.alpha / 100.0 if line.alpha is not None else 1.0
        )

    @classmethod
    def _ir_to_line(cls, b_ir: BorderStyle) -> Line:
        return Line(
            color=b_ir.color or "#1E293B",
            width=round(b_ir.width * PX_TO_PT, 2),
            style=b_ir.style,
            alpha=b_ir.alpha * 100.0
        )

    @classmethod
    def _shadow_to_ir(cls, shadow: Shadow) -> ShadowStyle:
        direction = getattr(shadow, "direction", getattr(shadow, "angle", 45.0))
        return ShadowStyle(
            enabled=shadow.enabled,
            color=shadow.color or "#000000",
            blur=round(shadow.blur * PT_TO_PX, 1),
            angle=direction,
            distance=round(shadow.distance * PT_TO_PX, 1),
            alpha=shadow.alpha / 100.0
        )

    @classmethod
    def _ir_to_shadow(cls, s_ir: ShadowStyle) -> Shadow:
        return Shadow(
            enabled=s_ir.enabled,
            color=s_ir.color,
            blur=round(s_ir.blur * PX_TO_PT, 2),
            direction=s_ir.angle,
            distance=round(s_ir.distance * PX_TO_PT, 2),
            alpha=s_ir.alpha * 100.0
        )

    @classmethod
    def _text_block_to_ir(cls, tb: TextBlock) -> TextContentIR:
        paras: List[ParagraphIR] = []
        for p in tb.paragraphs:
            runs: List[RunIR] = []
            for r in p.runs:
                font_ir = None
                if r.font:
                    font_ir = FontIR(
                        name=r.font.name or "Segoe UI",
                        size=round((r.font.size or 14.0) * PT_TO_PX, 1),
                        color=r.font.color or "#1E293B",
                        bold=r.font.bold,
                        italic=r.font.italic,
                        underline=r.font.underline
                    )
                runs.append(RunIR(text=r.text, font=font_ir))
            paras.append(ParagraphIR(
                align=p.style.align if p.style.align in ["left", "center", "right", "justify"] else "left",
                line_spacing=p.style.line_spacing or 1.2,
                runs=runs
            ))
        return TextContentIR(paragraphs=paras)

    @classmethod
    def _ir_to_text_block(cls, tc_ir: TextContentIR) -> TextBlock:
        paras: List[OOXMLParagraph] = []
        for p_ir in tc_ir.paragraphs:
            runs: List[OOXMLRun] = []
            for r_ir in p_ir.runs:
                font = None
                if r_ir.font:
                    font = OOXMLFont(
                        name=r_ir.font.name,
                        size=round(r_ir.font.size * PX_TO_PT, 1),
                        color=r_ir.font.color,
                        bold=r_ir.font.bold,
                        italic=r_ir.font.italic,
                        underline=r_ir.font.underline
                    )
                runs.append(OOXMLRun(text=r_ir.text, font=font))
            paras.append(OOXMLParagraph(
                runs=runs,
                style=ParagraphStyle(
                    align=p_ir.align,
                    line_spacing=p_ir.line_spacing
                )
            ))
        return TextBlock(paragraphs=paras)


def uuid_short() -> str:
    import uuid
    return uuid.uuid4().hex[:6]
