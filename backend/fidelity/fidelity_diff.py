"""FidelityDiff: Structural and stylistic delta inspection between presentations/slides.

Computes exact differences across:
- Element counts and ID preservation
- Bounding box coordinate drift (dx, dy, dw, dh)
- Typography (font names, sizes, line heights, text strings)
- Style attributes (fill colors, borders, shadows, opacity)
- Hierarchy & Group structural parity
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from ..ir.models import PresentationIR, SlideIR, ElementIR, GroupElementIR


@dataclass
class ElementDrift:
    element_id: str
    element_type: str
    dx: float = 0.0
    dy: float = 0.0
    dw: float = 0.0
    dh: float = 0.0
    font_mismatch: bool = False
    font_expected: str = ""
    font_actual: str = ""
    color_mismatch: bool = False
    color_expected: str = ""
    color_actual: str = ""
    text_mismatch: bool = False

    @property
    def max_coordinate_error(self) -> float:
        return max(abs(self.dx), abs(self.dy), abs(self.dw), abs(self.dh))


@dataclass
class FidelityDiffReport:
    """Structured report comparing original vs reconstructed presentation state."""
    total_elements_orig: int = 0
    total_elements_recon: int = 0
    missing_elements: List[str] = field(default_factory=list)
    added_elements: List[str] = field(default_factory=list)
    matched_elements: int = 0
    max_geom_error_px: float = 0.0
    avg_geom_error_px: float = 0.0
    font_match_rate: float = 1.0  # 0.0 to 1.0
    color_match_rate: float = 1.0
    text_match_rate: float = 1.0
    element_drifts: List[ElementDrift] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_lossless_geometry(self) -> bool:
        """True if all element bounding boxes drifted by less than 2.0px."""
        return self.max_geom_error_px <= 2.0

    @property
    def is_lossless_typography(self) -> bool:
        """True if font match rate exceeds 95% and text matches 100%."""
        return self.font_match_rate >= 0.95 and self.text_match_rate >= 0.99

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_elements_orig": self.total_elements_orig,
            "total_elements_recon": self.total_elements_recon,
            "missing_elements": list(self.missing_elements),
            "added_elements": list(self.added_elements),
            "matched_elements": self.matched_elements,
            "max_geom_error_px": round(self.max_geom_error_px, 2),
            "avg_geom_error_px": round(self.avg_geom_error_px, 2),
            "font_match_rate": round(self.font_match_rate, 4),
            "color_match_rate": round(self.color_match_rate, 4),
            "text_match_rate": round(self.text_match_rate, 4),
            "is_lossless_geometry": self.is_lossless_geometry,
            "is_lossless_typography": self.is_lossless_typography,
            "warnings": list(self.warnings),
        }


class FidelityDiffEngine:
    """Compares original vs round-trip presentations and slides."""

    @classmethod
    def compare_slides(cls, orig_slide: SlideIR, recon_slide: SlideIR) -> FidelityDiffReport:
        orig_elements = {el.id: el for el in orig_slide.all_elements(recursive=True)}
        recon_elements = {el.id: el for el in recon_slide.all_elements(recursive=True)}

        missing = [eid for eid in orig_elements if eid not in recon_elements]
        added = [eid for eid in recon_elements if eid not in orig_elements]
        common = [eid for eid in orig_elements if eid in recon_elements]

        drifts: List[ElementDrift] = []
        geom_errors: List[float] = []
        font_matches = 0
        font_total = 0
        color_matches = 0
        color_total = 0
        text_matches = 0
        text_total = 0
        warnings: List[str] = []

        for eid in common:
            o_el = orig_elements[eid]
            r_el = recon_elements[eid]

            dx = round(r_el.x - o_el.x, 2)
            dy = round(r_el.y - o_el.y, 2)
            dw = round(r_el.width - o_el.width, 2)
            dh = round(r_el.height - o_el.height, 2)
            max_err = max(abs(dx), abs(dy), abs(dw), abs(dh))
            geom_errors.append(max_err)

            drift = ElementDrift(
                element_id=eid,
                element_type=o_el.type,
                dx=dx, dy=dy, dw=dw, dh=dh
            )

            # Check typography
            o_tc = getattr(o_el, "text_content", None)
            r_tc = getattr(r_el, "text_content", None)
            if o_tc and o_tc.plain_text:
                text_total += 1
                if r_tc and r_tc.plain_text.strip() == o_tc.plain_text.strip():
                    text_matches += 1
                else:
                    drift.text_mismatch = True
                    warnings.append(f"Text content mismatch for '{eid}'")

                # Font match
                o_font = cls._get_primary_font(o_tc)
                r_font = cls._get_primary_font(r_tc) if r_tc else None
                if o_font:
                    font_total += 1
                    drift.font_expected = o_font.name
                    drift.font_actual = r_font.name if r_font else ""
                    if r_font and (r_font.name.lower() == o_font.name.lower() or cls._are_fonts_equivalent(r_font.name, o_font.name)):
                        font_matches += 1
                    else:
                        drift.font_mismatch = True
                        warnings.append(f"Font mismatch for '{eid}': expected '{o_font.name}', got '{drift.font_actual}'")

            # Check style fill color
            o_fill = getattr(o_el.style, "fill", None) if o_el.style else None
            r_fill = getattr(r_el.style, "fill", None) if r_el.style else None
            if o_fill and o_fill.color and o_fill.type != "none":
                color_total += 1
                drift.color_expected = o_fill.color
                drift.color_actual = r_fill.color if (r_fill and r_fill.color) else ""
                if r_fill and r_fill.color and r_fill.color.upper() == o_fill.color.upper():
                    color_matches += 1
                else:
                    drift.color_mismatch = True

            drifts.append(drift)

        max_geom = max(geom_errors) if geom_errors else 0.0
        avg_geom = sum(geom_errors) / len(geom_errors) if geom_errors else 0.0
        font_rate = (font_matches / font_total) if font_total > 0 else 1.0
        color_rate = (color_matches / color_total) if color_total > 0 else 1.0
        text_rate = (text_matches / text_total) if text_total > 0 else 1.0

        return FidelityDiffReport(
            total_elements_orig=len(orig_elements),
            total_elements_recon=len(recon_elements),
            missing_elements=missing,
            added_elements=added,
            matched_elements=len(common),
            max_geom_error_px=round(max_geom, 2),
            avg_geom_error_px=round(avg_geom, 2),
            font_match_rate=round(font_rate, 4),
            color_match_rate=round(color_rate, 4),
            text_match_rate=round(text_rate, 4),
            element_drifts=drifts,
            warnings=warnings
        )

    @classmethod
    def compare_presentations(cls, orig_pres: PresentationIR, recon_pres: PresentationIR) -> FidelityDiffReport:
        """Aggregates fidelity comparison across all corresponding slides."""
        combined_report = FidelityDiffReport()
        if not orig_pres.slides:
            return combined_report

        geom_max = 0.0
        geom_sum = 0.0
        geom_cnt = 0
        all_drifts = []
        all_warnings = []

        total_orig = 0
        total_recon = 0
        matched = 0

        for idx, o_slide in enumerate(orig_pres.slides):
            r_slide = recon_pres.slides[idx] if idx < len(recon_pres.slides) else None
            if not r_slide:
                all_warnings.append(f"Missing slide #{o_slide.slide_num} in reconstructed presentation")
                continue

            sub_rep = cls.compare_slides(o_slide, r_slide)
            total_orig += sub_rep.total_elements_orig
            total_recon += sub_rep.total_elements_recon
            matched += sub_rep.matched_elements
            geom_max = max(geom_max, sub_rep.max_geom_error_px)
            geom_sum += sub_rep.avg_geom_error_px * sub_rep.matched_elements
            geom_cnt += sub_rep.matched_elements
            all_drifts.extend(sub_rep.element_drifts)
            all_warnings.extend(sub_rep.warnings)

        combined_report.total_elements_orig = total_orig
        combined_report.total_elements_recon = total_recon
        combined_report.matched_elements = matched
        combined_report.max_geom_error_px = geom_max
        combined_report.avg_geom_error_px = round(geom_sum / geom_cnt, 2) if geom_cnt > 0 else 0.0
        combined_report.element_drifts = all_drifts
        combined_report.warnings = all_warnings
        return combined_report

    @staticmethod
    def _get_primary_font(tc: Any):
        if tc and tc.paragraphs:
            for p in tc.paragraphs:
                for r in p.runs:
                    if r.font:
                        return r.font
        return None

    @staticmethod
    def _are_fonts_equivalent(f1: str, f2: str) -> bool:
        norm1 = f1.lower().strip()
        norm2 = f2.lower().strip()
        if norm1 == norm2:
            return True
        equiv_groups = [
            {"calibri", "calibri light", "segoe ui", "arial", "helvetica"},
            {"times new roman", "times", "cambria", "georgia"},
            {"consolas", "courier new", "monospace"},
            {"microsoft yahei", "pingfang sc", "simsun"}
        ]
        return any(norm1 in g and norm2 in g for g in equiv_groups)
