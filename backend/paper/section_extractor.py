"""Deterministic academic-PDF layout & reading-order extraction.

This module turns a raw PDF into a lightweight, dependency-neutral document model
(``PdfDocument``) that the parser uses to build a ``PaperIR``. Everything here is
deterministic heuristics (no network, no LLM):

- char-level lines with font size / boldness per visual text line
- per-page column detection and reading-order reflow (single / two column)
- caption detection for figures ("Fig. 1: ...") and tables ("Table 1: ...")
- body font estimation used by heading detection

Only ``pdfplumber`` internals live here; ``backend.paper.parser`` consumes the pure
data classes returned by ``analyze_pdf()``.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_FIG_CAPTION_RE = re.compile(
    r"^\s*(?:figure|fig\.?)\s*([0-9]+)\s*[:.\-)]\s*(.*)$", re.IGNORECASE | re.DOTALL
)
_TABLE_CAPTION_RE = re.compile(
    r"^\s*(?:table)\s*([0-9]+|[ivxlcdm]+)\s*[:.\-)]\s*(.*)$", re.IGNORECASE | re.DOTALL
)

_NUM_HEAD_RE = re.compile(r"^\s*(\d{1,2})\.\s+(.{2,120})$")
_SUB_HEAD_RE = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\s+(.{2,120})$")

_KNOWN_TOP_SECTIONS = {
    "introduction": 1,
    "background": 1,
    "related work": 1,
    "related works": 1,
    "preliminaries": 1,
    "problem definition": 1,
    "problem statement": 1,
    "motivation": 1,
    "method": 1,
    "methodology": 1,
    "approach": 1,
    "proposed method": 1,
    "proposed approach": 1,
    "framework": 1,
    "model": 1,
    "architecture": 1,
    "system overview": 1,
    "training": 1,
    "training process": 1,
    "experiments": 1,
    "experimental setup": 1,
    "experimental results": 1,
    "evaluation": 1,
    "results": 1,
    "ablation study": 1,
    "ablation studies": 1,
    "discussion": 1,
    "conclusion": 1,
    "conclusion and future work": 1,
    "conclusions": 1,
    "future work": 1,
    "limitations": 1,
    "acknowledgements": 1,
    "acknowledgment": 1,
    "references": 1,
    "appendix": 1,
    "appendix a": 1,
    "references": 1,
}

_KNOWN_SUBSECTIONS = {
    "dataset": 2,
    "datasets": 2,
    "implementation details": 2,
    "implementation": 2,
    "metrics": 2,
    "baselines": 2,
    "baseline": 2,
    "training details": 2,
    "training settings": 2,
    "qualitative results": 2,
    "quantitative results": 2,
}

_ABSTRACT_HEAD_RE = re.compile(r"^\s*(?:abstract)\b", re.IGNORECASE)


@dataclass
class LineSpan:
    """One visual text line on a page."""

    page: int  # 1-based
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bold: bool
    font: str
    column: int = 0
    seq: int = 0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 0.5)


@dataclass
class ImageSpan:
    """A raster image object embedded on a page."""

    page: int  # 1-based
    x0: float
    x1: float
    top: float
    bottom: float
    name: str
    xref: Optional[int] = None

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass
class PdfDocument:
    """Dependency-neutral extraction result for the whole PDF."""

    page_count: int
    lines: List[LineSpan] = field(default_factory=list)  # document reading order
    images: List[ImageSpan] = field(default_factory=list)
    page_widths: List[float] = field(default_factory=list)
    page_heights: List[float] = field(default_factory=list)


def analyze_pdf(path: Any) -> PdfDocument:
    """Extract ordered lines + images from a PDF (pdfplumber backend)."""
    import pdfplumber

    doc = PdfDocument(page_count=0)
    with pdfplumber.open(path) as pdf:
        doc.page_count = len(pdf.pages)
        for page_idx, page in enumerate(pdf.pages, start=1):
            doc.page_widths.append(float(page.width))
            doc.page_heights.append(float(page.height))

            page_lines = _chars_to_lines(page, page_idx)
            two_col, columns = _detect_columns(page_lines, float(page.width))
            if two_col and len(columns) == 2:
                for ln in page_lines:
                    ln.column = 0 if ln.center_x <= (columns[0][1] + columns[1][0]) / 2.0 else 1
                page_lines = _interleave_columns(page_lines)

            # Stabilize ordering within a single-column page
            if not two_col:
                page_lines.sort(key=lambda ln: (round(ln.top, 1), ln.x0))

            for seq, ln in enumerate(page_lines):
                ln.seq = seq
            doc.lines.extend(page_lines)

            for img in page.images:
                doc.images.append(
                    ImageSpan(
                        page=page_idx,
                        x0=float(img.get("x0", 0.0)),
                        x1=float(img.get("x1", 0.0)),
                        top=float(img.get("top", 0.0)),
                        bottom=float(img.get("bottom", 0.0)),
                        name=str(img.get("name", "")),
                        xref=img.get("xref"),
                    )
                )
    return doc


def _chars_to_lines(page: Any, page_idx: int) -> List[LineSpan]:
    """Merge pdfplumber chars into visual lines with font metadata + spacing."""
    chars = [c for c in page.chars if c.get("text", "").strip() != ""]
    chars.sort(key=lambda c: (round(float(c["top"]), 1), float(c["x0"])))

    raw_lines: List[List[Dict[str, Any]]] = []
    for ch in chars:
        top = float(ch["top"])
        if raw_lines:
            ref_top = float(raw_lines[-1][0]["top"])
            if abs(top - ref_top) <= 2.5:
                raw_lines[-1].append(ch)
                continue
        raw_lines.append([ch])

    lines: List[LineSpan] = []
    for group in raw_lines:
        group.sort(key=lambda c: float(c["x0"]))
        size = _median_float([float(c["size"]) for c in group])
        font = group[0].get("fontname", "")
        bold = _is_bold_font(font) or any(_is_bold_font(str(c.get("fontname", ""))) for c in group)

        text_parts: List[str] = []
        prev_x1: Optional[float] = None
        for c in group:
            x0, x1 = float(c["x0"]), float(c["x1"])
            if prev_x1 is not None:
                gap = x0 - prev_x1
                space_est = max(float(c["size"]) * 0.22, 1.2)
                if gap > space_est:
                    text_parts.append(" ")
            text_parts.append(str(c["text"]))
            prev_x1 = x1
        text = "".join(text_parts).strip()
        if not text:
            continue

        lines.append(
            LineSpan(
                page=page_idx,
                text=text,
                x0=float(group[0]["x0"]),
                x1=float(group[-1]["x1"]),
                top=float(group[0]["top"]),
                bottom=float(group[-1]["bottom"]),
                size=size,
                bold=bold,
                font=font,
            )
        )
    return lines


def _detect_columns(lines: List[LineSpan], page_width: float) -> Tuple[bool, List[Tuple[float, float]]]:
    """Detect a two-column layout via the vertical gutter in line-center histogram.

    Returns ``(is_two_column, [(x_start, x_end), ...])`` where the column ranges cover
    the text area only when two columns are detected (otherwise empty list).
    """
    if len(lines) < 12:
        return False, []

    centers = sorted(ln.center_x for ln in lines if ln.text)
    if len(centers) < 12:
        return False, []
    lo, hi = centers[0], centers[-1]
    if hi - lo < page_width * 0.25:
        return False, []

    # Histogram of line centers in 12pt bins across the text span
    bin_w = 12.0
    n_bins = max(int((hi - lo) / bin_w) + 1, 2)
    hist = [0] * n_bins
    for cx in centers:
        idx = min(int((cx - lo) / bin_w), n_bins - 1)
        hist[idx] += 1

    # Find a wide, nearly-empty gutter band strictly inside the text span
    total = len(centers)
    min_empty_ratio = 0.60
    i = 0
    while i < n_bins:
        if hist[i] / total >= 0.02:
            i += 1
            continue
        j = i
        while j < n_bins and hist[j] / total < min_empty_ratio:
            j += 1
        gutter_bins = j - i
        if gutter_bins >= 3:
            left_end = lo + i * bin_w
            right_start = lo + j * bin_w
            left_count = sum(1 for cx in centers if cx <= left_end)
            right_count = sum(1 for cx in centers if cx >= right_start)
            if left_count >= 4 and right_count >= 4 and left_count + right_count > total * 0.8:
                return True, [(lo, left_end), (right_start, hi)]
        i = j
    return False, []


def _interleave_columns(lines: List[LineSpan]) -> List[LineSpan]:
    """Return two columns merged in reading order (top-most next line wins)."""
    col0 = sorted((ln for ln in lines if ln.column == 0), key=lambda ln: (ln.top, ln.x0))
    col1 = sorted((ln for ln in lines if ln.column == 1), key=lambda ln: (ln.top, ln.x0))
    merged: List[LineSpan] = []
    i = j = 0
    while i < len(col0) or j < len(col1):
        if i < len(col0) and (j >= len(col1) or col0[i].top <= col1[j].top):
            merged.append(col0[i])
            i += 1
        else:
            merged.append(col1[j])
            j += 1
    return merged


def estimate_body_size(lines: List[LineSpan]) -> float:
    """Robust modal body font size across the document."""
    sizes = [ln.size for ln in lines if 4.0 <= ln.size <= 24.0]
    if not sizes:
        return 10.0
    sizes.sort()
    trimmed = sizes[int(len(sizes) * 0.1): int(len(sizes) * 0.95)]
    if not trimmed:
        trimmed = sizes
    # Round to nearest 0.25pt and pick the mode -> stable across fonts/weights
    quantized = [round(s * 4) / 4 for s in trimmed]
    try:
        mode = statistics.mode(quantized)
    except statistics.StatisticsError:
        mode = statistics.median(quantized)
    return float(mode)


def is_caption_line(text: str) -> bool:
    """True when a line is a figure or table caption opener."""
    return _caption_match(text) is not None


def caption_kind(text: str) -> Optional[str]:
    match = _caption_match(text)
    return match[0] if match else None


def caption_match(text: str) -> Optional[Tuple[str, str, str]]:
    """Return (kind, xref_label, caption_text) for a caption line, else None."""
    return _caption_match(text)


def _caption_match(text: str) -> Optional[Tuple[str, str, str]]:
    t = text.strip()
    m = _FIG_CAPTION_RE.match(t)
    if m:
        num = m.group(1)
        prefix = "Fig." if t[:3].lower() == "fig" else "Figure"
        return ("figure", f"{prefix} {num}", m.group(2).strip())
    m = _TABLE_CAPTION_RE.match(t)
    if m:
        num = m.group(1)
        is_roman = re.fullmatch(r"[IVXLCDM]+", num) is not None
        return ("table", f"Table {num}", m.group(2).strip()) if not is_roman else ("table", f"TABLE {num}", m.group(2).strip())
    return None


def classify_heading(line: LineSpan, body_size: float) -> Optional[Dict[str, Any]]:
    """Classify a line as a section heading.

    Returns a dict {number, title, level, is_abstract} or None. A line is treated as a
    heading only when it is short, and (matches a known section name) OR (is emphasised
    via bold/larger font AND carries a numeric / short-title shape).
    """
    text = line.text.strip()
    if not text or len(text) > 140:
        return None
    if is_caption_line(text):
        return None
    if _ABSTRACT_HEAD_RE.match(text) and len(text) <= 24:
        return {"number": None, "title": text, "level": 1, "is_abstract": True}

    emphasised = line.bold or line.size >= body_size + 0.4
    lowered = text.lower().lstrip("0123456789. ").strip()
    lead_word = re.split(r"[\s:,]", lowered, maxsplit=1)[0] if lowered else ""

    # Numbered subsection forms: "2.1 Method"
    m = _SUB_HEAD_RE.match(text)
    if m and emphasised:
        return {"number": m.group(1), "title": m.group(2).strip(), "level": 2, "is_abstract": False}

    # Numbered top-level forms: "1. Introduction". The numeric prefix already
    # disambiguates these from body sentences, so a trailing '.' is allowed.
    m = _NUM_HEAD_RE.match(text)
    if m and emphasised:
        return {"number": m.group(1), "title": m.group(2).strip(), "level": 1, "is_abstract": False}

    # Known top-level name (no numeric prefix) e.g. "Introduction", "References".
    # Body paragraphs can start with words like "Experiments", so we require the line
    # to be visually emphasised (bold / larger font) to avoid false positives.
    if lead_word in _KNOWN_TOP_SECTIONS or lowered in _KNOWN_TOP_SECTIONS:
        if emphasised and _looks_like_heading(text) and len(text) <= 80:
            return {"number": None, "title": text, "level": 1, "is_abstract": False}

    # Known subsection keyword without number, when emphasised (e.g. "Dataset").
    if lead_word in _KNOWN_SUBSECTIONS and emphasised and _looks_like_heading(text):
        return {"number": None, "title": text, "level": 2, "is_abstract": False}

    return None


def _looks_like_heading(text: str) -> bool:
    """Very short structural guard: headings do not end with '.', ';', ':' sentence tails."""
    stripped = text.strip()
    if len(stripped) < 2:
        return False
    # Allow trailing ':' (e.g. "References:") but not '.'
    if stripped.endswith("."):
        return False
    return True


def _is_bold_font(fontname: str) -> bool:
    low = fontname.lower()
    return "bold" in low or "black" in low or "heavy" in low


def _median_float(values: List[float]) -> float:
    if not values:
        return 10.0
    return float(statistics.median(values))
