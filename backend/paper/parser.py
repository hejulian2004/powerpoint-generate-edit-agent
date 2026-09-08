"""Paper PDF -> PaperIR parser (deterministic structural extraction).

Orchestrates the low-level heuristics from ``section_extractor`` into a ``PaperIR``:

    Paper PDF
        |
        v  section_extractor.analyze_pdf()   (ordered lines + images)
        v  heading / caption / title classification
        v  abstract + section paragraph segmentation
        v  figure / table record building
        v
     PaperIR (paper_ir.json)

The semantic fields (contributions / methodology / experiments / limitations) are left
empty here; use ``backend.paper.enricher`` to fill them with an LLM when available.
"""

from __future__ import annotations

import asyncio
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import section_extractor as se
from .schema import (
    BBox,
    ExtractionMeta,
    PaperFigure,
    PaperIR,
    PaperMetadata,
    PaperSection,
    PaperTable,
)

EXTRACTOR_VERSION = "1.0.0"
_METHODS = [
    "char-line extraction",
    "column detection & reading-order reflow",
    "body font estimation",
    "heading classification",
    "figure/table caption detection",
]


def extract_paper(pdf_path: Any, enrich: bool = False) -> PaperIR:
    """Parse a PDF into a PaperIR.

    ``enrich=True`` runs optional LLM semantic enrichment when an API key is configured;
    without a live key the PaperIR is returned with ``semantic_status='extracted'``.
    """
    paper = _parse_structure(pdf_path)
    if enrich:
        # Optional LLM layer; imports here so a missing key never breaks the parser.
        from .enricher import enrich_paper

        return enrich_paper(paper)
    return paper


def _parse_structure(pdf_path: Any) -> PaperIR:
    path = Path(pdf_path)
    doc = se.analyze_pdf(path)
    body_size = se.estimate_body_size(doc.lines)

    events = _classify_lines(doc.lines, body_size)

    paper = PaperIR(source_filename=path.name)
    paper.metadata.page_count = doc.page_count

    headings = [ev for ev in events if ev["kind"] == "heading"]
    first_heading_idx = doc.lines.index(headings[0]["line"]) if headings else len(doc.lines)

    # ---- Front matter: title + authors -------------------------------
    front_lines = doc.lines[:first_heading_idx]
    title, authors = _extract_front_matter(front_lines, doc.page_heights)
    paper.metadata.title = title
    paper.metadata.authors = authors

    # ---- Walk events: abstract / sections / figures / tables ----------
    figures: List[PaperFigure] = []
    tables: List[PaperTable] = []
    sections: List[PaperSection] = []
    draft: List[se.LineSpan] = []
    region_kind: Optional[str] = None  # 'abstract' | 'section'
    section_draft: Optional[PaperSection] = None
    abstract_draft: List[str] = []

    def _flush() -> None:
        nonlocal draft, region_kind, section_draft
        if region_kind == "abstract" and draft:
            paragraphs = _lines_to_paragraphs(draft, body_size)
            abstract_draft.append(" ".join(paragraphs))
        elif region_kind == "section" and section_draft is not None:
            section_draft.paragraphs = _lines_to_paragraphs(draft, body_size)
            sections.append(section_draft)
        draft = []
        section_draft = None
        region_kind = None

    for ev in events:
        if ev["kind"] == "heading":
            spec: Dict[str, Any] = ev["spec"]
            _flush()
            if spec.get("is_abstract"):
                region_kind = "abstract"
            else:
                ln: se.LineSpan = ev["line"]
                section_draft = PaperSection(
                    number=spec.get("number"),
                    title=spec["title"],
                    level=spec.get("level", 1),
                    page=ln.page,
                    paragraphs=[],
                )
                region_kind = "section"
            continue

        if ev["kind"] == "figure":
            _flush()
            xref_label, cap_text = ev["cap"][1], ev["cap"][2]
            caption_line: se.LineSpan = ev["line"]
            bbox = _image_bbox_above(doc.images, caption_line)
            figures.append(
                PaperFigure(
                    id=f"figure{len(figures) + 1}",
                    xref_label=xref_label,
                    caption=cap_text,
                    page=caption_line.page,
                    bbox=bbox,
                    is_raster=bbox is not None,
                )
            )
            continue

        if ev["kind"] == "table":
            _flush()
            xref_label, cap_text = ev["cap"][1], ev["cap"][2]
            caption_line = ev["line"]
            tables.append(
                PaperTable(
                    id=f"table{len(tables) + 1}",
                    xref_label=xref_label,
                    caption=cap_text,
                    page=caption_line.page,
                )
            )
            continue

        # body line
        draft.append(ev["line"])

    _flush()

    paper.abstract = " ".join(abstract_draft).strip()
    paper.sections = sections
    paper.figures = figures
    paper.tables = tables
    paper.extraction = ExtractionMeta(
        engine="pdfplumber",
        extractor_version=EXTRACTOR_VERSION,
        methods=list(_METHODS),
        warnings=[],
        semantic_status="extracted",
    )
    return paper


# =====================================================================
# Event classification
# =====================================================================


def _classify_lines(lines: List[se.LineSpan], body_size: float) -> List[Dict[str, Any]]:
    """Tag every document line as heading / figure / table / body (in reading order)."""
    events: List[Dict[str, Any]] = []
    for ln in lines:
        cap = se.caption_match(ln.text)
        if cap:
            kind, xref_label, cap_text = cap
            events.append(
                {
                    "kind": kind,  # 'figure' | 'table'
                    "cap": cap,
                    "line": ln,
                }
            )
            continue
        h = se.classify_heading(ln, body_size)
        if h:
            events.append({"kind": "heading", "spec": h, "line": ln})
            continue
        events.append({"kind": "body", "line": ln})
    return events


# =====================================================================
# Front matter
# =====================================================================


def _extract_front_matter(front_lines: List[se.LineSpan], page_heights: List[float]) -> Tuple[str, List[str]]:
    """Title = the visually dominant line cluster; authors = remaining front lines."""
    page1_lines = [ln for ln in front_lines if ln.page == 1]
    title = ""
    authors: List[str] = []

    if not page1_lines:
        return title, authors

    first_page_h = page_heights[0] if page_heights else 720.0
    max_size = max(ln.size for ln in page1_lines)
    title_threshold = max_size - 1.2
    candidates = [
        ln
        for ln in page1_lines
        if ln.size >= title_threshold and ln.top < first_page_h * 0.5
    ]
    if candidates:
        candidates.sort(key=lambda ln: (ln.top, ln.x0))
        t0 = candidates[0].top
        block = [ln for ln in candidates if ln.top <= t0 + 60.0]
        block.sort(key=lambda ln: (ln.top, ln.x0))
        title = " ".join(ln.text.strip() for ln in block).strip()

    # Everything else above the first heading is treated as author / affiliation lines
    after_title_top = block[-1].bottom if candidates else page1_lines[0].bottom
    for ln in sorted(page1_lines, key=lambda l: (l.top, l.x0)):
        if ln.top >= after_title_top - 0.5 and ln.text.strip() and len(ln.text.strip()) > 2:
            authors.append(ln.text.strip())

    # Deduplicate preserving order
    seen = set()
    deduped = []
    for a in authors:
        if a not in seen:
            seen.add(a)
            deduped.append(a)
    return title, deduped


# =====================================================================
# Body segmentation
# =====================================================================


def _lines_to_paragraphs(lines: List[se.LineSpan], body_size: float) -> List[str]:
    """Group consecutive body lines into paragraphs on vertical-gap breaks.

    Paragraph breaks occur at gaps noticeably larger than the regular inter-line gap.
    The inter-line baseline is estimated from the lower half of observed gaps so that a
    mix of tightly-spaced lines and slightly larger paragraph spacing is split robustly.
    """
    if not lines:
        return []
    gaps = []
    for a, b in zip(lines, lines[1:]):
        if a.page == b.page and a.column == b.column:
            gaps.append(max(b.top - a.bottom, 0.0))
        else:
            gaps.append(float("inf"))  # force paragraph break across pages / columns
    if not gaps:
        gaps = [0.0]

    finite = sorted(g for g in gaps if g != float("inf"))
    if finite:
        # Baseline = median of the smaller half (i.e. the regular inter-line gap)
        small_half = finite[: max(len(finite) // 2, 1)]
        baseline = statistics.median(small_half)
        threshold = max(baseline * 2.0, body_size * 0.9)
    else:
        threshold = body_size * 0.9

    groups: List[List[se.LineSpan]] = []
    for ln in lines:
        if groups and ln.page == groups[-1][-1].page and ln.column == groups[-1][-1].column:
            gap = max(ln.top - groups[-1][-1].bottom, 0.0)
            if gap <= threshold:
                groups[-1].append(ln)
                continue
        groups.append([ln])

    out = []
    for grp in groups:
        text = " ".join(x.text.strip() for x in grp).strip()
        if text:
            out.append(text)
    return out


# =====================================================================
# Figure building
# =====================================================================


def _image_bbox_above(images: List[se.ImageSpan], caption_line: se.LineSpan) -> Optional[BBox]:
    """BBox of the raster image sitting directly above the caption (same page/column)."""
    matched = _find_image_above(images, caption_line)
    if matched is None:
        return None
    return BBox(x0=matched.x0, top=matched.top, x1=matched.x1, bottom=matched.bottom)


def _find_image_above(images: List[se.ImageSpan], caption_line: se.LineSpan) -> Optional[se.ImageSpan]:
    """Pick the raster image sitting directly above the caption on the same page/column."""
    candidates = []
    for im in images:
        if im.page != caption_line.page:
            continue
        if im.bottom > caption_line.top + 1.0:
            continue
        overlap = min(im.x1, caption_line.x1) - max(im.x0, caption_line.x0)
        if overlap < -(im.x1 - im.x0) * 0.2:
            continue
        candidates.append(im)
    if not candidates:
        return None
    candidates.sort(key=lambda im: (caption_line.top - im.bottom))
    return candidates[0]
