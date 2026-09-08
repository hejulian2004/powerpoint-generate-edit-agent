"""Text parser for OOXML txBody, paragraphs, and runs."""

from __future__ import annotations
from typing import Optional, List, Dict, Any
import xml.etree.ElementTree as ET

from ..model.style import Font, ParagraphStyle
from ..model.text import Run, Paragraph, TextBlock
from .constants import NS, emu_to_inches
from .style_parser import StyleParser


class TextParser:
    """Parses text bodies, paragraphs, runs, fonts, and alignments from <p:txBody>."""

    def __init__(self, style_parser: StyleParser):
        self.style_parser = style_parser

    def parse_tx_body(self, tx_body: ET.Element) -> Optional[TextBlock]:
        """Parse <p:txBody> or <a:txBody> element into a TextBlock."""
        if tx_body is None:
            return None

        # Parse body properties <a:bodyPr>
        body_pr = tx_body.find("a:bodyPr", NS)
        vertical_align = "middle"
        word_wrap = True
        margin_l, margin_r, margin_t, margin_b = 0.1, 0.1, 0.05, 0.05

        if body_pr is not None:
            anchor = body_pr.get("anchor", "ctr")
            if anchor in ("t", "top"):
                vertical_align = "top"
            elif anchor in ("b", "bottom"):
                vertical_align = "bottom"
            elif anchor in ("ctr", "middle"):
                vertical_align = "middle"

            wrap = body_pr.get("wrap")
            if wrap == "none":
                word_wrap = False

            if body_pr.get("lIns"):
                margin_l = emu_to_inches(int(body_pr.get("lIns")))
            if body_pr.get("rIns"):
                margin_r = emu_to_inches(int(body_pr.get("rIns")))
            if body_pr.get("tIns"):
                margin_t = emu_to_inches(int(body_pr.get("tIns")))
            if body_pr.get("bIns"):
                margin_b = emu_to_inches(int(body_pr.get("bIns")))

        paragraphs: List[Paragraph] = []
        for p_elem in tx_body.findall("a:p", NS):
            para = self._parse_paragraph(p_elem, vertical_align)
            paragraphs.append(para)

        # If no text at all, return None or empty
        if not paragraphs or not any(p.runs for p in paragraphs):
            return None

        return TextBlock(
            paragraphs=paragraphs,
            vertical_align=vertical_align,
            word_wrap=word_wrap,
            margin_left=margin_l,
            margin_right=margin_r,
            margin_top=margin_t,
            margin_bottom=margin_b
        )

    def _parse_paragraph(self, p_elem: ET.Element, default_vertical: str) -> Paragraph:
        """Parse a single <a:p> element."""
        p_pr = p_elem.find("a:pPr", NS)
        align = "left"
        space_before = None
        space_after = None
        line_spacing = None
        bullet = None

        if p_pr is not None:
            algn_val = p_pr.get("algn", "l")
            if algn_val in ("ctr", "center"):
                align = "center"
            elif algn_val in ("r", "right"):
                align = "right"
            elif algn_val in ("just", "justify"):
                align = "justify"
            else:
                align = "left"

            # Check bullet
            bu_char = p_pr.find("a:buChar", NS)
            if bu_char is not None:
                bullet = bu_char.get("char", "•")

        para_style = ParagraphStyle(
            align=align,
            vertical=default_vertical,
            line_spacing=line_spacing,
            space_before=space_before,
            space_after=space_after
        )

        runs: List[Run] = []
        # Find all run elements, line breaks, fields
        for child in p_elem:
            tag = child.tag.split("}")[-1]
            if tag == "r":
                run = self._parse_run(child)
                if run.text:
                    runs.append(run)
            elif tag == "br":
                # Line break
                runs.append(Run(text="\n", font=Font()))
            elif tag == "fld":
                t_elem = child.find("a:t", NS)
                if t_elem is not None and t_elem.text:
                    r_pr = child.find("a:rPr", NS)
                    font = self._parse_font(r_pr) if r_pr is not None else Font()
                    runs.append(Run(text=t_elem.text, font=font))

        return Paragraph(runs=runs, style=para_style, bullet=bullet)

    def _parse_run(self, r_elem: ET.Element) -> Run:
        """Parse a single <a:r> run element."""
        t_elem = r_elem.find("a:t", NS)
        text = t_elem.text if t_elem is not None and t_elem.text is not None else ""

        r_pr = r_elem.find("a:rPr", NS)
        font = self._parse_font(r_pr) if r_pr is not None else Font()

        return Run(text=text, font=font)

    def _parse_font(self, r_pr: Optional[ET.Element]) -> Font:
        """Parse font attributes from <a:rPr>."""
        if r_pr is None:
            return Font()

        # Size: sz is in hundredths of a point (e.g. 1800 = 18 pt)
        sz_val = r_pr.get("sz")
        size = float(sz_val) / 100.0 if sz_val and sz_val.isdigit() else 14.0

        # Bold, italic, underline, strike
        bold = r_pr.get("b") in ("1", "true")
        italic = r_pr.get("i") in ("1", "true")
        underline = r_pr.get("u") in ("sng", "dbl", "true", "1")
        strike = r_pr.get("strike") in ("sngStrike", "dblStrike", "true", "1")

        # Color & alpha
        color_hex = "#000000"
        alpha = 100.0
        color_res = self.style_parser.parse_color_element(r_pr)
        if color_res:
            color_hex, alpha, _ = color_res

        # Font family name
        font_name = "Calibri"
        latin = r_pr.find("a:latin", NS)
        if latin is not None:
            tf = latin.get("typeface", "")
            if tf.startswith("+mj"):
                font_name = self.style_parser.theme_fonts.get("major", "Calibri")
            elif tf.startswith("+mn"):
                font_name = self.style_parser.theme_fonts.get("minor", "Calibri")
            elif tf:
                font_name = tf
        else:
            ea = r_pr.find("a:ea", NS)
            if ea is not None:
                tf = ea.get("typeface", "")
                if tf.startswith("+mj"):
                    font_name = self.style_parser.theme_fonts.get("major_ea", "Microsoft YaHei")
                elif tf.startswith("+mn"):
                    font_name = self.style_parser.theme_fonts.get("minor_ea", "Microsoft YaHei")
                elif tf:
                    font_name = tf

        return Font(
            name=font_name,
            size=size,
            bold=bold,
            italic=italic,
            underline=underline,
            strike=strike,
            color=color_hex,
            alpha=alpha
        )
