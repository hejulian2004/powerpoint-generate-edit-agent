"""Canonical PDF page rasterization (pypdfium2 only).

pypdfium2 is the SOLE rasterizer for the pipeline. pdfplumber remains the
text / line / image-bbox structural extractor (``backend.paper.section_extractor``)
and never renders pages; Pillow is used only downstream for cropping/encoding.

Every page the vision model sees must come from here, so that:

    PaperIR.BBox (pdfplumber points)  ->  normalized against page.get_size()
    Vision coordinates (normalized)   ->  same orientation / crop box / DPI

pypdfium2's ``PdfPage.get_size()`` is rotation-aware and matches the rendered
bitmap orientation, which is what makes the normalized region contract stable.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from ..config import settings
from .constants import RENDERER_VERSION
from .errors import PaperRenderError
from .schema import PaperPageAsset

logger = logging.getLogger(__name__)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Union[str, Path]) -> str:
    """Streaming SHA-256 of a file (used for content-addressed caching)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RenderResult:
    """Outcome of a canonical page-render pass."""

    assets: List[PaperPageAsset] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    pdf_sha256: str = ""
    page_count: int = 0
    cache_hit: bool = False
    dpi: int = 0


def effective_page_size(page) -> tuple:
    """Rotation-aware page size in PDF points (matches pypdfium2 raster output)."""
    return tuple(page.get_size())


def render_pdf_pages(
    pdf_path: Union[str, Path],
    output_dir: Union[str, Path],
    dpi: Optional[int] = None,
    fmt: str = "webp",
    force: bool = False,
) -> RenderResult:
    """Rasterize every page of ``pdf_path`` into ``output_dir/pages``.

    Failures are isolated: a single page that cannot be rendered is recorded as a
    warning and skipped, while the rest of the document still renders. Only an
    unopenable PDF raises ``PaperRenderError``.

    ``force`` is accepted for API symmetry; the renderer itself always renders.
    Cache short-circuiting lives in ``cache.load_or_render``.
    """
    import pypdfium2 as pdfium

    path = Path(pdf_path)
    if not path.exists():
        raise PaperRenderError(f"PDF not found: {path}")

    active_dpi = int(dpi or settings.paper_page_render_dpi)
    scale = active_dpi / 72.0
    pages_dir = Path(output_dir) / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    warnings: List[str] = []
    assets: List[PaperPageAsset] = []

    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception as exc:  # pragma: no cover - environment dependent
        raise PaperRenderError(f"Failed to open PDF '{path}': {exc}") from exc

    page_count = 0
    try:
        page_count = len(doc)
        for page_index in range(page_count):
            page_number = page_index + 1
            try:
                page = doc[page_index]
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                filename = f"page_{page_number:03d}.{fmt}"
                out_path = pages_dir / filename
                if fmt.lower() == "webp":
                    image.save(out_path, "WEBP", quality=90, method=4)
                elif fmt.lower() == "png":
                    image.save(out_path, "PNG")
                else:
                    image.save(out_path)
                assets.append(
                    PaperPageAsset(
                        page_number=page_number,
                        image_path=str(out_path),
                        width=int(image.width),
                        height=int(image.height),
                        dpi=active_dpi,
                        sha256=sha256_bytes(out_path.read_bytes()),
                    )
                )
            except Exception as exc:
                logger.warning("Page %s render failed: %s", page_number, exc)
                warnings.append(f"page_{page_number:03d}: render failed ({exc})")
                continue
    finally:
        closer = getattr(doc, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # pragma: no cover
                pass

    if page_count and not assets:
        raise PaperRenderError(
            f"Failed to rasterize any page of '{path}': {'; '.join(warnings)}",
            warnings=warnings,
        )

    return RenderResult(
        assets=assets,
        warnings=warnings,
        pdf_sha256=file_sha256(path),
        page_count=page_count,
        dpi=active_dpi,
    )


__all__ = [
    "RENDERER_VERSION",
    "RenderResult",
    "effective_page_size",
    "file_sha256",
    "sha256_bytes",
    "render_pdf_pages",
]
