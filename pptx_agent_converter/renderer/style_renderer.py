"""Style renderer for converting models into OOXML DrawingML elements."""

from __future__ import annotations
from typing import Optional, Dict, Any
import xml.etree.ElementTree as ET

from ..model.style import Fill, Line, Shadow, Font, ParagraphStyle
from ..model.text import TextBlock, Paragraph, Run
from ..extractor.constants import (
    NS,
    inches_to_emu,
    pt_to_emu,
    degrees_to_angle,
    hex_to_rgb
)


class StyleRenderer:
    """Renders styling models (fills, borders, effects, fonts) to OOXML XML elements."""

    @staticmethod
    def build_color_element(
        hex_color: str = "#000000",
        alpha: float = 100.0,
        scheme_color: Optional[str] = None
    ) -> ET.Element:
        """Constructs an <a:srgbClr> or <a:schemeClr> XML element."""
        cleaned_hex = hex_color.lstrip("#").upper()
        if len(cleaned_hex) != 6:
            cleaned_hex = "000000"

        if scheme_color:
            elem = ET.Element(f"{{{NS['a']}}}schemeClr", {"val": scheme_color})
        else:
            elem = ET.Element(f"{{{NS['a']}}}srgbClr", {"val": cleaned_hex})

        if alpha < 100.0:
            # Alpha in DrawingML: 100000 = 100%
            alpha_val = str(max(0, min(100000, int(alpha * 1000))))
            alpha_elem = ET.SubElement(elem, f"{{{NS['a']}}}alpha", {"val": alpha_val})

        return elem

    @staticmethod
    def build_fill(fill: Optional[Fill]) -> Optional[ET.Element]:
        """Builds <a:solidFill>, <a:gradFill>, or <a:noFill>."""
        if fill is None or fill.type == "none":
            return ET.Element(f"{{{NS['a']}}}noFill")

        if fill.type == "solid":
            solid = ET.Element(f"{{{NS['a']}}}solidFill")
            clr = StyleRenderer.build_color_element(
                hex_color=fill.color or "#000000",
                alpha=fill.alpha,
                scheme_color=fill.scheme_color
            )
            solid.append(clr)
            return solid

        if fill.type == "gradient":
            grad = ET.Element(f"{{{NS['a']}}}gradFill")
            gs_lst = ET.SubElement(grad, f"{{{NS['a']}}}gsLst")

            stops = fill.stops
            if not stops:
                # Default gradient if none specified
                from ..model.style import GradientStop
                stops = [
                    GradientStop(position=0.0, color=fill.color or "#3366FF", alpha=fill.alpha),
                    GradientStop(position=1.0, color="#FFFFFF", alpha=fill.alpha)
                ]

            for stop in stops:
                pos_str = str(int(round(stop.position * 100000)))
                gs = ET.SubElement(gs_lst, f"{{{NS['a']}}}gs", {"pos": pos_str})
                c_elem = StyleRenderer.build_color_element(stop.color, stop.alpha)
                gs.append(c_elem)

            angle = fill.angle if fill.angle is not None else 90.0
            ET.SubElement(grad, f"{{{NS['a']}}}lin", {"ang": str(degrees_to_angle(angle)), "scaled": "1"})
            return grad

        return ET.Element(f"{{{NS['a']}}}noFill")

    @staticmethod
    def build_line(line: Optional[Line]) -> Optional[ET.Element]:
        """Builds <a:ln> with width, color, stroke style, and arrow ends."""
        if line is None:
            return None

        ln = ET.Element(f"{{{NS['a']}}}ln", {"w": str(pt_to_emu(line.width))})

        if line.color:
            solid = ET.SubElement(ln, f"{{{NS['a']}}}solidFill")
            c_elem = StyleRenderer.build_color_element(line.color, line.alpha)
            solid.append(c_elem)
        else:
            ET.SubElement(ln, f"{{{NS['a']}}}noFill")

        if line.style and line.style != "solid":
            dash_map = {
                "dash": "dash",
                "dot": "dot",
                "dashDot": "dashDot",
                "longDash": "lgDash"
            }
            ET.SubElement(ln, f"{{{NS['a']}}}prstDash", {"val": dash_map.get(line.style, line.style)})

        # Arrow head (end of arrow) & tail (start of arrow)
        # DrawingML schema CT_LineProperties requires <headEnd> before <tailEnd> in sequence
        if line.arrow_end and line.arrow_end != "none":
            ET.SubElement(ln, f"{{{NS['a']}}}headEnd", {
                "type": line.arrow_end,
                "w": "med",
                "len": "med"
            })

        if line.arrow_start and line.arrow_start != "none":
            ET.SubElement(ln, f"{{{NS['a']}}}tailEnd", {
                "type": line.arrow_start,
                "w": "med",
                "len": "med"
            })

        return ln

    @staticmethod
    def build_shadow(shadow: Optional[Shadow]) -> Optional[ET.Element]:
        """Builds <a:effectLst> containing <a:outerShdw>."""
        if shadow is None or not shadow.enabled:
            return None

        effect_lst = ET.Element(f"{{{NS['a']}}}effectLst")
        shdw = ET.SubElement(effect_lst, f"{{{NS['a']}}}outerShdw", {
            "blurRad": str(pt_to_emu(shadow.blur)),
            "dist": str(pt_to_emu(shadow.distance)),
            "dir": str(degrees_to_angle(shadow.direction)),
            "algn": "tl",
            "rotWithShape": "0"
        })
        clr_elem = StyleRenderer.build_color_element(shadow.color, shadow.alpha)
        shdw.append(clr_elem)
        return effect_lst

    @staticmethod
    def build_tx_body(text_block: Optional[TextBlock]) -> Optional[ET.Element]:
        """Builds complete <p:txBody> structure."""
        if text_block is None:
            return None

        tx_body = ET.Element(f"{{{NS['p']}}}txBody")

        # Map vertical alignment to anchor
        anchor_map = {"top": "t", "middle": "ctr", "bottom": "b"}
        anchor_val = anchor_map.get(text_block.vertical_align, "ctr")

        body_pr_attrs = {
            "wrap": "square" if text_block.word_wrap else "none",
            "rtlCol": "0",
            "anchor": anchor_val,
            "lIns": str(inches_to_emu(text_block.margin_left)),
            "rIns": str(inches_to_emu(text_block.margin_right)),
            "tIns": str(inches_to_emu(text_block.margin_top)),
            "bIns": str(inches_to_emu(text_block.margin_bottom)),
        }
        ET.SubElement(tx_body, f"{{{NS['a']}}}bodyPr", body_pr_attrs)
        ET.SubElement(tx_body, f"{{{NS['a']}}}lstStyle")

        # Alignment mapping
        align_map = {"left": "l", "center": "ctr", "right": "r", "justify": "just"}

        for para in text_block.paragraphs:
            p_elem = ET.SubElement(tx_body, f"{{{NS['a']}}}p")
            algn_code = align_map.get(para.style.align, "l")
            p_pr = ET.SubElement(p_elem, f"{{{NS['a']}}}pPr", {"algn": algn_code})

            if para.bullet:
                ET.SubElement(p_pr, f"{{{NS['a']}}}buChar", {"char": para.bullet})

            for run in para.runs:
                if run.text == "\n":
                    ET.SubElement(p_elem, f"{{{NS['a']}}}br")
                    continue

                r_elem = ET.SubElement(p_elem, f"{{{NS['a']}}}r")
                r_pr_attrs = {
                    "lang": "en-US",
                    "sz": str(int(round(run.font.size * 100))),
                }
                if run.font.bold:
                    r_pr_attrs["b"] = "1"
                if run.font.italic:
                    r_pr_attrs["i"] = "1"
                if run.font.underline:
                    r_pr_attrs["u"] = "sng"
                if run.font.strike:
                    r_pr_attrs["strike"] = "sngStrike"

                r_pr = ET.SubElement(r_elem, f"{{{NS['a']}}}rPr", r_pr_attrs)

                # Solid fill for run text color
                solid = ET.SubElement(r_pr, f"{{{NS['a']}}}solidFill")
                solid.append(StyleRenderer.build_color_element(run.font.color, run.font.alpha))

                # Font family
                ET.SubElement(r_pr, f"{{{NS['a']}}}latin", {"typeface": run.font.name})
                ET.SubElement(r_pr, f"{{{NS['a']}}}ea", {"typeface": run.font.name})
                ET.SubElement(r_pr, f"{{{NS['a']}}}cs", {"typeface": run.font.name})

                # Text element
                t_elem = ET.SubElement(r_elem, f"{{{NS['a']}}}t")
                t_elem.text = run.text

            # End paragraph run properties
            end_r_pr = ET.SubElement(p_elem, f"{{{NS['a']}}}endParaRPr", {
                "lang": "en-US",
                "sz": str(int(round(text_block.primary_font.size * 100)))
            })

        return tx_body
