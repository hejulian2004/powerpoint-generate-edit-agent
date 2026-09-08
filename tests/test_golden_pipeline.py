"""PR4 Golden PPTX Benchmark & End-to-End Pipeline Integration Suite.

Validates the complete closed loop:
input.pptx -> PPT Parser -> PresentationIR -> Vision Snapshot ->
Agent Decision -> Tool Mutations -> Dual-Channel Rendering ->
Visual Evaluation -> Self-Healing Loop -> output.pptx
"""

import asyncio
from pathlib import Path
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    TextContentIR, FontIR, ElementStyleIR, FillStyle
)
from backend.ir.converter import import_pptx, export_pptx
from backend.eval.renderer_snapshot import SlideSnapshotRenderer
from backend.eval.visual_critic import VisualCritic
from backend.pipeline import PPTEndToEndPipeline, PipelineResult
from pptx_agent_converter.validation import validate_pptx


def test_headless_snapshot_renderer():
    """Verifies that SlideSnapshotRenderer deterministically generates valid PNG bytes and base64 URI."""
    slide = SlideIR(id="snap_slide", slide_num=1, width=1280, height=720)
    card = ShapeElementIR(
        id="card_1",
        shape_type="roundRect",
        x=100.0,
        y=150.0,
        width=300.0,
        height=200.0,
        style=dict(fill=FillStyle(type="solid", color="#1E293B"), radius=12.0)
    )
    text = TextElementIR(
        id="txt_1",
        x=120.0,
        y=170.0,
        width=260.0,
        height=80.0,
        text_content=TextContentIR.from_plain_text("Golden Architecture Snapshot")
    )
    slide.add_element(card)
    slide.add_element(text)

    # 1. Test raw PNG bytes
    png_bytes = SlideSnapshotRenderer.render_png_bytes(slide)
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500
    # Standard PNG magic signature: \x89PNG\r\n\x1a\n
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    # 2. Test base64 data URI
    data_uri = SlideSnapshotRenderer.render_data_uri(slide)
    assert isinstance(data_uri, str)
    assert data_uri.startswith("data:image/png;base64,")
    assert len(data_uri) > 600

    # 3. Test SVG output
    svg_code = SlideSnapshotRenderer.render_svg(slide)
    assert "<svg" in svg_code
    assert 'viewBox="0 0 1280 720"' in svg_code


@pytest.mark.parametrize("fixture_name", ["simple.pptx", "academic.pptx", "diagram.pptx"])
def test_golden_deck_roundtrip_fidelity(fixture_name: str, tmp_path: Path):
    """Verifies that golden benchmark presentations parse to IR and re-export without data loss."""
    fixture_path = Path("tests/fixtures") / fixture_name
    if not fixture_path.exists():
        pytest.skip(f"Fixture {fixture_name} not found")

    # 1. Parse OOXML -> PresentationIR
    pres = import_pptx(fixture_path)
    assert isinstance(pres, PresentationIR)
    assert len(pres.slides) >= 1
    assert pres.slides[0].width == 1280
    assert pres.slides[0].height == 720
    assert len(pres.slides[0].elements) >= 1

    # 2. Re-export PresentationIR -> OOXML
    out_file = tmp_path / f"re_exported_{fixture_name}"
    export_pptx(pres, out_file)
    assert out_file.exists()

    # 3. Validate output file structure
    val = validate_pptx(out_file)
    assert val["valid"] is True


def test_pipeline_new_presentation_generation(tmp_path: Path):
    """Verifies that the end-to-end pipeline can generate a new presentation from scratch."""
    async def _run():
        pipeline = PPTEndToEndPipeline()
        out_file = tmp_path / "quantum_computing.pptx"

        result: PipelineResult = await pipeline.process_deck(
            user_instruction="制作一份关于量子计算架构演进的演示文稿",
            output_path=out_file
        )

        assert result.success is True
        assert result.validation_valid is True
        assert out_file.exists()
        assert result.slide_count >= 1
        assert len(result.tools_executed) >= 1
        assert result.tools_executed[0]["tool"] == "generate_presentation"
        assert result.snapshot_uri is not None
        assert result.snapshot_uri.startswith("data:image/png;base64,")

    asyncio.run(_run())


def test_pipeline_edit_existing_deck_and_self_heal(tmp_path: Path):
    """Verifies that the pipeline parses an existing presentation, executes agent edits, and heals layout defects."""
    in_fixture = Path("tests/fixtures/simple.pptx")
    if not in_fixture.exists():
        pytest.skip("tests/fixtures/simple.pptx not found")

    async def _run():
        pipeline = PPTEndToEndPipeline()
        out_file = tmp_path / "edited_simple.pptx"

        result: PipelineResult = await pipeline.process_deck(
            input_path=in_fixture,
            user_instruction="优化当前页面，并应用科技蓝主题配色",
            output_path=out_file,
            target_slide_num=1
        )

        assert result.success is True
        assert result.validation_valid is True
        assert out_file.exists()
        assert result.input_path is not None
        assert len(result.tools_executed) >= 1
        assert result.final_score >= 80.0
        assert result.snapshot_uri is not None
        assert result.snapshot_uri.startswith("data:image/png;base64,")

    asyncio.run(_run())


def test_visual_critic_includes_raster_snapshot():
    """Verifies that VisualCritic.review_slide always packages high-resolution raster screenshot URI."""
    async def _run():
        slide = SlideIR(id="critic_snap_slide", slide_num=1, width=1280, height=720)
        slide.add_element(ShapeElementIR(id="box_critic", x=120.0, y=100.0, width=280.0, height=180.0))

        review = await VisualCritic.review_slide(slide, include_multimodal=False)

        assert review.slide_id == "critic_snap_slide"
        assert review.health_report.score >= 90.0
        assert review.snapshot_uri is not None
        assert review.snapshot_uri.startswith("data:image/png;base64,")
        review_dict = review.to_dict()
        assert "snapshot_uri" in review_dict
        assert review_dict["snapshot_uri"] == review.snapshot_uri

    asyncio.run(_run())
