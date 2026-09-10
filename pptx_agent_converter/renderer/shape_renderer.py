"""Shape renderer for creating OOXML shape and connector XML nodes."""

from __future__ import annotations
from typing import Optional, Dict, Any, Tuple
import xml.etree.ElementTree as ET

from ..model.shape import (
    ShapeElement,
    ConnectorElement,
    ImageElement,
    GroupElement,
    Position
)
from ..extractor.constants import (
    NS,
    inches_to_emu,
    degrees_to_angle,
    REVERSE_GEOM_MAP
)
from .style_renderer import StyleRenderer


class ShapeRenderer:
    """Constructs PresentationML XML nodes for shapes, textboxes, connectors, and pictures."""

    @staticmethod
    def render_shape(shape: ShapeElement, shape_id_num: int) -> ET.Element:
        """Constructs a <p:sp> element from ShapeElement."""
        sp = ET.Element(f"{{{NS['p']}}}sp")

        # 1. Non-visual shape properties <p:nvSpPr>
        nv_sp_pr = ET.SubElement(sp, f"{{{NS['p']}}}nvSpPr")
        elem_name = shape.name or f"Shape {shape_id_num}"
        c_nv_pr = ET.SubElement(nv_sp_pr, f"{{{NS['p']}}}cNvPr", {
            "id": str(shape_id_num),
            "name": elem_name
        })
        
        c_nv_sp_pr_attrs = {}
        if shape.type == "textbox" or shape.shape_type == "textbox":
            c_nv_sp_pr_attrs["txBox"] = "1"
        ET.SubElement(nv_sp_pr, f"{{{NS['p']}}}cNvSpPr", c_nv_sp_pr_attrs)
        ET.SubElement(nv_sp_pr, f"{{{NS['p']}}}nvPr")

        # 2. Shape properties <p:spPr>
        sp_pr = ET.SubElement(sp, f"{{{NS['p']}}}spPr")

        # Transform <a:xfrm>
        xfrm_attrs = {}
        if shape.rotation:
            xfrm_attrs["rot"] = str(degrees_to_angle(shape.rotation))
        if shape.flip_h:
            xfrm_attrs["flipH"] = "1"
        if shape.flip_v:
            xfrm_attrs["flipV"] = "1"

        xfrm = ET.SubElement(sp_pr, f"{{{NS['a']}}}xfrm", xfrm_attrs)
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {
            "x": str(inches_to_emu(shape.position.x)),
            "y": str(inches_to_emu(shape.position.y))
        })
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {
            "cx": str(inches_to_emu(shape.position.width)),
            "cy": str(inches_to_emu(shape.position.height))
        })

        # Geometry <a:prstGeom>
        # Note: OOXML has no "textbox" preset geometry. Textboxes use prst="rect"
        # combined with txBox="1" on <p:cNvSpPr> (set above). Emitting prst="textbox"
        # produces a package PowerPoint refuses to open.
        raw_geom = REVERSE_GEOM_MAP.get(shape.shape_type, shape.shape_type)
        if raw_geom == "textbox":
            raw_geom = "rect"
        prst_geom = ET.SubElement(sp_pr, f"{{{NS['a']}}}prstGeom", {"prst": raw_geom})
        av_lst = ET.SubElement(prst_geom, f"{{{NS['a']}}}avLst")

        # Handle roundRect corner radius adjustment if specified.
        # shape.radius is expressed in pixels at 96 DPI. OOXML "adj" is a ratio
        # of half the smaller side (0..50000, where 50000 == fully rounded pill):
        #   radius_px = adj / 100000 * min(w, h)_px
        # so writing a pixel value directly as adj produced oversized (>50000)
        # corners that PowerPoint clamps to full pills.
        if shape.shape_type in ("roundRect", "round_rect") and shape.radius is not None:
            min_side_in = min(shape.position.width, shape.position.height)
            if min_side_in > 0:
                min_side_px = min_side_in * 96.0
                adj_val = int(round(max(0.0, min(shape.radius / min_side_px, 0.5)) * 100000))
                adj_val = max(0, min(adj_val, 50000))
            else:
                adj_val = 0
            ET.SubElement(av_lst, f"{{{NS['a']}}}gd", {"name": "adj", "fmla": f"val {adj_val}"})

        # Fill
        fill_elem = StyleRenderer.build_fill(shape.fill)
        if fill_elem is not None:
            sp_pr.append(fill_elem)

        # Line / Border
        if shape.line is not None:
            line_elem = StyleRenderer.build_line(shape.line)
            if line_elem is not None:
                sp_pr.append(line_elem)
        elif shape.type == "textbox" or shape.shape_type == "textbox":
            # Default textboxes have no border
            sp_pr.append(ET.Element(f"{{{NS['a']}}}ln"))
            sp_pr[-1].append(ET.Element(f"{{{NS['a']}}}noFill"))

        # Shadow
        if shape.shadow and shape.shadow.enabled:
            shadow_elem = StyleRenderer.build_shadow(shape.shadow)
            if shadow_elem is not None:
                sp_pr.append(shadow_elem)

        # 3. Text body <p:txBody>
        if shape.text is not None:
            tx_body = StyleRenderer.build_tx_body(shape.text)
            if tx_body is not None:
                sp.append(tx_body)

        return sp

    @staticmethod
    def render_connector(connector: ConnectorElement, shape_id_num: int) -> ET.Element:
        """Constructs a <p:cxnSp> element from ConnectorElement."""
        cxn_sp = ET.Element(f"{{{NS['p']}}}cxnSp")

        # 1. Non-visual connector properties <p:nvCxnSpPr>
        nv_cxn_pr = ET.SubElement(cxn_sp, f"{{{NS['p']}}}nvCxnSpPr")
        elem_name = connector.name or f"Connector {shape_id_num}"
        ET.SubElement(nv_cxn_pr, f"{{{NS['p']}}}cNvPr", {
            "id": str(shape_id_num),
            "name": elem_name
        })

        c_nv_cxn = ET.SubElement(nv_cxn_pr, f"{{{NS['p']}}}cNvCxnSpPr")
        if connector.start_shape_id:
            ET.SubElement(c_nv_cxn, f"{{{NS['a']}}}stCxn", {"id": str(connector.start_shape_id)})
        if connector.end_shape_id:
            ET.SubElement(c_nv_cxn, f"{{{NS['a']}}}endCxn", {"id": str(connector.end_shape_id)})

        ET.SubElement(nv_cxn_pr, f"{{{NS['p']}}}nvPr")

        # 2. Shape properties <p:spPr>
        sp_pr = ET.SubElement(cxn_sp, f"{{{NS['p']}}}spPr")

        # Bounding box & flip calculation for accurate arrow direction
        sx, sy = connector.start
        ex, ey = connector.end

        min_x = min(sx, ex)
        max_x = max(sx, ex)
        min_y = min(sy, ey)
        max_y = max(sy, ey)

        cx = max_x - min_x
        cy = max_y - min_y

        # If connector is purely horizontal or vertical, set minimal thickness if needed or keep 0
        flip_h = (ex < sx)
        flip_v = (ey < sy)

        xfrm_attrs = {}
        if flip_h:
            xfrm_attrs["flipH"] = "1"
        if flip_v:
            xfrm_attrs["flipV"] = "1"

        xfrm = ET.SubElement(sp_pr, f"{{{NS['a']}}}xfrm", xfrm_attrs)
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {
            "x": str(inches_to_emu(min_x)),
            "y": str(inches_to_emu(min_y))
        })
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {
            "cx": str(inches_to_emu(cx)),
            "cy": str(inches_to_emu(cy))
        })

        # Geometry
        prst_val = "straightConnector1"
        if connector.connector_type == "bent":
            prst_val = "bentConnector3"
        elif connector.connector_type == "curved":
            prst_val = "curvedConnector3"

        prst_geom = ET.SubElement(sp_pr, f"{{{NS['a']}}}prstGeom", {"prst": prst_val})
        ET.SubElement(prst_geom, f"{{{NS['a']}}}avLst")

        # Line styling and arrow markers
        line = connector.line
        if connector.arrow_end:
            line.arrow_end = connector.arrow_end
        if connector.arrow_start:
            line.arrow_start = connector.arrow_start

        line_elem = StyleRenderer.build_line(line)
        if line_elem is not None:
            sp_pr.append(line_elem)

        return cxn_sp

    @staticmethod
    def render_picture(image: ImageElement, r_id: str, shape_id_num: int) -> ET.Element:
        """Constructs a <p:pic> element from ImageElement."""
        pic = ET.Element(f"{{{NS['p']}}}pic")

        # 1. Non-visual picture properties <p:nvPicPr>
        nv_pic_pr = ET.SubElement(pic, f"{{{NS['p']}}}nvPicPr")
        elem_name = image.name or f"Picture {shape_id_num}"
        ET.SubElement(nv_pic_pr, f"{{{NS['p']}}}cNvPr", {
            "id": str(shape_id_num),
            "name": elem_name
        })
        c_nv_pic = ET.SubElement(nv_pic_pr, f"{{{NS['p']}}}cNvPicPr")
        ET.SubElement(c_nv_pic, f"{{{NS['a']}}}picLocks", {"noChangeAspect": "1"})
        ET.SubElement(nv_pic_pr, f"{{{NS['p']}}}nvPr")

        # 2. Picture fill <p:blipFill>
        blip_fill = ET.SubElement(pic, f"{{{NS['p']}}}blipFill")
        ET.SubElement(blip_fill, f"{{{NS['a']}}}blip", {f"{{{NS['r']}}}embed": r_id})
        stretch = ET.SubElement(blip_fill, f"{{{NS['a']}}}stretch")
        ET.SubElement(stretch, f"{{{NS['a']}}}fillRect")

        # 3. Shape properties <p:spPr>
        sp_pr = ET.SubElement(pic, f"{{{NS['p']}}}spPr")
        xfrm_attrs = {}
        if image.rotation:
            xfrm_attrs["rot"] = str(degrees_to_angle(image.rotation))

        xfrm = ET.SubElement(sp_pr, f"{{{NS['a']}}}xfrm", xfrm_attrs)
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {
            "x": str(inches_to_emu(image.position.x)),
            "y": str(inches_to_emu(image.position.y))
        })
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {
            "cx": str(inches_to_emu(image.position.width)),
            "cy": str(inches_to_emu(image.position.height))
        })

        prst_geom = ET.SubElement(sp_pr, f"{{{NS['a']}}}prstGeom", {"prst": "rect"})
        ET.SubElement(prst_geom, f"{{{NS['a']}}}avLst")

        return pic

    @staticmethod
    def render_group(
        group: GroupElement,
        shape_id_num: int,
        get_next_id_func,
        img_rel_map: Dict[str, str]
    ) -> ET.Element:
        """Constructs a <p:grpSp> element recursively."""
        grp_sp = ET.Element(f"{{{NS['p']}}}grpSp")

        # Non-visual group properties
        nv_grp_pr = ET.SubElement(grp_sp, f"{{{NS['p']}}}nvGrpSpPr")
        elem_name = group.name or f"Group {shape_id_num}"
        ET.SubElement(nv_grp_pr, f"{{{NS['p']}}}cNvPr", {
            "id": str(shape_id_num),
            "name": elem_name
        })
        ET.SubElement(nv_grp_pr, f"{{{NS['p']}}}cNvGrpSpPr")
        ET.SubElement(nv_grp_pr, f"{{{NS['p']}}}nvPr")

        # Ensure valid group bounds
        if (group.position.width <= 0 or group.position.height <= 0) and group.elements:
            group.recompute_bounds()

        gx_emu = inches_to_emu(group.position.x)
        gy_emu = inches_to_emu(group.position.y)
        gw_emu = max(inches_to_emu(group.position.width), 1)
        gh_emu = max(inches_to_emu(group.position.height), 1)

        # Group shape properties (DrawingML xfrm: off, ext, chOff, chExt)
        grp_sp_pr = ET.SubElement(grp_sp, f"{{{NS['p']}}}grpSpPr")
        xfrm = ET.SubElement(grp_sp_pr, f"{{{NS['a']}}}xfrm")
        ET.SubElement(xfrm, f"{{{NS['a']}}}off", {"x": str(gx_emu), "y": str(gy_emu)})
        ET.SubElement(xfrm, f"{{{NS['a']}}}ext", {"cx": str(gw_emu), "cy": str(gh_emu)})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chOff", {"x": str(gx_emu), "y": str(gy_emu)})
        ET.SubElement(xfrm, f"{{{NS['a']}}}chExt", {"cx": str(gw_emu), "cy": str(gh_emu)})

        for child in group.elements:
            cid = get_next_id_func()
            if isinstance(child, ShapeElement):
                grp_sp.append(ShapeRenderer.render_shape(child, cid))
            elif isinstance(child, ConnectorElement):
                grp_sp.append(ShapeRenderer.render_connector(child, cid))
            elif isinstance(child, ImageElement):
                r_id = img_rel_map.get(child.src, "rId2")
                grp_sp.append(ShapeRenderer.render_picture(child, r_id, cid))
            elif isinstance(child, GroupElement):
                grp_sp.append(ShapeRenderer.render_group(child, cid, get_next_id_func, img_rel_map))

        return grp_sp
