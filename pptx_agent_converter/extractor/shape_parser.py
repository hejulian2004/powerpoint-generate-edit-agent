"""Shape and connector parser for OOXML elements."""

from __future__ import annotations
from typing import Optional, Dict, Any, Tuple
import xml.etree.ElementTree as ET

from ..model.shape import (
    Position,
    ShapeElement,
    ConnectorElement,
    GroupElement
)
from .constants import (
    NS,
    emu_to_inches,
    angle_to_degrees,
    PRESET_GEOM_MAP
)
from .style_parser import StyleParser
from .text_parser import TextParser


class ShapeParser:
    """Parses shapes, connectors, and groups from OOXML elements."""

    def __init__(self, style_parser: StyleParser, text_parser: TextParser):
        self.style_parser = style_parser
        self.text_parser = text_parser

    def parse_position(self, sp_pr: Optional[ET.Element]) -> Tuple[Position, float, bool, bool]:
        """
        Parses xfrm element to get Position (x, y, w, h in inches), rotation, flip_h, flip_v.
        """
        if sp_pr is None:
            return Position(), 0.0, False, False

        xfrm = sp_pr.find("a:xfrm", NS)
        if xfrm is None:
            return Position(), 0.0, False, False

        rot_val = xfrm.get("rot", "0")
        rotation = angle_to_degrees(int(rot_val)) if rot_val.lstrip("-").isdigit() else 0.0
        flip_h = xfrm.get("flipH") in ("1", "true")
        flip_v = xfrm.get("flipV") in ("1", "true")

        off = xfrm.find("a:off", NS)
        ext = xfrm.find("a:ext", NS)

        x = emu_to_inches(int(off.get("x", "0"))) if off is not None and off.get("x") else 0.0
        y = emu_to_inches(int(off.get("y", "0"))) if off is not None and off.get("y") else 0.0
        w = emu_to_inches(int(ext.get("cx", "0"))) if ext is not None and ext.get("cx") else 1.0
        h = emu_to_inches(int(ext.get("cy", "0"))) if ext is not None and ext.get("cy") else 1.0

        return Position(x=x, y=y, width=w, height=h), rotation, flip_h, flip_v

    def parse_shape(self, sp_elem: ET.Element, z_order: int = 0) -> ShapeElement:
        """Parses a standard <p:sp> element."""
        # Non-visual properties
        nv_sp_pr = sp_elem.find("p:nvSpPr", NS)
        elem_id = ""
        elem_name = ""
        is_textbox = False

        if nv_sp_pr is not None:
            c_nv_pr = nv_sp_pr.find("p:cNvPr", NS)
            if c_nv_pr is not None:
                elem_id = c_nv_pr.get("id", "")
                elem_name = c_nv_pr.get("name", "")

            c_nv_sp_pr = nv_sp_pr.find("p:cNvSpPr", NS)
            if c_nv_sp_pr is not None and c_nv_sp_pr.get("txBox") in ("1", "true"):
                is_textbox = True

        # Shape properties
        sp_pr = sp_elem.find("p:spPr", NS)
        pos, rot, flip_h, flip_v = self.parse_position(sp_pr)

        # Geometry
        raw_geom = "rect"
        radius = None
        if sp_pr is not None:
            prst_geom = sp_pr.find("a:prstGeom", NS)
            if prst_geom is not None:
                raw_geom = prst_geom.get("prst", "rect")
                av_lst = prst_geom.find("a:avLst", NS)
                if av_lst is not None:
                    adj = av_lst.find("a:gd[@name='adj']", NS)
                    if adj is not None and adj.get("fmla"):
                        parts = adj.get("fmla", "").split()
                        if len(parts) >= 2 and parts[-1].isdigit():
                            radius = round(float(parts[-1]) / 100000.0, 4)

        shape_type = PRESET_GEOM_MAP.get(raw_geom, raw_geom)

        # Styles: fill, line, shadow
        fill = self.style_parser.parse_fill(sp_pr)
        line = self.style_parser.parse_line(sp_pr)
        shadow = self.style_parser.parse_shadow(sp_pr)

        # Text
        tx_body = sp_elem.find("p:txBody", NS)
        text_block = self.text_parser.parse_tx_body(tx_body) if tx_body is not None else None

        elem_type = "textbox" if is_textbox else "shape"

        return ShapeElement(
            id=elem_id,
            name=elem_name,
            type=elem_type,
            z_order=z_order,
            shape_type=shape_type,
            position=pos,
            rotation=rot,
            flip_h=flip_h,
            flip_v=flip_v,
            fill=fill,
            line=line,
            shadow=shadow,
            radius=radius,
            text=text_block
        )

    def parse_connector(self, cxn_elem: ET.Element, z_order: int = 0) -> ConnectorElement:
        """Parses a <p:cxnSp> connector element."""
        # Non-visual properties
        nv_cxn_pr = cxn_elem.find("p:nvCxnSpPr", NS)
        elem_id = ""
        elem_name = ""
        start_shape_id = None
        end_shape_id = None

        if nv_cxn_pr is not None:
            c_nv_pr = nv_cxn_pr.find("p:cNvPr", NS)
            if c_nv_pr is not None:
                elem_id = c_nv_pr.get("id", "")
                elem_name = c_nv_pr.get("name", "")

            c_nv_cxn = nv_cxn_pr.find("p:cNvCxnSpPr", NS)
            if c_nv_cxn is not None:
                st_cxn = c_nv_cxn.find("a:stCxn", NS)
                if st_cxn is not None:
                    start_shape_id = st_cxn.get("id")
                end_cxn = c_nv_cxn.find("a:endCxn", NS)
                if end_cxn is not None:
                    end_shape_id = end_cxn.get("id")

        # Shape properties
        sp_pr = cxn_elem.find("p:spPr", NS)
        pos, _, flip_h, flip_v = self.parse_position(sp_pr)

        # Determine connector type
        conn_type = "straight"
        if sp_pr is not None:
            prst_geom = sp_pr.find("a:prstGeom", NS)
            if prst_geom is not None:
                prst_val = prst_geom.get("prst", "line")
                if "bent" in prst_val.lower():
                    conn_type = "bent"
                elif "curv" in prst_val.lower():
                    conn_type = "curved"

        # Calculate exact start and end points considering flips
        # Base box: from (x, y) with width and height
        x1 = pos.x
        y1 = pos.y
        x2 = pos.x + pos.width
        y2 = pos.y + pos.height

        start_x = x2 if flip_h else x1
        end_x = x1 if flip_h else x2

        start_y = y2 if flip_v else y1
        end_y = y1 if flip_v else y2

        # Parse line & arrows
        line = self.style_parser.parse_line(sp_pr)
        if line is None:
            from ..model.style import Line
            line = Line(color="#333333", width=1.5)

        arrow_start = line.arrow_start
        arrow_end = line.arrow_end

        return ConnectorElement(
            id=elem_id,
            name=elem_name,
            z_order=z_order,
            connector_type=conn_type,
            start=(start_x, start_y),
            end=(end_x, end_y),
            line=line,
            arrow_start=arrow_start,
            arrow_end=arrow_end,
            start_shape_id=start_shape_id,
            end_shape_id=end_shape_id
        )
