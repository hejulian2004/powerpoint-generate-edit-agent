"""Media parser for extracting images and resolving slide relationships."""

from __future__ import annotations
from typing import Dict, Optional, Tuple
import os
import zipfile
import xml.etree.ElementTree as ET

from ..model.shape import ImageElement, Position
from .constants import NS, emu_to_inches, angle_to_degrees


class MediaParser:
    """Handles extracting media files and resolving image references in slides."""

    def __init__(self, zf: zipfile.ZipFile):
        self.zf = zf
        self._media_cache: Dict[str, bytes] = {}
        self._extract_all_media()

    def _extract_all_media(self):
        """Pre-index all media files in ppt/media/."""
        for name in self.zf.namelist():
            if name.startswith("ppt/media/") and not name.endswith("/"):
                filename = os.path.basename(name)
                if filename:
                    self._media_cache[filename] = self.zf.read(name)

    @property
    def media_files(self) -> Dict[str, bytes]:
        return self._media_cache

    def parse_slide_rels(self, rels_content: bytes) -> Dict[str, str]:
        """
        Parses slide relationships file (slideX.xml.rels).
        Returns mapping of rId -> target filename (e.g. 'rId2' -> 'image1.png').
        """
        rels_map: Dict[str, str] = {}
        try:
            root = ET.fromstring(rels_content)
            for rel in root.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                r_id = rel.get("Id", "")
                target = rel.get("Target", "")
                rel_type = rel.get("Type", "")
                
                if "image" in rel_type or target.startswith("../media/") or target.startswith("media/"):
                    filename = os.path.basename(target)
                    rels_map[r_id] = filename
                else:
                    rels_map[r_id] = target
        except Exception:
            pass
        return rels_map

    def parse_picture(
        self,
        pic_elem: ET.Element,
        rels_map: Dict[str, str],
        z_order: int = 0
    ) -> Optional[ImageElement]:
        """Parses a <p:pic> element into an ImageElement."""
        # Non-visual properties
        nv_pic_pr = pic_elem.find("p:nvPicPr", NS)
        elem_id = ""
        elem_name = ""
        if nv_pic_pr is not None:
            c_nv_pr = nv_pic_pr.find("p:cNvPr", NS)
            if c_nv_pr is not None:
                elem_id = c_nv_pr.get("id", "")
                elem_name = c_nv_pr.get("name", "")

        # Picture fill properties: <p:blipFill>
        blip_fill = pic_elem.find("p:blipFill", NS)
        media_rel_id = ""
        original_name = ""
        if blip_fill is not None:
            blip = blip_fill.find("a:blip", NS)
            if blip is not None:
                # r:embed attribute
                for k, v in blip.attrib.items():
                    if k.endswith("embed") or "embed" in k:
                        media_rel_id = v
                        break
                if media_rel_id in rels_map:
                    original_name = rels_map[media_rel_id]

        # Shape properties: <p:spPr>
        sp_pr = pic_elem.find("p:spPr", NS)
        pos = Position()
        rot = 0.0

        if sp_pr is not None:
            xfrm = sp_pr.find("a:xfrm", NS)
            if xfrm is not None:
                rot_val = xfrm.get("rot", "0")
                rot = angle_to_degrees(int(rot_val)) if rot_val.lstrip("-").isdigit() else 0.0

                off = xfrm.find("a:off", NS)
                ext = xfrm.find("a:ext", NS)
                x = emu_to_inches(int(off.get("x", "0"))) if off is not None and off.get("x") else 0.0
                y = emu_to_inches(int(off.get("y", "0"))) if off is not None and off.get("y") else 0.0
                w = emu_to_inches(int(ext.get("cx", "0"))) if ext is not None and ext.get("cx") else 1.0
                h = emu_to_inches(int(ext.get("cy", "0"))) if ext is not None and ext.get("cy") else 1.0
                pos = Position(x=x, y=y, width=w, height=h)

        asset_src = f"assets/{original_name}" if original_name else ""

        return ImageElement(
            id=elem_id,
            name=elem_name,
            z_order=z_order,
            position=pos,
            src=asset_src,
            original_name=original_name,
            media_rel_id=media_rel_id,
            rotation=rot
        )
