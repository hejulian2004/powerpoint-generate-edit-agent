"""PPTX Builder for reconstructing valid, high-fidelity OOXML PowerPoint presentations."""

from __future__ import annotations
import os
import io
import zipfile
import json
import glob
from typing import Optional, List, Dict, Any, Tuple
import xml.etree.ElementTree as ET

from ..model.slide import Presentation, Slide, SlideSize, ThemeInfo, DEFAULT_WIDTH, DEFAULT_HEIGHT
from ..model.shape import (
    BaseElement,
    ShapeElement,
    ConnectorElement,
    ImageElement,
    GroupElement
)
from ..extractor.constants import (
    NS,
    inches_to_emu,
    degrees_to_angle,
    PRESET_COLORS
)
from .style_renderer import StyleRenderer
from .shape_renderer import ShapeRenderer
from .default_theme import build_theme_xml


# Register standard OOXML namespaces globally so ElementTree generates valid p:, a:, r: prefixes
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)


class PPTXBuilder:
    """Rebuilds a complete .pptx file from Presentation/Slide domain models."""

    def __init__(self):
        pass

    def build(
        self,
        presentation: Presentation,
        output_path: str,
        base_theme_bytes: Optional[bytes] = None
    ) -> str:
        """Builds a PPTX file from the Presentation domain model and saves it to output_path."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        theme_bytes_to_use = base_theme_bytes or presentation.theme_raw_bytes

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. _rels/.rels
            zf.writestr("_rels/.rels", self._build_package_rels())

            # 2. ppt/_rels/presentation.xml.rels
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                self._build_presentation_rels(len(presentation.slides))
            )

            # 3. ppt/presentation.xml
            zf.writestr(
                "ppt/presentation.xml",
                self._build_presentation_xml(presentation)
            )

            # 4. ppt/theme/theme1.xml (schema-compliant with valid formatting and styles)
            theme_xml_str = build_theme_xml(presentation.theme, base_theme_bytes=theme_bytes_to_use)
            zf.writestr("ppt/theme/theme1.xml", theme_xml_str.encode("utf-8"))

            # 5. Master & Layout
            zf.writestr("ppt/slideMasters/slideMaster1.xml", self._build_slide_master_xml())
            zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", self._build_slide_master_rels())
            zf.writestr("ppt/slideLayouts/slideLayout1.xml", self._build_slide_layout_xml())
            zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", self._build_slide_layout_rels())

            # 6. Slides & Slide Rels
            for idx, slide in enumerate(presentation.slides, start=1):
                slide_xml, slide_rels = self._build_slide_xml_and_rels(slide, idx)
                zf.writestr(f"ppt/slides/slide{idx}.xml", slide_xml)
                zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", slide_rels)

            # 7. Media files
            media_filenames = set()
            for fname, data in presentation.media_files.items():
                clean_name = os.path.basename(fname)
                if not clean_name:
                    continue
                zf.writestr(f"ppt/media/{clean_name}", data)
                media_filenames.add(clean_name)

            # 8. [Content_Types].xml
            zf.writestr(
                "[Content_Types].xml",
                self._build_content_types(len(presentation.slides), media_filenames)
            )

        return output_path

    @classmethod
    def build_from_project(cls, project_dir: str, output_pptx: Optional[str] = None) -> str:
        """Reads presentation.json and slide_XX.json files from project_dir and compiles rebuild.pptx."""
        pres_json_path = os.path.join(project_dir, "presentation.json")
        if not os.path.exists(pres_json_path):
            raise FileNotFoundError(f"Missing presentation.json in {project_dir}")

        with open(pres_json_path, "r", encoding="utf-8") as f:
            pres_meta = json.load(f)

        name = pres_meta.get("presentation_name", "rebuild")
        size = SlideSize.from_dict(pres_meta.get("size", {}))
        theme = ThemeInfo.from_dict(pres_meta.get("theme", {}))

        # Check for preserved template theme
        template_theme_path = os.path.join(project_dir, "template", "theme1.xml")
        theme_raw_bytes = None
        if os.path.exists(template_theme_path):
            with open(template_theme_path, "rb") as tf:
                theme_raw_bytes = tf.read()

        # Read slide JSONs
        slides_dir = os.path.join(project_dir, "slides")
        slide_files = sorted(glob.glob(os.path.join(slides_dir, "slide_*.json")))
        
        slides: List[Slide] = []
        for sf in slide_files:
            with open(sf, "r", encoding="utf-8") as f:
                s_data = json.load(f)
                slide = Slide.from_dict(s_data)
                # Ensure slide size matches presentation if not explicitly set
                if not s_data.get("size"):
                    slide.size = size
                slides.append(slide)

        # Read media assets
        assets_dir = os.path.join(project_dir, "assets")
        media_files: Dict[str, bytes] = {}
        if os.path.exists(assets_dir):
            for fname in os.listdir(assets_dir):
                fpath = os.path.join(assets_dir, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "rb") as mf:
                        media_files[fname] = mf.read()

        pres = Presentation(
            name=name,
            size=size,
            theme=theme,
            slides=slides,
            media_files=media_files,
            theme_raw_bytes=theme_raw_bytes
        )

        if not output_pptx:
            output_pptx = os.path.join(project_dir, "rebuild.pptx")

        builder = cls()
        return builder.build(pres, output_pptx, base_theme_bytes=theme_raw_bytes)

    @classmethod
    def build_single_slide(
        cls,
        slide_json_path: str,
        output_pptx: Optional[str] = None,
        assets_dir: Optional[str] = None
    ) -> str:
        """Builds a 1-slide presentation from a single slide JSON file."""
        with open(slide_json_path, "r", encoding="utf-8") as f:
            slide_data = json.load(f)

        slide = Slide.from_dict(slide_data)
        media_files: Dict[str, bytes] = {}

        # Look for referenced images
        candidate_dirs = []
        if assets_dir and os.path.exists(assets_dir):
            candidate_dirs.append(assets_dir)
        slide_parent = os.path.dirname(os.path.abspath(slide_json_path))
        candidate_dirs.append(os.path.join(slide_parent, "assets"))
        candidate_dirs.append(os.path.join(os.path.dirname(slide_parent), "assets"))

        for elem in slide.elements:
            if isinstance(elem, ImageElement) and elem.src:
                img_name = os.path.basename(elem.src)
                for cdir in candidate_dirs:
                    target = os.path.join(cdir, img_name)
                    if os.path.exists(target):
                        with open(target, "rb") as imf:
                            media_files[img_name] = imf.read()
                        break

        # Check for template theme in parent directory
        theme_raw_bytes = None
        proj_template = os.path.join(os.path.dirname(slide_parent), "template", "theme1.xml")
        if os.path.exists(proj_template):
            with open(proj_template, "rb") as tf:
                theme_raw_bytes = tf.read()

        pres = Presentation(
            name="SingleSlide",
            size=slide.size,
            slides=[slide],
            media_files=media_files,
            theme_raw_bytes=theme_raw_bytes
        )

        if not output_pptx:
            base_name = os.path.splitext(os.path.basename(slide_json_path))[0]
            output_pptx = os.path.join(slide_parent, f"{base_name}.pptx")

        builder = cls()
        return builder.build(pres, output_pptx, base_theme_bytes=theme_raw_bytes)

    # -------------------------------------------------------------------------
    # XML Generation Helpers
    # -------------------------------------------------------------------------

    def _build_content_types(self, slide_count: int, media_filenames: set) -> str:
        """Generates [Content_Types].xml."""
        root = ET.Element("Types", {
            "xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"
        })
        
        # Default extension mappings
        exts = {
            "rels": "application/vnd.openxmlformats-package.relationships+xml",
            "xml": "application/xml",
            "png": "image/png",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "svg": "image/svg+xml",
            "gif": "image/gif",
            "bmp": "image/bmp"
        }
        for ext, ct in exts.items():
            ET.SubElement(root, "Default", {"Extension": ext, "ContentType": ct})

        # Overrides
        overrides = [
            ("/ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
            ("/ppt/slideMasters/slideMaster1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"),
            ("/ppt/slideLayouts/slideLayout1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"),
            ("/ppt/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml"),
        ]
        for part, ct in overrides:
            ET.SubElement(root, "Override", {"PartName": part, "ContentType": ct})

        for i in range(1, slide_count + 1):
            ET.SubElement(root, "Override", {
                "PartName": f"/ppt/slides/slide{i}.xml",
                "ContentType": "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
            })

        return self._to_xml_string(root)

    def _build_package_rels(self) -> str:
        """Generates _rels/.rels."""
        root = ET.Element("Relationships", {
            "xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"
        })
        ET.SubElement(root, "Relationship", {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
            "Target": "ppt/presentation.xml"
        })
        return self._to_xml_string(root)

    def _build_presentation_rels(self, slide_count: int) -> str:
        """
        Generates ppt/_rels/presentation.xml.rels.
        Per ECMA-376 schema, presentation.xml references slideMaster and slides.
        Theme is referenced solely by slideMaster, not presentation.xml.
        """
        root = ET.Element("Relationships", {
            "xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"
        })
        ET.SubElement(root, "Relationship", {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
            "Target": "slideMasters/slideMaster1.xml"
        })

        for i in range(1, slide_count + 1):
            ET.SubElement(root, "Relationship", {
                "Id": f"rIdSlide{i}",
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                "Target": f"slides/slide{i}.xml"
            })

        return self._to_xml_string(root)

    def _build_presentation_xml(self, pres: Presentation) -> str:
        """Generates ppt/presentation.xml."""
        root = ET.Element(f"{{{NS['p']}}}presentation")

        # Slide master list
        sld_master_lst = ET.SubElement(root, f"{{{NS['p']}}}sldMasterIdLst")
        ET.SubElement(sld_master_lst, f"{{{NS['p']}}}sldMasterId", {
            "id": "2147483648",
            f"{{{NS['r']}}}id": "rId1"
        })

        # Slide ID list
        sld_id_lst = ET.SubElement(root, f"{{{NS['p']}}}sldIdLst")
        for i in range(1, len(pres.slides) + 1):
            ET.SubElement(sld_id_lst, f"{{{NS['p']}}}sldId", {
                "id": str(255 + i),
                f"{{{NS['r']}}}id": f"rIdSlide{i}"
            })

        # Slide size
        w_emu = str(inches_to_emu(pres.size.width))
        h_emu = str(inches_to_emu(pres.size.height))
        ET.SubElement(root, f"{{{NS['p']}}}sldSz", {"cx": w_emu, "cy": h_emu})
        ET.SubElement(root, f"{{{NS['p']}}}notesSz", {"cx": "6858000", "cy": "9144000"})

        # Required defaultTextStyle per ECMA-376 schema
        ET.SubElement(root, f"{{{NS['p']}}}defaultTextStyle")

        return self._to_xml_string(root)

    def _build_slide_master_xml(self) -> str:
        """Generates standard blank ppt/slideMasters/slideMaster1.xml with valid clrMap and txStyles."""
        root = ET.Element(f"{{{NS['p']}}}sldMaster")
        cSld = ET.SubElement(root, f"{{{NS['p']}}}cSld")
        spTree = ET.SubElement(cSld, f"{{{NS['p']}}}spTree")
        
        # nvGrpSpPr
        nvGrp = ET.SubElement(spTree, f"{{{NS['p']}}}nvGrpSpPr")
        ET.SubElement(nvGrp, f"{{{NS['p']}}}cNvPr", {"id": "1", "name": ""})
        ET.SubElement(nvGrp, f"{{{NS['p']}}}cNvGrpSpPr")
        ET.SubElement(nvGrp, f"{{{NS['p']}}}nvPr")

        # grpSpPr
        grpSpPr = ET.SubElement(spTree, f"{{{NS['p']}}}grpSpPr")
        xfrm = ET.SubElement(grpSpPr, f"{{{NS['a']}}}xfrm")
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {"x": "0", "y": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {"cx": "0", "cy": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chOff", {"x": "0", "y": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chExt", {"cx": "0", "cy": "0"})

        # Required clrMap for DrawingML color resolution in master
        ET.SubElement(root, f"{{{NS['p']}}}clrMap", {
            "bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2",
            "accent1": "accent1", "accent2": "accent2", "accent3": "accent3",
            "accent4": "accent4", "accent5": "accent5", "accent6": "accent6",
            "hlink": "hlink", "folHlink": "folHlink"
        })

        # sldLayoutIdLst
        sldLayoutIdLst = ET.SubElement(root, f"{{{NS['p']}}}sldLayoutIdLst")
        ET.SubElement(sldLayoutIdLst, f"{{{NS['p']}}}sldLayoutId", {
            "id": "2147483649",
            f"{{{NS['r']}}}id": "rIdLayout1"
        })

        # Required txStyles structure
        txStyles = ET.SubElement(root, f"{{{NS['p']}}}txStyles")
        ET.SubElement(txStyles, f"{{{NS['p']}}}titleStyle")
        ET.SubElement(txStyles, f"{{{NS['p']}}}bodyStyle")
        ET.SubElement(txStyles, f"{{{NS['p']}}}otherStyle")

        return self._to_xml_string(root)

    def _build_slide_master_rels(self) -> str:
        """Generates ppt/slideMasters/_rels/slideMaster1.xml.rels."""
        root = ET.Element("Relationships", {
            "xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"
        })
        ET.SubElement(root, "Relationship", {
            "Id": "rIdLayout1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
            "Target": "../slideLayouts/slideLayout1.xml"
        })
        ET.SubElement(root, "Relationship", {
            "Id": "rIdTheme",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
            "Target": "../theme/theme1.xml"
        })
        return self._to_xml_string(root)

    def _build_slide_layout_xml(self) -> str:
        """Generates blank slide layout ppt/slideLayouts/slideLayout1.xml with clrMapOvr."""
        root = ET.Element(f"{{{NS['p']}}}sldLayout", {
            "type": "blank",
            "preserve": "1"
        })
        cSld = ET.SubElement(root, f"{{{NS['p']}}}cSld", {"name": "Blank"})
        spTree = ET.SubElement(cSld, f"{{{NS['p']}}}spTree")
        
        nvGrp = ET.SubElement(spTree, f"{{{NS['p']}}}nvGrpSpPr")
        ET.SubElement(nvGrp, f"{{{NS['p']}}}cNvPr", {"id": "1", "name": ""})
        ET.SubElement(nvGrp, f"{{{NS['p']}}}cNvGrpSpPr")
        ET.SubElement(nvGrp, f"{{{NS['p']}}}nvPr")

        grpSpPr = ET.SubElement(spTree, f"{{{NS['p']}}}grpSpPr")
        xfrm = ET.SubElement(grpSpPr, f"{{{NS['a']}}}xfrm")
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {"x": "0", "y": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {"cx": "0", "cy": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chOff", {"x": "0", "y": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chExt", {"cx": "0", "cy": "0"})

        # Required clrMapOvr
        clrOvr = ET.SubElement(root, f"{{{NS['p']}}}clrMapOvr")
        ET.SubElement(clrOvr, f"{{{NS['a']}}}masterClrMapping")

        return self._to_xml_string(root)

    def _build_slide_layout_rels(self) -> str:
        """Generates ppt/slideLayouts/_rels/slideLayout1.xml.rels."""
        root = ET.Element("Relationships", {
            "xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"
        })
        ET.SubElement(root, "Relationship", {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
            "Target": "../slideMasters/slideMaster1.xml"
        })
        return self._to_xml_string(root)

    def _build_slide_xml_and_rels(self, slide: Slide, slide_num: int) -> Tuple[str, str]:
        """Renders slide XML and its relationship XML."""
        root = ET.Element(f"{{{NS['p']}}}sld")

        cSld = ET.SubElement(root, f"{{{NS['p']}}}cSld")

        # Background
        if slide.background:
            bg = ET.SubElement(cSld, f"{{{NS['p']}}}bg")
            bgPr = ET.SubElement(bg, f"{{{NS['p']}}}bgPr")
            bg_fill = StyleRenderer.build_fill(slide.background)
            if bg_fill is not None:
                bgPr.append(bg_fill)
            ET.SubElement(bgPr, f"{{{NS['a']}}}effectLst")

        # Shape tree
        spTree = ET.SubElement(cSld, f"{{{NS['p']}}}spTree")

        nvGrp = ET.SubElement(spTree, f"{{{NS['p']}}}nvGrpSpPr")
        ET.SubElement(nvGrp, f"{{{NS['p']}}}cNvPr", {"id": "1", "name": ""})
        ET.SubElement(nvGrp, f"{{{NS['p']}}}cNvGrpSpPr")
        ET.SubElement(nvGrp, f"{{{NS['p']}}}nvPr")

        grpSpPr = ET.SubElement(spTree, f"{{{NS['p']}}}grpSpPr")
        xfrm = ET.SubElement(grpSpPr, f"{{{NS['a']}}}xfrm")
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {"x": "0", "y": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {"cx": "0", "cy": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chOff", {"x": "0", "y": "0"})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chExt", {"cx": "0", "cy": "0"})

        # Collect images and assign rIds
        image_rels: Dict[str, str] = {}  # src -> rId
        rel_counter = 2

        for elem in slide.elements:
            if isinstance(elem, ImageElement) and elem.src:
                if elem.src not in image_rels:
                    image_rels[elem.src] = f"rIdImg{rel_counter}"
                    rel_counter += 1

        # Render elements
        next_shape_id = 2

        def get_next_id():
            nonlocal next_shape_id
            val = next_shape_id
            next_shape_id += 1
            return val

        for elem in slide.elements:
            sid = get_next_id()
            if isinstance(elem, ShapeElement):
                node = ShapeRenderer.render_shape(elem, sid)
                spTree.append(node)
            elif isinstance(elem, ConnectorElement):
                node = ShapeRenderer.render_connector(elem, sid)
                spTree.append(node)
            elif isinstance(elem, ImageElement):
                r_id = image_rels.get(elem.src, "rIdImg2")
                node = ShapeRenderer.render_picture(elem, r_id, sid)
                spTree.append(node)
            elif isinstance(elem, GroupElement):
                node = ShapeRenderer.render_group(elem, sid, get_next_id, image_rels)
                spTree.append(node)

        # Build slide rels XML
        rels_root = ET.Element("Relationships", {
            "xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"
        })
        ET.SubElement(rels_root, "Relationship", {
            "Id": "rId1",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
            "Target": "../slideLayouts/slideLayout1.xml"
        })

        for src, r_id in image_rels.items():
            img_filename = os.path.basename(src)
            ET.SubElement(rels_root, "Relationship", {
                "Id": r_id,
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                "Target": f"../media/{img_filename}"
            })

        return self._to_xml_string(root), self._to_xml_string(rels_root)

    def _to_xml_string(self, elem: ET.Element) -> str:
        """Serializes an XML Element to a clean UTF-8 XML string with declaration without duplicate xmlns."""
        for k in list(elem.attrib.keys()):
            if k.startswith("xmlns:") and k in ("xmlns:p", "xmlns:a", "xmlns:r"):
                del elem.attrib[k]
        raw_xml = ET.tostring(elem, encoding="utf-8", xml_declaration=True)
        return raw_xml.decode("utf-8")
