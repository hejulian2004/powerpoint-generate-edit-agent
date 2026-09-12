"""Trusted paper crop -> ImageElementIR resolution tests (Batch 1.5)."""

from __future__ import annotations

from pathlib import Path

from backend.compiler.presentation_ir import compile_layout_to_presentation_ir
from backend.design.layout_compiler import compile_llm_layout
from backend.design.layout_schema import LLMLayoutPlan
from backend.design.paper_assets import make_paper_asset_resolver
from backend.ir.models import ImageElementIR, ShapeElementIR
from backend.layout.schema import Canvas, DeckLayoutSpec
from backend.paper.schema import PaperFigure, PaperIR, PaperMetadata
from backend.paper_visual.schema import (
    PaperPageAsset,
    PaperPageVisual,
    PaperVisualIR,
    VisualRegion,
)
from backend.presentation.schema import SlideType
from backend.slidespec.schema import FigureBlock, SlideSpec, VisualIntent


def _slide_spec() -> SlideSpec:
    return SlideSpec(
        index=1,
        slide_type=SlideType.RESULT,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        title="Result",
        blocks=[
            FigureBlock(
                block_id="fig_block",
                source_figure_id="figure1",
                caption="Pipeline",
                xref_label="Fig. 1",
            )
        ],
    )


def _figure_layout():
    payload = {
        "slide_id": "slide_1",
        "elements": [
            {
                "element_id": "fig",
                "source_block_id": "fig_block",
                "element_type": "FIGURE",
                "x": 80,
                "y": 80,
                "width": 500,
                "height": 300,
                "content": {},
            }
        ],
    }
    return compile_llm_layout(LLMLayoutPlan.model_validate(payload), _slide_spec())


def _visual_ir(crop_path: str) -> PaperVisualIR:
    asset = PaperPageAsset(
        page_number=1, image_path=str(Path(crop_path).parent / "page_001.webp"),
        width=1280, height=720, dpi=144,
    )
    region = VisualRegion(
        region_id="page_001_region_001",
        page_number=1,
        region_type="figure",
        bbox=[0.1, 0.1, 0.5, 0.5],
        source_figure_id="figure1",
        crop_path=crop_path,
    )
    return PaperVisualIR(
        pages=[PaperPageVisual(page_number=1, page_asset=asset, regions=[region])]
    )


def _paper_ir() -> PaperIR:
    return PaperIR(
        source_filename="p.pdf",
        metadata=PaperMetadata(title="P", page_count=1),
        figures=[PaperFigure(id="figure1", caption="Pipeline", page=1)],
    )


def test_figure_resolves_to_image_element(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    crop = cache / "figure1.webp"
    crop.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")

    resolver = make_paper_asset_resolver(_paper_ir(), _visual_ir(str(crop)), str(cache))
    desk = DeckLayoutSpec(title="T", canvas=Canvas(), slides=[_figure_layout()])
    pres = compile_layout_to_presentation_ir(desk, asset_resolver=resolver)

    element = pres.slides[0].elements[0]
    assert isinstance(element, ImageElementIR)
    assert element.src.startswith("data:image/webp;base64,")
    assert pres.assets
    assert element.metadata["asset_status"] == "resolved"
    assert element.metadata["source_figure_id"] == "figure1"


def test_figure_without_trusted_crop_falls_back_to_placeholder(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "secret.webp"
    outside.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")

    resolver = make_paper_asset_resolver(_paper_ir(), _visual_ir(str(outside)), str(cache))
    desk = DeckLayoutSpec(title="T", canvas=Canvas(), slides=[_figure_layout()])
    pres = compile_layout_to_presentation_ir(desk, asset_resolver=resolver)

    element = pres.slides[0].elements[0]
    assert isinstance(element, ShapeElementIR)
    assert element.metadata.get("is_figure_placeholder") is True
    assert element.metadata["asset_status"] == "placeholder"
    assert element.metadata["source_figure_id"] == "figure1"
