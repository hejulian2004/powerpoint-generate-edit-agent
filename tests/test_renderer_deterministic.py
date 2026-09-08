"""PR4.1 Task 1 & Task 2 Test Suite: Unified Renderer Mode & Deterministic Execution."""

import hashlib
import pytest
from unittest.mock import patch, MagicMock
from backend.ir.models import (
    SlideIR, ShapeElementIR, TextElementIR, TextContentIR, FontIR, ElementStyleIR, FillStyle
)
from backend.eval.renderer_snapshot import (
    SlideSnapshotRenderer, RendererMode, RenderCapability, RenderMetadata
)


def _create_sample_slide() -> SlideIR:
    slide = SlideIR(id="deterministic_slide", slide_num=1, width=1280, height=720)
    card = ShapeElementIR(
        id="card_det_1",
        shape_type="roundRect",
        x=80.0,
        y=120.0,
        width=320.0,
        height=200.0,
        style=dict(fill=FillStyle(type="solid", color="#1E293B"), radius=8.0)
    )
    text = TextElementIR(
        id="txt_det_1",
        x=100.0,
        y=140.0,
        width=280.0,
        height=60.0,
        text_content=TextContentIR.from_plain_text("Deterministic Slide Architecture", font=FontIR(size=20, color="#FFFFFF"))
    )
    slide.add_element(card)
    slide.add_element(text)
    return slide


def test_renderer_deterministic_10_iterations_identical_hash():
    """Verify that rendering the exact same slide 10 consecutive times yields bit-identical hashes."""
    slide = _create_sample_slide()

    hashes = []
    for _ in range(10):
        png_bytes = SlideSnapshotRenderer.render_png_bytes(slide, mode=RendererMode.DETERMINISTIC)
        assert isinstance(png_bytes, bytes)
        assert len(png_bytes) > 0
        h = hashlib.sha256(png_bytes).hexdigest()
        hashes.append(h)

    # All 10 hashes must be strictly identical
    assert len(set(hashes)) == 1, f"Expected 1 unique hash across 10 runs, got: {set(hashes)}"


def test_renderer_deterministic_never_calls_playwright():
    """Verify that DETERMINISTIC mode strictly forbids Playwright execution even if available."""
    slide = _create_sample_slide()

    with patch("backend.eval.renderer_snapshot._PLAYWRIGHT_AVAILABLE", True):
        with patch("backend.eval.renderer_snapshot.async_playwright") as mock_pw:
            # Run async rendering in deterministic mode
            import asyncio
            png_bytes = asyncio.run(
                SlideSnapshotRenderer.render_png_bytes_async(slide, mode=RendererMode.DETERMINISTIC)
            )
            assert isinstance(png_bytes, bytes)
            assert mock_pw.called is False, "Playwright must never be called in DETERMINISTIC mode"


def test_renderer_preview_allows_playwright_when_available():
    """Verify that PREVIEW mode attempts Playwright headless Chromium when available."""
    slide = _create_sample_slide()

    with patch("backend.eval.renderer_snapshot._PLAYWRIGHT_AVAILABLE", True):
        # Mock Playwright async context manager
        mock_browser = MagicMock()
        mock_page = MagicMock()

        async def _mock_screenshot(**kwargs):
            return b"\x89PNG\r\n\x1a\nfake_playwright_bytes"

        mock_page.screenshot = _mock_screenshot

        async def _mock_set_content(html):
            pass

        mock_page.set_content = _mock_set_content

        async def _mock_new_page(**kwargs):
            return mock_page

        mock_browser.new_page = _mock_new_page

        async def _mock_close():
            pass

        mock_browser.close = _mock_close

        mock_p_instance = MagicMock()

        async def _mock_launch(**kwargs):
            return mock_browser

        mock_p_instance.chromium.launch = _mock_launch

        class MockPWContext:
            async def __aenter__(self):
                return mock_p_instance
            async def __aexit__(self, *args):
                pass

        with patch("backend.eval.renderer_snapshot.async_playwright", return_value=MockPWContext()):
            import asyncio
            result_bytes = asyncio.run(
                SlideSnapshotRenderer.render_png_bytes_async(slide, mode=RendererMode.PREVIEW)
            )
            assert result_bytes == b"\x89PNG\r\n\x1a\nfake_playwright_bytes"


def test_renderer_capability_and_metadata():
    """Verify RenderCapability matrix and Pillow geometry_only quality classification."""
    slide = _create_sample_slide()
    meta = SlideSnapshotRenderer.get_render_metadata(slide, mode=RendererMode.DETERMINISTIC)
    assert isinstance(meta, RenderMetadata)
    assert meta.mode == RendererMode.DETERMINISTIC

    meta_dict = meta.to_dict()
    assert "renderer" in meta_dict
    assert "quality" in meta_dict
    assert "capability" in meta_dict
    assert meta_dict["capability"]["geometry"] is True

    # When CairoSVG is not installed in the current environment, it reports Pillow with geometry_only
    if meta.renderer == "pillow":
        assert meta.quality == "geometry_only"
        assert meta.capability.typography is False
        assert meta.capability.effects is False


def test_renderer_deterministic_fallback_svg_uri():
    """Verify fallback_to_svg=True generates SVG data URI when Cairo is unavailable."""
    slide = _create_sample_slide()

    with patch("backend.eval.renderer_snapshot._CAIROSVG_AVAILABLE", False):
        uri = SlideSnapshotRenderer.render_data_uri(
            slide,
            mode=RendererMode.DETERMINISTIC,
            fallback_to_svg=True
        )
        assert uri.startswith("data:image/svg+xml;base64,")


def test_render_capability_dataclass_methods():
    """Verify RenderCapability defaults and custom values."""
    from backend.eval.renderer_snapshot import RenderCapability
    cap = RenderCapability(geometry=True, typography=True, effects=False)
    d = cap.to_dict()
    assert d == {"geometry": True, "typography": True, "effects": False}

    default_cap = RenderCapability()
    assert default_cap.geometry is True
    assert default_cap.typography is False
    assert default_cap.effects is False
