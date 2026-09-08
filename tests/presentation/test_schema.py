"""Tests for PresentationPlan & SlidePlan schemas (PR7.2)."""

import json
from pathlib import Path

import pytest

from backend.presentation.schema import PresentationPlan, SlidePlan, SlideType


def test_slide_type_values():
    assert SlideType.TITLE == "TITLE"
    assert SlideType.BACKGROUND == "BACKGROUND"
    assert SlideType.METHOD_OVERVIEW == "METHOD_OVERVIEW"
    assert SlideType.RESULT == "RESULT"
    assert SlideType.ABLATION == "ABLATION"


def test_slide_plan_instantiation():
    slide = SlidePlan(
        index=1,
        slide_type=SlideType.TITLE,
        title="My Great Paper",
        objective="Introduce the paper",
        key_messages=["Point 1", "Point 2"],
        source_sections=["1", "Introduction"],
        source_figures=["figure1"],
        source_tables=["table1"],
        notes="Speak clearly",
    )
    assert slide.index == 1
    assert slide.slide_type == SlideType.TITLE
    assert slide.source_figures == ["figure1"]
    assert slide.source_tables == ["table1"]


def test_presentation_plan_roundtrip(tmp_path: Path):
    slide1 = SlidePlan(
        index=1,
        slide_type=SlideType.TITLE,
        title="AnomalyAgent",
        objective="Title slide",
        key_messages=["Paper Overview"],
    )
    slide2 = SlidePlan(
        index=2,
        slide_type=SlideType.METHOD_OVERVIEW,
        title="Method Overview",
        objective="Explain framework",
        key_messages=["RL Agent", "Tool augmentation"],
        source_sections=["4"],
        source_figures=["figure1"],
    )

    plan = PresentationPlan(
        title="AnomalyAgent",
        audience="Research Lab",
        duration_minutes=15,
        profile="research_15min",
        source_filename="anomaly_agent.pdf",
        slides=[slide1, slide2],
    )

    assert plan.slide_count == 2
    assert len(plan.get_slides_by_type(SlideType.METHOD_OVERVIEW)) == 1

    json_path = tmp_path / "plan.json"
    plan.to_json_file(json_path)
    assert json_path.exists()

    loaded = PresentationPlan.from_json_file(json_path)
    assert loaded.title == plan.title
    assert loaded.duration_minutes == 15
    assert loaded.slide_count == 2
    assert loaded.slides[1].slide_type == SlideType.METHOD_OVERVIEW
    assert loaded.slides[1].source_figures == ["figure1"]
