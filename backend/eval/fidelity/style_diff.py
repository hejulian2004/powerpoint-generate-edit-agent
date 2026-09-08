"""StyleDiff: Evaluates styling fidelity (fill, stroke, opacity, shadows) across slide elements."""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from ...ir.models import SlideIR, ElementIR


@dataclass
class StyleMismatch:
    element_id: str
    property_name: str
    expected_value: Any
    actual_value: Any
    score: float


@dataclass
class StyleDiffReport:
    score: float = 100.0           # 0.0 to 100.0
    fill_score: float = 100.0      # 0.0 to 100.0
    border_score: float = 100.0    # 0.0 to 100.0
    effects_score: float = 100.0   # 0.0 to 100.0
    mismatches: List[StyleMismatch] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "fill_score": round(self.fill_score, 1),
            "border_score": round(self.border_score, 1),
            "effects_score": round(self.effects_score, 1),
            "mismatches_count": len(self.mismatches)
        }


def _hex_to_rgb(hex_str: Optional[str]) -> Tuple[int, int, int]:
    if not hex_str:
        return 0, 0, 0
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    if len(s) == 6:
        try:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        except ValueError:
            pass
    return 0, 0, 0


def _color_distance(hex1: Optional[str], hex2: Optional[str]) -> float:
    """Calculates normalized color similarity score between 0.0 and 1.0 (1.0 = identical)."""
    if not hex1 and not hex2:
        return 1.0
    if not hex1 or not hex2:
        return 0.0
    r1, g1, b1 = _hex_to_rgb(hex1)
    r2, g2, b2 = _hex_to_rgb(hex2)
    dist = math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)
    max_dist = math.sqrt(255 ** 2 + 255 ** 2 + 255 ** 2)  # ~441.67
    return max(0.0, 1.0 - (dist / max_dist))


class StyleDiffEngine:
    """Compares element visual styles between original and reconstructed slides."""

    @classmethod
    def compare_slides(cls, orig_slide: SlideIR, recon_slide: SlideIR) -> StyleDiffReport:
        orig_elements = {el.id: el for el in orig_slide.all_elements(recursive=True)}
        recon_elements = {el.id: el for el in recon_slide.all_elements(recursive=True)}

        fill_scores = []
        border_scores = []
        effects_scores = []
        mismatches: List[StyleMismatch] = []

        for eid, o_el in orig_elements.items():
            r_el = recon_elements.get(eid)
            o_style = getattr(o_el, "style", None)
            r_style = getattr(r_el, "style", None) if r_el else None

            # 1. Fill Evaluation
            o_fill = getattr(o_style, "fill", None) if o_style else None
            r_fill = getattr(r_style, "fill", None) if r_style else None

            f_score = 1.0
            if o_fill and getattr(o_fill, "type", "none") != "none":
                o_color = getattr(o_fill, "color", None)
                r_color = getattr(r_fill, "color", None) if r_fill else None
                f_score = _color_distance(o_color, r_color)
                fill_scores.append(f_score)
                if f_score < 0.9:
                    mismatches.append(StyleMismatch(
                        element_id=eid,
                        property_name="fill.color",
                        expected_value=o_color,
                        actual_value=r_color,
                        score=round(f_score, 2)
                    ))
            elif r_fill and getattr(r_fill, "type", "none") != "none":
                fill_scores.append(0.5)

            # 2. Border Evaluation
            o_border = getattr(o_style, "border", None) if o_style else None
            r_border = getattr(r_style, "border", None) if r_style else None

            b_score = 1.0
            if o_border and getattr(o_border, "style", "none") != "none":
                o_b_color = getattr(o_border, "color", None)
                r_b_color = getattr(r_border, "color", None) if r_border else None
                b_color_score = _color_distance(o_b_color, r_b_color)

                o_w = getattr(o_border, "width", 1.0)
                r_w = getattr(r_border, "width", 1.0) if r_border else 0.0
                w_score = max(0.0, 1.0 - (abs(o_w - r_w) / max(o_w, 1.0)))

                b_score = (b_color_score * 0.6 + w_score * 0.4)
                border_scores.append(b_score)
                if b_score < 0.85:
                    mismatches.append(StyleMismatch(
                        element_id=eid,
                        property_name="border",
                        expected_value={"color": o_b_color, "width": o_w},
                        actual_value={"color": r_b_color, "width": r_w},
                        score=round(b_score, 2)
                    ))

            # 3. Effects / Shadow
            o_shdw = getattr(o_style, "shadow", None) if o_style else None
            r_shdw = getattr(r_style, "shadow", None) if r_style else None
            if o_shdw and getattr(o_shdw, "enabled", False):
                shdw_match = 1.0 if (r_shdw and getattr(r_shdw, "enabled", False)) else 0.3
                effects_scores.append(shdw_match)

        avg_fill = (sum(fill_scores) / len(fill_scores) * 100.0) if fill_scores else 100.0
        avg_border = (sum(border_scores) / len(border_scores) * 100.0) if border_scores else 100.0
        avg_effects = (sum(effects_scores) / len(effects_scores) * 100.0) if effects_scores else 100.0

        comp_score = avg_fill * 0.50 + avg_border * 0.35 + avg_effects * 0.15

        return StyleDiffReport(
            score=round(comp_score, 1),
            fill_score=round(avg_fill, 1),
            border_score=round(avg_border, 1),
            effects_score=round(avg_effects, 1),
            mismatches=mismatches
        )
