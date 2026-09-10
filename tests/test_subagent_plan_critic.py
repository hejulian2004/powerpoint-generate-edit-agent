"""Unit tests for PlanCriticSubagent isolation and planning review lifecycle."""

import asyncio
import pytest
from typing import List, Dict, Any
from backend.agent.subagents.plan_critic import PlanCriticSubagent, PlanCriticResult
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR


class MockReasoningLLM:
    """Mock reasoning model capturing messages to verify zero context leakage."""
    def __init__(self, reply: str = "【架构优点】: 叙事结构闭环清晰\n【潜在风险】: 无明显风险\n【优化建议】: 重点突出卡片核心数字\n【评审结论】: 通过\n【规划健康分: 92/100】"):
        self.api_key = "test_key_plan_subagent"
        self.reply = reply
        self.received_messages: List[List[Dict[str, Any]]] = []

    async def chat_completion(self, messages, role="reasoning", **kwargs):
        self.received_messages.append(messages)
        return {
            "choices": [{
                "message": {
                    "content": self.reply
                }
            }]
        }


def test_plan_critic_zero_context_leakage():
    """Verify that Plan Critic Subagent receives ZERO conversation history or author reasoning."""
    async def _run():
        mock_llm = MockReasoningLLM()
        events_captured = []

        async def capture_event(ev):
            events_captured.append(ev)

        plan_desc = "规划生成多页精美演示文稿: 包含封面、核心架构、实施流程时间线、关键性能指标与总结展望。"
        res: PlanCriticResult = await PlanCriticSubagent.audit_plan(
            plan_desc=plan_desc,
            target_intent="generate_presentation",
            slide_count=5,
            llm_client=mock_llm,
            on_event=capture_event
        )

        # 1. Verify LLM received exactly 2 messages: system prompt and user prompt
        assert len(mock_llm.received_messages) == 1
        messages = mock_llm.received_messages[0]
        assert len(messages) == 2

        # System message is isolated plan critic prompt
        assert messages[0]["role"] == "system"
        assert "第三方 PPT 策划架构评审总监" in messages[0]["content"]

        # User message has ONLY task intent, count, and plan description
        assert messages[1]["role"] == "user"
        assert "待审大纲架构规划" in messages[1]["content"]
        assert "generate_presentation" in messages[1]["content"]

        # 2. Verify lifecycle broadcasts
        start_events = [e for e in events_captured if e.get("type") == "subagent_lifecycle" and e.get("subagent") == "PlanCriticSubagent" and e.get("phase") == "started"]
        done_events = [e for e in events_captured if e.get("type") == "subagent_lifecycle" and e.get("subagent") == "PlanCriticSubagent" and e.get("phase") == "completed"]

        assert len(start_events) == 1
        assert start_events[0]["main_agent_status"] == "paused_waiting"

        assert len(done_events) == 1
        assert done_events[0]["main_agent_status"] == "resumed"

        # 3. Verify evaluation results
        assert res.approved is True
        assert res.score == 91.2  # 0.4 * 90 + 0.6 * 92 = 36 + 55.2 = 91.2
        assert res.subagent_info["context_isolated"] is True

    asyncio.run(_run())


def test_langgraph_integration_with_plan_critic():
    """Verify that LangGraph planner node invokes PlanCriticSubagent without errors."""
    async def _run():
        app = build_ppt_agent_graph()
        pres = PresentationIR(title="Test Deck", slides=[SlideIR(id="s1", slide_num=1, width=1280, height=720)])

        events = []
        async def on_ev(ev):
            events.append(ev)

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "请为我生成一个关于AI Agent的精美完整PPT",
            "intent": "generate_presentation"
        }

        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "on_event": on_ev
            }
        })

        # Verify plan was reviewed by Subagent
        assert "plan_review" in final_state
        assert final_state["plan_review"] is not None
        assert final_state["plan_review"]["approved"] is True
        assert any(e.get("type") == "subagent_lifecycle" and e.get("subagent") == "PlanCriticSubagent" for e in events)

    asyncio.run(_run())
