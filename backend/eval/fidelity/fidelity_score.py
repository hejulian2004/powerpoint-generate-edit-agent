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
    passed: bool = True       # total >= 90.0% AND not degraded
    diagnostics: List[str] = field(default_factory=list)
    # Basis of the visual dimension:
    # - "external_raster": both images were supplied by the caller (e.g. PowerPoint /
    #   LibreOffice rendered screenshots) — the only basis that proves true WYSIWYG fidelity.
    # - "internal_rasterizer": both images were produced by the project's own Pillow
    #   rasterizer; this measures IR-to-IR consistency, NOT PowerPoint visual fidelity.
    # - "fallback": raster comparison failed and the visual score was synthesized from
    #   other dimensions; such a score can never count as a PASS.
    visual_source: str = "raster"
    degraded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "geometry": round(self.geometry, 1),
            "text": round(self.text, 1),
            "style": round(self.style, 1),
            "visual": round(self.visual, 1),
            "total": round(self.total, 1),
            "passed": self.passed,
            "visual_source": self.visual_source,
            "degraded": self.degraded,
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
        scale: float = 0.5,
        strict_visual: bool = False
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
        # NOTE: supplying no images means BOTH sides are rendered by the project's own
        # Pillow rasterizer. That measures IR-to-IR consistency, NOT PowerPoint WYSIWYG
        # fidelity. Only externally supplied screenshots (PowerPoint/LibreOffice) are
        # reported as "external_raster"; pass strict_visual=True to gate on that.
        visual_score = 100.0
        visual_source = "fallback"
        degraded = False
        try:
            im1 = orig_image if orig_image is not None else PillowSlideRasterizer.render_to_image(orig_slide, scale=scale)
            im2 = recon_image if recon_image is not None else PillowSlideRasterizer.render_to_image(recon_slide, scale=scale)
            visual_source = "external_raster" if (orig_image is not None and recon_image is not None) else "internal_rasterizer"
            pixel_res = PixelDiffEngine.compare_images(im1, im2)
            visual_score = pixel_res.ssim * 100.0
            if visual_score < 90.0:
                diagnostics.append(f"Visual SSIM low: {pixel_res.ssim:.3f} (MSE: {pixel_res.mse:.1f})")
        except Exception as e:
            degraded = True
            visual_source = "fallback"
            diagnostics.append(
                f"DEGRADED: visual raster comparison failed ({e}); "
                "visual score was synthesized from other dimensions and cannot count as a PASS"
            )
            visual_score = (geom_score * 0.5 + text_score * 0.25 + style_score * 0.25)

        if strict_visual and visual_source != "external_raster":
            degraded = True
            diagnostics.append(
                f"DEGRADED: strict_visual requested but visual basis is '{visual_source}'; "
                "supply PowerPoint/LibreOffice rendered screenshots for a valid visual acceptance gate"
            )

        # Total Composite Calculation: 40% + 20% + 20% + 20%
        total = (
            geom_score * 0.40 +
            text_score * 0.20 +
            style_score * 0.20 +
            visual_score * 0.20
        )
        total = max(0.0, min(100.0, total))
        passed = total >= 90.0 and not degraded

        return FidelityScore(
            geometry=round(geom_score, 1),
            text=round(text_score, 1),
            style=round(style_score, 1),
            visual=round(visual_score, 1),
            total=round(total, 1),
            passed=passed,
            diagnostics=diagnostics,
            visual_source=visual_source,
            degraded=degraded
        )

    @classmethod
    def _iou(cls, a: Any, b: Any) -> float:
        """Intersection-over-union of two element bounding boxes (0.0 - 1.0)."""
        ax1, ay1, ax2, ay2 = a.x, a.y, a.x + a.width, a.y + a.height
        bx1, by1, bx2, by2 = b.x, b.y, b.x + b.width, b.y + b.height
        inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
        inter = inter_w * inter_h
        union = max(0.0, a.width * a.height) + max(0.0, b.width * b.height) - inter
        if union <= 0.0:
            return 1.0
        return max(0.0, min(1.0, inter / union))

    @classmethod
    def _iou_target(cls, o_el: Any) -> float:
        """Worst-case IoU still achievable by an element within the 2px drift ball.

        The drift gate accepts `max(dx, dy, dw, dh) <= 2`, so a reconstructed box may
        legally be shifted by +/-2px on both axes AND grown by +2px on both
        dimensions. Under that recon, the intersection is always (w-2)(h-2) while
        the union is maximized by the grown box, giving the worst-case:

            inter = (w - 2)(h - 2)
            union = w*h + (w + 2)(h + 2) - inter
            target = min(0.98, inter / union)

        This is the only size-aware bar that cannot penalize a geometry which
        satisfies `max_drift <= 2` (e.g. same-size translation-only IoU for a 50x50
        box is ~0.855, higher than the 0.794 target, because translation does not
        inflate the union). Large elements stay capped at the 0.98 bar.
        """
        w, h = max(1.0, o_el.width), max(1.0, o_el.height)
        if w <= 2.0 or h <= 2.0:
            return 0.0
        inter = (w - 2.0) * (h - 2.0)
        union = (w * h) + ((w + 2.0) * (h + 2.0)) - inter
        if union <= 0.0:
            return 0.0
        return min(0.98, inter / union)

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
            iou = cls._iou(o_el, r_el)
            iou_target = cls._iou_target(o_el)

            # Lossless geometry: < 2px max drift AND IoU at/above the size-aware bar.
            drift_score = 100.0 if max_drift <= 2.0 else max(0.0, 100.0 - (max_drift - 2.0) * 5.0)
            iou_score = 100.0 if iou >= iou_target else max(0.0, (iou / iou_target) * 100.0 if iou_target > 0 else 100.0)
            el_score = min(drift_score, iou_score)

            if max_drift > 2.0:
                diagnostics.append(f"Geometry drift on '{eid}': max error {max_drift:.1f}px")
            if iou < iou_target:
                diagnostics.append(f"Geometry IoU on '{eid}': {iou:.3f} < {iou_target:.3f}")

            scores.append(el_score)

        return (sum(scores) / len(scores)), diagnostics
