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

        return Slide(
            slide_id=slide_id,
            slide_num=slide_id,
            size=slide_size,
            background=bg_fill,
            elements=elements,
            xml_path=xml_path
        )

    def _parse_group(self, grp_elem: ET.Element, rels: Dict[str, str], z_order: int = 0) -> GroupElement:
        """Parses a <p:grpSp> group element recursively."""
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

        children = []
        child_z = 0
        for child in grp_elem:
            tag = child.tag.split("}")[-1]
            if tag == "sp":
                children.append(self.shape_parser.parse_shape(child, z_order=child_z))
                child_z += 1
            elif tag == "cxnSp":
                children.append(self.shape_parser.parse_connector(child, z_order=child_z))
                child_z += 1
            elif tag == "pic":
                pic = self.media_parser.parse_picture(child, rels, z_order=child_z)
                if pic is not None:
                    children.append(pic)
                    child_z += 1
            elif tag == "grpSp":
                children.append(self._parse_group(child, rels, z_order=child_z))
                child_z += 1

        return GroupElement(
            id=elem_id,
            name=elem_name,
            z_order=z_order,
            position=pos,
            elements=children
        )
