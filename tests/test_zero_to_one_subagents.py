"""Unit test: Verify that Plan Critic Subagent and Visual Critic Subagent trigger during 0-to-1 PPT generation."""

import asyncio
import pytest
from typing import List, Dict, Any
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


class MockAgentLLM:
    """Mock LLM supporting reasoning role for Plan Subagent and vision role for Visual Subagent."""
    def __init__(self):
        self.api_key = "live_test_key_zero_to_one"
        self.plan_calls = 0
        self.vision_calls = 0

    async def chat_completion(self, messages, role="reasoning", **kwargs):
        if role == "vision":
            self.vision_calls += 1
            return {
                "choices": [{
                    "message": {
                        "content": "构图呼吸感良好，主次结构分明。\n【美学评分: 90/100】"
                    }
                }]
            }
        else:
            self.plan_calls += 1
            # Reasoning role for plan subagent or tool calls
            # If system message is plan critic
            sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
            if "第三方 PPT 策划架构评审总监" in sys_msg:
                return {
                    "choices": [{
                        "message": {
                            "content": "【架构优点】: 5页结构层级清晰，覆盖封面、功能、演进与指标\n【潜在风险】: 无明显风险\n【优化建议】: 强化结论核心数据\n【评审结论】: 通过\n【规划健康分: 93/100】"
                        }
                    }]
                }
            # Fallback tool call response
            return {
                "choices": [{
                    "message": {
                        "content": "执行生成"
                    }
                }]
            }


def test_zero_to_one_generation_triggers_both_critic_subagents():
    """Verify that from a brand new empty presentation (0 to 1),
    PlanCriticSubagent audits the outline, and VisualCriticSubagent audits generated slides.
    """
    async def _run():
        app = build_ppt_agent_graph()
        # Empty presentation (0 slides)
        pres = PresentationIR(title="Untitled")
        assert len(pres.slides) == 0

        history = HistoryManager(pres)
        mock_llm = MockAgentLLM()
        events_emitted = []

        async def capture_event(ev):
            events_emitted.append(ev)

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "从零制作一份关于量子计算与量子优越性的专业PPT汇报",
            "intent": "generate_presentation"
        }

        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "session": PPTSession(session_id="sess_zero_to_one", pres=pres),
                "llm_client": mock_llm,
                "on_event": capture_event
            }
        })

        # 1. Verify deck is generated from 0 to 5 slides
        assert len(pres.slides) >= 5
        assert "量子计算" in pres.title

        # 2. Verify PlanCriticSubagent triggered during 0-to-1 planning
        assert "plan_review" in final_state
        assert final_state["plan_review"] is not None
        assert final_state["plan_review"]["approved"] is True
        assert final_state["plan_review"]["subagent_info"]["subagent_name"] == "PlanCriticSubagent"
        assert final_state["plan_review"]["subagent_info"]["context_isolated"] is True

        # Check Plan Critic lifecycle events
        plan_starts = [e for e in events_emitted if e.get("type") == "subagent_lifecycle" and e.get("subagent") == "PlanCriticSubagent" and e.get("phase") == "started"]
        plan_dones = [e for e in events_emitted if e.get("type") == "subagent_lifecycle" and e.get("subagent") == "PlanCriticSubagent" and e.get("phase") == "completed"]
        assert len(plan_starts) == 1
        assert plan_starts[0]["main_agent_status"] == "paused_waiting"
        assert len(plan_dones) == 1
        assert plan_dones[0]["main_agent_status"] == "resumed"

        # 3. Verify VisualCriticSubagent triggered after slides were created
        assert "visual_review" in final_state
        assert final_state["visual_review"] is not None
        assert final_state["visual_review"]["score"] > 80.0
        assert final_state["visual_review"]["subagent_info"]["subagent_name"] == "VisualCriticSubagent"
        assert final_state["visual_review"]["subagent_info"]["context_isolated"] is True

        # Check Visual Critic lifecycle events
        vision_starts = [e for e in events_emitted if e.get("type") == "subagent_lifecycle" and e.get("subagent") == "VisualCriticSubagent" and e.get("phase") == "started"]
        vision_dones = [e for e in events_emitted if e.get("type") == "subagent_lifecycle" and e.get("subagent") == "VisualCriticSubagent" and e.get("phase") == "completed"]
        assert len(vision_starts) >= 1
        assert vision_starts[0]["main_agent_status"] == "paused_waiting"
        assert len(vision_dones) >= 1
        assert vision_dones[0]["main_agent_status"] == "resumed"

    asyncio.run(_run())
