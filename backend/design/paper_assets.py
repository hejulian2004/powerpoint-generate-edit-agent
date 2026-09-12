"""Trusted resolution of PaperVisualIR crops into PresentationIR image assets.

A figure region in ``PaperVisualIR`` points at a deterministic crop produced by
Pillow. This module turns a layout FIGURE element (canonically bound to a
``FigureBlock.source_figure_id``) into a real ``ImageElementIR`` payload by
resolving that crop/page image **inside the trusted cache root**. Only when no
trusted crop exists does the compiler fall back to the editable placeholder.

Path safety: every resolved path is re-checked with ``assert_within`` against the
cache root, so an untrusted ``PaperVisualIR`` can never make the generator read an
arbitrary server file.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..paper.schema import PaperIR
from ..paper_visual.paths import assert_within
from ..paper_visual.schema import PaperVisualIR

logger = logging.getLogger(__name__)


def _data_uri(path: Path) -> str:
    raw = path.read_bytes()
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/webp"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _trusted_data_uri(raw: Optional[str], root: Path) -> Optional[str]:
    if not raw:
        return None
    try:
        path = assert_within(raw, root)
    except Exception as exc:
        logger.warning("Refusing source asset outside cache root: %s", exc)
        return None
    if not path.exists():
        return None
    try:
        return _data_uri(path)
    except OSError:
        return None


def _figure_id_from_element(element: Any) -> Optional[str]:
    content = getattr(element, "content", None)
    if isinstance(content, dict):
        figure_id = content.get("source_figure_id") or content.get("figure_id")
        if figure_id:
            return str(figure_id)
    return None


def _region_crop_for_figure(
    paper_visual_ir: PaperVisualIR, figure_id: str
) -> Optional[str]:
    for page in paper_visual_ir.pages:
        for region in page.regions:
            if region.source_figure_id == figure_id and region.crop_path:
                return region.crop_path
    return None


def _figure_page_image(
    paper_ir: Optional[PaperIR],
    paper_visual_ir: PaperVisualIR,
    figure_id: str,
) -> Optional[str]:
    if paper_ir is None:
        return None
    for figure in getattr(paper_ir, "figures", []) or []:
        if figure.id == figure_id and figure.page:
            page = paper_visual_ir.page_by_number(figure.page)
            if page is not None:
                return page.page_asset.image_path
    return None


def make_paper_asset_resolver(
    paper_ir: Optional[PaperIR],
    paper_visual_ir: Optional[PaperVisualIR],
    cache_dir: Optional[str],
) -> Optional[Callable[[Any], Optional[Dict[str, str]]]]:
    """Build a resolver(element) -> {src, asset_id, alt_text} or None.

    Returns ``None`` when no visual IR / cache root is available, in which case the
    compiler keeps emitting editable figure placeholders.
    """
    if paper_visual_ir is None or not cache_dir:
        return None
    root = Path(cache_dir)

    def _resolver(element: Any) -> Optional[Dict[str, str]]:
        figure_id = _figure_id_from_element(element)
        if not figure_id:
            return None

        raw = _region_crop_for_figure(paper_visual_ir, figure_id)
        if not raw:
            raw = _figure_page_image(paper_ir, paper_visual_ir, figure_id)
        if not raw:
            return None

        try:
            path = assert_within(raw, root)
        except Exception as exc:
            logger.warning("Refusing figure asset outside cache root: %s", exc)
            return None
        if not path.exists():
            return None
        try:
            src = _data_uri(path)
        except OSError as exc:
            logger.warning("Could not read figure asset %s: %s", path, exc)
            return None

        return {
            "src": src,
            "asset_id": f"asset_{figure_id}",
            "alt_text": figure_id,
        }

    return _resolver


def paper_source_images_by_slide(
    paper_ir: Optional[PaperIR],
    paper_visual_ir: Optional[PaperVisualIR],
    cache_dir: Optional[str],
    slide_plans: Any,
) -> Dict[str, list]:
    """Map ``slide_{index}`` -> trusted source page/crop data URIs for the critic.

    Only visuals selected for that slide (explicit pages, referenced figures/tables)
    are attached, so the deck-level critic can compare the rendered slide against
    the paper page it claims to represent.
    """
    if paper_visual_ir is None or not cache_dir:
        return {}
    from ..paper_visual.context import select_visual_context_for_slide

    root = Path(cache_dir)
    result: Dict[str, list] = {}
    for slide_plan in slide_plans or []:
        index = getattr(slide_plan, "index", None)
        if index is None:
            continue
        context = select_visual_context_for_slide(
            paper_visual_ir,
            source_pages=getattr(slide_plan, "source_pages", []) or [],
            figure_ids=getattr(slide_plan, "source_figures", []) or [],
            table_ids=getattr(slide_plan, "source_tables", []) or [],
        )
        uris = []
        for raw in list(context.page_image_paths) + list(context.crop_paths):
            uri = _trusted_data_uri(raw, root)
            if uri:
                uris.append(uri)
        if uris:
            result[f"slide_{index}"] = uris
    return result


__all__ = ["make_paper_asset_resolver", "paper_source_images_by_slide"]
