"""End-to-end paper -> PPT graph tests (S4).

Covers both the LLM-native branch (fake multimodal client) and the deterministic
fallback branch (no API key), plus CAS persistence provenance.
"""

from __future__ import annotations

import asyncio

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
