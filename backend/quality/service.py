"""Unified QualityService facade.

Thin delegation layer over the two quality engines; no algorithms live here:

- IR path: `backend.eval` operates on `SlideIR` (interactive agent / websocket).
- LayoutSpec path: `backend.evaluation` operates on `LayoutSpec` (PPTGeneration).

The LayoutSpec branch is imported lazily because `backend.evaluation` pulls in
PIL and python-pptx; the interactive path must not pay that import cost.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .contracts import (
    QualityReport,
    merge_reports,
)

IR_SOURCE = "ir"
LAYOUT_SOURCE = "layout"
FIDELITY_SOURCE = "fidelity"


class QualityService:
    """Single entry point for layout quality evaluation and remediation planning."""

    # ------------------------------------------------------------------
    # IR path (SlideIR)
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_slide(slide: Any) -> Any:
        """Rule-based geometry/contrast/aesthetic evaluation of a SlideIR."""
        from ..eval.layout_diff import LayoutDiffEngine

        return LayoutDiffEngine.evaluate_slide(slide)

    @staticmethod
    def compare_slides(before: Any, after: Any) -> Any:
        """Score delta and resolved/new defects between two SlideIR snapshots."""
        from ..eval.layout_diff import compare_slides

        return compare_slides(before, after)

    @staticmethod
    def plan_remediation(slide: Any, health_report: Any) -> Any:
        """Translate layout defects into tool-agnostic FixActions."""
        from ..eval.visual_critic import VisualCritic

        return VisualCritic.plan_remediations(slide, health_report)

    @classmethod
    async def review_slide(
        cls,
        slide: Any,
        llm_client: Optional[Any] = None,
        include_multimodal: bool = True,
        on_event: Optional[Any] = None,
    ) -> Any:
        """Run the blind VisualCritic audit loop on a SlideIR."""
        from ..eval.visual_critic import VisualCritic

        return await VisualCritic.review_slide(
            slide=slide,
            llm_client=llm_client,
            include_multimodal=include_multimodal,
            on_event=on_event,
        )

    @staticmethod
    def render_metadata(slide: Optional[Any] = None, mode: Optional[Any] = None) -> Any:
        from ..eval.renderer_snapshot import SlideSnapshotRenderer

        return SlideSnapshotRenderer.get_render_metadata(slide, mode=mode)

    @staticmethod
    def render_svg(slide: Any) -> str:
        from ..eval.renderer_snapshot import SlideSnapshotRenderer

        return SlideSnapshotRenderer.render_svg(slide)

    @staticmethod
    def render_data_uri(
        slide: Any,
        *,
        mode: Optional[Any] = None,
        fallback_to_svg: bool = False,
    ) -> str:
        from ..eval.renderer_snapshot import SlideSnapshotRenderer

        return SlideSnapshotRenderer.render_data_uri(
            slide, mode=mode, fallback_to_svg=fallback_to_svg
        )

    @staticmethod
    def score_fidelity(orig: Any, recon: Any, **kwargs: Any) -> Any:
        """Composite geometry/text/style/visual fidelity score."""
        from ..eval.fidelity.fidelity_score import FidelityEvaluator

        return FidelityEvaluator.evaluate_slides(orig, recon, **kwargs)

    # ------------------------------------------------------------------
    # LayoutSpec path (lazy imports: keeps PIL/python-pptx out of the agent hot path)
    # ------------------------------------------------------------------
    @staticmethod
    def evaluate_layout(
        layout_spec: Any,
        slide_images: Optional[List[Any]] = None,
        evaluator: Optional[Any] = None,
    ) -> List[Any]:
        """Rule-based evaluation of a LayoutSpec/DeckLayoutSpec."""
        if evaluator is None:
            from ..evaluation.evaluator import RuleBasedEvaluator

            evaluator = RuleBasedEvaluator()
        return evaluator.evaluate_deck(
            slide_images=list(slide_images or []), deck_spec=layout_spec
        )

    @staticmethod
    def patches_for_issues(issues: List[Any], layout_spec: Any) -> List[Any]:
        from ..evaluation.repair import generate_patches_for_issues

        return generate_patches_for_issues(issues, layout_spec)

    @staticmethod
    def apply_layout_patches(
        deck_spec: Any,
        patches: List[Any],
        enforce_transaction: bool = True,
    ) -> Any:
        from ..evaluation.patch import apply_deck_patches

        return apply_deck_patches(
            deck_spec, patches, enforce_transaction=enforce_transaction
        )

    # ------------------------------------------------------------------
    # Canonical reports
    # ------------------------------------------------------------------
    @staticmethod
    def report_from_health_report(health_report: Any) -> QualityReport:
        return QualityReport.from_health_report(health_report, source=IR_SOURCE)

    @staticmethod
    def report_from_issues(
        issues: List[Any], slide_id: Optional[str] = None
    ) -> QualityReport:
        return QualityReport.from_visual_issues(
            issues, slide_id=slide_id, source=LAYOUT_SOURCE
        )

    @staticmethod
    def report_from_fidelity(score: Any, slide_id: Optional[str] = None) -> QualityReport:
        return QualityReport.from_fidelity_score(
            score, slide_id=slide_id, source=FIDELITY_SOURCE
        )

    @staticmethod
    def aggregate(*reports: Optional[QualityReport]) -> QualityReport:
        return merge_reports(*reports)
