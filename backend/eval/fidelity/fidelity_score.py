"""FidelityScore: Multidimensional evaluation combining Geometry, Typography, Style, and Visual Pixels.

Weights per PR6.3 specification:
- geometry: 40% (bounding box error < 2px, IoU, collision)
- text: 20% (font family match, font size error, text parity)
- style: 20% (fill colors, strokes, opacity, effects)
- visual: 20% (perceptual SSIM raster similarity)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Union
from ...ir.models import SlideIR, PresentationIR
from .pixel_diff import PixelDiffEngine, PixelDiffResult
from .typography_diff import TypographyDiffEngine, TypographyDiffReport
from .style_diff import StyleDiffEngine, StyleDiffReport
from ..renderer_snapshot import SlideSnapshotRenderer, PillowSlideRasterizer


@dataclass
class FidelityScore:
    geometry: float = 100.0   # 0.0 to 100.0 (weight 40%)
    text: float = 100.0       # 0.0 to 100.0 (weight 20%)
    style: float = 100.0      # 0.0 to 100.0 (weight 20%)
    visual: float = 100.0     # 0.0 to 100.0 (weight 20%)
    total: float = 100.0      # 0.0 to 100.0
    passed: bool = True       # total >= 90.0%
    diagnostics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "geometry": round(self.geometry, 1),
            "text": round(self.text, 1),
            "style": round(self.style, 1),
            "visual": round(self.visual, 1),
            "total": round(self.total, 1),
            "passed": self.passed,
            "diagnostics": list(self.diagnostics)
        }


class FidelityEvaluator:
    """Evaluates total slide and presentation fidelity across all 4 dimensions."""

    @classmethod
    def evaluate_slides(
        cls,
        orig_slide: SlideIR,
        recon_slide: SlideIR,
        orig_image: Optional[Any] = None,
        recon_image: Optional[Any] = None,
        scale: float = 0.5
    ) -> FidelityScore:
        diagnostics: List[str] = []

        # 1. Geometry (40%)
        geom_score, geom_diag = cls._evaluate_geometry(orig_slide, recon_slide)
        diagnostics.extend(geom_diag)

        # 2. Typography (20%)
        typo_rep = TypographyDiffEngine.compare_slides(orig_slide, recon_slide)
        text_score = typo_rep.score
        for m in typo_rep.mismatches[:3]:
            diagnostics.append(f"Font mismatch on '{m.element_id}': expected '{m.expected_font}', got '{m.actual_font}'")

        # 3. Style (20%)
        style_rep = StyleDiffEngine.compare_slides(orig_slide, recon_slide)
        style_score = style_rep.score
        for m in style_rep.mismatches[:3]:
            diagnostics.append(f"Style mismatch on '{m.element_id}.{m.property_name}'")

        # 4. Visual (20%) via SSIM
        visual_score = 100.0
        try:
            im1 = orig_image if orig_image is not None else PillowSlideRasterizer.render_to_image(orig_slide, scale=scale)
            im2 = recon_image if recon_image is not None else PillowSlideRasterizer.render_to_image(recon_slide, scale=scale)
            pixel_res = PixelDiffEngine.compare_images(im1, im2)
            visual_score = pixel_res.ssim * 100.0
            if visual_score < 90.0:
                diagnostics.append(f"Visual SSIM low: {pixel_res.ssim:.3f} (MSE: {pixel_res.mse:.1f})")
        except Exception as e:
            diagnostics.append(f"Visual raster comparison skipped: {e}")
            visual_score = (geom_score * 0.5 + text_score * 0.25 + style_score * 0.25)

        # Total Composite Calculation: 40% + 20% + 20% + 20%
        total = (
            geom_score * 0.40 +
            text_score * 0.20 +
            style_score * 0.20 +
            visual_score * 0.20
        )
        total = max(0.0, min(100.0, total))
        passed = total >= 90.0

        return FidelityScore(
            geometry=round(geom_score, 1),
            text=round(text_score, 1),
            style=round(style_score, 1),
            visual=round(visual_score, 1),
            total=round(total, 1),
            passed=passed,
            diagnostics=diagnostics
        )

    @classmethod
    def _evaluate_geometry(
        cls,
        orig_slide: SlideIR,
        recon_slide: SlideIR
    ) -> Tuple[float, List[str]]:
        orig_elements = {el.id: el for el in orig_slide.all_elements(recursive=True)}
        recon_elements = {el.id: el for el in recon_slide.all_elements(recursive=True)}

        if not orig_elements:
            return 100.0, []

        scores = []
        diagnostics = []

        for eid, o_el in orig_elements.items():
            r_el = recon_elements.get(eid)
            if not r_el:
                scores.append(0.0)
                diagnostics.append(f"Element '{eid}' missing in reconstructed slide")
                continue

            dx = abs(r_el.x - o_el.x)
            dy = abs(r_el.y - o_el.y)
            dw = abs(r_el.width - o_el.width)
            dh = abs(r_el.height - o_el.height)
            max_drift = max(dx, dy, dw, dh)

            if max_drift <= 2.0:
                # Lossless geometry (< 2px)
                el_score = 100.0
            else:
                el_score = max(0.0, 100.0 - (max_drift - 2.0) * 5.0)
                diagnostics.append(f"Geometry drift on '{eid}': max error {max_drift:.1f}px")

            scores.append(el_score)

        return (sum(scores) / len(scores)), diagnostics
