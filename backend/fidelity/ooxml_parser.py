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

# 1 inch = 914400 EMU. Standard canvas: 1280 x 720 px.
DEFAULT_EMU_WIDTH = 12192000   # 13.333 inches
DEFAULT_EMU_HEIGHT = 6858000   # 7.5 inches


class OOXMLParser:
    """Parses a PPTX archive directly into PresentationIR with full theme & style fidelity."""

    def __init__(self, pptx_source: Union[str, bytes, io.BytesIO]):
        self.source = pptx_source

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
            emu_w, emu_h, slide_r_ids = self._parse_presentation_xml(zf, namelist)
            scale_x = 1280.0 / (emu_w / 914400.0 * 96.0) if emu_w > 0 else 1.0
            scale_y = 720.0 / (emu_h / 914400.0 * 96.0) if emu_h > 0 else 1.0
            # Direct EMU to 1280x720 canvas factors
            emu_to_canvas_x = 1280.0 / emu_w if emu_w > 0 else 1280.0 / DEFAULT_EMU_WIDTH
            emu_to_canvas_y = 720.0 / emu_h if emu_h > 0 else 720.0 / DEFAULT_EMU_HEIGHT

            # 2. Parse Theme from ppt/theme/theme1.xml
            theme_engine = self._parse_theme(zf, namelist)
            style_resolver = StyleResolver(theme_engine)

            # 3. Read Media assets
            assets, asset_metadata = self._read_media(zf, namelist)

            # 4. Presentation Rels
            pres_rels = self._read_rels(zf, "ppt/_rels/presentation.xml.rels", namelist)

            # 5. Parse Slides
            slides: List[SlideIR] = []
            slide_paths = self._find_slide_paths(slide_r_ids, pres_rels, namelist)

            for s_idx, slide_zip_path in enumerate(slide_paths, start=1):
                slide_rels_path = self._get_rels_path(slide_zip_path)
                slide_rels = self._read_rels(zf, slide_rels_path, namelist)

                slide_xml = zf.read(slide_zip_path)
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

            pres_title = "Converted Presentation"
            if isinstance(self.source, str):
                pres_title = os.path.splitext(os.path.basename(self.source))[0]

            return PresentationIR(
                title=pres_title,
                width=1280,
                height=720,
                theme=theme_engine.to_dict(),
                slides=slides,
                active_slide_id=slides[0].id if slides else None,
                version=1,
                assets=assets,
                asset_metadata=asset_metadata
            )

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
                except Exception:
                    pass
        return ThemeEngine()

    def _read_media(
        self, zf: zipfile.ZipFile, namelist: set
    ) -> Tuple[Dict[str, str], Dict[str, Any]]:
        assets: Dict[str, str] = {}
        metadata: Dict[str, Any] = {}
        for path in namelist:
            if path.startswith("ppt/media/"):
                fname = os.path.basename(path)
                data = zf.read(path)
                b64 = base64.b64encode(data).decode("utf-8")
                ext = fname.split(".")[-1].lower() if "." in fname else "png"
                mime = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
                assets[fname] = f"data:{mime};base64,{b64}"
                metadata[fname] = {"mime_type": mime, "size_bytes": len(data), "filename": fname}
        return assets, metadata

    def _read_rels(
        self, zf: zipfile.ZipFile, rels_path: str, namelist: set
    ) -> RelationshipGraph:
        if rels_path in namelist:
            try:
                return RelationshipGraph.from_xml_bytes(zf.read(rels_path), rels_path)
            except Exception:
                pass
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
            bg_fill = self._parse_fill_element(bg_elem, theme)

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

        children: List[ElementIR] = []
        for child in grpSp:
            tag = child.tag.split("}")[-1]
            if tag == "sp":
                c = self._parse_shape(child, scale_x, scale_y, theme, style_resolver)
                if c:
                    children.append(c)
            elif tag == "pic":
                c = self._parse_pic(child, scale_x, scale_y, slide_rels, assets)
                if c:
                    children.append(c)
            elif tag == "cxnSp":
                c = self._parse_connector(child, scale_x, scale_y, theme, style_resolver)
                if c:
                    children.append(c)
            elif tag == "grpSp":
                c = self._parse_group(child, scale_x, scale_y, theme, style_resolver, slide_rels, assets)
                if c:
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

    def _extract_color(
        self, parent: ET.Element, theme: ThemeEngine
    ) -> Tuple[str, float, Optional[str]]:
        srgb = parent.find(".//a:srgbClr", NS)
        if srgb is not None and srgb.get("val"):
            alpha = self._parse_alpha(srgb)
            return f"#{srgb.get('val').upper()}", alpha, None

        scheme = parent.find(".//a:schemeClr", NS)
        if scheme is not None and scheme.get("val"):
            val = scheme.get("val")
            alpha = self._parse_alpha(scheme)
            resolved = theme.resolve_color(val)
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
            if pPr is not None and pPr.get("algn"):
                raw_algn = pPr.get("algn")
                if raw_algn in ["ctr", "center"]:
                    align = "center"
                elif raw_algn in ["r", "right"]:
                    align = "right"
                elif raw_algn in ["just", "justify"]:
                    align = "justify"

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

            paragraphs.append(ParagraphIR(align=align, runs=runs))

        return TextContentIR(paragraphs=paragraphs)
