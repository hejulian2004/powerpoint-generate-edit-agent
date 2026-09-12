"""Content-addressed cache for canonically rendered paper pages + visual IR.

Cache key::

    sha256( sha256(PDF) + renderer_version + dpi )

Layout under ``BASE_DIR/output/paper_cache/{cache_key}/``::

    pages/page_001.webp ...
    crops/page_005_region_001.webp
    paper_visual_ir.json
    manifest.json

The cache is content-addressed (never session-addressed) so re-running the same
paper with the same renderer/DPI reuses pages across sessions and generations.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Tuple, Union

from ..config import BASE_DIR, settings
from .constants import RENDERER_VERSION
from .renderer import RenderResult, file_sha256, render_pdf_pages
from .schema import PaperPageAsset, PaperVisualIR

logger = logging.getLogger(__name__)

DEFAULT_CACHE_ROOT = BASE_DIR / "output" / "paper_cache"
MANIFEST_NAME = "manifest.json"
VISUAL_IR_NAME = "paper_visual_ir.json"
RENDER_DIR_NAME = "pages"
CROP_DIR_NAME = "crops"


def compute_cache_key(
    pdf_sha256: str,
    renderer_version: str = RENDERER_VERSION,
    dpi: Optional[int] = None,
) -> str:
    """Deterministic cache key for a rendered-pages bundle."""
    from .renderer import sha256_bytes

    active_dpi = int(dpi or settings.paper_page_render_dpi)
    return sha256_bytes(
        f"{pdf_sha256}:{renderer_version}:{active_dpi}".encode("utf-8")
    )


def paper_cache_dir(
    cache_key: str,
    root: Optional[Union[str, Path]] = None,
) -> Path:
    base = Path(root) if root is not None else DEFAULT_CACHE_ROOT
    return base / cache_key


def _read_manifest(cache_dir: Path) -> Optional[dict]:
    manifest_path = cache_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - corrupted cache
        logger.warning("Ignoring unreadable paper cache manifest %s: %s", manifest_path, exc)
        return None


def _write_manifest(cache_dir: Path, result: RenderResult, source_filename: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "renderer_version": RENDERER_VERSION,
        "dpi": result.dpi,
        "pdf_sha256": result.pdf_sha256,
        "source_filename": source_filename,
        "page_count": result.page_count,
        "warnings": list(result.warnings),
        "assets": [asset.model_dump(mode="json") for asset in result.assets],
    }
    (cache_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _result_from_manifest(manifest: dict, cache_dir: Path) -> RenderResult:
    assets = [
        PaperPageAsset.model_validate(entry) for entry in manifest.get("assets", [])
    ]
    return RenderResult(
        assets=assets,
        warnings=list(manifest.get("warnings", [])),
        pdf_sha256=manifest.get("pdf_sha256", ""),
        page_count=int(manifest.get("page_count", len(assets))),
        cache_hit=True,
        dpi=int(manifest.get("dpi", 0)),
    )


def load_or_render(
    pdf_path: Union[str, Path],
    dpi: Optional[int] = None,
    root: Optional[Union[str, Path]] = None,
    force: bool = False,
) -> Tuple[RenderResult, Path]:
    """Return ``(RenderResult, cache_dir)``, reusing cached pages when valid.

    A cache hit requires both a readable manifest and evidence that every asset
    file still exists; otherwise the bundle is re-rendered.
    """
    path = Path(pdf_path)
    pdf_sha = file_sha256(path)
    active_dpi = int(dpi or settings.paper_page_render_dpi)
    cache_dir = paper_cache_dir(compute_cache_key(pdf_sha, dpi=active_dpi), root)

    if not force:
        manifest = _read_manifest(cache_dir)
        if manifest and manifest.get("renderer_version") == RENDERER_VERSION:
            if all(Path(a.get("image_path", "")).exists() for a in manifest.get("assets", [])):
                logger.debug("Paper cache hit: %s", cache_dir)
                return _result_from_manifest(manifest, cache_dir), cache_dir

    result = render_pdf_pages(path, cache_dir, dpi=active_dpi)
    _write_manifest(cache_dir, result, source_filename=path.name)
    return result, cache_dir


def save_visual_ir(visual_ir: PaperVisualIR, cache_dir: Union[str, Path]) -> Path:
    out = Path(cache_dir) / VISUAL_IR_NAME
    visual_ir.to_json_file(out)
    return out


def load_visual_ir(cache_dir: Union[str, Path]) -> Optional[PaperVisualIR]:
    path = Path(cache_dir) / VISUAL_IR_NAME
    if not path.exists():
        return None
    try:
        return PaperVisualIR.from_json_file(path)
    except Exception as exc:  # pragma: no cover - corrupted cache
        logger.warning("Ignoring unreadable PaperVisualIR %s: %s", path, exc)
        return None


def crops_dir(cache_dir: Union[str, Path]) -> Path:
    out = Path(cache_dir) / CROP_DIR_NAME
    out.mkdir(parents=True, exist_ok=True)
    return out


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "compute_cache_key",
    "paper_cache_dir",
    "load_or_render",
    "save_visual_ir",
    "load_visual_ir",
    "crops_dir",
]
