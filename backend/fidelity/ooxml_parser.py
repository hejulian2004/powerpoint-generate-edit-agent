"""OOXMLParser: Direct, lossless OOXML PowerPoint package parser.

Parses .pptx zip components directly into PresentationIR, resolving themes,
relationships, custom geometry adjustments, nested groups, and typography.
"""

from __future__ import annotations
import os
import io
import zipfile
import base64
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List, Tuple, Union

from .theme_engine import ThemeEngine
from .style_resolver import StyleResolver
from .relationship import RelationshipGraph, REL_TYPE_IMAGE
from .capability import CapabilityDetector, DetectedFeatures
from ..ir.models import (
    PresentationIR, SlideIR, ElementIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, ImageElementIR, TableElementIR, TableCellIR,
    GroupElementIR, TransformIR, ElementStyleIR, FillStyle, BorderStyle,
    ShadowStyle, GradientFill, GradientStop, TextContentIR, ParagraphIR,
    RunIR, FontIR
)

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

_KNOWN_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


def _looks_like_known_image(data: bytes) -> bool:
    """Returns True when the media bytes carry a recognizable raster image signature."""
    return any(data.startswith(sig) for sig, _ in _KNOWN_IMAGE_SIGNATURES)

# 1 inch = 914400 EMU. Standard canvas: 1280 x 720 px.
DEFAULT_EMU_WIDTH = 12192000   # 13.333 inches
DEFAULT_EMU_HEIGHT = 6858000   # 7.5 inches


class OOXMLParser:
    """Parses a PPTX archive directly into PresentationIR with full theme & style fidelity."""

    def __init__(self, pptx_source: Union[str, bytes, io.BytesIO]):
        self.source = pptx_source
        self._warnings: List[str] = []

    def _warn(self, message: str) -> None:
        self._warnings.append(message)

    def parse(self) -> PresentationIR:
        """Parses presentation package into PresentationIR."""
        if isinstance(self.source, (str, os.PathLike)):
            zf = zipfile.ZipFile(self.source, "r")
        elif isinstance(self.source, bytes):
            zf = zipfile.ZipFile(io.BytesIO(self.source), "r")
        else:
            zf = zipfile.ZipFile(self.source, "r")

        with zf:
            namelist = set(zf.namelist())

            # 1. Parse Dimensions from ppt/presentation.xml
            # PR6.1 failure recovery: a corrupt presentation.xml must not crash the whole
            # import; fall back to default canvas + slide discovery and surface a warning.
            try:
                emu_w, emu_h, slide_r_ids = self._parse_presentation_xml(zf, namelist)
            except Exception as e:
                self._warn(f"presentation.xml unreadable, using defaults: {e}")
                emu_w, emu_h, slide_r_ids = DEFAULT_EMU_WIDTH, DEFAULT_EMU_HEIGHT, []
            scale_x = 1280.0 / (emu_w / 914400.0 * 96.0) if emu_w > 0 else 1.0
            scale_y = 720.0 / (emu_h / 914400.0 * 96.0) if emu_h > 0 else 1.0
            # Direct EMU to 1280x720 canvas factors
            emu_to_canvas_x = 1280.0 / emu_w if emu_w > 0 else 1280.0 / DEFAULT_EMU_WIDTH
            emu_to_canvas_y = 720.0 / emu_h if emu_h > 0 else 720.0 / DEFAULT_EMU_HEIGHT

            # 2. Parse Theme from ppt/theme/theme1.xml
            theme_engine = self._parse_theme(zf, namelist)
            style_resolver = StyleResolver(theme_engine)

            # 3. Read Media assets
            try:
                assets, asset_metadata = self._read_media(zf, namelist)
            except Exception as e:
                self._warn(f"media assets unreadable, imported without media: {e}")
                assets, asset_metadata = {}, {}

            # 4. Presentation Rels
            pres_rels = self._read_rels(zf, "ppt/_rels/presentation.xml.rels", namelist)

            # 5. Parse Slides
            slides: List[SlideIR] = []
            slide_paths = self._find_slide_paths(slide_r_ids, pres_rels, namelist)

            for s_idx, slide_zip_path in enumerate(slide_paths, start=1):
                slide_rels_path = self._get_rels_path(slide_zip_path)
                slide_rels = self._read_rels(zf, slide_rels_path, namelist)

                slide_xml = zf.read(slide_zip_path)
                try:
                    slide_ir = self._parse_slide_xml(
                        slide_xml=slide_xml,
                        slide_num=s_idx,
                        scale_x=emu_to_canvas_x,
                        scale_y=emu_to_canvas_y,
                        theme=theme_engine,
                        style_resolver=style_resolver,
                        slide_rels=slide_rels,
                        assets=assets
                    )
                    slides.append(slide_ir)
                except Exception as e:
                    self._warn(f"slide {slide_zip_path} unreadable, skipped: {e}")

            if not slide_paths:
                self._warn("no slide parts found in presentation package")

            pres_title = "Converted Presentation"
            if isinstance(self.source, str):
                pres_title = os.path.splitext(os.path.basename(self.source))[0]

            pres = PresentationIR(
                title=pres_title,
                width=1280,
                height=720,
                theme=theme_engine.to_dict(),
                slides=slides,
                active_slide_id=slides[0].id if slides else None,
                version=1,
                assets=assets,
                asset_metadata=asset_metadata,
                capabilities={}
            )

            # OOXML capability detection (PR6.1): surface which features the file uses and
            # which of those the engine can only detect (chart/smartart/animation/master).
            detected = CapabilityDetector.detect_from_ir(pres, CapabilityDetector.detect_in_open_zip(zf))
            pres.capabilities = detected.to_dict()
            unsupported = detected.unsupported_warnings()

            # PR6.1 failure recovery: surface per-part parse failures as a partial import.
            all_warnings = list(self._warnings) + list(unsupported)
            pres.metadata["parser_warnings"] = all_warnings
            if unsupported:
                pres.metadata["capability_warnings"] = unsupported
            pres.metadata["parse_status"] = "partial" if all_warnings else "ok"

            return pres

    def _parse_presentation_xml(
        self, zf: zipfile.ZipFile, namelist: set
    ) -> Tuple[int, int, List[str]]:
        path = "ppt/presentation.xml"
        if path not in namelist:
            return DEFAULT_EMU_WIDTH, DEFAULT_EMU_HEIGHT, []

        tree = ET.fromstring(zf.read(path))
        sld_sz = tree.find(".//p:sldSz", NS)
        cx = int(sld_sz.get("cx", str(DEFAULT_EMU_WIDTH))) if sld_sz is not None else DEFAULT_EMU_WIDTH
        cy = int(sld_sz.get("cy", str(DEFAULT_EMU_HEIGHT))) if sld_sz is not None else DEFAULT_EMU_HEIGHT

        slide_r_ids: List[str] = []
        for sld_id in tree.findall(".//p:sldIdLst/p:sldId", NS):
            r_id = sld_id.get(f"{{{NS['r']}}}id")
            if r_id:
                slide_r_ids.append(r_id)

        return cx, cy, slide_r_ids

    def _parse_theme(self, zf: zipfile.ZipFile, namelist: set) -> ThemeEngine:
        for theme_path in ["ppt/theme/theme1.xml", "ppt/theme/theme.xml"]:
            if theme_path in namelist:
                try:
                    return ThemeEngine.from_theme_xml(zf.read(theme_path))
                except Exception as e:
                    self._warn(f"theme part {theme_path} unreadable, using default theme: {e}")
        return ThemeEngine()

    def _read_media(
        self, zf: zipfile.ZipFile, namelist: set
    ) -> Dict[str, str]:
        assets: Dict[str, str] = {}
        metadata: Dict[str, Any] = {}
        for path in namelist:
            if path.startswith("ppt/media/"):
                fname = os.path.basename(path)
                data = zf.read(path)
                ext = fname.split(".")[-1].lower() if "." in fname else "png"
                mime = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
                # PR6.1 failure recovery: flag media that does not carry a known image
                # signature so corrupt binary parts surface a warning instead of silent junk.
                if not _looks_like_known_image(data):
                    self._warn(f"media {path} has unrecognized image signature, imported as-is")
                b64 = base64.b64encode(data).decode("utf-8")
                assets[fname] = f"data:{mime};base64,{b64}"
                metadata[fname] = {"mime_type": mime, "size_bytes": len(data), "filename": fname}
        return assets, metadata

    def _read_rels(
        self, zf: zipfile.ZipFile, rels_path: str, namelist: set
    ) -> RelationshipGraph:
        if rels_path in namelist:
            try:
                data = zf.read(rels_path)
                # RelationshipGraph.from_xml_bytes swallows malformed XML internally, so
                # validate well-formedness here to surface a warning on corrupt .rels parts.
                ET.fromstring(data)
                return RelationshipGraph.from_xml_bytes(data, rels_path)
            except Exception as e:
                self._warn(f"relationships {rels_path} unreadable, using empty graph: {e}")
        return RelationshipGraph(source_path=rels_path)

    def _find_slide_paths(
        self, slide_r_ids: List[str], pres_rels: RelationshipGraph, namelist: set
    ) -> List[str]:
        paths: List[str] = []
        for r_id in slide_r_ids:
            target = pres_rels.get_target(r_id)
            if target:
                clean_target = target.lstrip("/")
                if not clean_target.startswith("ppt/"):
                    clean_target = f"ppt/{clean_target}"
                if clean_target in namelist:
                    paths.append(clean_target)

        # Fallback: scan ppt/slides/slide*.xml
        if not paths:
            slide_files = [p for p in namelist if p.startswith("ppt/slides/slide") and p.endswith(".xml")]
            # Sort numerically
            def _num_key(p):
                name = os.path.basename(p)
                digits = "".join(c for c in name if c.isdigit())
                return int(digits) if digits else 0
            paths = sorted(slide_files, key=_num_key)

        return paths

    def _get_rels_path(self, xml_path: str) -> str:
        d = os.path.dirname(xml_path)
        f = os.path.basename(xml_path)
        return f"{d}/_rels/{f}.rels"

    def _parse_slide_xml(
        self,
        slide_xml: bytes,
        slide_num: int,
        scale_x: float,
        scale_y: float,
        theme: ThemeEngine,
        style_resolver: StyleResolver,
        slide_rels: RelationshipGraph,
        assets: Dict[str, str]
    ) -> SlideIR:
        tree = ET.fromstring(slide_xml)
        sp_tree = tree.find(".//p:spTree", NS)

        elements: List[ElementIR] = []
        if sp_tree is not None:
            for child in sp_tree:
                tag = child.tag.split("}")[-1]
                if tag == "sp":
                    elem = self._parse_shape(child, scale_x, scale_y, theme, style_resolver)
                    if elem:
                        elements.append(elem)
                elif tag == "pic":
                    elem = self._parse_pic(child, scale_x, scale_y, slide_rels, assets)
                    if elem:
                        elements.append(elem)
                elif tag == "cxnSp":
                    elem = self._parse_connector(child, scale_x, scale_y, theme, style_resolver)
                    if elem:
                        elements.append(elem)
                elif tag == "grpSp":
                    elem = self._parse_group(child, scale_x, scale_y, theme, style_resolver, slide_rels, assets)
                    if elem:
                        elements.append(elem)
                elif tag == "graphicFrame":
                    elem = self._parse_table(child, scale_x, scale_y, theme, style_resolver)
                    if elem:
                        elements.append(elem)

        # Slide background
        bg_fill = FillStyle(type="solid", color="#FFFFFF", alpha=1.0)
        bg_elem = tree.find(".//p:bg", NS)
        if bg_elem is not None:
            bg_pr = bg_elem.find("p:bgPr", NS)
            bg_target = bg_pr if bg_pr is not None else bg_elem
            parsed_bg = self._parse_fill_element(bg_target, theme)
            if parsed_bg.type != "none":
                bg_fill = parsed_bg
            else:
                # p:bgRef theme fill reference (e.g. bg1 -> lt1)
                bg_ref = bg_elem.find("p:bgRef", NS)
                if bg_ref is not None:
                    scheme = bg_ref.find(".//a:schemeClr", NS)
                    if scheme is not None and scheme.get("val"):
                        color, alpha, _ = self._extract_color(bg_ref, theme)
                        bg_fill = FillStyle(type="solid", color=color, alpha=alpha)

        return SlideIR(
            id=f"slide_{slide_num:02d}",
            slide_num=slide_num,
            title=f"Slide {slide_num}",
            width=1280,
            height=720,
            background=bg_fill,
            elements=elements
        )

    def _parse_shape(
        self,
        sp: ET.Element,
        scale_x: float,
        scale_y: float,
        theme: ThemeEngine,
        style_resolver: StyleResolver
    ) -> Optional[ElementIR]:
        cNvPr = sp.find(".//p:nvSpPr/p:cNvPr", NS)
        elem_id = cNvPr.get("id", "sp_0") if cNvPr is not None else "sp_0"
        elem_name = cNvPr.get("name", "Shape") if cNvPr is not None else "Shape"

        spPr = sp.find("p:spPr", NS)
        if spPr is None:
            return None

        # Coordinates from xfrm
        xfrm = spPr.find("a:xfrm", NS)
        x, y, w, h, rot, flip_h, flip_v = self._parse_xfrm(xfrm, scale_x, scale_y)

        # Shape geometry & preset
        prstGeom = spPr.find("a:prstGeom", NS)
        stype = prstGeom.get("prst", "rect") if prstGeom is not None else "rect"

        # Adjust values
        adjust_values: Dict[str, float] = {}
        if prstGeom is not None:
            avLst = prstGeom.find("a:avLst", NS)
            if avLst is not None:
                for gd in avLst.findall("a:gd", NS):
                    name = gd.get("name", "")
                    fmla = gd.get("fmla", "")
                    if name and fmla.startswith("val "):
                        try:
                            adjust_values[name] = float(fmla.split(" ")[1])
                        except Exception:
                            pass

        # Fill & Border
        fill = self._parse_fill_element(spPr, theme)
        border = self._parse_border_element(spPr, theme)
        shadow = self._parse_shadow_element(spPr)

        # Text body
        txBody = sp.find("p:txBody", NS)
        text_content = self._parse_text_body(txBody, theme) if txBody is not None else None

        # Is this a textbox?
        is_textbox = (stype in ["textbox", "text"]) or (fill.type == "none" and border.style == "none" and text_content)

        if is_textbox:
            return TextElementIR(
                id=f"elem_{elem_id}",
                name=elem_name,
                x=x,
                y=y,
                width=w,
                height=h,
                rotation=rot,
                text_content=text_content or TextContentIR(),
                style=ElementStyleIR(fill=fill, border=border, shadow=shadow)
            )

        return ShapeElementIR(
            id=f"elem_{elem_id}",
            name=elem_name,
            shape_type=stype,
            x=x,
            y=y,
            width=w,
            height=h,
            rotation=rot,
            flip_h=flip_h,
            flip_v=flip_v,
            adjust_values=adjust_values,
            text_content=text_content,
            style=ElementStyleIR(fill=fill, border=border, shadow=shadow)
        )

    def _parse_pic(
        self,
        pic: ET.Element,
        scale_x: float,
        scale_y: float,
        slide_rels: RelationshipGraph,
        assets: Dict[str, str]
    ) -> Optional[ElementIR]:
        cNvPr = pic.find(".//p:nvPicPr/p:cNvPr", NS)
        elem_id = cNvPr.get("id", "pic_0") if cNvPr is not None else "pic_0"
        elem_name = cNvPr.get("name", "Picture") if cNvPr is not None else "Picture"

        spPr = pic.find("p:spPr", NS)
        if spPr is None:
            return None

        xfrm = spPr.find("a:xfrm", NS)
        x, y, w, h, rot, _, _ = self._parse_xfrm(xfrm, scale_x, scale_y)

        # Blip image ref
        blip = pic.find(".//a:blip", NS)
        r_id = blip.get(f"{{{NS['r']}}}embed") if blip is not None else None

        src = ""
        asset_id = None
        if r_id:
            target = slide_rels.get_target(r_id)
            if target:
                fname = os.path.basename(target)
                asset_id = fname
                src = assets.get(fname, "")

        return ImageElementIR(
            id=f"elem_{elem_id}",
            name=elem_name,
            x=x,
            y=y,
            width=w,
            height=h,
            rotation=rot,
            src=src,
            asset_id=asset_id,
            style=ElementStyleIR()
        )

    def _parse_connector(
        self,
        cxnSp: ET.Element,
        scale_x: float,
        scale_y: float,
        theme: ThemeEngine,
        style_resolver: StyleResolver
    ) -> Optional[ElementIR]:
        cNvPr = cxnSp.find(".//p:nvCxnSpPr/p:cNvPr", NS)
        elem_id = cNvPr.get("id", "cxn_0") if cNvPr is not None else "cxn_0"
        elem_name = cNvPr.get("name", "Connector") if cNvPr is not None else "Connector"

        spPr = cxnSp.find("p:spPr", NS)
        if spPr is None:
            return None

        xfrm = spPr.find("a:xfrm", NS)
        x, y, w, h, _, _, _ = self._parse_xfrm(xfrm, scale_x, scale_y)
        border = self._parse_border_element(spPr, theme)

        # Arrow types
        ln = spPr.find("a:ln", NS)
        arrow_start = "none"
        arrow_end = "triangle"
        if ln is not None:
            t_head = ln.find("a:headEnd", NS)
            t_tail = ln.find("a:tailEnd", NS)
            if t_tail is not None and t_tail.get("type"):
                arrow_end = t_tail.get("type", "triangle")
            if t_head is not None and t_head.get("type"):
                arrow_start = t_head.get("type", "none")

        return ConnectorElementIR(
            id=f"elem_{elem_id}",
            name=elem_name,
            x=x,
            y=y,
            width=w,
            height=h,
            start_x=x,
            start_y=y,
            end_x=x + w,
            end_y=y + h,
            arrow_start=arrow_start if arrow_start in ["none", "triangle", "stealth", "oval"] else "none",
            arrow_end=arrow_end if arrow_end in ["none", "triangle", "stealth", "oval"] else "triangle",
            style=ElementStyleIR(border=border)
        )

    def _parse_group(
        self,
        grpSp: ET.Element,
        scale_x: float,
        scale_y: float,
        theme: ThemeEngine,
        style_resolver: StyleResolver,
        slide_rels: RelationshipGraph,
        assets: Dict[str, str]
    ) -> Optional[ElementIR]:
        cNvPr = grpSp.find(".//p:nvGrpSpPr/p:cNvPr", NS)
        elem_id = cNvPr.get("id", "grp_0") if cNvPr is not None else "grp_0"
        elem_name = cNvPr.get("name", "Group") if cNvPr is not None else "Group"

        grpSpPr = grpSp.find("p:grpSpPr", NS)
        xfrm = grpSpPr.find("a:xfrm", NS) if grpSpPr is not None else None
        x, y, w, h, _, _, _ = self._parse_xfrm(xfrm, scale_x, scale_y)

        # Coordinate projection for child elements via a:chOff and a:chExt
        off = xfrm.find("a:off", NS) if xfrm is not None else None
        ext = xfrm.find("a:ext", NS) if xfrm is not None else None
        chOff = xfrm.find("a:chOff", NS) if xfrm is not None else None
        chExt = xfrm.find("a:chExt", NS) if xfrm is not None else None

        off_x_emu = int(off.get("x", "0")) if off is not None else 0
        off_y_emu = int(off.get("y", "0")) if off is not None else 0
        ext_cx_emu = int(ext.get("cx", "1")) if ext is not None else 1
        ext_cy_emu = int(ext.get("cy", "1")) if ext is not None else 1

        # Defaults: If chOff/chExt not specified, they equal off/ext
        ch_x_emu = int(chOff.get("x", str(off_x_emu))) if chOff is not None else off_x_emu
        ch_y_emu = int(chOff.get("y", str(off_y_emu))) if chOff is not None else off_y_emu
        ch_cx_emu = int(chExt.get("cx", str(ext_cx_emu))) if chExt is not None else ext_cx_emu
        ch_cy_emu = int(chExt.get("cy", str(ext_cy_emu))) if chExt is not None else ext_cy_emu
        if ch_cx_emu == 0: ch_cx_emu = 1
        if ch_cy_emu == 0: ch_cy_emu = 1

        child_scale_x = scale_x * (float(ext_cx_emu) / float(ch_cx_emu))
        child_scale_y = scale_y * (float(ext_cy_emu) / float(ch_cy_emu))
        origin_offset_x = (off_x_emu - ch_x_emu * (float(ext_cx_emu) / float(ch_cx_emu))) * scale_x
        origin_offset_y = (off_y_emu - ch_y_emu * (float(ext_cy_emu) / float(ch_cy_emu))) * scale_y

        children: List[ElementIR] = []
        for child in grpSp:
            tag = child.tag.split("}")[-1]
            c = None
            if tag == "sp":
                c = self._parse_shape(child, child_scale_x, child_scale_y, theme, style_resolver)
            elif tag == "pic":
                c = self._parse_pic(child, child_scale_x, child_scale_y, slide_rels, assets)
            elif tag == "cxnSp":
                c = self._parse_connector(child, child_scale_x, child_scale_y, theme, style_resolver)
            elif tag == "grpSp":
                c = self._parse_group(child, child_scale_x, child_scale_y, theme, style_resolver, slide_rels, assets)

            if c:
                c.x = round(c.x + origin_offset_x, 2)
                c.y = round(c.y + origin_offset_y, 2)
                if hasattr(c, "transform") and c.transform:
                    c.transform.x = c.x
                    c.transform.y = c.y
                children.append(c)

        # If bounding box is empty, calculate from children
        if children and (w <= 0 or h <= 0):
            min_x = min(c.x for c in children)
            min_y = min(c.y for c in children)
            max_x = max(c.x + c.width for c in children)
            max_y = max(c.y + c.height for c in children)
            x, y, w, h = min_x, min_y, max(1.0, max_x - min_x), max(1.0, max_y - min_y)

        return GroupElementIR(
            id=f"elem_{elem_id}",
            name=elem_name,
            x=x,
            y=y,
            width=w,
            height=h,
            children=children,
            style=ElementStyleIR()
        )

    def _parse_table(
        self,
        graphicFrame: ET.Element,
        scale_x: float,
        scale_y: float,
        theme: ThemeEngine,
        style_resolver: StyleResolver
    ) -> Optional[ElementIR]:
        cNvPr = graphicFrame.find(".//p:nvGraphicFramePr/p:cNvPr", NS)
        elem_id = cNvPr.get("id", "tbl_0") if cNvPr is not None else "tbl_0"
        elem_name = cNvPr.get("name", "Table") if cNvPr is not None else "Table"

        xfrm = graphicFrame.find("p:xfrm", NS)
        x, y, w, h, _, _, _ = self._parse_xfrm(xfrm, scale_x, scale_y)

        tbl = graphicFrame.find(".//a:tbl", NS)
        if tbl is None:
            return None

        tr_list = tbl.findall("a:tr", NS)
        rows_count = len(tr_list)
        cols_count = len(tr_list[0].findall("a:tc", NS)) if rows_count > 0 else 0

        cells: List[List[TableCellIR]] = []
        for r_idx, tr in enumerate(tr_list):
            row_cells: List[TableCellIR] = []
            for c_idx, tc in enumerate(tr.findall("a:tc", NS)):
                txBody = tc.find("a:txBody", NS)
                tc_text = self._parse_text_body(txBody, theme) if txBody is not None else TextContentIR()
                cell_ir = TableCellIR(
                    row=r_idx,
                    col=c_idx,
                    row_span=int(tc.get("rowSpan", "1")),
                    col_span=int(tc.get("gridSpan", "1")),
                    text_content=tc_text
                )
                row_cells.append(cell_ir)
            cells.append(row_cells)

        return TableElementIR(
            id=f"elem_{elem_id}",
            name=elem_name,
            x=x,
            y=y,
            width=w,
            height=h,
            rows=rows_count,
            cols=cols_count,
            cells=cells,
            style=ElementStyleIR()
        )

    def _parse_xfrm(
        self,
        xfrm: Optional[ET.Element],
        scale_x: float,
        scale_y: float
    ) -> Tuple[float, float, float, float, float, bool, bool]:
        """Parses DrawingML a:xfrm element into canvas coordinates."""
        if xfrm is None:
            return 0.0, 0.0, 100.0, 50.0, 0.0, False, False

        off = xfrm.find("a:off", NS)
        ext = xfrm.find("a:ext", NS)

        x_emu = int(off.get("x", "0")) if off is not None else 0
        y_emu = int(off.get("y", "0")) if off is not None else 0
        cx_emu = int(ext.get("cx", "914400")) if ext is not None else 914400
        cy_emu = int(ext.get("cy", "457200")) if ext is not None else 457200

        x = round(x_emu * scale_x, 2)
        y = round(y_emu * scale_y, 2)
        w = round(max(1.0, cx_emu * scale_x), 2)
        h = round(max(1.0, cy_emu * scale_y), 2)

        rot_val = xfrm.get("rot")
        rot = round(float(rot_val) / 60000.0, 1) if rot_val else 0.0
        flip_h = xfrm.get("flipH") == "1"
        flip_v = xfrm.get("flipV") == "1"

        return x, y, w, h, rot, flip_h, flip_v

    def _parse_fill_element(self, parent: ET.Element, theme: ThemeEngine) -> FillStyle:
        """Parses a:solidFill, a:gradFill, or a:noFill into FillStyle."""
        if parent is None:
            return FillStyle(type="none", color=None, alpha=0.0)

        if parent.find("a:noFill", NS) is not None:
            return FillStyle(type="none", color=None, alpha=0.0)

        solid = parent.find("a:solidFill", NS)
        if solid is not None:
            color, alpha, scheme = self._extract_color(solid, theme)
            return FillStyle(
                type="solid",
                color=color,
                alpha=alpha,
                theme_color=scheme
            )

        grad = parent.find("a:gradFill", NS)
        if grad is not None:
            stops: List[GradientStop] = []
            gsLst = grad.find("a:gsLst", NS)
            if gsLst is not None:
                for gs in gsLst.findall("a:gs", NS):
                    pos = float(gs.get("pos", "0")) / 100000.0
                    c, a, _ = self._extract_color(gs, theme)
                    stops.append(GradientStop(position=pos, color=c, alpha=a))

            angle = 90.0
            lin = grad.find("a:lin", NS)
            if lin is not None and lin.get("ang"):
                angle = float(lin.get("ang")) / 60000.0

            return FillStyle(
                type="gradient",
                color=stops[0].color if stops else "#2563EB",
                alpha=1.0,
                gradient=GradientFill(type="linear", angle=angle, stops=stops)
            )

        return FillStyle(type="none", color=None, alpha=0.0)

    def _parse_border_element(self, parent: ET.Element, theme: ThemeEngine) -> BorderStyle:
        ln = parent.find("a:ln", NS)
        if ln is None:
            return BorderStyle(color=None, width=0.0, style="none", alpha=0.0)

        w_emu = int(ln.get("w", "12700"))  # Default 1pt
        width_px = round(w_emu / 12700.0 * 1.333, 1)

        solid = ln.find("a:solidFill", NS)
        if solid is not None:
            color, alpha, scheme = self._extract_color(solid, theme)
            dash = "solid"
            prstDash = ln.find("a:prstDash", NS)
            if prstDash is not None and prstDash.get("val"):
                dval = prstDash.get("val")
                if "dash" in dval:
                    dash = "dashed"
                elif "dot" in dval:
                    dash = "dotted"

            return BorderStyle(
                color=color,
                width=max(0.5, width_px),
                style=dash,
                alpha=alpha,
                theme_color=scheme
            )

        return BorderStyle(color=None, width=0.0, style="none", alpha=0.0)

    def _parse_shadow_element(self, parent: ET.Element) -> ShadowStyle:
        effectLst = parent.find("a:effectLst", NS)
        if effectLst is None:
            return ShadowStyle(enabled=False)

        outerShdw = effectLst.find("a:outerShdw", NS)
        if outerShdw is not None:
            dist_emu = int(outerShdw.get("dist", "25400"))
            blur_emu = int(outerShdw.get("blurRad", "38100"))
            dir_val = float(outerShdw.get("dir", "3240000")) / 60000.0
            return ShadowStyle(
                enabled=True,
                color="#000000",
                blur=round(blur_emu / 12700.0, 1),
                distance=round(dist_emu / 12700.0, 1),
                angle=round(dir_val, 1),
                alpha=0.3
            )
        return ShadowStyle(enabled=False)

    def _extract_color_modifiers(self, elem: ET.Element) -> Dict[str, Any]:
        mods = {}
        for tag, key in [
            ("a:lumMod", "lumMod"),
            ("a:lumOff", "lumOff"),
            ("a:tint", "tint"),
            ("a:shade", "shade"),
        ]:
            child = elem.find(tag, NS)
            if child is not None and child.get("val"):
                try:
                    mods[key] = int(child.get("val"))
                except Exception:
                    pass
        return mods

    def _extract_color(
        self, parent: ET.Element, theme: ThemeEngine
    ) -> Tuple[str, float, Optional[str]]:
        srgb = parent.find(".//a:srgbClr", NS)
        if srgb is not None and srgb.get("val"):
            alpha = self._parse_alpha(srgb)
            mods = self._extract_color_modifiers(srgb)
            raw_hex = f"#{srgb.get('val').upper()}"
            resolved = theme.resolve_color(raw_hex, modifiers=mods) if mods else raw_hex
            return resolved, alpha, None

        scheme = parent.find(".//a:schemeClr", NS)
        if scheme is not None and scheme.get("val"):
            val = scheme.get("val")
            alpha = self._parse_alpha(scheme)
            mods = self._extract_color_modifiers(scheme)
            resolved = theme.resolve_color(val, modifiers=mods)
            return resolved, alpha, val

        return "#000000", 1.0, None

    def _parse_alpha(self, elem: ET.Element) -> float:
        a_elem = elem.find("a:alpha", NS)
        if a_elem is not None and a_elem.get("val"):
            try:
                return round(float(a_elem.get("val")) / 100000.0, 2)
            except Exception:
                pass
        return 1.0

    def _parse_text_body(
        self, txBody: Optional[ET.Element], theme: ThemeEngine
    ) -> TextContentIR:
        if txBody is None:
            return TextContentIR()

        paragraphs: List[ParagraphIR] = []
        for p in txBody.findall("a:p", NS):
            pPr = p.find("a:pPr", NS)
            align = "left"
            line_spacing = 1.2
            line_spacing_px: Optional[float] = None
            space_before = 0.0
            space_after = 0.0
            bullet: Optional[str] = None
            indent_level = 0
            margin_left = 0.0

            if pPr is not None:
                if pPr.get("algn"):
                    raw_algn = pPr.get("algn")
                    if raw_algn in ["ctr", "center"]:
                        align = "center"
                    elif raw_algn in ["r", "right"]:
                        align = "right"
                    elif raw_algn in ["just", "justify"]:
                        align = "justify"

                if pPr.get("lvl"):
                    try:
                        indent_level = max(0, min(9, int(pPr.get("lvl"))))
                    except Exception:
                        indent_level = 0

                lnSpc = pPr.find("a:lnSpc", NS)
                if lnSpc is not None:
                    pct = lnSpc.find("a:spcPct", NS)
                    pts = lnSpc.find("a:spcPts", NS)
                    if pct is not None and pct.get("val"):
                        line_spacing = round(float(pct.get("val")) / 100000.0, 2)
                    elif pts is not None and pts.get("val"):
                        line_spacing_px = float(pts.get("val")) / 100.0 * (96.0 / 72.0)

                spcBef = pPr.find("a:spcBef/a:spcPts", NS)
                if spcBef is not None and spcBef.get("val"):
                    space_before = round(float(spcBef.get("val")) / 100.0 * (96.0 / 72.0), 1)
                spcAft = pPr.find("a:spcAft/a:spcPts", NS)
                if spcAft is not None and spcAft.get("val"):
                    space_after = round(float(spcAft.get("val")) / 100.0 * (96.0 / 72.0), 1)

                if pPr.get("marL"):
                    try:
                        margin_left = round(float(pPr.get("marL")) / 12700.0 * (96.0 / 72.0) * 0.75, 1)
                    except Exception:
                        margin_left = 0.0

                if pPr.find("a:buNone", NS) is not None:
                    bullet = "none"
                else:
                    buChar = pPr.find("a:buChar", NS)
                    buAuto = pPr.find("a:buAutoNum", NS)
                    if buAuto is not None:
                        bullet = "number"
                    elif buChar is not None:
                        bullet = buChar.get("char") or "disc"

            runs: List[RunIR] = []
            for r in p.findall("a:r", NS):
                t = r.find("a:t", NS)
                txt = t.text if (t is not None and t.text) else ""

                rPr = r.find("a:rPr", NS)
                font_name = "Segoe UI"
                font_size = 18.0
                font_color = "#1E293B"
                bold = False
                italic = False
                theme_color = None

                if rPr is not None:
                    sz = rPr.get("sz")
                    if sz:
                        # 100ths of pt to px (1pt = 1.333px)
                        font_size = round(float(sz) / 100.0 * 1.333, 1)
                    bold = rPr.get("b") == "1"
                    italic = rPr.get("i") == "1"

                    latin = rPr.find("a:latin", NS)
                    if latin is not None and latin.get("typeface"):
                        font_name = latin.get("typeface")

                    c, _, sch = self._extract_color(rPr, theme)
                    font_color = c
                    theme_color = sch

                font_ir = FontIR(
                    name=font_name,
                    size=max(6.0, font_size),
                    color=font_color,
                    bold=bold,
                    italic=italic,
                    theme_color=theme_color
                )
                runs.append(RunIR(text=txt, font=font_ir))

            if line_spacing_px is not None:
                max_size = max((r.font.size for r in runs if r.font and r.font.size), default=18.0)
                line_spacing = round(max(0.5, min(4.0, line_spacing_px / max(max_size, 1.0))), 2)

            paragraphs.append(ParagraphIR(
                align=align,
                line_spacing=line_spacing,
                space_before=space_before,
                space_after=space_after,
                bullet=bullet,
                indent_level=indent_level,
                margin_left=margin_left,
                runs=runs
            ))

        return TextContentIR(paragraphs=paragraphs)
