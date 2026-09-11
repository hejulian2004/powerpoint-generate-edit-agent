"""Tests for chat generation grounding (no source -> ask first; numbers grounded)."""

import asyncio

from backend.agent.graph import mutation_node, router_node
from backend.agent.grounding import (
    assess_generation_request,
    collect_generation_text,
    extract_source_text,
    unsupported_numbers,
)
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager


# =====================================================================
# 1. Grounding assessment
# =====================================================================

def test_factual_request_without_source_requires_clarification():
    assessment = assess_generation_request("根据2025年Q3财报制作一份数据汇报PPT")
    assert assessment.factual_subject is True
    assert assessment.has_source is False
    assert assessment.requires_source is True
    assert assessment.question and "原始资料" in assessment.question
    assert assessment.enforce_numeric_grounding is True


def test_factual_request_with_source_data_is_grounded():
    assessment = assess_generation_request(
        "根据以下资料制作一份数据汇报PPT",
        messages=[{"role": "user", "content": "2025年Q3营收12.3亿元，同比增长35%，覆盖120个城市。"}],
    )
    assert assessment.has_source is True
    assert assessment.requires_source is False
    assert assessment.enforce_numeric_grounding is True


def test_generic_request_needs_no_source():
    assessment = assess_generation_request("制作一份关于公司文化的PPT")
    assert assessment.factual_subject is False
    assert assessment.requires_source is False
    assert assessment.enforce_numeric_grounding is False


def test_placeholder_request_skips_grounding():
    assessment = assess_generation_request("随意生成一份示例数据PPT，用占位内容即可")
    assert assessment.is_placeholder_request is True
    assert assessment.requires_source is False
    assert assessment.enforce_numeric_grounding is False


def test_extract_source_text_concatenates_user_messages():
    source = extract_source_text(
        "再来一页",
        messages=[
            {"role": "user", "content": "第一段素材内容"},
            {"role": "assistant", "content": "收到"},
            {"role": "user", "content": [{"type": "text", "text": "第二段素材内容"}]},
        ],
    )
    assert "第一段素材内容" in source
    assert "第二段素材内容" in source
    assert "收到" not in source


# =====================================================================
# 2. Numeric grounding
# =====================================================================

def test_unsupported_numbers_detects_fabricated_values():
    unsupported = unsupported_numbers("增长35%，覆盖120个城市", "营收增长35%")
    assert unsupported == ["120"]


def test_unsupported_numbers_accepts_equivalent_tokens():
    assert unsupported_numbers("准确率 99.8%", "模型准确率达到99.8%") == []
    assert unsupported_numbers("延迟 < 300ms", "延迟 < 300ms") == []


def test_collect_generation_text_excludes_structural_badges():
    text = collect_generation_text({
        "topic": "AI 平台",
        "slides": [
            {
                "title": "核心功能",
                "items": [
                    {"title": "功能一", "description": "描述", "badge": "01"},
                ],
            }
        ],
    })
    assert "核心功能" in text
    assert "01" not in text


# =====================================================================
# 3. Router clarification gate
# =====================================================================

def test_router_asks_for_source_when_factual_and_ungrounded():
    state = {"user_query": "制作一份关于2025年Q3财报的数据汇报PPT", "messages": []}
    result = asyncio.run(router_node(state, {"configurable": {}}))
    assert result["intent"] == "generate_presentation"
    assert result["grounding_clarification"]
    assert result["grounding"]["requires_source"] is True


def test_router_proceeds_when_source_supplied():
    state = {
        "user_query": "根据以上数据制作一份汇报PPT",
        "messages": [{"role": "user", "content": "2025年Q3营收12.3亿元，同比增长35%。"}],
    }
    result = asyncio.run(router_node(state, {"configurable": {}}))
    assert result["grounding_clarification"] is None
    assert result["grounding"]["has_source"] is True


# =====================================================================
# 4. Mutation-time enforcement
# =====================================================================

def _generation_call(number_text: str) -> dict:
    return {
        "name": "generate_presentation",
        "arguments": {
            "topic": "Q3 汇报",
            "slides": [{"title": number_text, "layout": "card_grid"}],
        },
        "id": "call_ground",
    }


def test_mutation_blocks_ungrounded_numbers():
    async def _run():
        pres = PresentationIR(id="pres_g", title="Deck", slides=[])
        history = HistoryManager(pres)
        state = {
            "intent": "generate_presentation",
            "user_query": "制作一份Q3数据汇报PPT",
            "execution_plan": [_generation_call("同比增长 42%")],
            "grounding": {"source_text": "营收同比增长 35%", "enforce_numeric_grounding": True},
        }
        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert pres.slides == [], "ungrounded generation must not write any slide"
        assert result["grounding_clarification"]
        assert "42" in result["grounding_clarification"]
        blocked = [r for r in result["tool_results"] if r.get("result", {}).get("error") == "unsupported_facts"]
        assert blocked and blocked[0]["result"]["unsupported_numbers"] == ["42%"]

    asyncio.run(_run())


def test_mutation_allows_grounded_numbers():
    async def _run():
        pres = PresentationIR(id="pres_g", title="Deck", slides=[])
        history = HistoryManager(pres)
        state = {
            "intent": "generate_presentation",
            "user_query": "根据以上数据制作PPT",
            "execution_plan": [_generation_call("同比增长 35%")],
            "grounding": {"source_text": "营收同比增长 35%", "enforce_numeric_grounding": True},
        }
        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert len(pres.slides) >= 1
        assert not result.get("grounding_clarification")
        assert all(
            r.get("result", {}).get("success") is not False for r in result["tool_results"]
        )

    asyncio.run(_run())


def test_mutation_skips_enforcement_for_generic_request():
    async def _run():
        pres = PresentationIR(id="pres_g", title="Deck", slides=[])
        history = HistoryManager(pres)
        state = {
            "intent": "generate_presentation",
            "user_query": "制作一份关于AI的PPT",
            "execution_plan": [_generation_call("效率提升 10x")],
            "grounding": {"source_text": "", "enforce_numeric_grounding": False},
        }
        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert len(pres.slides) >= 1
        assert not result.get("grounding_clarification")

    asyncio.run(_run())


# =====================================================================
# 5. Tool-execution-boundary enforcement (Finding 8)
# =====================================================================

def test_mutation_enforces_grounding_for_non_generate_intent():
    """Grounding applies at the tool boundary, not only for generate_presentation.

    The router only assesses the `generate_presentation` intent, but the Executor
    can emit `generate_slide_layout` from e.g. a `generate_slide` intent. A
    fabricated metric must still be blocked even without a router-supplied
    `grounding` entry in state.
    """

    async def _run():
        pres = PresentationIR(id="pres_slide", title="Deck", slides=[])
        history = HistoryManager(pres)
        call = {
            "name": "generate_slide_layout",
            "arguments": {
                "layout": "two_column",
                "items": [
                    {"title": "性能对比", "value": "准确率 99.8%"},
                ],
            },
            "id": "call_slide_ground",
        }
        state = {
            "intent": "generate_slide",
            "user_query": "生成两栏性能指标对比",
            "execution_plan": [call],
        }
        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert result["grounding_clarification"]
        assert "99.8" in result["grounding_clarification"]
        blocked = [
            r for r in result["tool_results"]
            if r.get("result", {}).get("error") == "unsupported_facts"
        ]
        assert blocked, "non-generate_presentation intent must not bypass grounding"

    asyncio.run(_run())


def test_mutation_allows_non_generate_intent_without_factual_subject():
    """Generic (non-factual) requests are not hard-blocked at the boundary."""

    async def _run():
        pres = PresentationIR(id="pres_slide_ok", title="Deck", slides=[])
        history = HistoryManager(pres)
        call = {
            "name": "generate_slide_layout",
            "arguments": {
                "layout": "two_column",
                "items": [{"title": "视觉风格", "value": "简洁大气"}],
            },
            "id": "call_slide_ok",
        }
        state = {
            "intent": "generate_slide",
            "user_query": "生成一页关于设计理念的幻灯片",
            "execution_plan": [call],
        }
        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert not result.get("grounding_clarification")

    asyncio.run(_run())
