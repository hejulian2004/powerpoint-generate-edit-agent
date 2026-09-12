"""PaperVisualIR schema contract tests."""

from __future__ import annotations

from backend.paper_visual.schema import (
    PaperPageAsset,
    PaperPageVisual,
    PaperVisualIR,
    VisualRegion,
)


def _asset(page: int = 1) -> PaperPageAsset:
    return PaperPageAsset(page_number=page, image_path=f"pages/page_{page:03d}.webp",
                          width=1224, height=1584, dpi=144, sha256="a" * 64)


def _region(region_id: str, page: int, bbox) -> VisualRegion:
    return VisualRegion(region_id=region_id, page_number=page, region_type="figure",
                        bbox=bbox, description="arch", importance=0.9, ppt_usefulness=0.8)


def test_visual_ir_json_roundtrip():
    ir = PaperVisualIR(
        source_filename="paper.pdf",
        source_sha256="b" * 64,
        pages=[
            PaperPageVisual(
                page_number=1,
                page_asset=_asset(1),
                visual_summary="one figure",
                visual_importance=0.7,
                density="high",
                regions=[_region("page_001_region_001", 1, [0.1, 0.2, 0.5, 0.6])],
                design_observations=["left-aligned"],
            )
        ],
        vision_model="vision-x",
        warnings=["note"],
    )
    restored = PaperVisualIR.model_validate_json(ir.model_dump_json())
    assert restored == ir
    assert restored.page_count == 1
    assert restored.page_by_number(1) is not None
    assert restored.page_by_number(2) is None
    assert restored.visual_evidence_ids() == ["page_001_region_001"]


def test_bbox_is_normalized_and_clamped():
    region = _region("r", 1, [-0.5, 1.4, 0.2, 0.3])
    x0, y0, x1, y1 = region.bbox
    assert 0.0 <= x0 <= 1.0 and 0.0 <= y0 <= 1.0
    assert 0.0 <= x1 <= 1.0 and 0.0 <= y1 <= 1.0


def test_bbox_rejects_wrong_length():
    import pytest

    with pytest.raises(ValueError):
        _region("r", 1, [0.1, 0.2, 0.3])


def test_visual_ir_file_roundtrip(tmp_path):
    ir = PaperVisualIR(source_filename="p.pdf", pages=[PaperPageVisual(page_number=1, page_asset=_asset(1))])
    out = ir.to_json_file(tmp_path / "pvir.json")
    assert out.exists()
    assert PaperVisualIR.from_json_file(out) == ir
