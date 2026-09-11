"""Phase 6: structured ALLOW / PLACEHOLDER / BLOCK grounding policy."""

from backend.agent.graph import _heuristic_tool_planner
from backend.agent.grounding import (
    DECISION_BLOCK,
    DECISION_PLACEHOLDER,
    blocking_verdicts,
    collect_generation_text,
    data_claim_numbers,
    scan_text_verdicts,
)


def _decisions(text: str, source: str = ""):
    return [v.decision for v in scan_text_verdicts(text, source)]


def test_bare_enterprise_term_is_placeholder_with_replacement():
    verdicts = scan_text_verdicts("打造企业级可靠性平台")
    placeholders = [v for v in verdicts if v.decision == DECISION_PLACEHOLDER]
    assert placeholders, "bare 企业级 must degrade to a placeholder"
    assert all(v.replacement for v in placeholders)


def test_specific_enterprise_commitment_escalates_to_block():
    verdicts = scan_text_verdicts("满足企业级 SLA 99.99% 的高并发要求")
    assert any(v.decision == DECISION_BLOCK for v in verdicts)


def test_fuzzy_performance_claim_degrades_with_performance_replacement():
    verdicts = [v for v in scan_text_verdicts("实现毫秒级响应") if v.decision == DECISION_PLACEHOLDER]
    assert verdicts
    assert verdicts[0].replacement == "[待验证性能描述]"


def test_fuzzy_compatibility_claim_degrades_with_compat_replacement():
    verdicts = [v for v in scan_text_verdicts("全平台无缝运行") if v.decision == DECISION_PLACEHOLDER]
    assert verdicts
    assert verdicts[0].replacement == "[待补充兼容性依据]"


def test_unbacked_number_is_blocked_but_design_copy_is_allowed():
    blocked = scan_text_verdicts("准确率达到 99.8%", "")
    assert any(v.decision == DECISION_BLOCK and v.category == "numeric" for v in blocked)
    assert scan_text_verdicts("简洁视觉风格，突出核心结论", "") == []


def test_claims_present_in_source_are_allowed():
    source = "企业级 SLA 99.99%，毫秒级响应"
    assert scan_text_verdicts("企业级 SLA 99.99%，毫秒级响应", source) == []


def test_blocking_verdicts_respects_placeholder_opt_in():
    assert blocking_verdicts("毫秒级响应", "")
    assert blocking_verdicts("毫秒级响应", "", placeholder_ok=True) == []


def test_heuristic_deck_contains_no_fabricated_data_claims():
    calls = _heuristic_tool_planner("generate_presentation", "制作关于AI架构的PPT", None)
    text = collect_generation_text(dict(calls[0]["arguments"]))
    assert data_claim_numbers(text, "") == []
    assert not [v for v in scan_text_verdicts(text, "") if v.decision == DECISION_BLOCK]


def test_heuristic_kpi_slide_contains_no_fabricated_numbers():
    calls = _heuristic_tool_planner("generate_slide", "做一个指标页", None)
    text = collect_generation_text(dict(calls[0]["arguments"]))
    assert data_claim_numbers(text, "") == []
