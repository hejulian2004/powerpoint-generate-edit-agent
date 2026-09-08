"""Tests for research presentation templates (PR7.2)."""

from backend.presentation.schema import SlideType
from backend.presentation.templates import (
    RESEARCH_10MIN_SLOTS,
    RESEARCH_15MIN_SLOTS,
    get_profile,
)


def test_research_15min_profile_structure():
    profile = get_profile("research_15min")
    assert profile.name == "research_15min"
    assert profile.target_duration_minutes == 15
    assert len(profile.slots) == 12

    types = [slot.slide_type for slot in profile.slots]
    assert types[0] == SlideType.TITLE
    assert types[1] == SlideType.BACKGROUND
    assert SlideType.METHOD_OVERVIEW in types
    assert SlideType.RESULT in types
    assert SlideType.ABLATION in types
    assert types[-1] == SlideType.CONCLUSION


def test_research_10min_profile_structure():
    profile = get_profile("research_10min")
    assert profile.name == "research_10min"
    assert profile.target_duration_minutes == 10
    assert len(profile.slots) == 8

    types = [slot.slide_type for slot in profile.slots]
    assert types[0] == SlideType.TITLE
    assert types[1] == SlideType.BACKGROUND
    assert types[2] == SlideType.METHOD_OVERVIEW
    assert SlideType.LIMITATION in types
    assert types[-1] == SlideType.CONCLUSION


def test_fallback_to_default_profile():
    profile = get_profile("non_existent_profile")
    assert profile.name == "research_15min"
    assert len(profile.slots) == 12
