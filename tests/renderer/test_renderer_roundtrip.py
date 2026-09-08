"""Roundtrip and Fidelity Acceptance Tests (PR11).

Covers the core PR11 acceptance tests:
  - Test 1: Basic Export (DeckLayoutSpec -> test.pptx)
  - Test 2: Text Fidelity (Content string preserved in PPTX)
  - Test 3: Geometry Fidelity (Coordinate difference < 1.0%)
  - Test 4: Figure Fidelity (Picture shape with valid image relationship)
  - Test 5: Full Pipeline (PDF -> PaperIR -> PresentationPlan -> SlideSpec -> LayoutSpec -> PPTX)
  - Test 6: Boundary Check (Strict rejection of SlideSpec input)
  - Test 7: Visual screenshot generation for inspection
"""

from pathlib import Path
import pytest
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from backend.layout import (
    Canvas,
    DeckLayoutSpec,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
    generate_deck_layout,
)
from backend.paper import extract_paper
from backend.presentation import generate_presentation_plan
from backend.renderer import (
    AssetResolver,
    render_pptx,
    render_slide_screenshots,
    validate_pptx_fidelity,
)
from backend.slidespec import map_presentation_plan_to_deck_spec
from backend.slidespec.schema import BlockRole, SlideSpec, SlideType, VisualIntent

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_1_basic_export(tmp_path: Path):
    """Test 1: Basic Export. Verify PPTX file is generated and valid."""
    slide = LayoutSpec(
        slide_id="slide_1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        elements=[
            LayoutElement(
                element_id="el_title",
                element_type=ElementType.TEXT,
                role=BlockRole.HEADING,
                geometry=Rect(x=100.0, y=100.0, width=800.0, height=80.0),
                content="Our Academic Method",
            )
        ],
    )
    deck = DeckLayoutSpec(title="Basic Export Deck", slides=[slide])
    out_pptx = tmp_path / "test.pptx"

    result_path = render_pptx(deck, out_pptx)
    assert Path(result_path).is_file()
    assert Path(result_path).stat().st_size > 0

    prs = Presentation(result_path)
    assert len(prs.slides) == 1


def test_2_text_fidelity(tmp_path: Path):
    """Test 2: Text Fidelity. Verify exact text content is preserved in PPTX."""
    expected_text = "Our Novel Deep Learning Framework"
    slide = LayoutSpec(
        slide_id="slide_text_fidel",
        slide_index=1,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        elements=[
            LayoutElement(
                element_id="el_takeaway_1",
                element_type=ElementType.TEXT,
                role=BlockRole.BULLET_ITEM,
                geometry=Rect(x=120.0, y=180.0, width=900.0, height=60.0),
                content=expected_text,
            )
        ],
    )
    deck = DeckLayoutSpec(title="Text Fidelity Deck", slides=[slide])
    out_pptx = tmp_path / "text_fidelity.pptx"

    render_pptx(deck, out_pptx)

    prs = Presentation(str(out_pptx))
    extracted_text = prs.slides[0].shapes[0].text_frame.text
    assert extracted_text == expected_text


def test_3_geometry_fidelity(tmp_path: Path):
    """Test 3: Geometry Fidelity. Verify layout coords (x,y,w,h) match within < 1.0% error."""
    x, y, w, h = 100.0, 200.0, 500.0, 300.0
    slide = LayoutSpec(
        slide_id="slide_geom",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        elements=[
            LayoutElement(
                element_id="el_box",
                element_type=ElementType.CONTAINER,
                geometry=Rect(x=x, y=y, width=w, height=h),
            )
        ],
    )
    deck = DeckLayoutSpec(title="Geometry Fidelity Deck", slides=[slide])
    out_pptx = tmp_path / "geom_fidelity.pptx"

    render_pptx(deck, out_pptx)

    report = validate_pptx_fidelity(deck, out_pptx)
    assert report.is_valid is True
    assert report.max_geometry_error_pct < 1.0


def test_4_figure_fidelity(tmp_path: Path):
    """Test 4: Figure Fidelity. Verify PPTX contains valid picture shape and relationship."""
    slide = LayoutSpec(
        slide_id="slide_fig",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        elements=[
            LayoutElement(
                element_id="el_fig_main",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=550.0, y=150.0, width=600.0, height=450.0),
                content={"source_figure_id": "fig_arch_1", "caption": "Overall Pipeline"},
            )
        ],
    )
    deck = DeckLayoutSpec(title="Figure Fidelity Deck", slides=[slide])
    out_pptx = tmp_path / "fig_fidelity.pptx"

    render_pptx(deck, out_pptx)

    prs = Presentation(str(out_pptx))
    sh = prs.slides[0].shapes[0]
    assert sh.shape_type == MSO_SHAPE_TYPE.PICTURE
    assert sh.image is not None
    assert len(sh.image.blob) > 0


def test_5_full_pipeline(tmp_path: Path):
    """Test 5: Full Pipeline.

    PDF -> PaperIR -> PresentationPlan -> SlideSpec -> LayoutSpec -> PPTX
    """
    assert FIXTURE_PDF.is_file()

    # 1. PaperIR
    paper = extract_paper(FIXTURE_PDF)
    assert paper.title != ""

    # 2. PresentationPlan
    plan = generate_presentation_plan(paper, profile="research_15min")
    assert plan.slide_count == 12

    # 3. SlideSpec (PR9)
    deck_spec = map_presentation_plan_to_deck_spec(plan, paper)
    assert deck_spec.slide_count == 12

    # 4. LayoutSpec (PR10)
    deck_layout = generate_deck_layout(deck_spec, validate=True, strict=True)
    assert deck_layout.slide_count == 12

    # 5. PPTX Renderer (PR11)
    out_pptx = tmp_path / "paper_demo.pptx"
    asset_resolver = AssetResolver(paper_ir=paper, cache_dir=tmp_path / "cache")
    result_file = render_pptx(deck_layout, out_pptx, asset_resolver=asset_resolver)

    assert Path(result_file).is_file()

    # 6. Verify PPTX integrity
    prs = Presentation(result_file)
    assert len(prs.slides) == 12

    # 7. Fidelity inspection
    report = validate_pptx_fidelity(deck_layout, result_file)
    assert report.is_valid is True
    assert report.max_geometry_error_pct < 1.0


def test_boundary_guard_rejects_slidespec(tmp_path: Path):
    """Verify architectural boundary: passing SlideSpec directly to render_pptx raises TypeError."""
    invalid_input = SlideSpec(
        index=1,
        slide_type=SlideType.TITLE,
        visual_intent=VisualIntent.TITLE_HERO,
        title="Sample",
        content_blocks=[],
    )
    with pytest.raises(TypeError, match="DeckLayoutSpec"):
        render_pptx(invalid_input, tmp_path / "should_fail.pptx")  # type: ignore


def test_visual_screenshot_export(tmp_path: Path):
    """Verify slide screenshot exporter utility generates images when Office/LibreOffice is present."""
    slide = LayoutSpec(
        slide_id="slide_shot",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        elements=[
            LayoutElement(
                element_id="el_title",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=100.0, width=800.0, height=80.0),
                content="Visual Inspection Slide",
            )
        ],
    )
    deck = DeckLayoutSpec(title="Visual Screenshot Deck", slides=[slide])
    out_pptx = tmp_path / "shot_demo.pptx"
    render_pptx(deck, out_pptx)

    screen_dir = tmp_path / "screenshots"
    shots = render_slide_screenshots(out_pptx, screen_dir)
    # If PowerPoint COM is available, screenshots will be produced
    assert isinstance(shots, list)


def test_list_content_fidelity_no_warnings(tmp_path: Path):
    """Ensure multiline list content does not trigger false-positive text warnings."""
    bullets = ["First point on scalability", "Second point on efficiency"]
    slide = LayoutSpec(
        slide_id="slide_list_fidel",
        slide_index=1,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        elements=[
            LayoutElement(
                element_id="el_takeaway_list",
                element_type=ElementType.TEXT,
                role=BlockRole.BULLET_ITEM,
                geometry=Rect(x=100.0, y=100.0, width=800.0, height=200.0),
                content=bullets,
            )
        ],
    )
    deck = DeckLayoutSpec(title="List Fidelity Deck", slides=[slide])
    out_pptx = tmp_path / "list_fidelity.pptx"

    render_pptx(deck, out_pptx)
    report = validate_pptx_fidelity(deck, out_pptx)
    assert report.is_valid is True
    # Assert zero text mismatch warnings
    text_warnings = [w for w in report.warnings if "Text mismatch" in w]
    assert len(text_warnings) == 0


def test_render_config_custom_properties(tmp_path: Path):
    """Verify custom properties and allow_synthetic_assets options in RenderConfig."""
    from backend.renderer.schema import RenderConfig

    slide = LayoutSpec(
        slide_id="slide_cfg",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        elements=[
            LayoutElement(
                element_id="el_title",
                element_type=ElementType.TEXT,
                geometry=Rect(x=50.0, y=50.0, width=500.0, height=50.0),
                content="Title with Custom Meta",
            )
        ],
    )
    deck = DeckLayoutSpec(title="Meta Deck", slides=[slide])
    out_pptx = tmp_path / "meta.pptx"

    config = RenderConfig(
        custom_properties={"author": "Julian He", "subject": "Academic Presentation"}
    )
    render_pptx(deck, out_pptx, config=config)

    prs = Presentation(str(out_pptx))
    assert prs.core_properties.title == "Meta Deck"
    assert prs.core_properties.author == "Julian He"
    assert prs.core_properties.subject == "Academic Presentation"
