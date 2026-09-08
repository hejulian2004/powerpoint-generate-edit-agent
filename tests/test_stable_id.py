"""Stable semantic element IDs tests (PR6.1 Task 5).

Verifies:
- Parsing the same PPTX twice produces identical stable ids (replay/undo/cross-render).
- Stable ids are robust to internal element-id instability (same content -> same id).
- Distinct content / position / role yield distinct ids.
- Semantic graph node summaries expose the stable id.
"""

import re
from pathlib import Path

from backend.semantic.stable_id import compute_stable_id
from backend.semantic.element_graph import SemanticElementGraph
from backend.fidelity import OOXMLParser
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ElementStyleIR, FillStyle, TextContentIR, FontIR,
)
from backend.ir import export_pptx

ID_PATTERN = re.compile(r"^[a-z_]+_[0-9a-f]{5}$")


def _build_pres(element_id: str) -> PresentationIR:
    pres = PresentationIR(title="Stable")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id=element_id, name="Slide Title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Quarterly Performance Review", font=FontIR(name="Segoe UI", size=26.0)
        )
    ))
    slide.add_element(ShapeElementIR(
        id=f"{element_id}_card", name="KPI Card", shape_type="roundRect",
        x=80.0, y=160.0, width=300.0, height=140.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#2563EB"))
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _export(tmp_path: Path, pres: PresentationIR) -> Path:
    out = tmp_path / "stable.pptx"
    export_pptx(pres, str(out))
    return out


def _graph_from_path(path: Path):
    pres = OOXMLParser(path).parse()
    return SemanticElementGraph(pres.slides[0])


# =====================================================================
# Determinism
# =====================================================================

def test_same_deck_parsed_twice_yields_same_stable_ids(tmp_path):
    out = _export(tmp_path, _build_pres("elem_a"))
    g1 = _graph_from_path(out)
    g2 = _graph_from_path(out)
    assert set(g1.stable_ids.keys()) == set(g2.stable_ids.keys())
    for eid in g1.stable_ids:
        assert g1.stable_ids[eid] == g2.stable_ids[eid]


def test_stable_id_survives_element_id_instability():
    """Same content/position/role but different internal ids -> identical stable ids."""
    g1 = SemanticElementGraph(_build_pres("elem_1").slides[0])
    g2 = SemanticElementGraph(_build_pres("elem_2").slides[0])
    # The first text element carries the same content/bbox in both, so stable ids match.
    assert g1.stable_ids["elem_1"] == g2.stable_ids["elem_2"]


# =====================================================================
# Discrimination
# =====================================================================

def test_distinct_elements_have_distinct_stable_ids():
    slide = _build_pres("elem_1").slides[0]
    graph = SemanticElementGraph(slide)
    ids = set(graph.stable_ids.values())
    assert len(ids) == len(graph.stable_ids), "distinct elements must not share a stable id"


def test_content_change_changes_stable_id():
    slide = _build_pres("elem_1").slides[0]
    original = compute_stable_id(slide.get_element("elem_1"), role="slide_title", slide=slide)
    slide.get_element("elem_1").text_content.paragraphs[0].runs[0].text = "Changed Title"
    changed = compute_stable_id(slide.get_element("elem_1"), role="slide_title", slide=slide)
    assert original != changed


def test_bbox_change_changes_stable_id():
    slide = _build_pres("elem_1").slides[0]
    original = compute_stable_id(slide.get_element("elem_1"), role="slide_title", slide=slide)
    slide.get_element("elem_1").x = 500.0
    moved = compute_stable_id(slide.get_element("elem_1"), role="slide_title", slide=slide)
    assert original != moved


# =====================================================================
# Format & integration
# =====================================================================

def test_stable_id_format():
    slide = _build_pres("elem_1").slides[0]
    sid = compute_stable_id(slide.get_element("elem_1"), role="slide_title", slide=slide)
    assert ID_PATTERN.match(sid), f"unexpected stable id format: {sid}"
    assert sid.startswith("slide_title_")


def test_node_summary_exposes_stable_id():
    slide = _build_pres("elem_1").slides[0]
    graph = SemanticElementGraph(slide)
    summary = graph.get_node_summary("elem_1")
    assert summary is not None
    assert "stable_id" in summary
    assert summary["stable_id"] == graph.stable_ids["elem_1"]