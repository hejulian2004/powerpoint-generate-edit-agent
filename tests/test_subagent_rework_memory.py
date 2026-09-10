"""Unit test: Verify that subagents maintain independent, persistent rework memory across loops."""

import asyncio
import pytest
from typing import List, Dict, Any
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager
from backend.agent.subagents.memory import SubagentSessionMemory


class MockReworkMemoryLLM:
    """Mock LLM verifying that previous round findings are preserved during rework."""
    def __init__(self):
        self.api_key = "rework_mem_test_key"
        self.plan_rounds = 0
        self.received_plan_prompts = []

    async def chat_completion(self, messages, role="reasoning", **kwargs):
        if role == "vision":
            return {
                "choices": [{
                    "message": {
                        "content": "排版优秀。\n【排版与视觉诊断】: 排版优良\n【美化优化建议】: 保持当前呼吸留白\n【美学评分: 90/100】"
                    }
                }]
            }

        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")

        if "第三方 PPT 策划架构评审总监" in sys_msg:
            self.plan_rounds += 1
            user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
            self.received_plan_prompts.append(user_msg)

            if self.plan_rounds == 1:
                # First round rejects
                return {
                    "choices": [{
                        "message": {
                            "content": "【架构优点】: 包含基本标题\n【潜在风险】: 结构篇幅定义模糊\n【优化建议】: 聚焦三大核心矩阵\n【评审结论】: 需修正\n【规划健康分: 62/100】"
                        }
                    }]
                }
            else:
                # Second round sees previous history in prompt and approves
                return {
                    "choices": [{
                        "message": {
                            "content": "【架构优点】: 已核验上一轮整改要求，结构收敛清晰\n【潜在风险】: 无明显风险\n【优化建议】: 落地执行\n【评审结论】: 通过\n【规划健康分: 94/100】"
                        }
                    }]
                }

        # Content and other critic responses
        return {
            "choices": [{
                "message": {
                    "content": "【文案优点】: 精简明了\n【文字冗余诊断】: 精炼达标\n【精炼修改建议】: 保持\n【内容评审结论】: 通过\n【内容健康分: 92/100】"
                }
            }]
        }


def test_subagent_private_memory_preserves_history_on_rework():
    """Verify that when Plan Critic rejects and loops back, round 1 history is preserved and fed to round 2."""
    async def _run():
        app = build_ppt_agent_graph()
        pres = PresentationIR(title="Untitled")
        history = HistoryManager(pres)
        mock_llm = MockReworkMemoryLLM()

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "设计一份多页前沿科技展示PPT",
            "intent": "generate_presentation"
        }

        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "llm_client": mock_llm
            }
        })

        # 1. Plan was audited twice
        assert mock_llm.plan_rounds == 2

        # 2. Check that subagent_memories was populated in the state
        subagent_mems = final_state.get("subagent_memories", {})
        assert "PlanCriticSubagent" in subagent_mems

        plan_mem_dict = subagent_mems["PlanCriticSubagent"]
        assert plan_mem_dict["entries_count"] == 2
        # Round 1 was rejected
        assert plan_mem_dict["entries"][0]["approved"] is False
        assert "结构篇幅定义模糊" in plan_mem_dict["entries"][0]["defects_or_risks"][0]
        # Round 2 was approved
        assert plan_mem_dict["entries"][1]["approved"] is True

        # 3. Check that prompt in round 2 contained the private historical audit trace
        assert len(mock_llm.received_plan_prompts) == 2
        round2_prompt = mock_llm.received_plan_prompts[1]
        assert "Subagent 专属历史审查记忆" in round2_prompt
        assert "第 1 轮评审: 结论=未通过/需修正" in round2_prompt

    asyncio.run(_run())
