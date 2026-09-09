"""Unit tests for DeckLayoutSpec -> PresentationIR Compiler (PR13 Step 4)."""

from backend.compiler.presentation_ir import compile_layout_to_presentation_ir
from backend.ir.models import ShapeElementIR, TableElementIR, TextElementIR
from backend.ir.svg_renderer import SVGRenderer
from backend.layout.engine import generate_deck_layout
from backend.pptspec.compiler import compile_pptspec_to_deckspec
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    ClaimEvidence,
    FigureReferenceEvidence,
    MetricEvidence,
    PresentationConfig,
    SlideRequest,
    TableEvidence,
)
from backend.presentation.schema import SlideType
from backend.slidespec.schema import VisualIntent


def test_layout_to_presentation_ir_end_to_end():
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="End-to-End IR Compilation"),
        evidence=[
            ClaimEvidence(id="ev_c1", content="Transformer scales linearly in representation."),
            FigureReferenceEvidence(id="ev_f1", label="Figure 3", caption="System Diagram", source_page=5),
            TableEvidence(
                id="ev_t_comp",
                columns=["Method", "Accuracy"],
                rows=[["Baseline", "78.2%"], ["Ours", "89.5%"]],
                caption="Main Comparison",
                complete_table=True,
            ),
            TableEvidence(
                id="ev_t_inc",
                columns=[],
                rows=[],
                caption="Ablation Table",
                source_page=9,
                complete_table=False,
            ),
        ],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.TITLE,
                title="Transformer Scaling",
                evidence_refs=["ev_c1"],
            ),
            SlideRequest(
                id="slide_02",
                type=SlideType.METHOD_OVERVIEW,
                title="Architecture",
                visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
                evidence_refs=["ev_f1"],
            ),
            SlideRequest(
                id="slide_03",
                type=SlideType.RESULT,
                title="Evaluation",
                visual_intent=VisualIntent.BENCHMARK_COMPARISON,
                evidence_refs=["ev_t_comp"],
            ),
            SlideRequest(
                id="slide_04",
                type=SlideType.ABLATION,
                title="Ablation Study",
                evidence_refs=["ev_t_inc"],
            ),
        ],
    )

    # 1. PPTSpec -> DeckSpec
    deck_spec = compile_pptspec_to_deckspec(spec)
    assert deck_spec.slide_count == 4

    # 2. DeckSpec -> DeckLayoutSpec
    deck_layout = generate_deck_layout(deck_spec)
    assert deck_layout.slide_count == 4

    # 3. DeckLayoutSpec -> PresentationIR
    pres_ir = compile_layout_to_presentation_ir(deck_layout)
    assert pres_ir.title == "End-to-End IR Compilation"
    assert len(pres_ir.slides) == 4
    assert pres_ir.width == 1280
    assert pres_ir.height == 720

    # Slide 1: Title
    s1 = pres_ir.slides[0]
    assert s1.slide_num == 1
    assert len(s1.elements) > 0
    # Check title text element exists
    title_elems = [e for e in s1.elements if isinstance(e, TextElementIR) and "Transformer Scaling" in e.text_content.plain_text]
    assert len(title_elems) >= 1
    # Check provenance
    assert title_elems[0].source_ref is not None

    # Slide 2: Figure Placeholder Verification
    s2 = pres_ir.slides[1]
    fig_placeholders = [
        e for e in s2.elements
        if isinstance(e, ShapeElementIR) and e.metadata.get("is_figure_placeholder") is True
    ]
    assert len(fig_placeholders) == 1
    fig_p = fig_placeholders[0]
    assert fig_p.metadata["label"] == "Figure 3"
    assert fig_p.metadata["page"] == 5
    assert "请粘贴论文原始 Figure 3" in fig_p.text_content.plain_text
    assert "System Diagram" in fig_p.text_content.plain_text
    assert fig_p.style.border.style == "dashed"
    assert fig_p.source_ref is not None

    # Slide 3: Complete Table Verification
    s3 = pres_ir.slides[2]
    tables = [e for e in s3.elements if isinstance(e, TableElementIR)]
    assert len(tables) == 1
    tbl = tables[0]
    assert tbl.cols == 2
    assert tbl.rows == 3  # 1 header + 2 data rows
    assert tbl.cells[0][0].text_content.plain_text == "Method"
    assert tbl.cells[0][1].text_content.plain_text == "Accuracy"
    assert tbl.cells[2][0].text_content.plain_text == "Ours"
    assert tbl.cells[2][1].text_content.plain_text == "89.5%"
    assert tbl.source_ref is not None

    # Slide 4: Table Placeholder Verification
    s4 = pres_ir.slides[3]
    tbl_placeholders = [
        e for e in s4.elements
        if isinstance(e, ShapeElementIR) and e.metadata.get("is_table_placeholder") is True
    ]
    assert len(tbl_placeholders) == 1
    tbl_p = tbl_placeholders[0]
    assert "请粘贴论文原始" in tbl_p.text_content.plain_text
    assert tbl_p.metadata.get("page") == 9
    assert tbl_p.style.border.style == "dashed"
    assert tbl_p.source_ref is not None

    # Verify SVG Rendering works on all slides without exceptions
    for s in pres_ir.slides:
        svg = SVGRenderer.render_slide(s)
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")
        assert f'id="{s.id}"' in svg
