"""End-to-end paper -> PPT graph tests (S4).

Covers both the LLM-native branch (fake multimodal client) and the deterministic
fallback branch (no API key), plus CAS persistence provenance.
"""

from __future__ import annotations

import asyncio
import json

from backend.agent.graphs.generation import generation_graph
from backend.session.manager import session_manager


def _run_paper_graph(session_id: str, paper_ir, client):
    session = session_manager.get_or_create(session_id)
    state = {
        "session_id": session_id,
        "source_type": "paper",
        "mode": "generate",
        "paper_ir": paper_ir,
        "user_prompt": "15 minute lab seminar",
        "duration_minutes": 15,
        "max_repair_iterations": 1,
        "base_document_epoch": session.document_epoch,
        "base_revision": session.document.presentation.version,
    }
    return asyncio.run(
        generation_graph.ainvoke(
            state, config={"configurable": {"llm_client": client}}
        )
    )


def _messages_text(messages) -> str:
    parts = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


def _truthfulness_builder(hallucinated: str, repaired: str | None):
    """Art Director emits a fabricated metric; optionally grounds it on repair."""
    from tests.design import conftest as design_conftest

    def _builder(messages, role="reasoning"):
        system = str(messages[0].get("content", "")) if messages else ""
        if "art_direction" in system:
            payload = design_conftest.art_direction_payload()
            user_text = _messages_text(messages)
            if repaired is not None and "TRUTHFULNESS VIOLATIONS" in user_text:
                payload["slides"][0]["key_messages"] = [repaired]
            else:
                payload["slides"][0]["key_messages"] = [hallucinated]
            return json.dumps(payload)
        return json.dumps(
            design_conftest.valid_layout_payload(
                design_conftest._slide_id_from_messages(messages),
                design_conftest.blocks_from_messages(messages),
            )
        )

    return _builder


def test_paper_pipeline_llm_native(
    paper_ir_fixture, design_client_cls, paper_pipeline_response_builder
):
    session_id = "test_paper_e2e_llm_native"
    client = design_client_cls(paper_pipeline_response_builder)

    result = _run_paper_graph(session_id, paper_ir_fixture, client)

    assert result["status"] == "completed", result.get("error")
    pres_ir = result["presentation_ir"]
    generation = pres_ir.metadata["generation"]
    assert generation["source_type"] == "paper"
    assert generation["mode"] == "llm_native"
    assert generation["paper"]["title"] == "A Research Title"
    assert generation["duration_minutes"] == 15
    assert "art_direction" in generation

    session_after = session_manager.get_session(session_id)
    assert session_after is not None
    assert len(session_after.pres.slides) == len(pres_ir.slides) == 2

    # Source-aware deck review ran and the slides were rasterized for vision.
    assert result.get("slide_rasters")
    assert result.get("deck_review") is not None

    session_manager.delete_session(session_id)


def test_paper_pipeline_legacy_fallback(paper_ir_fixture, design_client_cls):
    session_id = "test_paper_e2e_fallback"
    client = design_client_cls(api_key="")  # no key -> deterministic fallback

    result = _run_paper_graph(session_id, paper_ir_fixture, client)

    assert result["status"] == "completed"
    generation = result["presentation_ir"].metadata["generation"]
    assert generation["source_type"] == "paper"
    assert generation["mode"] == "legacy_template"
    assert generation["fallback_reason"] == "art_direction_unavailable"
    assert len(result["presentation_ir"].slides) > 0

    session_manager.delete_session(session_id)


def test_paper_pipeline_without_paper_ir_terminates(design_client_cls):
    session_id = "test_paper_e2e_missing_ir"
    session_manager.get_or_create(session_id)
    state = {
        "session_id": session_id,
        "source_type": "paper",
        "mode": "generate",
        "base_document_epoch": None,
        "base_revision": None,
    }
    result = asyncio.run(
        generation_graph.ainvoke(
            state, config={"configurable": {"llm_client": design_client_cls()}}
        )
    )
    assert result["status"] == "validation_failed"
    assert "PAPER_IR_MISSING" in result["validation_errors"]
    assert result.get("presentation_ir") is None
    session_manager.delete_session(session_id)


def test_paper_truthfulness_repairs_hallucinated_metric(paper_ir_fixture, design_client_cls):
    session_id = "test_paper_e2e_truth_repair"
    client = design_client_cls(
        _truthfulness_builder("Accuracy improved by 42%", "Grounded summary")
    )

    result = _run_paper_graph(session_id, paper_ir_fixture, client)

    assert result["status"] == "completed", result.get("error")
    assert result["paper_truthfulness_attempts"] == 1
    session_manager.delete_session(session_id)


def test_paper_truthfulness_persistent_violation_fails(paper_ir_fixture, design_client_cls):
    session_id = "test_paper_e2e_truth_fail"
    client = design_client_cls(
        _truthfulness_builder("Accuracy improved by 42%", None)
    )

    result = _run_paper_graph(session_id, paper_ir_fixture, client)

    assert result["status"] == "validation_failed"
    assert "PAPER_TRUTHFULNESS_FAILED" in result["error"]
    assert result.get("presentation_ir") is None
    session_manager.delete_session(session_id)


def _multi_asset_paper_ir():
    from backend.paper.schema import (
        PaperFigure,
        PaperIR,
        PaperMetadata,
        PaperSection,
        PaperTable,
    )

    return PaperIR(
        source_filename="paper.pdf",
        metadata=PaperMetadata(
            title="A Research Title", authors=["A. Author"], page_count=2
        ),
        abstract="We present a concise method for research.",
        sections=[
            PaperSection(
                number="1",
                title="Introduction",
                page=1,
                paragraphs=["Prior work has limitations."],
            ),
            PaperSection(
                number="2",
                title="Method",
                page=2,
                paragraphs=["Our method combines stages."],
            ),
        ],
        figures=[
            PaperFigure(
                id="figure1",
                xref_label="Figure 1",
                caption="Pipeline overview",
                page=2,
            ),
            PaperFigure(
                id="figure2",
                xref_label="Figure 2",
                caption="Component detail",
                page=2,
            ),
        ],
        tables=[
            PaperTable(
                id="table1",
                xref_label="Table 1",
                caption="Results",
                page=2,
            ),
        ],
    )


def _multi_asset_fallback_builder():
    """Art Director plans 2 figures + 1 table; layout LLM returns invalid plans."""
    from tests.design import conftest as design_conftest

    def _builder(messages, role="reasoning"):
        system = str(messages[0].get("content", "")) if messages else ""
        if "art_direction" in system:
            payload = design_conftest.art_direction_payload()
            payload["slides"][1]["slide_type"] = "METHOD_DETAIL"
            payload["slides"][1]["source_figures"] = ["figure1", "figure2"]
            payload["slides"][1]["source_tables"] = ["table1"]
            payload["slides"][1]["key_messages"] = ["Two figures and a table"]
            return json.dumps(payload)
        return json.dumps(
            design_conftest.invalid_layout_payload(
                design_conftest._slide_id_from_messages(messages)
            )
        )

    return _builder


def test_paper_multi_visual_assets_fallback_commits_without_loss(design_client_cls):
    """Layout LLM fails -> template fallback -> final gate -> commit, no asset loss."""
    session_id = "test_paper_multi_asset_fallback"
    client = design_client_cls(_multi_asset_fallback_builder())

    result = _run_paper_graph(session_id, _multi_asset_paper_ir(), client)

    assert result["status"] == "completed", result.get("error")
    assert result["deck_layout"].metadata.get("layout_source") in (
        "fallback_template",
        "mixed",
    )
    pres_ir = result["presentation_ir"]
    figure_ids = {
        el.metadata.get("source_figure_id")
        for slide in pres_ir.slides
        for el in slide.elements
        if getattr(el, "metadata", {}).get("source_figure_id")
    }
    table_ids = {
        el.metadata.get("source_table_id")
        for slide in pres_ir.slides
        for el in slide.elements
        if getattr(el, "metadata", {}).get("source_table_id")
    }
    assert {"figure1", "figure2"} <= figure_ids
    assert "table1" in table_ids
    session_manager.delete_session(session_id)


def test_paper_plan_forwards_contact_sheet_dir(monkeypatch, paper_ir_fixture):
    from backend.agent.graphs import generation as generation_module
    from backend.design import art_director
    from backend.presentation.schema import PresentationPlan, SlidePlan, SlideType

    captured = {}

    async def fake_build(llm_client, paper_ir, paper_visual_ir, **kwargs):
        captured.update(kwargs)
        plan = PresentationPlan(
            title="T",
            slides=[
                SlidePlan(
                    index=1,
                    slide_type=SlideType.TITLE,
                    title="T",
                    objective="o",
                    key_messages=["m"],
                )
            ],
        )
        return art_director.default_art_direction(), plan, False

    monkeypatch.setattr("backend.design.build_plan_and_direction", fake_build)

    state = {
        "paper_ir": paper_ir_fixture,
        "paper_visual_ir": None,
        "paper_cache_dir": "C:/trusted/cache",
        "user_prompt": "",
        "duration_minutes": 15,
    }
    asyncio.run(
        generation_module.paper_plan_node(
            state, {"configurable": {"llm_client": None, "on_event": None}}
        )
    )
    assert captured.get("contact_sheet_dir") == "C:/trusted/cache"
