"""Phase 2.2: ContentCritic rejection produces a targeted rework directive.

When the Content Critic rejects, the graph loops back to the Executor. Before this
change the Executor had no idea what was wrong and could regenerate the whole deck.
Now `content_critic_node` emits a `rework_directive`, `executor_node` forwards it,
and only precise text edits are allowed in rework mode.
"""

import asyncio
import json

from backend.agent.graph import (
    PPTAgentState,
    build_ppt_agent_graph,
    content_critic_node,
)
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager


class RejectingContentLLM:
    api_key = "live_rework_key"

    def __init__(self):
        self.content_calls = 0

    async def chat_completion(self, messages, tools=None, role="reasoning", **kwargs):
        self.content_calls += 1
        return {"choices": [{"message": {"content": (
            "【文案优点】: 观点明确\n"
            "【文字冗余诊断】: 正文某处偏长超过 40 字\n"
            "【精炼修改建议】: 将正文改为'精简结论'\n"
            "【内容评审结论】: 需修正\n"
            "【内容健康分: 58/100】"
        )}}]}


class ReworkLLM:
    api_key = "live_rework_key"

    def __init__(self):
        self.content_calls = 0
        self.executor_messages = []

    async def chat_completion(self, messages, tools=None, role="reasoning", **kwargs):
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        if role == "vision":
            return {"choices": [{"message": {"content": (
                "【排版与视觉诊断】: 排版优良\n【美学评分: 92/100】"
            )}}]}
        if "策划架构评审总监" in sys_msg:
            return {"choices": [{"message": {"content": (
                "【评审结论】: 通过\n【规划健康分: 93/100】"
            )}}]}
        if "内容与叙事结构总监" in sys_msg:
            self.content_calls += 1
            if self.content_calls == 1:
                return {"choices": [{"message": {"content": (
                    "【文字冗余诊断】: 正文某处偏长超过 40 字\n"
                    "【精炼修改建议】: 将正文改为'精简结论'\n"
                    "【内容评审结论】: 需修正\n"
                    "【内容健康分: 58/100】"
                )}}]}
            return {"choices": [{"message": {"content": (
                "【文字冗余诊断】: 精炼达标\n"
                "【精炼修改建议】: 保持\n"
                "【内容评审结论】: 通过\n"
                "【内容健康分: 92/100】"
            )}}]}
        if tools:
            self.executor_messages.append(messages)
            is_rework = any(
                "返工模式" in str(m.get("content", "")) for m in messages
            )
            text = "精简结论" if is_rework else "这是一段非常冗长的正文内容需要被精简处理"
            call_id = "call_rework" if is_rework else "call_seed"
            return {"choices": [{"message": {"tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {
                    "name": "update_element",
                    "arguments": json.dumps({"element_id": "body_1", "text": text}),
                },
            }]}}]}
        return {"choices": [{"message": {"content": "ok"}}]}


def _pres_with_body():
    pres = PresentationIR(title="Rework")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="body_1", x=80.0, y=160.0, width=900.0, height=120.0,
        text_content=TextContentIR.from_plain_text("这是一段非常冗长的正文内容需要被精简处理")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def test_content_critic_node_emits_rework_directive():
    async def _run():
        pres = _pres_with_body()
        llm = RejectingContentLLM()
        out = await content_critic_node(
            {"content_iteration": 0},
            {"configurable": {"pres": pres, "llm_client": llm}},
        )
        directive = out["rework_directive"]
        assert directive is not None
        assert directive["source"] == "content_critic"
        assert directive["slide_id"] == "slide_1"
        assert "body_1" in directive["target_ids"]
        assert any("偏长" in d for d in directive["defects"])
        assert any("精简结论" in r for r in directive["recommendations"])

    asyncio.run(_run())


def test_rework_loop_changes_target_text_and_clears_directive():
    async def _run():
        app = build_ppt_agent_graph()
        pres = _pres_with_body()
        history = HistoryManager()
        llm = ReworkLLM()
        events = []

        async def on_event(payload):
            events.append(payload)

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "把正文文字精简一下",
            "intent": "modify_elements",
        }
        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "llm_client": llm,
                "on_event": on_event,
            }
        })

        # Content critic rejected once, then approved after the targeted rework.
        assert llm.content_calls == 2
        assert final_state["content_review"]["approved"] is True
        assert final_state.get("rework_directive") is None

        # The flagged text actually changed (not a full-deck regeneration).
        body = pres.slides[0].get_element("body_1")
        assert body.text_content.plain_text == "精简结论"

        # The executor saw the rework directive on the second planning pass.
        rework_prompts = [
            messages for messages in llm.executor_messages
            if any("返工模式" in str(m.get("content", "")) for m in messages)
        ]
        assert rework_prompts
        assert any(
            "精简结论" in str(m.get("content", ""))
            for m in rework_prompts[0]
        )

    asyncio.run(_run())
