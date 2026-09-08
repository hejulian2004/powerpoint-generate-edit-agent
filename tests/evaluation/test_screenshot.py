"""Tests for PPTX Slide Screenshot Renderer Pipeline (PR12 Test 1)."""

from pathlib import Path
import pytest
from PIL import Image

from backend.evaluation.screenshot import (
    FallbackScreenshotBackend,
    ScreenshotRenderer,
    render_screenshots,
)
from backend.layout.schema import Canvas, DeckLayoutSpec, ElementType, LayoutElement, LayoutSpec, Rect
from backend.renderer.renderer import render_pptx
from backend.slidespec.schema import VisualIntent


@pytest.fixture
def sample_test_pptx(tmp_path: Path) -> Path:
    """Generate a valid 3-slide PPTX for screenshot testing."""
    deck = DeckLayoutSpec(
        title="Screenshot Test Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id=f"slide_{i}",
                slide_index=i,
                visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
                elements=[
                    LayoutElement(
                        element_id=f"title_{i}",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80, y=50, width=1000, height=80),
                        content=f"Slide {i} Title",
                    ),
                    LayoutElement(
                        element_id=f"body_{i}",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80, y=160, width=900, height=300),
                        content=f"Content for slide {i} demonstrating deterministic export.",
                    ),
                ],
            )
            for i in range(1, 4)
        ],
    )
    pptx_path = tmp_path / "sample_deck.pptx"
    render_pptx(deck, pptx_path)
    return pptx_path


def test_screenshot_export_count_and_naming(sample_test_pptx: Path, tmp_path: Path) -> None:
    """Test 1: Render presentation to slide screenshots, verifying count, naming, and size."""
    out_dir = tmp_path / "screenshots"
    # Use deterministic fallback backend to ensure test passes in all environments
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())
    images = renderer.render_screenshots(sample_test_pptx, out_dir, resolution=(1280, 720))

    # Expect 3 slides
    assert len(images) == 3
    assert images[0].name == "1.png"
    assert images[1].name == "2.png"
    assert images[2].name == "3.png"

    # Verify resolution
    for img_p in images:
        assert img_p.is_file()
        with Image.open(img_p) as img:
            assert img.size == (1280, 720)


def test_screenshot_hash_stability(sample_test_pptx: Path, tmp_path: Path) -> None:
    """Verify that exporting the same deck twice produces identical stable SHA256 hashes."""
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    dir1 = tmp_path / "export_run_1"
    dir2 = tmp_path / "export_run_2"

    imgs1 = renderer.render_screenshots(sample_test_pptx, dir1)
    imgs2 = renderer.render_screenshots(sample_test_pptx, dir2)

    assert len(imgs1) == len(imgs2) == 3
    for p1, p2 in zip(imgs1, imgs2):
        hash1 = ScreenshotRenderer.compute_image_hash(p1)
        hash2 = ScreenshotRenderer.compute_image_hash(p2)
        assert hash1 == hash2


def test_convenience_render_screenshots_function(sample_test_pptx: Path, tmp_path: Path) -> None:
    """Verify top-level functional helper render_screenshots."""
    out_dir = tmp_path / "quick_export"
    images = render_screenshots(sample_test_pptx, out_dir)
    assert len(images) == 3
    assert all(p.is_file() for p in images)


def test_screenshot_file_not_found(tmp_path: Path) -> None:
    """Non-existent PPTX file raises FileNotFoundError."""
    renderer = ScreenshotRenderer(force_fallback=True)
    with pytest.raises(FileNotFoundError):
        renderer.render_screenshots(tmp_path / "non_existent.pptx", tmp_path / "out")


def test_screenshot_backends_availability() -> None:
    """Verify backend availability checks."""
    from backend.evaluation.screenshot import FallbackScreenshotBackend, LibreOfficeBackend, PowerPointBackend

    fb = FallbackScreenshotBackend()
    assert fb.is_available() is True

    # Check that instantiating other backends does not crash
    lo = LibreOfficeBackend()
    assert isinstance(lo.is_available(), bool)

    ppt = PowerPointBackend()
    assert isinstance(ppt.is_available(), bool)

