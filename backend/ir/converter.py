"""Bidirectional converter between PPT-IR and pptx_agent_converter models.

Enables seamless lossless translation between:
- Standard 1280x720 ViewBox Pixel Canvas (PPT-IR)
- Physical Inch/EMU/OOXML Representation (pptx_agent_converter.model)
"""

from __future__ import annotations
import os
import base64
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Union
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
    GroupElementIR, TransformIR,
    ElementStyleIR, FillStyle, BorderStyle, ShadowStyle, GradientFill, GradientStop,
    TextContentIR, ParagraphIR, RunIR, FontIR
)


# Standard 96 DPI coordinate scaling factors
# 1280 / 13.33333333 ≈ 96.0 px/inch; 720 / 7.5 = 96.0 px/inch
DPI = 96.0
PT_TO_PX = 96.0 / 72.0  # 1.333333
PX_TO_PT = 72.0 / 96.0  # 0.75


@dataclass
class ConversionReport:
    """Report tracking element conversion fidelity, counts, and skipped items."""
    converted_elements: int = 0
    skipped_elements: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "converted_elements": self.converted_elements,
            "skipped_elements": self.skipped_elements,
            "warnings": list(self.warnings)
        }


class PPTIRConverter:
    """High-fidelity bidirectional converter."""

    last_report: Optional[ConversionReport] = None

    # -----------------------------------------------------------------
    # OOXML Model -> PPT-IR
    # -----------------------------------------------------------------

    @classmethod
    def presentation_to_ir(
        cls,
        pres: Presentation,
        report: Optional[ConversionReport] = None
    ) -> PresentationIR:
        if pres is None:
            raise ValueError("Critical corruption: cannot convert None Presentation to PPT-IR")
        if pres.size is None or pres.size.width <= 0 or pres.size.height <= 0:
            raise ValueError("Critical corruption: presentation dimensions must be positive")

        if report is None:
            report = ConversionReport()
        cls.last_report = report

        w_in = pres.size.width if pres.size.width > 0 else DEFAULT_WIDTH
        h_in = pres.size.height if pres.size.height > 0 else DEFAULT_HEIGHT

        # Calculate scale ratio to map to 1280x720 standard canvas
        scale_x = 1280.0 / w_in
        scale_y = 720.0 / h_in

        slides_ir: List[SlideIR] = []
        for s in pres.slides:
            slides_ir.append(cls.slide_to_ir(s, scale_x, scale_y, report=report))

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
    def convert_presentation_with_report(cls, pres: Presentation) -> Tuple[PresentationIR, ConversionReport]:
        """Converts Presentation to PresentationIR and returns a structured ConversionReport."""
        report = ConversionReport()
        pres_ir = cls.presentation_to_ir(pres, report=report)
        return pres_ir, report

    @classmethod
    def slide_to_ir(
        cls,
        slide: Slide,
        scale_x: float = DPI,
        scale_y: float = DPI,
        report: Optional[ConversionReport] = None
    ) -> SlideIR:
        if slide is None:
            raise ValueError("Critical corruption: cannot convert None Slide to SlideIR")

        # Record warnings from slide's parsed unsupported elements (e.g. SmartArt, chart, table)
        if hasattr(slide, "unsupported_elements") and slide.unsupported_elements:
            for item in slide.unsupported_elements:
                if report is not None:
                    report.skipped_elements += 1
                    report.warnings.append(f"Slide {slide.slide_num}: {item}")

        elements_ir: List[ElementIR] = []
        for el in slide.elements:
            ir_el = cls.element_to_ir(el, scale_x, scale_y, report=report)
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
    def element_to_ir(
        cls,
        elem: Any,
        scale_x: float = DPI,
        scale_y: float = DPI,
        report: Optional[ConversionReport] = None
    ) -> Optional[ElementIR]:
        if elem is None:
            return None

        # Check for explicit unsupported shape types
        if hasattr(elem, "shape_type") and elem.shape_type in ["smartArt", "chart", "diagram", "oleObject"]:
            if report is not None:
                report.skipped_elements += 1
                report.warnings.append(f"Element '{getattr(elem, 'name', '')}' has unsupported shape_type '{elem.shape_type}'")
            return None

        res: Optional[ElementIR] = None

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

            res = ConnectorElementIR(
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
                start_shape_id=getattr(elem, "start_shape_id", None),
                end_shape_id=getattr(elem, "end_shape_id", None),
                start_site_index=getattr(elem, "start_site_index", None),
                end_site_index=getattr(elem, "end_site_index", None),
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

            res = ImageElementIR(
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

            flip_h = getattr(elem, "flip_h", False)
            flip_v = getattr(elem, "flip_v", False)

            # Distinguish pure textbox vs shape
            if elem.shape_type in ["textbox", "text"] or (not fill and not border and text_content):
                res = TextElementIR(
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
            else:
                res = ShapeElementIR(
                    id=elem.id or f"shape_{uuid_short()}",
                    name=elem.name or "Shape",
                    shape_type=elem.shape_type or "roundRect",
                    x=x,
                    y=y,
                    width=w,
                    height=h,
                    rotation=elem.rotation,
                    flip_h=flip_h,
                    flip_v=flip_v,
                    adjust_values=getattr(elem, "adjust_values", {}),
                    text_content=text_content,
                    style=ElementStyleIR(
                        fill=fill,
                        border=border,
                        shadow=shadow,
                        radius=elem.radius if elem.radius is not None else 0.0
                    )
                )

        elif isinstance(elem, GroupElement):
            # Native Slide IR v2 hierarchical group representation
            pos = getattr(elem, "position", None)
            x = round(pos.x * scale_x, 2) if pos else 0.0
            y = round(pos.y * scale_y, 2) if pos else 0.0
            w = round(pos.width * scale_x, 2) if pos else 0.0
            h = round(pos.height * scale_y, 2) if pos else 0.0

            children_ir: List[ElementIR] = []
            for child in elem.elements:
                c_ir = cls.element_to_ir(child, scale_x, scale_y, report=report)
                if c_ir:
                    children_ir.append(c_ir)

            # If group bounding box is empty, default (0, 0, 1, 1), or pos is None, compute from children
            if children_ir:
                min_x = min(c.x for c in children_ir)
                min_y = min(c.y for c in children_ir)
                max_x = max(c.x + c.width for c in children_ir)
                max_y = max(c.y + c.height for c in children_ir)
                is_default_pos = (pos is None) or (pos.x == 0.0 and pos.y == 0.0 and pos.width <= 1.0 and pos.height <= 1.0)
                if is_default_pos or w <= 0 or h <= 0:
                    x = min_x
                    y = min_y
                    w = max(max_x - min_x, 1.0)
                    h = max(max_y - min_y, 1.0)

            res = GroupElementIR(
                id=elem.id or f"grp_{uuid_short()}",
                name=elem.name or "Group",
                x=x,
                y=y,
                width=w,
                height=h,
                children=children_ir,
                style=ElementStyleIR()
            )

        else:
            if report is not None:
                report.skipped_elements += 1
                elem_name = getattr(elem, 'name', '') or str(elem)
                report.warnings.append(f"Unsupported element class '{type(elem).__name__}' ({elem_name})")
            return None

        if res is not None:
            if report is not None and not isinstance(elem, GroupElement):
                report.converted_elements += 1
            return res

        return None

    @classmethod
    def _flatten_group_to_ir(
        cls,
        grp: GroupElement,
        acc: List[ElementIR],
        scale_x: float,
        scale_y: float,
        report: Optional[ConversionReport] = None
    ):
        """Recursively unwraps group elements into flat IR elements."""
        for child in grp.elements:
            if isinstance(child, GroupElement):
                cls._flatten_group_to_ir(child, acc, scale_x, scale_y, report=report)
            else:
                ir_child = cls.element_to_ir(child, scale_x, scale_y, report=report)
                if ir_child:
                    acc.append(ir_child)

    # -----------------------------------------------------------------
    # PPT-IR -> OOXML Model
    # -----------------------------------------------------------------

    @classmethod
    def ir_to_presentation(
        cls,
        pres_ir: PresentationIR,
        report: Optional[ConversionReport] = None
    ) -> Presentation:
        if pres_ir is None:
            raise ValueError("Critical corruption: cannot convert None PresentationIR to Presentation")
        if pres_ir.width <= 0 or pres_ir.height <= 0:
            raise ValueError("Critical corruption: PresentationIR canvas width and height must be positive")

        if report is None:
            report = ConversionReport()
        cls.last_report = report

        w_in = DEFAULT_WIDTH  # 13.333
        h_in = DEFAULT_HEIGHT  # 7.5
        scale_x = 1280.0 / w_in
        scale_y = 720.0 / h_in

        slides: List[Slide] = []
        for idx, s_ir in enumerate(pres_ir.slides):
            slides.append(cls.ir_to_slide(s_ir, idx + 1, scale_x, scale_y, report=report))

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
    def ir_to_presentation_with_report(cls, pres_ir: PresentationIR) -> Tuple[Presentation, ConversionReport]:
        """Converts PresentationIR to Presentation and returns a structured ConversionReport."""
        report = ConversionReport()
        pres = cls.ir_to_presentation(pres_ir, report=report)
        return pres, report

    @classmethod
    def ir_to_slide(
        cls,
        s_ir: SlideIR,
        slide_num: int = 1,
        scale_x: float = DPI,
        scale_y: float = DPI,
        report: Optional[ConversionReport] = None
    ) -> Slide:
        if s_ir is None:
            raise ValueError("Critical corruption: cannot convert None SlideIR to Slide")

        elements: List[Any] = []
        for el in s_ir.elements:
            elem = cls.ir_to_element(el, scale_x, scale_y, report=report)
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
    def ir_to_element(
        cls,
        el: ElementIR,
        scale_x: float = DPI,
        scale_y: float = DPI,
        report: Optional[ConversionReport] = None
    ) -> Optional[Any]:
        if el is None:
            return None

        if isinstance(el, TableElementIR):
            if report is not None:
                report.skipped_elements += 1
                report.warnings.append(f"Table element '{el.id}' is not yet supported for OOXML export")
            return None

        res: Optional[Any] = None

        if isinstance(el, ConnectorElementIR):
            ln = cls._ir_to_line(el.style.border) if el.style.border else Line()
            if el.arrow_end and el.arrow_end != "none":
                ln.arrow_end = el.arrow_end
            if el.arrow_start and el.arrow_start != "none":
                ln.arrow_start = el.arrow_start

            res = ConnectorElement(
                id=el.id,
                name=el.name or "Connector",
                connector_type=el.line_type,
                start=(el.start_x / scale_x, el.start_y / scale_y),
                end=(el.end_x / scale_x, el.end_y / scale_y),
                start_shape_id=el.start_shape_id,
                end_shape_id=el.end_shape_id,
                start_site_index=el.start_site_index,
                end_site_index=el.end_site_index,
                line=ln,
                arrow_start=el.arrow_start if el.arrow_start != "none" else None,
                arrow_end=el.arrow_end if el.arrow_end != "none" else None
            )

        elif isinstance(elem := el, ImageElementIR):
            res = ImageElement(
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
            flip_h = getattr(elem, "flip_h", False) or (elem.transform.flip_h if elem.transform else False)
            flip_v = getattr(elem, "flip_v", False) or (elem.transform.flip_v if elem.transform else False)
            res = ShapeElement(
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
                flip_h=flip_h,
                flip_v=flip_v,
                fill=cls._ir_to_fill(elem.style.fill) if elem.style.fill else Fill(type="none"),
                line=cls._ir_to_line(elem.style.border) if elem.style.border else None,
                shadow=cls._ir_to_shadow(elem.style.shadow) if elem.style.shadow else None,
                text=text_block
            )

        elif isinstance(elem := el, ShapeElementIR):
            text_block = cls._ir_to_text_block(elem.text_content) if elem.text_content else None
            flip_h = getattr(elem, "flip_h", False) or (elem.transform.flip_h if elem.transform else False)
            flip_v = getattr(elem, "flip_v", False) or (elem.transform.flip_v if elem.transform else False)
            res = ShapeElement(
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
                flip_h=flip_h,
                flip_v=flip_v,
                fill=cls._ir_to_fill(elem.style.fill) if elem.style.fill else Fill(type="solid", color="#3B82F6"),
                line=cls._ir_to_line(elem.style.border) if elem.style.border else None,
                shadow=cls._ir_to_shadow(elem.style.shadow) if elem.style.shadow else None,
                radius=elem.style.radius if elem.style.radius > 0 else None,
                adjust_values=elem.adjust_values,
                text=text_block
            )

        elif isinstance(elem := el, GroupElementIR):
            child_ooxml_elements = []
            for child_ir in elem.children:
                c_elem = cls.ir_to_element(child_ir, scale_x, scale_y, report=report)
                if c_elem:
                    child_ooxml_elements.append(c_elem)

            res = GroupElement(
                id=elem.id,
                name=elem.name or "Group",
                position=Position(
                    x=elem.x / scale_x,
                    y=elem.y / scale_y,
                    width=elem.width / scale_x,
                    height=elem.height / scale_y
                ),
                elements=child_ooxml_elements
            )

        else:
            if report is not None:
                report.skipped_elements += 1
                report.warnings.append(f"Element '{getattr(el, 'id', 'unnamed')}' of type '{getattr(el, 'type', type(el).__name__)}' cannot be converted to OOXML and was skipped")
            return None

        if res is not None:
            if report is not None and not isinstance(el, GroupElementIR):
                report.converted_elements += 1
            return res

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
                        underline=r.font.underline,
                        strikethrough=getattr(r.font, "strike", False)
                    )
                runs.append(RunIR(text=r.text, font=font_ir))
            paras.append(ParagraphIR(
                align=p.style.align if p.style.align in ["left", "center", "right", "justify"] else "left",
                line_spacing=p.style.line_spacing or 1.2,
                space_before=p.style.space_before or 0.0,
                space_after=p.style.space_after or 0.0,
                bullet=p.bullet,
                runs=runs
            ))
        return TextContentIR(paragraphs=paras)

    @classmethod
    def _ir_to_text_block(cls, tc_ir: TextContentIR) -> TextBlock:
        paras: List[OOXMLParagraph] = []
        for p_ir in tc_ir.paragraphs:
            runs: List[OOXMLRun] = []
            for r_ir in p_ir.runs:
                if r_ir.font:
                    font = OOXMLFont(
                        name=r_ir.font.name,
                        size=round(r_ir.font.size * PX_TO_PT, 1),
                        color=r_ir.font.color,
                        bold=r_ir.font.bold,
                        italic=r_ir.font.italic,
                        underline=r_ir.font.underline,
                        strike=r_ir.font.strikethrough
                    )
                else:
                    font = OOXMLFont(name="Segoe UI", size=14.0, color="#000000")
                runs.append(OOXMLRun(text=r_ir.text, font=font))
            paras.append(OOXMLParagraph(
                runs=runs,
                style=ParagraphStyle(
                    align=p_ir.align,
                    line_spacing=p_ir.line_spacing,
                    space_before=p_ir.space_before if p_ir.space_before > 0 else None,
                    space_after=p_ir.space_after if p_ir.space_after > 0 else None
                ),
                bullet=p_ir.bullet
            ))
        return TextBlock(paragraphs=paras)


def uuid_short() -> str:
    import uuid
    return uuid.uuid4().hex[:6]


def import_pptx(source: Union[str, Path, os.PathLike]) -> PresentationIR:
    """Imports a PPTX file into PPT-IR representation."""
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"PPTX file not found: {path}")

    from pptx_agent_converter.extractor.pptx_parser import PPTXParser
    parser = PPTXParser(str(path))
    ooxml_pres = parser.parse()
    return PPTIRConverter.presentation_to_ir(ooxml_pres)


def export_pptx(pres_ir: PresentationIR, output_path: Union[str, Path, os.PathLike]) -> Path:
    """Exports a PPT-IR presentation into a valid OOXML PPTX file."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder
    ooxml_pres = PPTIRConverter.ir_to_presentation(pres_ir)
    builder = PPTXBuilder()
    builder.build(ooxml_pres, str(out))
    return out
