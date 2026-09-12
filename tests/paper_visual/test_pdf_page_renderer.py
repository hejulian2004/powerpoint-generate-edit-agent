"""Canonical page renderer contract tests (pypdfium2 only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.paper_visual import PaperRenderError, render_pdf_pages


def test_render_yields_one_asset_per_page(multicase_pdf: Path, tmp_path: Path):
    result = render_pdf_pages(multicase_pdf, tmp_path, dpi=144)

    assert result.page_count == 10
    assert len(result.assets) == 10
    assert [a.page_number for a in result.assets] == list(range(1, 11))
    for asset in result.assets:
        path = Path(asset.image_path)
        assert path.exists()
        assert path.name == f"page_{asset.page_number:03d}.webp"
        assert asset.width > 0 and asset.height > 0
        assert asset.dpi == 144
        assert len(asset.sha256) == 64


def test_render_is_deterministic(multicase_pdf: Path, tmp_path: Path):
    first = render_pdf_pages(multicase_pdf, tmp_path / "a", dpi=144)
    second = render_pdf_pages(multicase_pdf, tmp_path / "b", dpi=144)

    assert [a.sha256 for a in first.assets] == [b.sha256 for b in second.assets]


def test_render_dpi_scales_page_dimensions(multicase_pdf: Path, tmp_path: Path):
    low = render_pdf_pages(multicase_pdf, tmp_path / "low", dpi=72)
    high = render_pdf_pages(multicase_pdf, tmp_path / "high", dpi=144)

    assert high.assets[0].width == pytest.approx(low.assets[0].width * 2, abs=2)
    assert high.assets[0].height == pytest.approx(low.assets[0].height * 2, abs=2)


def test_render_missing_file_raises(tmp_path: Path):
    with pytest.raises(PaperRenderError):
        render_pdf_pages(tmp_path / "nope.pdf", tmp_path / "out")


def test_render_invalid_pdf_raises(tmp_path: Path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(PaperRenderError):
        render_pdf_pages(bad, tmp_path / "out")


def test_single_page_failure_is_isolated(multicase_pdf: Path, tmp_path: Path, monkeypatch):
    import pypdfium2 as pdfium
    from PIL import Image

    class _Bitmap:
        def __init__(self, w=120, h=120):
            self._img = Image.new("RGB", (w, h), "white")

        def to_pil(self):
            return self._img

    class _Page:
        def __init__(self, fail: bool):
            self.fail = fail

        def render(self, scale=1):
            if self.fail:
                raise RuntimeError("boom")
            return _Bitmap()

    class _Doc:
        def __init__(self, _path):
            self._pages = [_Page(False), _Page(True), _Page(False)]

        def __len__(self):
            return len(self._pages)

        def __getitem__(self, index):
            return self._pages[index]

        def close(self):
            pass

    monkeypatch.setattr(pdfium, "PdfDocument", _Doc)

    result = render_pdf_pages(multicase_pdf, tmp_path, dpi=144)

    assert result.page_count == 3
    assert [a.page_number for a in result.assets] == [1, 3]
    assert any("page_002" in w for w in result.warnings)


def test_rotation_aware_page_size(multicase_pdf: Path):
    import pypdfium2 as pdfium
    from backend.paper_visual.renderer import effective_page_size

    doc = pdfium.PdfDocument(str(multicase_pdf))
    try:
        page = doc[0]
        width, height = effective_page_size(page)
        page.set_rotation(90)
        rot_width, rot_height = effective_page_size(page)
        assert (rot_width, rot_height) == (height, width)
    finally:
        doc.close()
