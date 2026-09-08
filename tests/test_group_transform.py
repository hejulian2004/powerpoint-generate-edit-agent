"""DrawingML Group Transform & Hierarchical Coordinates Suite.

Validates:
1. DrawingML group coordinate mapping under non-trivial (chOff, chExt, off, ext) child spaces.
2. Nested group hierarchical transforms, regrouping, and ungrouping coordinate invariance.
"""

import xml.etree.ElementTree as ET
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, GroupElementIR
)
from backend.ir.patch import HistoryManager
from backend.agent.tools import tools
from pptx_agent_converter.extractor.constants import NS, inches_to_emu
from pptx_agent_converter.model.shape import (
    ShapeElement, GroupElement
)
from pptx_agent_converter.extractor.slide_parser import SlideParser
from pptx_agent_converter.extractor.style_parser import StyleParser
from pptx_agent_converter.extractor.shape_parser import ShapeParser
from pptx_agent_converter.extractor.text_parser import TextParser
from pptx_agent_converter.extractor.media_parser import MediaParser


def test_drawingml_group_local_coordinate_mapping():
    """Validates SlideParser child mapping when chOff != off or chExt != ext."""
    # Construct synthetic DrawingML <p:grpSp> XML
    # Group outer position: off=(2.0in, 3.0in), ext=(4.0in, 2.0in)
    # Child coordinate space: chOff=(0, 0), chExt=(2.0in, 1.0in) -> scale_x=2.0, scale_y=2.0
    # Child shape raw position in child space: off=(0.5in, 0.25in), ext=(0.5in, 0.5in)
    # Expected child position in parent space:
    #   X = 2.0 + (0.5 - 0.0) * 2.0 = 3.0 in
    #   Y = 3.0 + (0.25 - 0.0) * 2.0 = 3.5 in
    #   W = 0.5 * 2.0 = 1.0 in
    #   H = 0.5 * 2.0 = 1.0 in
    grp_xml = f"""<p:grpSp xmlns:p="{NS['p']}" xmlns:a="{NS['a']}">
        <p:nvGrpSpPr>
            <p:cNvPr id="42" name="Mapped Group"/>
            <p:cNvGrpSpPr/>
            <p:nvPr/>
        </p:nvGrpSpPr>
        <p:grpSpPr>
            <a:xfrm>
                <a:off x="{inches_to_emu(2.0)}" y="{inches_to_emu(3.0)}"/>
                <a:ext cx="{inches_to_emu(4.0)}" cy="{inches_to_emu(2.0)}"/>
                <a:chOff x="0" y="0"/>
                <a:chExt cx="{inches_to_emu(2.0)}" cy="{inches_to_emu(1.0)}"/>
            </a:xfrm>
        </p:grpSpPr>
        <p:sp>
            <p:nvSpPr>
                <p:cNvPr id="43" name="Scaled Child"/>
                <p:cNvSpPr/>
                <p:nvPr/>
            </p:nvSpPr>
            <p:spPr>
                <a:xfrm>
                    <a:off x="{inches_to_emu(0.5)}" y="{inches_to_emu(0.25)}"/>
                    <a:ext cx="{inches_to_emu(0.5)}" cy="{inches_to_emu(0.5)}"/>
                </a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
            </p:spPr>
        </p:sp>
    </p:grpSp>"""

    grp_elem = ET.fromstring(grp_xml)
    style_p = StyleParser()
    text_p = TextParser(style_p)
    shape_p = ShapeParser(style_p, text_p)
    media_p = MediaParser()
    slide_parser = SlideParser(style_p, shape_p, text_p, media_p)

    parsed_group = slide_parser._parse_group(grp_elem, rels={})

    assert isinstance(parsed_group, GroupElement)
    assert parsed_group.position.x == 2.0
    assert parsed_group.position.y == 3.0
    assert parsed_group.position.width == 4.0
    assert parsed_group.position.height == 2.0
    assert len(parsed_group.elements) == 1

    child = parsed_group.elements[0]
    assert isinstance(child, ShapeElement)
    assert abs(child.position.x - 3.0) < 1e-3, f"Expected X=3.0, got {child.position.x}"
    assert abs(child.position.y - 3.5) < 1e-3, f"Expected Y=3.5, got {child.position.y}"
    assert abs(child.position.width - 1.0) < 1e-3, f"Expected Width=1.0, got {child.position.width}"
    assert abs(child.position.height - 1.0) < 1e-3, f"Expected Height=1.0, got {child.position.height}"


def test_nested_groups_transform_and_regrouping():
    """Verifies recursive coordinate updates when groups move/scale, group, and ungroup."""
    pres = PresentationIR(title="Grouping Operations")
    slide = SlideIR(id="slide_groups", slide_num=1)

    s1 = ShapeElementIR(id="card_1", x=100.0, y=100.0, width=120.0, height=80.0)
    s2 = ShapeElementIR(id="card_2", x=260.0, y=100.0, width=120.0, height=80.0)
    slide.add_element(s1)
    slide.add_element(s2)
    pres.slides.append(slide)

    history = HistoryManager()

    # 1. Group cards via tool
    res_group = tools.execute(
        "group_elements",
        {"element_ids": ["card_1", "card_2"], "group_name": "Card Cluster"},
        pres,
        history
    )
    assert res_group["success"] is True
    gid = res_group["group_id"]
    grp = slide.get_element(gid)
    assert isinstance(grp, GroupElementIR)
    assert grp.x == 100.0
    assert grp.y == 100.0
    assert grp.width == 280.0  # 260 + 120 - 100
    assert grp.height == 80.0

    # 2. Update group position via update_element tool (translate +50, +30)
    res_update = tools.execute(
        "update_element",
        {"element_id": gid, "x": 150.0, "y": 130.0},
        pres,
        history
    )
    assert res_update["success"] is True
    assert grp.x == 150.0
    assert grp.y == 130.0

    # Verify children shifted synchronously
    c1 = grp.get_child("card_1")
    c2 = grp.get_child("card_2")
    assert c1.x == 150.0  # 100 + 50
    assert c1.y == 130.0  # 100 + 30
    assert c2.x == 310.0  # 260 + 50
    assert c2.y == 130.0  # 100 + 30

    # 3. Ungroup via tool and verify children positions remain invariant
    res_ungroup = tools.execute(
        "ungroup_elements",
        {"group_id": gid},
        pres,
        history
    )
    assert res_ungroup["success"] is True
    assert slide.get_element(gid) is None

    restored_c1 = slide.get_element("card_1")
    restored_c2 = slide.get_element("card_2")
    assert restored_c1 is not None
    assert restored_c2 is not None
    assert restored_c1.x == 150.0
    assert restored_c1.y == 130.0
    assert restored_c2.x == 310.0
    assert restored_c2.y == 130.0
