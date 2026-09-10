"""Unit tests for VisualCriticSubagent isolation and lifecycle."""

import asyncio
import pytest
from typing import List, Dict, Any
from backend.ir.models import SlideIR, TextElementIR, TextContentIR, FontIR
from backend.agent.subagents.visual_critic import VisualCriticSubagent


class MockVisionLLM:
    """Mock vision model capturing sent messages to verify zero context leakage."""
    def __init__(self, reply: str = "构图规整。\n【美学评分: 88/100】"):
        self.api_key = "test_key_subagent"
        self.reply = reply
        self.received_messages: List[List[Dict[str, Any]]] = []

    async def chat_completion(self, messages, role="vision", **kwargs):
        self.received_messages.append(messages)
        return {
            "choices": [{
                "message": {
                    "content": self.reply
                }
            }]
        }


def test_subagent_zero_context_leakage():
    """Verify that Subagent receives ZERO main agent conversation history or author reasoning."""
    async def _run():
        slide = SlideIR(id="slide_blind", slide_num=1, width=1280, height=720)
        slide.add_element(TextElementIR(
            id="t1", x=80, y=80, width=800, height=60,
            text_content=TextContentIR.from_plain_text("严苛客观评审测试", font=FontIR(size=32.0, color="#16181D"))
        ))

        mock_llm = MockVisionLLM()
        events_captured = []

        async def capture_event(ev):
            events_captured.append(ev)

        res = await VisualCriticSubagent.audit_slide(
            slide=slide,
            llm_client=mock_llm,
            include_multimodal=True,
            on_event=capture_event
        )

        # 1. Verify LLM received exactly 2 messages: system prompt (critic persona) and user prompt (manifest + snapshot)
        assert len(mock_llm.received_messages) == 1
        messages = mock_llm.received_messages[0]
        assert len(messages) == 2

        # System message is isolated critic prompt
        sys_msg = messages[0]
        assert sys_msg["role"] == "system"
        assert "第三方 PPT 视觉艺术总监与版式排版审计专家" in sys_msg["content"]

        # User message has ONLY slide manifest and snapshot, NO author context or chat history
        user_msg = messages[1]
        assert user_msg["role"] == "user"
        content_items = user_msg["content"]
        assert len(content_items) == 2
        assert content_items[0]["type"] == "text"
        assert "画布图元坐标清册" in content_items[0]["text"]
        assert content_items[1]["type"] == "image_url"

        # 2. Verify lifecycle broadcasts: main agent pauses -> subagent reviews -> main agent resumes
        start_events = [e for e in events_captured if e.get("type") == "subagent_lifecycle" and e.get("phase") == "started"]
        done_events = [e for e in events_captured if e.get("type") == "subagent_lifecycle" and e.get("phase") == "completed"]

        assert len(start_events) == 1
        assert start_events[0]["main_agent_status"] == "paused_waiting"

        assert len(done_events) == 1
        assert done_events[0]["main_agent_status"] == "resumed"

        # 3. Verify score fusion with subagent aesthetic evaluation (rule 100 + model 88 -> fused 94)
        assert res.health_report.quality_score.aesthetics == 94.0
        assert res.subagent_info["context_isolated"] is True

    asyncio.run(_run())
