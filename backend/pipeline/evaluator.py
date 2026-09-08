"""Pipeline Visual Evaluator: Diagnostic layout inspection and snapshot generation."""

from __future__ import annotations
import logging
from typing import Optional, Any
from ..ir.models import SlideIR
from ..eval.visual_critic import VisualCritic, VisualReviewResult
from ..eval.renderer_snapshot import SlideSnapshotRenderer, RendererMode

logger = logging.getLogger("backend.pipeline.evaluator")


class PipelineEvaluator:
    """Manages pre/post visual evaluation, defect diagnosis, and snapshot rendering."""

    @classmethod
    async def evaluate_slide(
        cls,
        slide: SlideIR,
        llm_client: Optional[Any] = None,
        include_multimodal: bool = False
    ) -> VisualReviewResult:
        """Conducts full diagnostic inspection on the slide layout."""
        return await VisualCritic.review_slide(
            slide=slide,
            llm_client=llm_client,
            include_multimodal=include_multimodal
        )

    @classmethod
    def capture_snapshot_uri(
        cls,
        slide: SlideIR,
        mode: RendererMode = RendererMode.DETERMINISTIC
    ) -> Optional[str]:
        """Captures a base64 encoded snapshot URI in the requested renderer mode."""
        try:
            return SlideSnapshotRenderer.render_data_uri(slide, mode=mode)
        except Exception as e:
            logger.debug(f"Failed to render snapshot data URI: {e}")
            return None
