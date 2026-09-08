"""Tests for PresentationPlan Snapshot and Deterministic Roundtrip (PR7.2.1)."""

import json
from pathlib import Path

from backend.paper.parser import extract_paper
from backend.presentation import PresentationPlan, SlideType, generate_presentation_plan

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_research_15min_plan_snapshot(tmp_path: Path):
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")

    assert plan.slide_count == 12
    assert plan.profile == "research_15min"
    assert plan.duration_minutes == 15

    expected_sequence = [
        SlideType.TITLE,
        SlideType.BACKGROUND,
        SlideType.PROBLEM,
        SlideType.MOTIVATION,
        SlideType.RELATED_WORK,
        SlideType.METHOD_OVERVIEW,
        SlideType.METHOD_DETAIL,
        SlideType.METHOD_DETAIL,
        SlideType.EXPERIMENT_SETUP,
        SlideType.RESULT,
        SlideType.ABLATION,
        SlideType.CONCLUSION,
    ]
    actual_sequence = [s.slide_type for s in plan.slides]
    assert actual_sequence == expected_sequence

    # Verify JSON round-trip snapshot equality
    snap_file = tmp_path / "presentation_plan_15min.json"
    plan.to_json_file(snap_file)
    reloaded = PresentationPlan.from_json_file(snap_file)

    assert reloaded.model_dump() == plan.model_dump()


def test_research_10min_plan_snapshot(tmp_path: Path):
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_10min")

    assert plan.slide_count == 8
    assert plan.profile == "research_10min"
    assert plan.duration_minutes == 10

    expected_sequence = [
        SlideType.TITLE,
        SlideType.BACKGROUND,
        SlideType.METHOD_OVERVIEW,
        SlideType.METHOD_DETAIL,
        SlideType.EXPERIMENT_SETUP,
        SlideType.RESULT,
        SlideType.LIMITATION,
        SlideType.CONCLUSION,
    ]
    actual_sequence = [s.slide_type for s in plan.slides]
    assert actual_sequence == expected_sequence

    snap_file = tmp_path / "presentation_plan_10min.json"
    plan.to_json_file(snap_file)
    reloaded = PresentationPlan.from_json_file(snap_file)

    assert reloaded.model_dump() == plan.model_dump()
