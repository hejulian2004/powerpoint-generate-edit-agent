"""Phase 1.4: grounding source provenance.

A source supplied for an earlier turn must NOT ground a later, unrelated
generation request. Prior user turns are only bound when the current turn
explicitly refers back to them (continuation markers).
"""

from backend.agent.grounding import assess_generation_request, build_source_bundle


def test_prior_turn_source_does_not_ground_later_unrelated_request():
    messages = [
        {"role": "user", "content": "以下是我的素材：2025年Q3营收97.2亿元，同比增长35%。"},
        {"role": "assistant", "content": "收到，我会基于该资料。"},
    ]
    assessment = assess_generation_request("制作一份关于2025年Q3财报的数据汇报PPT", messages)

    assert assessment.has_source is False
    assert assessment.requires_source is True
    assert assessment.source_origin == "none"


def test_continuation_marker_binds_prior_source():
    messages = [
        {"role": "user", "content": "素材：2025年Q3营收12.3亿元，同比增长35%。"}
    ]
    assessment = assess_generation_request("根据以上资料制作一份汇报PPT", messages)

    assert assessment.has_source is True
    assert assessment.requires_source is False
    assert assessment.source_origin == "conversation"


def test_source_in_current_turn_is_bound():
    assessment = assess_generation_request(
        "制作一份PPT，素材：营收12.3亿元，同比增长35%。"
    )
    assert assessment.has_source is True
    assert assessment.source_origin == "current_turn"


def test_bare_request_has_no_source_origin():
    assessment = assess_generation_request("制作一份关于AI的PPT")
    assert assessment.source_origin == "none"
    assert assessment.enforce_numeric_grounding is False


def test_build_source_bundle_ignores_unreferenced_prior_turns():
    bundle = build_source_bundle(
        "再来一页",
        messages=[{"role": "user", "content": "营收97.2%。"}],
    )
    assert bundle.origin == "none"
    assert "97.2" not in bundle.text
