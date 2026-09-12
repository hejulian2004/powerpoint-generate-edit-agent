"""Multimodal paper visual analyzer (vision LLM, batched).

Sends canonical page rasters to the vision model in batches and parses strict JSON
into ``PaperVisualIR``. Designed to degrade gracefully:

- vision disabled / no client / no API key -> page assets with empty regions
- a batch failure -> that batch's pages get empty regions + a warning; the rest
  of the paper still analyses
- malformed region entries are dropped individually

Fact boundary: the model is instructed to describe visual STRUCTURE only and is
forbidden from inferring numeric values or making scientific claims. Numbers must
come from ``PaperIR`` (validated by ``backend.agent.grounding``).
"""

from __future__ import annotations

import base64
import inspect
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import settings
from ..paper.schema import PaperFigure, PaperIR, PaperTable
from .constants import ANALYSIS_VERSION, VISION_PROMPT_VERSION
from .crops import crop_regions
from .geometry import bbox_iou, normalize_bbox
from .schema import PaperPageAsset, PaperPageVisual, PaperVisualIR, VisualRegion

logger = logging.getLogger(__name__)

VISION_SYSTEM_PROMPT = """You are analyzing the VISUAL STRUCTURE of an academic paper for slide design.
You are a vision system, not a fact extractor.

Strict rules:
1. Do NOT infer numeric values from charts, tables, or plots. Never state a number that is not visually written as a label.
2. Do NOT create scientific claims, comparisons, or conclusions.
3. Do NOT summarize textual facts; only describe visual structure (what occupies where).
4. Describe figure / table / diagram / equation / chart / code regions and how visually important they are.
5. Return page-relative NORMALIZED bounding boxes as [x0, y0, x1, y1] in the range 0..1 (top-left origin).

Return STRICT JSON only, matching:
{
  "pages": [
    {
      "page_number": <int>,
      "visual_summary": "<one line, structure only>",
      "visual_importance": <0..1>,
      "density": "low" | "medium" | "high",
      "regions": [
        {
          "region_type": "figure|table|diagram|equation|chart|code|algorithm|other",
          "bbox": [x0, y0, x1, y1],
          "description": "<structural description, no numbers/facts>",
          "importance": <0..1>,
          "ppt_usefulness": <0..1>
        }
      ],
      "design_observations": ["<layout observation, no facts>"]
    }
  ]
}
"""

_ALLOWED_REGION_TYPES = {
    "figure", "table", "diagram", "equation", "chart", "code", "algorithm", "other",
}


async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
    if not on_event:
        return
    try:
        result = on_event(data)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover
        logger.debug("Analyzer event ignored: %s", exc)


def _image_data_uri(path: str) -> str:
    raw = Path(path).read_bytes()
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/webp"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_json(text: str) -> Any:
    """Best-effort extraction of a JSON object/array from model output."""
    if not text:
        raise ValueError("empty model response")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except Exception:
                continue
    raise ValueError("no parseable JSON in model response")


def _coerce_bbox(raw: Any) -> Optional[List[float]]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if max(values) > 1.5:
        values = [v / 100.0 for v in values]
    return values


def _region_type(raw: Any) -> str:
    value = str(raw or "other").strip().lower()
    return value if value in _ALLOWED_REGION_TYPES else "other"


def _paper_context_text(paper_ir: Optional[PaperIR]) -> str:
    if paper_ir is None:
        return ""
    parts: List[str] = []
    if paper_ir.title:
        parts.append(f"Paper title: {paper_ir.title}")
    figures = [f for f in paper_ir.figures if f.page]
    if figures:
        labels = ", ".join(
            f"{f.id}@p{f.page}" for f in figures[:20] if f.id
        )
        parts.append(f"Known figures (structural refs only): {labels}")
    tables = [t for t in paper_ir.tables if t.page]
    if tables:
        labels = ", ".join(
            f"{t.id}@p{t.page}" for t in tables[:20] if t.id
        )
        parts.append(f"Known tables (structural refs only): {labels}")
    return "\n".join(parts)


def _build_batch_messages(
    paper_ir: Optional[PaperIR],
    batch: Sequence[PaperPageAsset],
):
    page_numbers = [a.page_number for a in batch]
    context = _paper_context_text(paper_ir)
    user_text = (
        f"Analyze the following paper pages: {page_numbers}.\n"
        f"Use these exact page numbers in the JSON output.\n"
        f"{context}\n\n"
        "Describe visual structure only. Return strict JSON as specified."
    )
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
    for asset in batch:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _image_data_uri(asset.image_path), "detail": "low"},
            }
        )
    return [
        {"role": "system", "content": VISION_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _page_visual_stub(asset: PaperPageAsset, summary: str = "") -> PaperPageVisual:
    return PaperPageVisual(
        page_number=asset.page_number,
        page_asset=asset,
        visual_summary=summary,
        visual_importance=0.0,
        density="medium",
        regions=[],
        design_observations=[],
    )


def _associate_regions(
    regions: List[VisualRegion],
    paper_ir: Optional[PaperIR],
    page_number: int,
    page_width_pt: float,
    page_height_pt: float,
) -> None:
    """Best-effort mapping of visual regions to PaperIR figure/table ids."""
    if paper_ir is None:
        return

    page_figures: List[PaperFigure] = [
        f for f in paper_ir.figures if f.page == page_number and f.bbox is not None
    ]
    page_tables: List[PaperTable] = [
        t for t in paper_ir.tables if t.page == page_number
    ]
    figure_boxes = []
    for fig in page_figures:
        box = normalize_bbox(
            [fig.bbox.x0, fig.bbox.top, fig.bbox.x1, fig.bbox.bottom],
            page_width_pt,
            page_height_pt,
        )
        figure_boxes.append((fig.id, box))

    for region in regions:
        best_id = None
        best_iou = 0.1
        for fig_id, box in figure_boxes:
            iou = bbox_iou(region.bbox, box)
            if iou >= best_iou and fig_id:
                best_iou = iou
                best_id = fig_id
        if best_id:
            region.source_figure_id = best_id
        if region.region_type == "table" and len(page_tables) == 1:
            region.source_table_id = page_tables[0].id or None


def _parse_batch(
    raw_content: str,
    batch: Sequence[PaperPageAsset],
    paper_ir: Optional[PaperIR],
) -> List[PaperPageVisual]:
    payload = _extract_json(raw_content)
    if isinstance(payload, dict):
        page_entries = payload.get("pages")
        if page_entries is None and "page_number" in payload:
            page_entries = [payload]
    elif isinstance(payload, list):
        page_entries = payload
    else:
        page_entries = None
    if not isinstance(page_entries, list):
        raise ValueError("model response has no 'pages' list")

    by_number: Dict[int, Dict[str, Any]] = {}
    for idx, entry in enumerate(page_entries):
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("page_number", batch[idx].page_number if idx < len(batch) else 0))
        except (TypeError, ValueError):
            continue
        by_number[number] = entry

    results: List[PaperPageVisual] = []
    for asset in batch:
        entry = by_number.get(asset.page_number, {})
        page_width_pt = asset.width * 72.0 / max(asset.dpi, 1)
        page_height_pt = asset.height * 72.0 / max(asset.dpi, 1)

        regions: List[VisualRegion] = []
        raw_regions = entry.get("regions") if isinstance(entry, dict) else None
        if isinstance(raw_regions, list):
            for r_idx, raw_region in enumerate(raw_regions, start=1):
                if not isinstance(raw_region, dict):
                    continue
                bbox = _coerce_bbox(raw_region.get("bbox") or raw_region.get("box"))
                if bbox is None:
                    continue
                try:
                    region = VisualRegion(
                        region_id=f"page_{asset.page_number:03d}_region_{r_idx:03d}",
                        page_number=asset.page_number,
                        region_type=_region_type(raw_region.get("region_type") or raw_region.get("type")),
                        bbox=bbox,
                        description=str(raw_region.get("description", ""))[:500],
                        importance=_clamp_unit(raw_region.get("importance")),
                        ppt_usefulness=_clamp_unit(raw_region.get("ppt_usefulness")),
                    )
                except Exception as exc:
                    logger.debug("Dropping invalid region: %s", exc)
                    continue
                regions.append(region)

        _associate_regions(regions, paper_ir, asset.page_number, page_width_pt, page_height_pt)

        observations = entry.get("design_observations") if isinstance(entry, dict) else None
        results.append(
            PaperPageVisual(
                page_number=asset.page_number,
                page_asset=asset,
                visual_summary=str(entry.get("visual_summary", ""))[:500] if isinstance(entry, dict) else "",
                visual_importance=_clamp_unit(entry.get("visual_importance")) if isinstance(entry, dict) else 0.0,
                density=_density(entry.get("density")) if isinstance(entry, dict) else "medium",
                regions=regions,
                design_observations=[str(o)[:300] for o in observations if str(o).strip()]
                if isinstance(observations, list)
                else [],
            )
        )
    return results


def _clamp_unit(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _density(value: Any) -> str:
    text = str(value or "medium").strip().lower()
    return text if text in ("low", "medium", "high") else "medium"


def _vision_available(llm_client: Any) -> bool:
    if not settings.paper_vision_enabled:
        return False
    if llm_client is None:
        return False
    api_key = getattr(llm_client, "api_key", None)
    if not api_key:
        return False
    return True


def _chunk(items: Sequence[PaperPageAsset], size: int) -> List[List[PaperPageAsset]]:
    size = max(1, size)
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


async def analyze_paper_visual(
    paper_ir: Optional[PaperIR],
    page_assets: Sequence[PaperPageAsset],
    llm_client: Any = None,
    batch_size: Optional[int] = None,
    crop_output_dir: Optional[str] = None,
    source_sha256: str = "",
    on_event: Optional[Callable] = None,
) -> PaperVisualIR:
    """Analyze paper pages into a ``PaperVisualIR`` (vision, batched, degradable)."""
    source_filename = paper_ir.source_filename if paper_ir else ""
    active_batch = int(batch_size or settings.paper_vision_batch_size)
    warnings: List[str] = []

    if not _vision_available(llm_client):
        reason = (
            "vision_disabled" if not settings.paper_vision_enabled else "vision_unavailable"
        )
        warnings.append(reason)
        pages = [_page_visual_stub(asset) for asset in page_assets]
        return PaperVisualIR(
            source_filename=source_filename,
            source_sha256=source_sha256,
            pages=pages,
            vision_model=None,
            analysis_version=ANALYSIS_VERSION,
            warnings=warnings,
        )

    vision_model = None
    getter = getattr(llm_client, "get_model_for_role", None)
    if callable(getter):
        try:
            vision_model = getter("vision")
        except Exception:
            vision_model = None

    pages_by_number: Dict[int, PaperPageVisual] = {}
    batches = _chunk(list(page_assets), active_batch)
    for batch_index, batch in enumerate(batches, start=1):
        await _safe_emit(
            on_event,
            {
                "type": "generation_stage",
                "phase": "paper_visual_analysis",
                "current": batch_index,
                "total": len(batches),
            },
        )
        try:
            messages = _build_batch_messages(paper_ir, batch)
            response = await llm_client.chat_completion(
                messages, role="vision", max_tokens=2000
            )
            content = response["choices"][0]["message"].get("content", "")
            for page_visual in _parse_batch(content, batch, paper_ir):
                pages_by_number[page_visual.page_number] = page_visual
        except Exception as exc:
            logger.warning("Paper vision batch %s failed: %s", batch_index, exc)
            warnings.append(f"batch_{batch_index}: vision analysis failed ({exc})")
            for asset in batch:
                pages_by_number.setdefault(asset.page_number, _page_visual_stub(asset))

    pages: List[PaperPageVisual] = []
    for asset in page_assets:
        pages.append(pages_by_number.get(asset.page_number, _page_visual_stub(asset)))

    if crop_output_dir:
        for page in pages:
            if page.regions:
                crop_regions(page.page_asset, page.regions, crop_output_dir)

    return PaperVisualIR(
        source_filename=source_filename,
        source_sha256=source_sha256,
        pages=pages,
        vision_model=vision_model,
        analysis_version=ANALYSIS_VERSION,
        warnings=warnings,
    )


__all__ = [
    "VISION_SYSTEM_PROMPT",
    "VISION_PROMPT_VERSION",
    "analyze_paper_visual",
]
