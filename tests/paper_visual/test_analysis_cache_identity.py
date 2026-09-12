"""Analysis cache identity is split from the page-render cache key (Batch 3.13)."""

from __future__ import annotations

from backend.paper_visual.cache import (
    compute_analysis_fingerprint,
    load_analysis_identity,
    load_visual_ir,
    save_visual_ir,
)
from backend.paper_visual.schema import PaperPageAsset, PaperPageVisual, PaperVisualIR


def _visual_ir(vision_model: str | None) -> PaperVisualIR:
    asset = PaperPageAsset(
        page_number=1, image_path="pages/page_001.webp", width=1280, height=720, dpi=144
    )
    return PaperVisualIR(
        source_filename="x.pdf",
        source_sha256="a" * 64,
        vision_model=vision_model,
        pages=[PaperPageVisual(page_number=1, page_asset=asset, visual_summary="s")],
    )


def test_fingerprint_distinguishes_vision_models():
    assert compute_analysis_fingerprint("model-a") != compute_analysis_fingerprint("model-b")
    assert compute_analysis_fingerprint(None) == compute_analysis_fingerprint(None)


def test_visual_ir_is_stale_after_model_change(tmp_path):
    save_visual_ir(_visual_ir("model-a"), tmp_path)
    identity = load_analysis_identity(tmp_path)
    assert identity["vision_model"] == "model-a"

    fresh = load_visual_ir(tmp_path, expected_fingerprint=compute_analysis_fingerprint("model-a"))
    assert fresh is not None

    stale = load_visual_ir(tmp_path, expected_fingerprint=compute_analysis_fingerprint("model-b"))
    assert stale is None


def test_visual_ir_loads_without_expected_fingerprint(tmp_path):
    save_visual_ir(_visual_ir(None), tmp_path)
    assert load_visual_ir(tmp_path) is not None
