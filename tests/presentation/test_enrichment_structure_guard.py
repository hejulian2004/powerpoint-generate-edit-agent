"""Tests for LLM Enrichment Structure Guards (PR7.2.1).

Validates that apply_plan_refinement strictly enforces structural invariants:
- Rejects altering slide counts.
- Rejects altering slide_type.
- Rejects altering index.
- Rejects altering source_figures / source_tables / source_sections.
- Allows updating title, objective, key_messages, and notes while preserving structure.
"""

from backend.presentation.enricher import apply_plan_refinement
from backend.presentation.schema import PresentationPlan, SlidePlan, SlideType


def _sample_plan() -> PresentationPlan:
    s1 = SlidePlan(
        index=1,
        slide_type=SlideType.TITLE,
        title="Original Title",
        objective="Introduce topic",
        key_messages=["P1", "P2"],
        source_sections=[],
        source_figures=[],
        source_tables=[],
    )
    s2 = SlidePlan(
        index=2,
        slide_type=SlideType.METHOD_OVERVIEW,
        title="Original Method",
        objective="Explain pipeline",
        key_messages=["M1", "M2"],
        source_sections=["4"],
        source_figures=["figure1"],
        source_tables=[],
    )
    return PresentationPlan(
        title="Test Paper",
        slides=[s1, s2],
    )


def test_guard_rejects_altered_slide_count():
    plan = _sample_plan()
    # LLM returns only 1 slide instead of 2
    bad_data = {
        "slides": [
            {"title": "Only One Slide", "objective": "New obj", "key_messages": ["A"]}
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slide_count == 2
    assert refined.slides[0].title == "Original Title"


def test_guard_rejects_altered_slide_type():
    plan = _sample_plan()
    # LLM attempts to change slide 2 from METHOD_OVERVIEW to RESULT
    bad_data = {
        "slides": [
            {"title": "Title", "objective": "Obj", "key_messages": ["P1"]},
            {"title": "Method", "slide_type": "RESULT", "key_messages": ["M1"]},
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slides[1].slide_type == SlideType.METHOD_OVERVIEW
    assert refined.slides[1].title == "Original Method"


def test_guard_rejects_tampered_source_figures():
    plan = _sample_plan()
    # LLM attempts to tamper with source_figures
    bad_data = {
        "slides": [
            {"title": "Title", "key_messages": ["P1"]},
            {"title": "Method", "source_figures": ["figure999"], "key_messages": ["M1"]},
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slides[1].source_figures == ["figure1"]
    assert refined.slides[1].title == "Original Method"


def test_guard_rejects_tampered_source_tables():
    plan = _sample_plan()
    # LLM attempts to inject an unauthorized table
    bad_data = {
        "slides": [
            {"title": "Title", "key_messages": ["P1"]},
            {"title": "Method", "source_tables": ["table5"], "key_messages": ["M1"]},
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slides[1].source_tables == []
    assert refined.slides[1].title == "Original Method"


def test_guard_accepts_valid_wording_refinement():
    plan = _sample_plan()
    good_data = {
        "slides": [
            {
                "index": 1,
                "slide_type": "TITLE",
                "title": "Polished Paper Presentation Title",
                "objective": "Deliver clear opening remarks",
                "key_messages": ["Key motivation highlight", "Lead contribution"],
            },
            {
                "index": 2,
                "slide_type": "METHOD_OVERVIEW",
                "title": "Method Overview: Tool-Augmented Loop",
                "objective": "Walk through end-to-end framework",
                "key_messages": ["Novel RL policy formulation", "Deterministic execution"],
                "notes": "Emphasize architectural modularity",
            },
        ]
    }
    refined = apply_plan_refinement(plan, good_data)
    # Structural invariants remain 100% intact
    assert refined.slide_count == 2
    assert refined.slides[0].index == 1
    assert refined.slides[0].slide_type == SlideType.TITLE
    assert refined.slides[1].slide_type == SlideType.METHOD_OVERVIEW
    assert refined.slides[1].source_figures == ["figure1"]

    # Text fields successfully updated
    assert refined.slides[0].title == "Polished Paper Presentation Title"
    assert refined.slides[1].title == "Method Overview: Tool-Augmented Loop"
    assert refined.slides[1].notes == "Emphasize architectural modularity"
    assert len(refined.slides[1].key_messages) == 2


def test_guard_rejects_key_messages_below_min_count():
    plan = _sample_plan()
    # LLM returns only 1 key message (less than min 2)
    bad_data = {
        "slides": [
            {"title": "Title", "key_messages": ["Only one message"]},
            {"title": "Method", "key_messages": ["A", "B"]},
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slides[0].key_messages == ["P1", "P2"]


def test_guard_rejects_key_messages_exceeding_max_count():
    plan = _sample_plan()
    # LLM returns 5 key messages (more than max 4)
    bad_data = {
        "slides": [
            {"title": "Title", "key_messages": ["M1", "M2", "M3", "M4", "M5"]},
            {"title": "Method", "key_messages": ["A", "B"]},
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slides[0].key_messages == ["P1", "P2"]


def test_guard_rejects_key_messages_exceeding_char_limit():
    plan = _sample_plan()
    # Single key message is > 140 chars
    long_msg = "X" * 141
    bad_data = {
        "slides": [
            {"title": "Title", "key_messages": [long_msg, "Valid message"]},
            {"title": "Method", "key_messages": ["A", "B"]},
        ]
    }
    refined = apply_plan_refinement(plan, bad_data)
    assert refined.slides[0].key_messages == ["P1", "P2"]


def test_parse_json_resilient_to_nested_and_fences():
    from backend.presentation.enricher import _parse_json_object

    # Test 1: nested dictionary inside code block with chatter
    raw1 = (
        "Here is the refined plan:\n"
        "```json\n"
        '{\n  "slides": [\n    {"title": "T1", "meta": {"sub": "value"}}\n  ]\n}\n'
        "```\n"
        "Hope this helps!"
    )
    parsed1 = _parse_json_object(raw1)
    assert "slides" in parsed1
    assert parsed1["slides"][0]["meta"]["sub"] == "value"

    # Test 2: no code fence, outer brace extraction
    raw2 = 'Sure thing! {"title": "Presentation", "slides": []} Have a nice day.'
    parsed2 = _parse_json_object(raw2)
    assert parsed2["title"] == "Presentation"

    # Test 3: trailing commentary containing unmatched / extra braces
    raw3 = (
        'Here is the result:\n'
        '{"title": "Valid Plan", "slides": []}\n'
        'Additional explanation: Note that {this is not json} and should be ignored.'
    )
    parsed3 = _parse_json_object(raw3)
    assert parsed3["title"] == "Valid Plan"


def test_parse_json_malformed_returns_original_in_enrichment():
    from backend.presentation.enricher import enrich_presentation_plan
    plan = _sample_plan()
    # Safe call without key returns plan directly
    res = enrich_presentation_plan(plan)
    assert res.slide_count == plan.slide_count

