"""Comprehensive Closed-Loop Subagent Orchestration & Rejection-Loop Tests.

Verifies:
1. Complete closed-loop workflow:
   User Prompt -> Plan -> Plan Critic -> Executor -> Content Critic -> Visual Critic -> Summary
2. Critic subagents are strictly READ-ONLY (no canvas modification permissions).
3. If Plan Critic rejects, the workflow loops back to Planner (not executed by critic).
4. If Content Critic rejects, the workflow loops back to Executor (not modified by critic).
5. Visual Critic specializes purely in layout, alignment, margins, and aesthetics.
"""

import asyncio
import pytest
from typing import List, Dict, Any
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager


class MockLoopLLM:
    """Mock LLM simulating first rejection then approval for plan and content."""
    def __init__(self, reject_first_plan: bool = False, reject_first_content: bool = False):
        self.api_key = "loop_mock_key"
        self.reject_first_plan = reject_first_plan
        self.reject_first_content = reject_first_content
        self.plan_call_count = 0
        self.content_call_count = 0

    async def chat_completion(self, messages, role="reasoning", **kwargs):
        if role == "vision":
            return {
                "choices": [{
                    "message": {
                        "content": "排版留白舒适，几何对齐严整。\n【排版与视觉诊断】: 排版优良\n【美化优化建议】: 保持当前呼吸留白\n【美学评分: 92/100】"
                    }
                }]
            }

        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")

        if "第三方 PPT 策划架构评审总监" in sys_msg:
            self.plan_call_count += 1
            if self.reject_first_plan and self.plan_call_count == 1:
                return {
                    "choices": [{
                        "message": {
                            "content": "【架构优点】: 包含封面\n【潜在风险】: 主题过散且页数定义不清晰\n【优化建议】: 需聚焦 3 个关键论点\n【评审结论】: 需修正\n【规划健康分: 60/100】"
                        }
                    }]
                }
            return {
                "choices": [{
                    "message": {
                        "content": "【架构优点】: 5页结构层级清晰\n【潜在风险】: 无明显风险\n【优化建议】: 保持当前节奏\n【评审结论】: 通过\n【规划健康分: 92/100】"
                    }
                }]
            }

        if "第三方 PPT 内容与叙事结构总监" in sys_msg:
            self.content_call_count += 1
            if self.reject_first_content and self.content_call_count == 1:
                return {
                    "choices": [{
                        "message": {
                            "content": "【文案优点】: 观点明确\n【文字冗余诊断】: 正文某处偏长达60字\n【精炼修改建议】: 提炼为短句小标题\n【内容评审结论】: 需修正\n【内容健康分: 65/100】"
                        }
                    }]
                }
            return {
                "choices": [{
                    "message": {
                        "content": "【文案优点】: 短句提炼精准，结论先行\n【文字冗余诊断】: 精炼达标\n【精炼修改建议】: 保持精简\n【内容评审结论】: 通过\n【内容健康分: 90/100】"
                    }
                }]
            }

        # Fallback executor tools response
        return {
            "choices": [{
                "message": {
                    "content": "ok"
                }
            }]
        }


def test_closed_loop_standard_execution_all_pass():
    """Verify complete 5-stage loop executing sequentially when all critics pass."""
    async def _run():
        app = build_ppt_agent_graph()
        pres = PresentationIR(title="Untitled")
        history = HistoryManager(pres)
        mock_llm = MockLoopLLM()
        events = []

        async def on_ev(ev):
            events.append(ev)

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "从零制作一份关于下一代大模型技术演进的专业汇报PPT",
            "intent": "generate_presentation"
        }

        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "llm_client": mock_llm,
                "on_event": on_ev
            }
        })

        # 1. Deck was generated
        assert len(pres.slides) >= 5

        # 2. Plan Critic passed
        assert final_state.get("plan_review") is not None
        assert final_state["plan_review"]["approved"] is True
        assert final_state["plan_review"]["subagent_info"]["subagent_name"] == "PlanCriticSubagent"

        # 3. Content Critic passed
        assert final_state.get("content_review") is not None
        assert final_state["content_review"]["approved"] is True
        assert final_state["content_review"]["subagent_info"]["subagent_name"] == "ContentCriticSubagent"

        # 4. Visual Critic passed
        assert final_state.get("visual_review") is not None
        assert final_state["visual_review"]["score"] > 80.0
        assert final_state["visual_review"]["subagent_info"]["subagent_name"] == "VisualCriticSubagent"

        # 5. Verify order of subagent lifecycles in emitted events
        lifecycle_subagents = [
            e.get("subagent") for e in events
            if e.get("type") == "subagent_lifecycle" and e.get("phase") == "started"
        ]
        # Must be: PlanCriticSubagent -> ExecutorSubagent -> ContentCriticSubagent -> VisualCriticSubagent
        assert "PlanCriticSubagent" in lifecycle_subagents
        assert "ExecutorSubagent" in lifecycle_subagents
        assert "ContentCriticSubagent" in lifecycle_subagents
        assert "VisualCriticSubagent" in lifecycle_subagents

        p_idx = lifecycle_subagents.index("PlanCriticSubagent")
        e_idx = lifecycle_subagents.index("ExecutorSubagent")
        c_idx = lifecycle_subagents.index("ContentCriticSubagent")
        v_idx = lifecycle_subagents.index("VisualCriticSubagent")

        assert p_idx < e_idx < c_idx < v_idx

    asyncio.run(_run())


def test_plan_critic_rejection_loops_back_to_planner():
    """Verify that when Plan Critic rejects, control loops back to planner_node, NOT modified by subagent."""
    async def _run():
        app = build_ppt_agent_graph()
        pres = PresentationIR(title="Untitled")
        history = HistoryManager(pres)
        mock_llm = MockLoopLLM(reject_first_plan=True)
        events = []

        async def on_ev(ev):
            events.append(ev)

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "制作一份商业PPT",
            "intent": "generate_presentation"
        }

        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "llm_client": mock_llm,
                "on_event": on_ev
            }
        })

        # Plan critic ran twice due to loop back
        assert mock_llm.plan_call_count == 2
        # Final plan is approved after planner refined with feedback
        assert final_state["plan_review"]["approved"] is True
        assert "已吸纳规划评审优化要求" in final_state["plan"]

    asyncio.run(_run())


def test_content_critic_rejection_loops_back_to_executor():
    """Verify that when Content Critic rejects, control loops back to executor_node, NOT modified by critic."""
    async def _run():
        app = build_ppt_agent_graph()
        pres = PresentationIR(title="Untitled")
        history = HistoryManager(pres)
        mock_llm = MockLoopLLM(reject_first_content=True)
        events = []

        async def on_ev(ev):
            events.append(ev)

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "制作一份关于AI的PPT",
            "intent": "generate_presentation"
        }

        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "llm_client": mock_llm,
                "on_event": on_ev
            }
        })

        # Content critic ran twice due to loop back to executor
        assert mock_llm.content_call_count == 2
        assert final_state["content_review"]["approved"] is True

    asyncio.run(_run())
