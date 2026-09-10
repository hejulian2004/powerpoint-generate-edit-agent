"""Unit test: Verify that ContentCriticSubagent detects unclosed tags and format violations, triggering loop back."""

import asyncio
import pytest
from backend.ir.models import SlideIR, TextElementIR, TextContentIR, FontIR
from backend.agent.subagents.content_critic import ContentCriticSubagent
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager


def test_tag_and_format_closure_detection_rules():
    """Verify rule-based check detects HTML/XML unclosed tags, template unclosed vars, and symbol mismatches."""
    # 1. Unclosed HTML tags
    issues1 = ContentCriticSubagent.check_unclosed_tags_and_formatting("这是<b>加粗标题未闭合")
    assert any("未闭合标签 '<b>'" in iss for iss in issues1)

    # 2. Tag mismatch
    issues2 = ContentCriticSubagent.check_unclosed_tags_and_formatting("这是<b>加粗<i>倾斜</b>错配</i>")
    assert any("标签闭合错配" in iss for iss in issues2)

    # 3. Clean paired tags
    issues3 = ContentCriticSubagent.check_unclosed_tags_and_formatting("这是<b>加粗</b>和<i>倾斜</i>，无错")
    assert len(issues3) == 0

    # 4. Asymmetrical paired symbols
    issues4 = ContentCriticSubagent.check_unclosed_tags_and_formatting("《学术研究成果发布（未闭合")
    assert any("书名号未成对闭合" in iss for iss in issues4)
    assert any("全角括号未成对闭合" in iss for iss in issues4)


def test_unclosed_tag_rejects_content_review():
    """Verify that a slide with unclosed tags fails content review immediately."""
    async def _run():
        slide = SlideIR(id="s_bad", slide_num=1, width=1280, height=720)
        slide.add_element(TextElementIR(
            id="t_broken", x=100, y=100, width=500, height=50,
            text_content=TextContentIR.from_plain_text("系统核心架构 <b>未闭合标签", font=FontIR(size=24.0))
        ))

        res = await ContentCriticSubagent.audit_content(slide=slide)
        # Must be rejected because tags are broken
        assert res.approved is False
        assert any("未闭合标签 '<b>'" in issue for issue in res.redundancy_issues)
        assert res.score < 70.0

    asyncio.run(_run())
