"""Slide parser for OOXML slide XML files."""

from __future__ import annotations
from typing import Optional, List, Dict, Any, Union
import xml.etree.ElementTree as ET

from ..model.slide import Slide, SlideSize
from ..model.shape import (
    BaseElement,
    ShapeElement,
    ConnectorElement,
    ImageElement,
    GroupElement,
    Position
)
from .constants import NS, emu_to_inches
from .style_parser import StyleParser
from .shape_parser import ShapeParser
from .text_parser import TextParser
from .media_parser import MediaParser


class SlideParser:
    """Parses a single slide XML into a Slide domain model."""

    def __init__(
        self,
        style_parser: StyleParser,
        shape_parser: ShapeParser,
        text_parser: TextParser,
        media_parser: MediaParser,
    ):
        self.style_parser = style_parser
        self.shape_parser = shape_parser
        self.text_parser = text_parser
        self.media_parser = media_parser

    def parse_slide(
        self,
        slide_xml_bytes: bytes,
        slide_id: int,
        slide_size: SlideSize,
        rels_map: Optional[Dict[str, str]] = None,
        xml_path: Optional[str] = None
    ) -> Slide:
        """Parses slide XML bytes into a Slide object."""
        root = ET.fromstring(slide_xml_bytes)
        rels = rels_map or {}

        # Parse background if present
        bg_fill = None
        bg_elem = root.find(".//p:bg", NS)
        if bg_elem is not None:
            bg_pr = bg_elem.find("p:bgPr", NS)
            if bg_pr is not None:
                bg_fill = self.style_parser.parse_fill(bg_pr)

        # Parse shape tree: <p:spTree>
        sp_tree = root.find(".//p:spTree", NS)
        elements: List[Union[ShapeElement, ConnectorElement, ImageElement, GroupElement]] = []
        unsupported_elements: List[str] = []

        if sp_tree is not None:
            z_order = 0
            for child in sp_tree:
                tag = child.tag.split("}")[-1]
                if tag == "sp":
                    elem = self.shape_parser.parse_shape(child, z_order=z_order)
                    elements.append(elem)
                    z_order += 1
                elif tag == "cxnSp":
                    elem = self.shape_parser.parse_connector(child, z_order=z_order)
                    elements.append(elem)
                    z_order += 1
                elif tag == "pic":
                    pic = self.media_parser.parse_picture(child, rels, z_order=z_order)
                    if pic is not None:
                        elements.append(pic)
                        z_order += 1
                elif tag == "grpSp":
                    grp = self._parse_group(child, rels, z_order=z_order)
                    elements.append(grp)
                    z_order += 1
                elif tag == "graphicFrame":
                    # Detect graphic frame type (SmartArt, Chart, Table, etc.)
                    gf_uri = ""
                    graphic_data = child.find(".//a:graphicData", NS)
                    if graphic_data is not None:
                        gf_uri = graphic_data.get("uri", "")
                    if "diagram" in gf_uri:
                        unsupported_elements.append("SmartArt unsupported")
                    elif "chart" in gf_uri:
                        unsupported_elements.append("Chart unsupported")
                    elif "table" in gf_uri:
                        unsupported_elements.append("Table graphicFrame unsupported")
                    else:
                        unsupported_elements.append(f"GraphicFrame ({gf_uri or 'unknown'}) unsupported")
                elif tag not in ["nvGrpSpPr", "grpSpPr"]:
                    unsupported_elements.append(f"Unsupported OOXML element tag: <{tag}>")

        return Slide(
            slide_id=slide_id,
            slide_num=slide_id,
            size=slide_size,
            background=bg_fill,
            elements=elements,
            unsupported_elements=unsupported_elements,
            xml_path=xml_path
        )

    def _parse_group(self, grp_elem: ET.Element, rels: Dict[str, str], z_order: int = 0) -> GroupElement:
        """Parses a <p:grpSp> group element recursively, mapping DrawingML child coordinates."""
        nv_grp_pr = grp_elem.find("p:nvGrpSpPr", NS)
        elem_id = ""
        elem_name = ""
        if nv_grp_pr is not None:
            c_nv_pr = nv_grp_pr.find("p:cNvPr", NS)
            if c_nv_pr is not None:
                elem_id = c_nv_pr.get("id", "")
                elem_name = c_nv_pr.get("name", "")

        grp_sp_pr = grp_elem.find("p:grpSpPr", NS)
        pos, _, _, _ = self.shape_parser.parse_position(grp_sp_pr)

        # DrawingML Group Coordinate Mapping (off, ext, chOff, chExt)
        grp_xfrm = grp_sp_pr.find("a:xfrm", NS) if grp_sp_pr is not None else None
        ch_off = grp_xfrm.find("a:chOff", NS) if grp_xfrm is not None else None
        ch_ext = grp_xfrm.find("a:chExt", NS) if grp_xfrm is not None else None

        ch_x = emu_to_inches(int(ch_off.get("x", "0"))) if ch_off is not None and ch_off.get("x") else pos.x
        ch_y = emu_to_inches(int(ch_off.get("y", "0"))) if ch_off is not None and ch_off.get("y") else pos.y
        ch_w = emu_to_inches(int(ch_ext.get("cx", "0"))) if ch_ext is not None and ch_ext.get("cx") else pos.width
        ch_h = emu_to_inches(int(ch_ext.get("cy", "0"))) if ch_ext is not None and ch_ext.get("cy") else pos.height

        scale_x = (pos.width / ch_w) if ch_w > 0.0 else 1.0
        scale_y = (pos.height / ch_h) if ch_h > 0.0 else 1.0

        children = []
        child_z = 0
        for child in grp_elem:
            tag = child.tag.split("}")[-1]
            elem = None
            if tag == "sp":
                elem = self.shape_parser.parse_shape(child, z_order=child_z)
            elif tag == "cxnSp":
                elem = self.shape_parser.parse_connector(child, z_order=child_z)
            elif tag == "pic":
                elem = self.media_parser.parse_picture(child, rels, z_order=child_z)
            elif tag == "grpSp":
                elem = self._parse_group(child, rels, z_order=child_z)

            if elem is not None:
                self._apply_child_coordinate_transform(elem, pos, ch_x, ch_y, scale_x, scale_y)
                children.append(elem)
                child_z += 1

        grp = GroupElement(
            id=elem_id,
            name=elem_name,
            z_order=z_order,
            position=pos,
            elements=children
        )
        if (pos.width <= 0 or pos.height <= 0) and children:
            grp.recompute_bounds()
        return grp

    def _apply_child_coordinate_transform(
        self,
        elem: Union[ShapeElement, ConnectorElement, ImageElement, GroupElement],
        pos: Position,
        ch_x: float,
        ch_y: float,
        scale_x: float,
        scale_y: float
    ) -> None:
        """Transforms child from local (chOff, chExt) space into parent group space."""
        # Check if child coordinate space is already 1:1 with group parent
        is_identity = (
            abs(pos.x - ch_x) < 1e-6 and
            abs(pos.y - ch_y) < 1e-6 and
            abs(scale_x - 1.0) < 1e-6 and
            abs(scale_y - 1.0) < 1e-6
        )
        if is_identity:
            return

        if isinstance(elem, GroupElement):
            old_x = elem.position.x
            old_y = elem.position.y
            elem.scale(scale_x, scale_y, origin_x=old_x, origin_y=old_y)
            new_x = pos.x + (old_x - ch_x) * scale_x
            new_y = pos.y + (old_y - ch_y) * scale_y
            elem.translate(new_x - elem.position.x, new_y - elem.position.y)
        elif hasattr(elem, "position") and elem.position is not None:
            p = elem.position
            p.x = round(pos.x + (p.x - ch_x) * scale_x, 4)
            p.y = round(pos.y + (p.y - ch_y) * scale_y, 4)
            p.width = round(p.width * scale_x, 4)
            p.height = round(p.height * scale_y, 4)
        elif isinstance(elem, ConnectorElement):
            sx = round(pos.x + (elem.start[0] - ch_x) * scale_x, 4)
            sy = round(pos.y + (elem.start[1] - ch_y) * scale_y, 4)
            ex = round(pos.x + (elem.end[0] - ch_x) * scale_x, 4)
            ey = round(pos.y + (elem.end[1] - ch_y) * scale_y, 4)
            elem.start = (sx, sy)
            elem.end = (ex, ey)
