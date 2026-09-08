"""Pipeline Failure Recovery and Resilience Tests (PR4.1 Task 5).

Covers:
Case 1: Tool failure (e.g. update_element exception) triggers rollback, output == input.
Case 2: Export failure (e.g. invalid OOXML packaging) returns failed, pres untouched.
Case 3: Vision API failure (e.g. timeout) falls back to geometric critic, pipeline continues.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch
import pytest

from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    TextContentIR, FontIR
)
from backend.ir.converter import import_pptx, export_pptx
from backend.pipeline import PPTEndToEndPipeline, PipelineResult
from backend.eval.visual_critic import VisualCritic


def _create_sample_deck(path: Path) -> PresentationIR:
    pres = PresentationIR(title="Resilience Test Deck")
    slide = SlideIR(id="slide_fail_1", slide_num=1, width=1280, height=720)
    box = ShapeElementIR(id="card_main", x=150.0, y=180.0, width=350.0, height=200.0)
    title = TextElementIR(
        id="title_res",
        x=150.0,
        y=80.0,
        width=500.0,
        height=60.0,
        text_content=TextContentIR.from_plain_text("Original Title Text", font=FontIR(size=28, color="#FFFFFF"))
    )
    slide.add_element(box)
    slide.add_element(title)
    pres.slides = [slide]
    export_pptx(pres, path)
    return pres


def test_failure_recovery_case1_tool_failure_triggers_rollback(tmp_path: Path):
    """Case 1: When a tool execution raises an unhandled exception, pipeline rolls back to input state."""
    in_file = tmp_path / "case1_input.pptx"
    out_file = tmp_path / "case1_output.pptx"
    _create_sample_deck(in_file)

    async def _run():
        pipeline = PPTEndToEndPipeline()

        # Simulate update_element raising an unexpected exception
        with patch.object(
            pipeline.runtime,
            "run_turn",
            side_effect=RuntimeError("update_element() failed with memory corruption")
        ):
            result: PipelineResult = await pipeline.process_deck(
                input_path=in_file,
                user_instruction="将标题修改为故障文字",
                output_path=out_file
            )

            assert result.success is False
            assert "Agent execution failed" in (result.error or "")
            assert "update_element() failed" in (result.error or "")

            # Output was restored to initial snapshot
            assert out_file.exists()
            restored_pres = import_pptx(out_file)
            input_pres = import_pptx(in_file)

            # Verification: output == input (title text and coordinates are unchanged)
            orig_title = input_pres.slides[0].elements[1]
            rest_title = restored_pres.slides[0].elements[1]
            assert orig_title.text_content.plain_text == rest_title.text_content.plain_text
            assert orig_title.x == rest_title.x
            assert orig_title.y == rest_title.y

    asyncio.run(_run())


def test_failure_recovery_case2_export_failure_preserves_state(tmp_path: Path):
    """Case 2: When OOXML export fails, pipeline returns failure without corrupting input or workspace."""
    in_file = tmp_path / "case2_input.pptx"
    out_file = tmp_path / "case2_output.pptx"
    _create_sample_deck(in_file)

    # Read original input byte content
    orig_bytes = in_file.read_bytes()

    async def _run():
        pipeline = PPTEndToEndPipeline()

        # Mock PPTExporter.export_and_validate to simulate corrupt OOXML packaging
        with patch(
            "backend.pipeline.exporter.export_pptx",
            side_effect=IOError("OOXML invalid packaging structure: corrupted zip stream")
        ):
            result: PipelineResult = await pipeline.process_deck(
                input_path=in_file,
                user_instruction="添加一页关于架构的幻灯片",
                output_path=out_file
            )

            assert result.success is False
            assert "Failed to export PPTX" in (result.error or "")
            assert "OOXML invalid packaging structure" in (result.error or "")

            # Verification: input presentation file remains completely untouched
            assert in_file.read_bytes() == orig_bytes

    asyncio.run(_run())


def test_failure_recovery_case3_vision_timeout_falls_back_cleanly(tmp_path: Path):
    """Case 3: When Vision API times out, VisualCritic falls back to geometric critic and pipeline continues."""
    in_file = tmp_path / "case3_input.pptx"
    out_file = tmp_path / "case3_output.pptx"
    _create_sample_deck(in_file)

    class MockFailingVisionLLM:
        api_key = "sk-fake-key"
        async def chat_completion(self, *args, **kwargs):
            raise asyncio.TimeoutError("Vision API upstream gateway timeout after 10000ms")

    async def _run():
        pipeline = PPTEndToEndPipeline()

        # 1. Direct VisualCritic inspection with timing out LLM client
        pres = import_pptx(in_file)
        slide = pres.slides[0]
        review = await VisualCritic.review_slide(
            slide=slide,
            llm_client=MockFailingVisionLLM(),
            include_multimodal=True
        )

        assert review.health_report.score >= 80.0
        assert review.vision_status["vision_available"] is False
        assert review.vision_status["fallback"] == "geometry_only"
        assert "自动回退到几何" in review.vision_status["message"]

        # 2. Pipeline execution continues cleanly despite vision model failure
        with patch.object(pipeline.runtime, "llm", MockFailingVisionLLM()):
            result: PipelineResult = await pipeline.process_deck(
                input_path=in_file,
                user_instruction="优化当前页面",
                output_path=out_file
            )

            assert result.success is True
            assert result.validation_valid is True
            assert out_file.exists()

    asyncio.run(_run())


def test_failure_recovery_nonexistent_input_file_returns_error(tmp_path: Path):
    """Verifies that attempting to process a non-existent PPTX returns failed PipelineResult gracefully."""
    nonexistent = tmp_path / "missing_file_404.pptx"
    out_file = tmp_path / "out_should_not_exist.pptx"

    async def _run():
        pipeline = PPTEndToEndPipeline()
        result: PipelineResult = await pipeline.process_deck(
            input_path=nonexistent,
            user_instruction="检查幻灯片",
            output_path=out_file
        )

        assert result.success is False
        assert result.validation_valid is False
        assert "不存在" in (result.error or "")
        assert not out_file.exists()

    asyncio.run(_run())
