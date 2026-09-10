"""Phase 2.1: compressed conversation context reaches the Executor planning call.

The runtime compresses the session transcript into `state["messages"]`; before this
change the Executor LLM only received `[system, user(exec_directive)]`, so multi-turn
context never reached the model that plans tool calls. These tests pin the wiring.
"""

import asyncio

from backend.agent.graph import executor_node
from backend.agent.subagents.executor import (
    ExecutorSubagent,
    _split_conversation_context,
)
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR


class CapturingLLM:
    api_key = "live_test_key"

    def __init__(self):
        self.calls = []

    async def chat_completion(self, messages, tools=None, role="reasoning", **kwargs):
        self.calls.append(list(messages))
        return {"choices": [{"message": {"content": "ok"}}]}


def _pres():
    pres = PresentationIR(title="Context")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title_node", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def test_split_context_windows_chat_and_extracts_anchor():
    context = [
        {"role": "system", "content": "【历史上下文自动压缩摘要】: 早期设计结论"},
        {"role": "user", "content": "第一轮需求"},
        {"role": "assistant", "content": "第一轮回复"},
        {"role": "user", "content": "当前需求"},
    ]
    anchor, chat = _split_conversation_context(context, current_user_query="当前需求")
    assert "压缩摘要" in anchor
    assert [m["content"] for m in chat] == ["第一轮需求", "第一轮回复"]


def test_split_context_caps_long_messages():
    context = [{"role": "user", "content": "x" * 5000}]
    _, chat = _split_conversation_context(context)
    assert len(chat[0]["content"]) == 1200


def test_plan_task_includes_conversation_context():
    async def _run():
        llm = CapturingLLM()
        pres = _pres()
        await ExecutorSubagent.plan_task(
            intent="modify_elements",
            user_query="再往下一点",
            plan_desc="定位目标图元",
            pres=pres,
            llm_client=llm,
            conversation_context=[
                {"role": "system", "content": "【历史上下文自动压缩摘要】: 早期设计结论"},
                {"role": "user", "content": "第一轮需求"},
                {"role": "assistant", "content": "第一轮回复"},
                {"role": "user", "content": "再往下一点"},
            ],
        )
        messages = llm.calls[0]
        assert messages[0]["role"] == "system"
        assert "历史上下文自动压缩摘要" in messages[0]["content"]
        contents = [m["content"] for m in messages]
        assert "第一轮需求" in contents
        assert "第一轮回复" in contents
        # The current user turn must not be duplicated alongside the exec directive.
        assert sum(1 for c in contents if c == "再往下一点") == 0
        assert any("用户输入: 再往下一点" in c for c in contents)

    asyncio.run(_run())


def test_executor_node_forwards_state_messages():
    async def _run():
        llm = CapturingLLM()
        pres = _pres()
        state = {
            "user_query": "再往下一点",
            "intent": "modify_elements",
            "plan": "定位目标图元",
            "messages": [
                {"role": "user", "content": "第一轮需求"},
                {"role": "assistant", "content": "第一轮回复"},
            ],
        }
        await executor_node(state, {"configurable": {
            "pres": pres,
            "llm_client": llm,
            "memory": None,
        }})
        contents = [m["content"] for m in llm.calls[0]]
        assert "第一轮需求" in contents
        assert "第一轮回复" in contents

    asyncio.run(_run())
