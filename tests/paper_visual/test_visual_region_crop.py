"""Deterministic region cropping tests."""

from __future__ import annotations

from pathlib import Path

from backend.paper_visual import crop_regions, render_pdf_pages
from backend.paper_visual.geometry import normalize_bbox, normalized_to_pixels
from backend.paper_visual.schema import VisualRegion


def _region(bbox, region_id="page_001_region_001") -> VisualRegion:
    return VisualRegion(region_id=region_id, page_number=1, region_type="figure",
                        bbox=bbox, importance=0.8, ppt_usefulness=0.7)


def test_crop_produces_file_with_expected_dimensions(multicase_pdf: Path, tmp_path: Path):
    result = render_pdf_pages(multicase_pdf, tmp_path / "render", dpi=144)
    asset = result.assets[0]
    region = _region([0.25, 0.25, 0.75, 0.75])

    crop_regions(asset, [region], tmp_path / "crops")

    assert region.crop_path is not None
    crop_file = Path(region.crop_path)
    assert crop_file.exists()
    assert crop_file.name == "page_001_region_001.webp"

    from PIL import Image

    with Image.open(crop_file) as img:
        expected_w = round(0.5 * asset.width)
        expected_h = round(0.5 * asset.height)
        assert abs(img.width - expected_w) <= 1
        assert abs(img.height - expected_h) <= 1


def test_missing_page_image_is_tolerated(tmp_path: Path):
    from backend.paper_visual.schema import PaperPageAsset

    asset = PaperPageAsset(page_number=1, image_path=str(tmp_path / "missing.webp"),
                           width=100, height=100, dpi=144)
    region = _region([0.1, 0.1, 0.5, 0.5])

    crop_regions(asset, [region], tmp_path / "crops")

    assert region.crop_path is None


def test_normalize_bbox_matches_point_convention():
    # PaperIR.BBox -> [x0, top, x1, bottom] in points, top-left origin.
    normalized = normalize_bbox([100.0, 200.0, 300.0, 400.0], 1000.0, 800.0)
    assert normalized == [0.1, 0.25, 0.3, 0.5]


def test_normalized_to_pixels_is_clamped():
    left, top, right, bottom = normalized_to_pixels([-0.2, -0.2, 1.5, 1.5], 100, 50)
    assert left == 0 and top == 0
    assert right == 100 and bottom == 50
