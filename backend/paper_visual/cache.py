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
from typing import Any, Optional, Tuple, Union

from ..config import BASE_DIR, settings
from .constants import ANALYSIS_VERSION, RENDERER_VERSION, VISION_PROMPT_VERSION
from .renderer import RenderResult, file_sha256, render_pdf_pages
from .schema import PaperPageAsset, PaperVisualIR

logger = logging.getLogger(__name__)

DEFAULT_CACHE_ROOT = BASE_DIR / "output" / "paper_cache"
MANIFEST_NAME = "manifest.json"
VISUAL_IR_NAME = "paper_visual_ir.json"
PAPER_IR_NAME = "paper_ir.json"
ANALYSIS_IDENTITY_NAME = "analysis_identity.json"
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


def compute_analysis_fingerprint(
    vision_model: Optional[str],
    analysis_version: str = ANALYSIS_VERSION,
    prompt_version: str = VISION_PROMPT_VERSION,
) -> str:
    """Identity of a visual-analysis result (distinct from the render key).

    Pages are keyed by render identity (pdf + renderer + dpi); the vision analysis
    is additionally keyed by the vision model and prompt/analysis versions, so a
    cached ``paper_visual_ir.json`` can never be silently reused after a model swap.
    """
    from .renderer import sha256_bytes

    return sha256_bytes(
        f"{vision_model or 'none'}:{analysis_version}:{prompt_version}".encode("utf-8")
    )


def save_analysis_identity(
    cache_dir: Union[str, Path],
    vision_model: Optional[str],
    analysis_version: str = ANALYSIS_VERSION,
    prompt_version: str = VISION_PROMPT_VERSION,
) -> Path:
    identity = {
        "vision_model": vision_model,
        "analysis_version": analysis_version,
        "vision_prompt_version": prompt_version,
        "fingerprint": compute_analysis_fingerprint(
            vision_model, analysis_version, prompt_version
        ),
    }
    out = Path(cache_dir) / ANALYSIS_IDENTITY_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return out


def load_analysis_identity(cache_dir: Union[str, Path]) -> Optional[dict]:
    path = Path(cache_dir) / ANALYSIS_IDENTITY_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - corrupted cache
        logger.warning("Ignoring unreadable analysis identity %s: %s", path, exc)
        return None


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
    save_analysis_identity(
        cache_dir,
        visual_ir.vision_model,
        analysis_version=visual_ir.analysis_version,
    )
    return out


def load_visual_ir(
    cache_dir: Union[str, Path],
    expected_fingerprint: Optional[str] = None,
) -> Optional[PaperVisualIR]:
    """Load the cached ``PaperVisualIR``.

    When ``expected_fingerprint`` is given, a stale bundle (produced by a different
    vision model / analysis / prompt version) is treated as a cache miss.
    """
    if expected_fingerprint is not None:
        identity = load_analysis_identity(cache_dir)
        if not identity or identity.get("fingerprint") != expected_fingerprint:
            logger.debug("Paper visual analysis is stale for %s", cache_dir)
            return None
    path = Path(cache_dir) / VISUAL_IR_NAME
    if not path.exists():
        return None
    try:
        return PaperVisualIR.from_json_file(path)
    except Exception as exc:  # pragma: no cover - corrupted cache
        logger.warning("Ignoring unreadable PaperVisualIR %s: %s", path, exc)
        return None


def save_paper_ir(paper_ir: Any, cache_dir: Union[str, Path]) -> Path:
    """Persist the textual ``PaperIR`` next to the visual IR (trusted source)."""
    out = Path(cache_dir) / PAPER_IR_NAME
    paper_ir.to_json_file(out)
    return out


def load_paper_ir(cache_dir: Union[str, Path]) -> Optional[Any]:
    from ..paper.schema import PaperIR

    path = Path(cache_dir) / PAPER_IR_NAME
    if not path.exists():
        return None
    try:
        return PaperIR.from_json_file(path)
    except Exception as exc:  # pragma: no cover - corrupted cache
        logger.warning("Ignoring unreadable PaperIR %s: %s", path, exc)
        return None


def crops_dir(cache_dir: Union[str, Path]) -> Path:
    out = Path(cache_dir) / CROP_DIR_NAME
    out.mkdir(parents=True, exist_ok=True)
    return out


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "compute_cache_key",
    "compute_analysis_fingerprint",
    "paper_cache_dir",
    "load_or_render",
    "save_visual_ir",
    "load_visual_ir",
    "save_analysis_identity",
    "load_analysis_identity",
    "save_paper_ir",
    "load_paper_ir",
    "crops_dir",
]
