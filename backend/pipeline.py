"""End-to-End PPT Understanding, IR Editing & Visual Self-Healing Pipeline.

Coordinates the complete architectural loop:
input.pptx -> PPT Parser -> PresentationIR -> Vision Analyzer ->
Agent Decision -> Tool Mutations -> Deterministic Rendering ->
Visual Evaluation -> Self-Healing Loop -> output.pptx
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Callable

from .ir.models import PresentationIR, SlideIR
from .ir.converter import import_pptx, export_pptx
from .ir.patch import HistoryManager
from .agent.runtime import AgentRuntime
from .eval.visual_critic import VisualCritic, VisualReviewResult
from .eval.renderer_snapshot import SlideSnapshotRenderer
from pptx_agent_converter.validation import validate_pptx

logger = logging.getLogger("backend.pipeline")


@dataclass
class PipelineResult:
    """Consolidated outcome of the end-to-end PPT editing pipeline."""
    input_path: Optional[str]
    output_path: str
    user_instruction: str
    success: bool
    validation_valid: bool
    initial_score: float
    final_score: float
    tools_executed: List[Dict[str, Any]]
    agent_summary: str
    slide_count: int
    presentation_title: str
    snapshot_uri: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "user_instruction": self.user_instruction,
            "success": self.success,
            "validation_valid": self.validation_valid,
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "score_diff": round(self.final_score - self.initial_score, 2),
            "tools_executed": self.tools_executed,
            "agent_summary": self.agent_summary,
            "slide_count": self.slide_count,
            "presentation_title": self.presentation_title,
            "snapshot_uri": self.snapshot_uri,
            "error": self.error
        }


class PPTEndToEndPipeline:
    """Executes end-to-end PPT parsing, agent editing, visual critique, self-healing and export."""

    def __init__(self, agent_runtime: Optional[AgentRuntime] = None):
        self.runtime = agent_runtime or AgentRuntime()

    async def process_deck(
        self,
        user_instruction: str,
        output_path: Union[str, Path] = "output.pptx",
        input_path: Optional[Union[str, Path]] = None,
        target_slide_num: Optional[int] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        max_iterations: int = 5
    ) -> PipelineResult:
        """Processes a presentation through the complete agent understanding and editing loop."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        history = HistoryManager()
        pres: PresentationIR
        in_path_str: Optional[str] = None

        # 1. Parse or initialize PresentationIR
        if input_path and Path(input_path).exists():
            in_p = Path(input_path)
            in_path_str = str(in_p)
            try:
                pres = import_pptx(in_p)
                logger.info(f"Loaded existing presentation '{pres.title}' with {len(pres.slides)} slides from {in_path_str}")
            except Exception as e:
                return PipelineResult(
                    input_path=in_path_str,
                    output_path=str(out_p),
                    user_instruction=user_instruction,
                    success=False,
                    validation_valid=False,
                    initial_score=0.0,
                    final_score=0.0,
                    tools_executed=[],
                    agent_summary="",
                    slide_count=0,
                    presentation_title="",
                    error=f"Failed to import input PPTX: {str(e)}"
                )
        else:
            pres = PresentationIR(title="Untitled Presentation")
            logger.info("Initializing new PresentationIR workspace")

        # 2. Configure target active slide
        if target_slide_num is not None and 1 <= target_slide_num <= len(pres.slides):
            pres.active_slide_id = pres.slides[target_slide_num - 1].id
        elif pres.slides and not pres.active_slide_id:
            pres.active_slide_id = pres.slides[0].id

        active_slide = pres.get_active_slide()
        initial_score = 100.0
        if active_slide and active_slide.elements:
            try:
                pre_critique = await VisualCritic.review_slide(active_slide, include_multimodal=False)
                initial_score = pre_critique.health_report.score
            except Exception as e:
                logger.debug(f"Pre-edit critique failed: {e}")

        # 3. Execute LangGraph Agent Turn (Observe -> Plan -> Execute -> Critique -> Heal)
        try:
            agent_result = await self.runtime.run_turn(
                user_message=user_instruction,
                pres=pres,
                history=history,
                on_event=on_event,
                max_iterations=max_iterations
            )
            agent_summary = agent_result.get("reply", "处理完成。")
            executed_tools = agent_result.get("tools_executed", [])
        except Exception as e:
            return PipelineResult(
                input_path=in_path_str,
                output_path=str(out_p),
                user_instruction=user_instruction,
                success=False,
                validation_valid=False,
                initial_score=initial_score,
                final_score=0.0,
                tools_executed=[],
                agent_summary="",
                slide_count=len(pres.slides),
                presentation_title=pres.title,
                error=f"Agent execution failed: {str(e)}"
            )

        # 4. Post-edit evaluation and screenshot capture
        final_slide = pres.get_active_slide() or (pres.slides[0] if pres.slides else None)
        final_score = 100.0
        snapshot_uri = None

        if final_slide and final_slide.elements:
            try:
                post_critique = await VisualCritic.review_slide(final_slide, include_multimodal=False)
                final_score = post_critique.health_report.score
                snapshot_uri = post_critique.snapshot_uri or SlideSnapshotRenderer.render_data_uri(final_slide)
            except Exception as e:
                logger.debug(f"Post-edit critique failed: {e}")

        # 5. Export PresentationIR to OOXML .pptx
        try:
            export_pptx(pres, out_p)
        except Exception as e:
            return PipelineResult(
                input_path=in_path_str,
                output_path=str(out_p),
                user_instruction=user_instruction,
                success=False,
                validation_valid=False,
                initial_score=initial_score,
                final_score=final_score,
                tools_executed=executed_tools,
                agent_summary=agent_summary,
                slide_count=len(pres.slides),
                presentation_title=pres.title,
                snapshot_uri=snapshot_uri,
                error=f"Failed to export PPTX: {str(e)}"
            )

        # 6. Validate generated OOXML package
        val_res = validate_pptx(out_p)
        is_valid = bool(val_res.get("valid", False))

        return PipelineResult(
            input_path=in_path_str,
            output_path=str(out_p),
            user_instruction=user_instruction,
            success=True,
            validation_valid=is_valid,
            initial_score=initial_score,
            final_score=final_score,
            tools_executed=executed_tools,
            agent_summary=agent_summary,
            slide_count=len(pres.slides),
            presentation_title=pres.title,
            snapshot_uri=snapshot_uri
        )


def main():
    """CLI entrypoint for running the end-to-end agent PPT editing pipeline."""
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="PPT-Agent-Studio: End-to-End PPT Understanding, IR Editing & Visual Self-Healing Pipeline"
    )
    parser.add_argument("-i", "--input", help="Path to input .pptx presentation file", default=None)
    parser.add_argument("-p", "--prompt", help="Natural language instruction for the PPT agent", required=True)
    parser.add_argument("-o", "--output", help="Path to write output .pptx file", default="output.pptx")
    parser.add_argument("-s", "--slide", help="1-based index of target slide to edit", type=int, default=None)
    parser.add_argument("--json", help="Output pipeline result in machine-readable JSON", action="store_true")

    args = parser.parse_args()

    pipeline = PPTEndToEndPipeline()

    async def _run():
        return await pipeline.process_deck(
            input_path=args.input,
            user_instruction=args.prompt,
            output_path=args.output,
            target_slide_num=args.slide
        )

    result = asyncio.run(_run())

    if args.json:
        # Strip long snapshot URI for clean console JSON output unless requested
        res_dict = result.to_dict()
        if res_dict.get("snapshot_uri"):
            res_dict["snapshot_uri"] = res_dict["snapshot_uri"][:40] + "..."
        print(json.dumps(res_dict, ensure_ascii=False, indent=2))
    else:
        print("\n" + "=" * 60)
        print("  PPT-Agent End-to-End Pipeline Execution Summary")
        print("=" * 60)
        print(f"Status:             {'SUCCESS' if result.success else 'FAILED'}")
        print(f"OOXML Valid:        {result.validation_valid}")
        print(f"Presentation Title: {result.presentation_title}")
        print(f"Total Slides:       {result.slide_count}")
        print(f"Layout Health:      {result.initial_score:.1f} -> {result.final_score:.1f} (Diff: {result.final_score - result.initial_score:+.1f})")
        print(f"Tools Executed:     {len(result.tools_executed)}")
        for i, t in enumerate(result.tools_executed, 1):
            print(f"  {i}. {t.get('tool')} ({t.get('result', {}).get('message', 'ok')})")
        print(f"\nAgent Summary:\n{result.agent_summary}")
        print(f"\nSaved Output:       {result.output_path}")
        print("=" * 60 + "\n")

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
