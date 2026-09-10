"""Phase 2.3: deck-level review of every changed slide.

Generating a 5-slide deck must run Content/Visual review across all changed
slides, not just the first one. Critical defects in slide 3 must surface in the
deck-level review instead of being silently skipped.
"""

import asyncio

from backend.agent.graph import PPTAgentState, build_ppt_agent_graph
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager


class DeckLLM:
    """Approves all free-text critiques and lets the heuristic planner build the deck."""

    api_key = "live_deck_key"

    def __init__(self):
        self.content_manifest_slides = []
        self.vision_calls = 0

    async def chat_completion(self, messages, role="reasoning", tools=None, **kwargs):
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        if role == "vision":
            self.vision_calls += 1
            return {"choices": [{"message": {"content": "【排版与视觉诊断】: 排版优良\n【美学评分: 92/100】"}}]}
        if "策划架构评审总监" in sys_msg:
            return {"choices": [{"message": {"content": "【评审结论】: 通过\n【规划健康分: 93/100】"}}]}
        if "内容与叙事结构总监" in sys_msg:
            user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
            self.content_manifest_slides.append(user_msg)
            return {"choices": [{"message": {"content": "【内容评审结论】: 通过\n【内容健康分: 92/100】"}}]}
        if tools:
            # No tool calls -> deterministic heuristic planner generates the deck.
            return {"choices": [{"message": {"content": "ok"}}]}
        return {"choices": [{"message": {"content": "ok"}}]}


def test_generation_reviews_every_changed_slide():
    async def _run():
        app = build_ppt_agent_graph()
        pres = PresentationIR(title="Untitled")
        history = HistoryManager(pres)
        llm = DeckLLM()

        initial_state: PPTAgentState = {
            "messages": [],
            "user_query": "制作一份关于下一代大模型技术演进的专业汇报PPT",
            "intent": "generate_presentation",
        }
        final_state = await app.ainvoke(initial_state, config={
            "configurable": {
                "pres": pres,
                "history": history,
                "llm_client": llm,
            }
        })

        slide_ids = [s.id for s in pres.slides]
        assert len(slide_ids) >= 5

        content_review = final_state["content_review"]
        assert content_review["approved"] is True
        assert content_review["reviewed_slide_ids"] == slide_ids
        assert len(content_review["slides"]) == len(slide_ids)

        visual_review = final_state["visual_review"]
        assert visual_review["reviewed_slide_ids"] == slide_ids
        assert len(visual_review["slides"]) == len(slide_ids)
        assert llm.vision_calls == len(slide_ids)

        # Every slide's text manifest was actually audited by the content critic.
        assert len(llm.content_manifest_slides) == len(slide_ids)

    asyncio.run(_run())
