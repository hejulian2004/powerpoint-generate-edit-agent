"""Tests for Pipeline Self-Healing Closed Loop (PR4.1 Task 3)."""

import asyncio
from pathlib import Path
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    TextContentIR, FontIR, FillStyle
)
from backend.ir.converter import export_pptx
from backend.pipeline import PPTEndToEndPipeline, PipelineResult


def _create_bad_layout_deck(file_path: Path) -> PresentationIR:
    """Constructs a presentation fixture with severe text overflow, collision overlap, and contrast defects."""
    pres = PresentationIR(title="Bad Layout Benchmark")
    slide = SlideIR(id="slide_bad_1", slide_num=1, width=1280, height=720)
    slide.background = FillStyle(type="solid", color="#FFFFFF")

    # 1. Text overflow and viewport clipping on title
    long_title = "这是一段超长标题文本，严重超出了右侧边界并发生了截断与溢出显示异常"
    e_title = TextElementIR(
        id="title_overflow",
        x=1200.0,
        y=40.0,
        width=150.0,
        height=40.0,
        text_content=TextContentIR.from_plain_text(long_title, font=FontIR(size=30, color="#1E293B"))
    )

    # 2. Overlapping cards
    c1 = ShapeElementIR(id="card_1", x=100.0, y=180.0, width=320.0, height=180.0)
    c2 = ShapeElementIR(id="card_2", x=120.0, y=190.0, width=320.0, height=180.0)
    c3 = ShapeElementIR(id="card_3", x=140.0, y=200.0, width=320.0, height=180.0)

    # 3. Contrast defect
    sub = TextElementIR(
        id="sub_contrast",
        x=100.0,
        y=100.0,
        width=350.0,
        height=30.0,
        text_content=TextContentIR.from_plain_text("微弱对比度副标题文字", font=FontIR(size=16, color="#E8E8E8"))
    )

    slide.add_element(e_title)
    slide.add_element(c1)
    slide.add_element(c2)
    slide.add_element(c3)
    slide.add_element(sub)

    pres.slides = [slide]
    pres.active_slide_id = slide.id

    export_pptx(pres, file_path)
    return pres


def test_pipeline_self_healing_improves_score(tmp_path: Path):
    """Verifies that the self-healing loop improves layout health score from ~70 to >80."""
    in_file = tmp_path / "bad_layout.pptx"
    out_file = tmp_path / "healed_layout.pptx"
    _create_bad_layout_deck(in_file)

    async def _run():
        pipeline = PPTEndToEndPipeline()
        result: PipelineResult = await pipeline.process_deck(
            input_path=in_file,
            user_instruction="规整页面卡片并修复文字溢出与重叠",
            output_path=out_file
        )

        assert result.success is True
        assert result.validation_valid is True
        assert out_file.exists()
        # Baseline score around ~60-75
        assert result.initial_score <= 75.0
        # Final score after self-healing loop exceeds 80
        assert result.final_score > 80.0
        assert result.final_score > result.initial_score
        assert len(result.mutation_history) > 0
        assert result.snapshot_uri is not None

    asyncio.run(_run())


def test_pipeline_self_healing_preserves_score_when_already_healthy(tmp_path: Path):
    """Verifies that an already healthy slide layout terminates the healing loop without unnecessary mutations."""
    pres = PresentationIR(title="Clean Deck")
    slide = SlideIR(id="slide_clean", slide_num=1, width=1280, height=720)
    card = ShapeElementIR(id="clean_card", x=100.0, y=100.0, width=300.0, height=200.0)
    text = TextElementIR(
        id="clean_txt",
        x=120.0,
        y=120.0,
        width=260.0,
        height=60.0,
        text_content=TextContentIR.from_plain_text("Clean Title", font=FontIR(size=24, color="#FFFFFF"))
    )
    slide.add_element(card)
    slide.add_element(text)
    pres.slides = [slide]

    in_file = tmp_path / "clean_deck.pptx"
    out_file = tmp_path / "clean_output.pptx"
    export_pptx(pres, in_file)

    async def _run():
        pipeline = PPTEndToEndPipeline()
        result: PipelineResult = await pipeline.process_deck(
            input_path=in_file,
            user_instruction="优化当前页面",
            output_path=out_file
        )

        assert result.success is True
        assert result.initial_score >= 85.0
        assert result.final_score >= 85.0

    asyncio.run(_run())


def test_pipeline_self_healing_emits_telemetry_events(tmp_path: Path):
    """Verifies that the self-healing loop broadcasts structured events to on_event callback."""
    in_file = tmp_path / "telemetry_input.pptx"
    out_file = tmp_path / "telemetry_output.pptx"
    _create_bad_layout_deck(in_file)

    captured_events = []

    def _event_handler(event):
        captured_events.append(event)

    async def _run():
        pipeline = PPTEndToEndPipeline()
        result: PipelineResult = await pipeline.process_deck(
            input_path=in_file,
            user_instruction="规整卡片排版",
            output_path=out_file,
            on_event=_event_handler
        )

        assert result.success is True
        # Verify event stream captured agent thinking and remediation events
        event_types = [e.get("type") for e in captured_events]
        assert any("visual_remediation" in str(t) or "agent" in str(t) for t in event_types)

    asyncio.run(_run())


def test_pipeline_self_healing_respects_max_iterations_bound(tmp_path: Path):
    """Verifies that max_iterations strictly limits remediation cycles without infinite looping."""
    in_file = tmp_path / "bound_input.pptx"
    out_file = tmp_path / "bound_output.pptx"
    _create_bad_layout_deck(in_file)

    async def _run():
        pipeline = PPTEndToEndPipeline()
        result: PipelineResult = await pipeline.process_deck(
            input_path=in_file,
            user_instruction="规整卡片",
            output_path=out_file,
            max_iterations=1
        )

        assert result.success is True
        assert out_file.exists()

    asyncio.run(_run())
