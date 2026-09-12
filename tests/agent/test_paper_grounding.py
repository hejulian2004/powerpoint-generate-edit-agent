"""Paper plan grounding: every evidence handle must resolve (merge blocker 1)."""

from __future__ import annotations

from backend.agent.graphs.generation import _validate_paper_plan_grounding
from backend.paper.schema import (
    PaperFigure,
    PaperIR,
    PaperMetadata,
    PaperSection,
    PaperTable,
)
from backend.paper_visual.schema import (
    PaperPageAsset,
    PaperPageVisual,
    PaperVisualIR,
    VisualRegion,
)
from backend.presentation.schema import PresentationPlan, SlidePlan, SlideType


def _paper_ir() -> PaperIR:
    return PaperIR(
        source_filename="p.pdf",
        metadata=PaperMetadata(title="T", page_count=3),
        abstract="Abstract.",
        sections=[PaperSection(number="1", title="Intro", page=1, paragraphs=["x"])],
        figures=[PaperFigure(id="figure1", xref_label="Figure 1", caption="c", page=2)],
        tables=[PaperTable(id="table1", xref_label="Table 1", caption="c", page=3)],
    )


def _visual_ir() -> PaperVisualIR:
    asset = PaperPageAsset(
        page_number=1, image_path="p1.webp", width=1280, height=720, dpi=144
    )
    region = VisualRegion(
        region_id="page_001_region_001",
        page_number=1,
        region_type="figure",
        bbox=[0.1, 0.1, 0.5, 0.5],
        description="d",
        importance=1.0,
        ppt_usefulness=1.0,
        source_figure_id="figure1",
    )
    return PaperVisualIR(
        source_filename="p.pdf",
        pages=[PaperPageVisual(page_number=1, page_asset=asset, regions=[region])],
    )


def _plan(**overrides) -> PresentationPlan:
    slide = SlidePlan(
        index=1,
        slide_type=SlideType.TITLE,
        title="A Research Title",
        objective="Introduce",
        **overrides,
    )
    return PresentationPlan(title="T", slides=[slide])


def test_fully_grounded_plan_passes():
    errors = _validate_paper_plan_grounding(
        _plan(
            source_sections=["1"],
            source_figures=["figure1"],
            source_tables=["table1"],
            source_pages=[2],
            visual_evidence_ids=["page_001_region_001"],
            factual_evidence_ids=["section:1", "figure:figure1", "table:table1"],
        ),
        _paper_ir(),
        paper_visual_ir=_visual_ir(),
    )
    assert errors == []


def test_every_unknown_handle_is_reported():
    errors = _validate_paper_plan_grounding(
        _plan(
            source_sections=["99"],
            source_figures=["figure9"],
            source_tables=["table9"],
            source_pages=[9],
            visual_evidence_ids=["page_999_region_999"],
            factual_evidence_ids=["section:99"],
        ),
        _paper_ir(),
        paper_visual_ir=_visual_ir(),
    )
    joined = "\n".join(errors)
    assert "INVALID_SECTION_REFERENCE" in joined
    assert "INVALID_FIGURE_REFERENCE" in joined
    assert "INVALID_TABLE_REFERENCE" in joined
    assert "INVALID_SOURCE_PAGE" in joined
    assert "INVALID_VISUAL_EVIDENCE_ID" in joined
    assert "INVALID_EVIDENCE_REFERENCE" in joined


def test_visual_evidence_requires_visual_ir():
    errors = _validate_paper_plan_grounding(
        _plan(visual_evidence_ids=["page_001_region_001"]),
        _paper_ir(),
        paper_visual_ir=None,
    )
    assert any("INVALID_VISUAL_EVIDENCE_ID" in e for e in errors)


def test_page_bounds_use_paper_page_count():
    errors = _validate_paper_plan_grounding(
        _plan(source_pages=[3]),
        _paper_ir(),
        paper_visual_ir=_visual_ir(),
    )
    assert errors == []
