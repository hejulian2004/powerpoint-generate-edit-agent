"""End-to-End PPT Understanding, IR Editing & Visual Self-Healing Pipeline Runner.

Coordinates the complete closed architectural loop:
input.pptx -> PPT Parser -> PresentationIR -> Vision Analyzer ->
Agent Decision -> Tool Mutations -> Deterministic Rendering ->
Visual Evaluation -> Self-Healing Loop -> Rollback / Commit -> output.pptx -> Validation
"""

from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Callable

from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..agent.runtime import AgentRuntime
from ..agent.remediation_runner import RemediationRunner
from .result import PipelineResult
from .importer import PPTImporter
from .evaluator import PipelineEvaluator
from .exporter import PPTExporter

logger = logging.getLogger("backend.pipeline.runner")


class PPTEndToEndPipeline:
    """Executes end-to-end PPT parsing, agent editing, visual critique, self-healing loop and export."""

    def __init__(self, agent_runtime: Optional[AgentRuntime] = None):
        self.runtime = agent_runtime or AgentRuntime()
        self.importer = PPTImporter
        self.evaluator = PipelineEvaluator
        self.exporter = PPTExporter

    async def process_deck(
        self,
        user_instruction: str,
        output_path: Union[str, Path] = "output.pptx",
        input_path: Optional[Union[str, Path]] = None,
        target_slide_num: Optional[int] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        max_iterations: int = 5
    ) -> PipelineResult:
        """Processes a presentation through the complete agent understanding, editing, and self-healing loop."""
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        history = HistoryManager()

        # 1. Parse or initialize PresentationIR
        pres, in_path_str, import_err = self.importer.load_presentation(input_path, target_slide_num)
        if import_err:
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
                error=import_err
            )

        # Create baseline state snapshot for failure rollback protection
        initial_snapshot = pres.create_snapshot(history=history)

        # 2. Baseline layout evaluation
        active_slide = pres.get_active_slide()
        initial_score = 100.0
        if active_slide and active_slide.elements:
            try:
                pre_critique = await self.evaluator.evaluate_slide(active_slide, include_multimodal=False)
                initial_score = pre_critique.health_report.score
            except Exception as e:
                logger.debug(f"Pre-edit critique failed: {e}")

        # 3. Execute LangGraph Agent Turn
        try:
            agent_result = await self.runtime.run_turn(
                user_message=user_instruction,
                pres=pres,
                history=history,
                on_event=on_event,
                max_iterations=max_iterations
            )
            agent_summary = agent_result.get("reply", "处理完成。")
            executed_tools = list(agent_result.get("tools_executed", []))
        except Exception as e:
            logger.error(f"Agent execution error, restoring initial state: {e}")
            pres.restore_snapshot(initial_snapshot, history=history)
            # Re-export clean initial state if requested on fatal error
            try:
                self.exporter.export_and_validate(pres, out_p)
            except Exception:
                pass
            return PipelineResult(
                input_path=in_path_str,
                output_path=str(out_p),
                user_instruction=user_instruction,
                success=False,
                validation_valid=False,
                initial_score=initial_score,
                final_score=initial_score,
                tools_executed=[],
                agent_summary="",
                slide_count=len(pres.slides),
                presentation_title=pres.title,
                mutation_history=history.get_mutation_events(),
                error=f"Agent execution failed: {str(e)}"
            )

        # 4. Iterative Self-Healing Loop (Observation -> Evaluation -> Remediation -> Verification)
        curr_slide = pres.get_active_slide() or (pres.slides[0] if pres.slides else None)
        for _ in range(max_iterations):
            if not curr_slide or not curr_slide.elements:
                break

            critique = await self.evaluator.evaluate_slide(curr_slide, include_multimodal=False)
            # Break if slide layout is already healthy without critical defects
            if not critique.needs_auto_correction or not critique.remediation_plan.has_critical:
                break

            plan = critique.remediation_plan
            if not plan.auto_executable_actions:
                break

            rem_res = RemediationRunner.apply_plan(
                pres=pres,
                history=history,
                plan=plan,
                slide_id=curr_slide.id,
                only_critical=True,
                on_event=on_event
            )

            # Record any remediation tool actions into executed_tools telemetry
            for fix in rem_res.get("applied_records", []):
                executed_tools.append({
                    "tool": fix["tool"],
                    "arguments": fix.get("args", {}),
                    "result": fix.get("result", {}),
                    "source": "remediation"
                })

            if rem_res.get("rolled_back"):
                logger.info("Remediation triggered quality safety rollback; stopping self-healing loop.")
                break

        # 5. Final Post-edit evaluation and snapshot capture
        final_slide = pres.get_active_slide() or (pres.slides[0] if pres.slides else None)
        final_score = initial_score
        snapshot_uri = None

        if final_slide and final_slide.elements:
            try:
                post_critique = await self.evaluator.evaluate_slide(final_slide, include_multimodal=False)
                final_score = post_critique.health_report.score
                snapshot_uri = post_critique.snapshot_uri or self.evaluator.capture_snapshot_uri(final_slide)
            except Exception as e:
                logger.debug(f"Post-edit critique failed: {e}")

        # 6. Export PresentationIR to OOXML .pptx and validate
        exp_success, is_valid, exp_err = self.exporter.export_and_validate(pres, out_p)
        if not exp_success:
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
                mutation_history=history.get_mutation_events(),
                error=exp_err
            )

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
            snapshot_uri=snapshot_uri,
            mutation_history=history.get_mutation_events()
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
        print(f"Mutation Events:    {len(result.mutation_history)}")
        print(f"\nAgent Summary:\n{result.agent_summary}")
        print(f"\nSaved Output:       {result.output_path}")
        print("=" * 60 + "\n")

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
