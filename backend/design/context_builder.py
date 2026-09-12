"""Context builders for LLM-native deck design.

Keeps context bounded (three-tier strategy): the art director sees the paper text
digest + visual digest + a contact sheet, NOT every full-resolution page. Slide
layout design later sees only the pages/crops relevant to that slide.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence

from ..paper.schema import PaperIR
from ..paper_visual.schema import PaperPageAsset, PaperVisualIR

logger = logging.getLogger(__name__)


def build_paper_text_digest(paper_ir: Optional[PaperIR]) -> str:
    """Compact textual digest of the paper (facts remain authoritative here)."""
    if paper_ir is None:
        return ""
    lines: List[str] = []
    if paper_ir.title:
        lines.append(f"TITLE: {paper_ir.title}")
    if paper_ir.metadata.authors:
        lines.append(f"AUTHORS: {', '.join(paper_ir.metadata.authors[:8])}")
    if paper_ir.abstract:
        lines.append(f"ABSTRACT: {paper_ir.abstract[:800]}")
    if paper_ir.contributions:
        lines.append("CONTRIBUTIONS:")
        lines.extend(f"- {c[:200]}" for c in paper_ir.contributions[:8])
    lines.append("SECTIONS:")
    for section in paper_ir.sections[:20]:
        heading = f"{section.number or ''} {section.title}".strip()
        body = " ".join(section.paragraphs)[:300]
        lines.append(f"- [p{section.page}] {heading}: {body}")
    if paper_ir.figures:
        lines.append("FIGURES:")
        for fig in paper_ir.figures[:20]:
            lines.append(f"- {fig.id} @p{fig.page}: {fig.caption[:160]}")
    if paper_ir.tables:
        lines.append("TABLES:")
        for table in paper_ir.tables[:20]:
            lines.append(f"- {table.id} @p{table.page}: {table.caption[:160]}")
    return "\n".join(lines)


def build_paper_visual_digest(paper_visual_ir: Optional[PaperVisualIR]) -> str:
    """Compact visual-structure digest (no facts; visual evidence only)."""
    if paper_visual_ir is None:
        return ""
    lines: List[str] = []
    for page in paper_visual_ir.pages:
        region_bits = ", ".join(
            f"{r.region_id}:{r.region_type}"
            + (f"(fig={r.source_figure_id})" if r.source_figure_id else "")
            + (f"(tab={r.source_table_id})" if r.source_table_id else "")
            + f"[u={r.ppt_usefulness:.2f}]"
            for r in page.regions
        )
        summary = page.visual_summary or "(no summary)"
        lines.append(
            f"- p{page.page_number} [{page.density}] {summary}"
            + (f" | regions: {region_bits}" if region_bits else "")
        )
    return "\n".join(lines)


def build_art_direction_text(
    paper_ir: Optional[PaperIR],
    paper_visual_ir: Optional[PaperVisualIR],
    user_prompt: str = "",
    duration_minutes: int = 15,
) -> str:
    parts = [f"Target duration: {duration_minutes} minutes."]
    if user_prompt:
        parts.append(f"User request: {user_prompt}")
    text_digest = build_paper_text_digest(paper_ir)
    if text_digest:
        parts.append("PAPER TEXT (authoritative facts):\n" + text_digest)
    visual_digest = build_paper_visual_digest(paper_visual_ir)
    if visual_digest:
        parts.append("PAPER VISUAL STRUCTURE (visual evidence only, no facts):\n" + visual_digest)
    return "\n\n".join(parts)


def build_contact_sheet(
    page_assets: Sequence[PaperPageAsset],
    output_path: Path,
    columns: int = 4,
    thumb_width: int = 320,
    fmt: str = "webp",
) -> Optional[str]:
    """Compose a contact sheet of page thumbnails for deck-level planning."""
    if not page_assets:
        return None
    try:
        from PIL import Image

        thumbs = []
        for asset in page_assets:
            with Image.open(asset.image_path) as img:
                ratio = thumb_width / max(img.width, 1)
                thumb = img.convert("RGB").resize(
                    (thumb_width, max(1, int(img.height * ratio)))
                )
                thumbs.append(thumb)
        if not thumbs:
            return None

        rows = (len(thumbs) + columns - 1) // columns
        cell_h = max(t.height for t in thumbs)
        gap = 8
        sheet = Image.new(
            "RGB",
            (columns * thumb_width + (columns + 1) * gap, rows * cell_h + (rows + 1) * gap),
            "white",
        )
        for idx, thumb in enumerate(thumbs):
            row, col = divmod(idx, columns)
            x = gap + col * (thumb_width + gap)
            y = gap + row * (cell_h + gap)
            sheet.paste(thumb, (x, y))

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt.lower() == "webp":
            sheet.save(out, "WEBP", quality=85, method=4)
        else:
            sheet.save(out)
        return str(out)
    except Exception as exc:
        logger.warning("Contact sheet generation failed: %s", exc)
        return None


__all__ = [
    "build_paper_text_digest",
    "build_paper_visual_digest",
    "build_art_direction_text",
    "build_contact_sheet",
]
