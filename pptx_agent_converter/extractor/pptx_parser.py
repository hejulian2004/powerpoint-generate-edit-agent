"""Main PPTX OOXML extractor module."""

from __future__ import annotations
import os
import zipfile
from typing import Optional, List, Dict, Any, Tuple
import xml.etree.ElementTree as ET

from ..model.slide import Slide, SlideSize, ThemeInfo, Presentation, DEFAULT_WIDTH, DEFAULT_HEIGHT
from .constants import NS, emu_to_inches
from .style_parser import StyleParser
from .text_parser import TextParser
from .shape_parser import ShapeParser
from .media_parser import MediaParser
from .slide_parser import SlideParser


class PPTXParser:
    """Parses a PPTX file directly from its OOXML zip components."""

    def __init__(self, pptx_path: str):
        self.pptx_path = pptx_path
        if not os.path.exists(pptx_path):
            raise FileNotFoundError(f"PPTX file not found: {pptx_path}")

    def parse(self) -> Presentation:
        """Parses the entire PPTX archive into a Presentation object."""
        with zipfile.ZipFile(self.pptx_path, "r") as zf:
            # 1. Parse presentation.xml for slide dimensions & slide ID order
            pres_size, slide_r_ids = self._parse_presentation_xml(zf)

            # 2. Parse presentation relationships (presentation.xml.rels)
            pres_rels = self._parse_presentation_rels(zf)

            # 3. Parse theme XML if available
            theme_info, theme_raw_bytes = self._parse_theme(zf, pres_rels)

            # 4. Initialize specialized parsers
            style_parser = StyleParser(
                theme_colors=theme_info.color_scheme,
                theme_fonts=theme_info.font_scheme
            )
            text_parser = TextParser(style_parser)
            shape_parser = ShapeParser(style_parser, text_parser)
            media_parser = MediaParser(zf)
            slide_parser = SlideParser(style_parser, shape_parser, text_parser, media_parser)

            # 5. Parse each slide in order
            slides: List[Slide] = []
            slide_idx = 1
            for r_id in slide_r_ids:
                rel_target = pres_rels.get(r_id)
                if not rel_target:
                    continue

                # Normalize slide path within zip
                slide_path = self._resolve_zip_path("ppt", rel_target)
                if slide_path not in zf.namelist():
                    continue

                slide_xml = zf.read(slide_path)

                # Find relationships for this slide (ppt/slides/_rels/slideX.xml.rels)
                slide_dir = os.path.dirname(slide_path)
                slide_fname = os.path.basename(slide_path)
                slide_rels_path = f"{slide_dir}/_rels/{slide_fname}.rels"
                
                rels_map: Dict[str, str] = {}
                if slide_rels_path in zf.namelist():
                    rels_map = media_parser.parse_slide_rels(zf.read(slide_rels_path))

                slide = slide_parser.parse_slide(
                    slide_xml_bytes=slide_xml,
                    slide_id=slide_idx,
                    slide_size=pres_size,
                    rels_map=rels_map,
                    xml_path=slide_path
                )
                slides.append(slide)
                slide_idx += 1

            pres_name = os.path.splitext(os.path.basename(self.pptx_path))[0]

            return Presentation(
                name=pres_name,
                size=pres_size,
                theme=theme_info,
                slides=slides,
                media_files=media_parser.media_files,
                theme_raw_bytes=theme_raw_bytes
            )

    def _parse_presentation_xml(self, zf: zipfile.ZipFile) -> Tuple[SlideSize, List[str]]:
        """Extract slide dimensions and ordered slide relationship IDs."""
        pres_path = "ppt/presentation.xml"
        if pres_path not in zf.namelist():
            return SlideSize(), []

        tree = ET.fromstring(zf.read(pres_path))
        sld_sz = tree.find(".//p:sldSz", NS)
        width = DEFAULT_WIDTH
        height = DEFAULT_HEIGHT

        if sld_sz is not None:
            cx = sld_sz.get("cx")
            cy = sld_sz.get("cy")
            if cx and cx.isdigit():
                width = emu_to_inches(int(cx))
            if cy and cy.isdigit():
                height = emu_to_inches(int(cy))

        # Extract ordered slide r:id list from <p:sldIdLst>
        slide_r_ids: List[str] = []
        sld_id_lst = tree.find(".//p:sldIdLst", NS)
        if sld_id_lst is not None:
            for sld_id in sld_id_lst.findall("p:sldId", NS):
                # r:id attribute
                for k, v in sld_id.attrib.items():
                    if k.endswith("id") or "id" in k.lower():
                        if v.startswith("rId"):
                            slide_r_ids.append(v)
                            break

        return SlideSize(width=width, height=height), slide_r_ids

    def _parse_presentation_rels(self, zf: zipfile.ZipFile) -> Dict[str, str]:
        """Parses ppt/_rels/presentation.xml.rels."""
        rels_path = "ppt/_rels/presentation.xml.rels"
        if rels_path not in zf.namelist():
            return {}

        rels_map: Dict[str, str] = {}
        try:
            root = ET.fromstring(zf.read(rels_path))
            for rel in root.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                r_id = rel.get("Id", "")
                target = rel.get("Target", "")
                rels_map[r_id] = target
        except Exception:
            pass
        return rels_map

    def _parse_theme(self, zf: zipfile.ZipFile, pres_rels: Dict[str, str]) -> Tuple[ThemeInfo, Optional[bytes]]:
        """Finds and parses theme1.xml."""
        theme_info = ThemeInfo()
        theme_path = None
        theme_raw_bytes = None

        # Look in presentation rels for theme
        for r_id, target in pres_rels.items():
            if "theme" in target:
                theme_path = self._resolve_zip_path("ppt", target)
                break

        if not theme_path or theme_path not in zf.namelist():
            # Fallback search in zip
            for name in zf.namelist():
                if name.startswith("ppt/theme/theme") and name.endswith(".xml"):
                    theme_path = name
                    break

        if theme_path and theme_path in zf.namelist():
            try:
                theme_raw_bytes = zf.read(theme_path)
                theme_root = ET.fromstring(theme_raw_bytes)
                theme_name = theme_root.get("name", "Office Theme")
                colors, fonts = StyleParser.parse_theme_xml(theme_root)
                theme_info = ThemeInfo(name=theme_name, color_scheme=colors, font_scheme=fonts)
            except Exception:
                pass

        return theme_info, theme_raw_bytes

    def _resolve_zip_path(self, base_dir: str, target: str) -> str:
        """Resolves a relative OOXML target path to an absolute path within the zip archive."""
        if target.startswith("/"):
            return target.lstrip("/")
        return os.path.normpath(os.path.join(base_dir, target)).replace("\\", "/")
