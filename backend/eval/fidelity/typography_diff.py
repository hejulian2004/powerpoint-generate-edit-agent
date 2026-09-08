"""TypographyDiff: Precision comparison of font families, sizes, weights, and text strings."""

from __future__ import annotations
import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from ...ir.models import SlideIR, ElementIR


@dataclass
class TypographyMismatch:
    element_id: str
    expected_text: str
    actual_text: str
    expected_font: str
    actual_font: str
    expected_size: float
    actual_size: float
    font_score: float
    size_score: float
    text_score: float


@dataclass
class TypographyDiffReport:
    score: float = 100.0                 # 0.0 to 100.0
    font_match_rate: float = 1.0         # 0.0 to 1.0
    size_match_rate: float = 1.0         # 0.0 to 1.0
    text_match_rate: float = 1.0         # 0.0 to 1.0
    total_text_elements: int = 0
    mismatches: List[TypographyMismatch] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "font_match_rate": round(self.font_match_rate, 4),
            "size_match_rate": round(self.size_match_rate, 4),
            "text_match_rate": round(self.text_match_rate, 4),
            "total_text_elements": self.total_text_elements,
            "mismatches_count": len(self.mismatches)
        }


class TypographyDiffEngine:
    """Evaluates typographic fidelity between original and reconstructed slides."""

    EQUIV_GROUPS = [
        {"calibri", "calibri light", "segoe ui", "arial", "helvetica", "sans-serif"},
        {"times new roman", "times", "cambria", "georgia", "serif"},
        {"consolas", "courier new", "cascadia code", "monospace"},
        {"microsoft yahei", "pingfang sc", "simsun", "dengxian"}
    ]

    @classmethod
    def compare_slides(cls, orig_slide: SlideIR, recon_slide: SlideIR) -> TypographyDiffReport:
        orig_elements = {el.id: el for el in orig_slide.all_elements(recursive=True)}
        recon_elements = {el.id: el for el in recon_slide.all_elements(recursive=True)}

        font_scores = []
        size_scores = []
        text_scores = []
        mismatches: List[TypographyMismatch] = []
        total_text = 0

        for eid, o_el in orig_elements.items():
            o_tc = getattr(o_el, "text_content", None)
            if not o_tc or not o_tc.plain_text.strip():
                continue

            total_text += 1
            r_el = recon_elements.get(eid)
            r_tc = getattr(r_el, "text_content", None) if r_el else None

            o_text = o_tc.plain_text.strip()
            r_text = r_tc.plain_text.strip() if r_tc else ""

            # Text string similarity
            if o_text == r_text:
                t_score = 1.0
            elif o_text.lower() == r_text.lower():
                t_score = 0.95
            else:
                t_score = difflib.SequenceMatcher(None, o_text, r_text).ratio()
            text_scores.append(t_score)

            # Font attributes
            o_font = cls._extract_font(o_tc)
            r_font = cls._extract_font(r_tc) if r_tc else None

            o_name = o_font.name if o_font else "Segoe UI"
            r_name = r_font.name if r_font else ""
            f_score = cls._score_font_family(o_name, r_name)
            font_scores.append(f_score)

            o_size = o_font.size if (o_font and o_font.size) else 18.0
            r_size = r_font.size if (r_font and r_font.size) else 0.0
            delta_sz = abs(o_size - r_size)
            sz_score = max(0.0, 1.0 - (delta_sz / max(o_size, 1.0)))
            size_scores.append(sz_score)

            if t_score < 0.99 or f_score < 0.85 or sz_score < 0.9:
                mismatches.append(TypographyMismatch(
                    element_id=eid,
                    expected_text=o_text[:40],
                    actual_text=r_text[:40],
                    expected_font=o_name,
                    actual_font=r_name,
                    expected_size=round(o_size, 1),
                    actual_size=round(r_size, 1),
                    font_score=round(f_score, 2),
                    size_score=round(sz_score, 2),
                    text_score=round(t_score, 2)
                ))

        if total_text == 0:
            return TypographyDiffReport(score=100.0)

        avg_font = sum(font_scores) / len(font_scores)
        avg_size = sum(size_scores) / len(size_scores)
        avg_text = sum(text_scores) / len(text_scores)

        # Composite score: text string (40%), font family (35%), size (25%)
        comp_score = (avg_text * 0.40 + avg_font * 0.35 + avg_size * 0.25) * 100.0

        return TypographyDiffReport(
            score=round(comp_score, 1),
            font_match_rate=round(avg_font, 4),
            size_match_rate=round(avg_size, 4),
            text_match_rate=round(avg_text, 4),
            total_text_elements=total_text,
            mismatches=mismatches
        )

    @classmethod
    def _score_font_family(cls, expected: str, actual: str) -> float:
        if not actual:
            return 0.0
        e_norm = expected.lower().strip()
        a_norm = actual.lower().strip()
        if e_norm == a_norm:
            return 1.0
        for group in cls.EQUIV_GROUPS:
            if e_norm in group and a_norm in group:
                return 0.90
        # Generic classification fallback
        return 0.40

    @staticmethod
    def _extract_font(tc: Any):
        if tc and tc.paragraphs:
            for p in tc.paragraphs:
                for r in p.runs:
                    if r.font:
                        return r.font
        return None
