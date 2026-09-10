"""Phase 1.5: generated-content grounding.

Two layers are asserted:
1. Layout defaults must not fabricate factual numeric claims.
2. The gateway re-validates the committed IR text after a generation tool runs and
   rolls the whole atomic batch back when an ungrounded data claim appears.
"""

import asyncio

from backend.agent.grounding import collect_ir_text, data_claim_numbers
from backend.agent.tools import tools as registry
from backend.ir.models import (
    FillStyle,
    PresentationIR,
    SlideIR,
    TextContentIR,
    TextElementIR,
)
from backend.ir.patch import HistoryManager


def _empty_slide_pres() -> PresentationIR:
    pres = PresentationIR(title="Deck", slides=[])
    slide = SlideIR(
        id="s1", slide_num=1, width=1280, height=720,
        background=FillStyle(type="solid", color="#FFFFFF"),
    )
    pres.slides.append(slide)
    pres.active_slide_id = "s1"
    return pres


def test_kpi_layout_defaults_contain_no_numeric_data_claims():
    pres = _empty_slide_pres()
    history = HistoryManager(pres)
    res = registry.execute(
        "generate_slide_layout",
        {"title": "指标体系", "layout_type": "kpi_metrics", "clear_existing": True},
        pres,
        history,
    )
    assert res["success"] is True
    text = collect_ir_text(pres.slides)
    assert data_claim_numbers(text, "") == [], "layout defaults must not invent data claims"


def test_gateway_rolls_back_ungrounded_generated_number(monkeypatch):
    async def _run():
        import backend.agent.mutation_gateway as mg

        name = "test_inject_metric"
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": "test-only injected generation",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

        def handler(pres, history, slide_id=""):
            slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
            slide.add_element(TextElementIR(
                id="inj_1", x=20.0, y=20.0, width=220.0, height=40.0,
                text_content=TextContentIR.from_plain_text("增长 88%"),
            ))
            pres.version += 1
            history.record(action="test_inject", description="inject", before={}, after={})
            return {"success": True}

        registry.schemas.append(schema)
        registry.handlers[name] = handler
        monkeypatch.setattr(mg, "GENERATION_TOOLS", mg.GENERATION_TOOLS | {name})
        try:
            pres = _empty_slide_pres()
            history = HistoryManager(pres)
            version_before = pres.version

            batch = await mg.MutationGateway.execute_tool_calls(
                [{"name": name, "arguments": {}, "id": "call_inj"}],
                pres,
                history,
                bypass_confirmation=True,
                atomic=True,
                enforce_grounding=True,
                grounding_source="营收同比增长 35%",
            )

            assert batch.error == "unsupported_facts"
            assert batch.unsupported_numbers == ["88%"]
            assert batch.rolled_back is True
            assert pres.slides[0].get_element("inj_1") is None
            assert pres.version == version_before
            assert len(history.undo_stack) == 0
        finally:
            registry.handlers.pop(name, None)
            registry.schemas.remove(schema)

    asyncio.run(_run())
