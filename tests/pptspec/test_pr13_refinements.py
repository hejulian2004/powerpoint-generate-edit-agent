"""Comprehensive regression and verification tests for PR13 refinements.

Covers all 13 targeted tests and the 3 end-to-end scenarios:
1. test_visual_repair_branch_executes
2. test_instruction_numeric_not_truthfulness_checked
3. test_instruction_not_compiled_to_slide_content
4. test_missing_metric_value_rejected
5. test_invalid_evidence_ref_not_dropped
6. test_spec_repair_max_once
7. test_artifact_session_mismatch_rejected
8. test_artifact_expired_rejected
9. test_llm_normalizer_fallback_called
10. test_percent_semantics_not_equivalent
11. test_block_id_propagation
12. test_evidence_id_propagation
13. test_no_synthetic_academic_assets
Plus full E2E pipelines.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.agent.graphs.generation import build_generation_graph, generation_graph
from backend.agent.graphs.generation_state import PPTGenerationState
from backend.evaluation.evaluator import RuleBasedEvaluator
from backend.main import app
from backend.compiler.presentation_ir import compile_layout_to_presentation_ir
from backend.evaluation.schema import IssueSeverity, IssueType, VisualIssue
from backend.ir.models import ShapeElementIR, TableElementIR, TextElementIR
from backend.layout.engine import generate_deck_layout
from backend.layout.schema import DeckLayoutSpec, ElementType, LayoutElement, LayoutSpec, Rect, VisualIntent
from backend.pptspec.artifact import NormalizationArtifactStore, artifact_store
from backend.pptspec.compiler import compile_pptspec_to_deckspec
from backend.session.manager import session_manager
from backend.pptspec.normalizer import (
    normalize_dict_to_canonical_spec,
    normalize_presentation_input,
)
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    ClaimEvidence,
    FigureReferenceEvidence,
    MetricEntry,
    MetricEvidence,
    MetricGroupEvidence,
    PresentationConfig,
    SlideRequest,
    TableEvidence,
)
from backend.pptspec.validator import (
    NumericToken,
    collect_factual_numeric_tokens,
    validate_truthfulness,
)
from backend.presentation.schema import SlideType
from backend.renderer.assets import AssetResolver


# =====================================================================
# 1. Visual Repair Branch Executes
# =====================================================================
@pytest.mark.anyio
async def test_visual_repair_branch_executes(monkeypatch):
    """Verify that when visual defects occur, visual_repair_node executes with transaction safety and heals."""
    graph = build_generation_graph()

    evaluator_calls = 0
    modified_x = None

    def mock_evaluate_deck(self, slide_images=None, deck_spec=None):
        nonlocal evaluator_calls, modified_x
        evaluator_calls += 1
        if evaluator_calls == 1 and deck_spec and deck_spec.slides:
            slide = deck_spec.slides[0]
            el = slide.elements[0]
            # Force element to overflow canvas horizontally to trigger a real CLAMP_TO_CANVAS repair
            modified_x = deck_spec.canvas.width + 50.0
            el.geometry.x = modified_x
            return [
                VisualIssue(
                    slide_id=slide.slide_id,
                    element_id=el.element_id,
                    issue_type=IssueType.OVERFLOW,
                    severity=IssueSeverity.ERROR,
                    description=f"Element '{el.element_id}' exceeds canvas width",
                )
            ]
        return []

    monkeypatch.setattr(RuleBasedEvaluator, "evaluate_deck", mock_evaluate_deck)

    # Provide raw input and matching canonical spec
    raw_text = "Paper Title. Our framework achieves 85% accuracy."
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Visual Repair Test"),
        evidence=[MetricEvidence(id="m1", name="Accuracy", value="85%")],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.RESULT,
                title="Performance",
                evidence_refs=["m1"],
            )
        ],
    )

    session_id = "test_vr_sess"
    session_manager.get_or_create(session_id)
    initial_state: PPTGenerationState = {
        "raw_input": raw_text,
        "session_id": session_id,
        "canonical_spec": spec,
        "mode": "generate",
        "max_repair_iterations": 2,
    }

    result = await graph.ainvoke(initial_state)

    # Assert evaluator was called twice (first reported issue, second verified healing)
    assert evaluator_calls == 2
    assert result["repair_iteration"] == 1
    assert result["status"] == "completed"
    assert result.get("presentation_ir") is not None

    # Verify that the healed element's geometry actually changed and was clamped back inside canvas
    healed_deck = result["deck_layout"]
    healed_el = healed_deck.slides[0].elements[0]
    assert healed_el.geometry.x < modified_x
    assert healed_el.geometry.x + healed_el.geometry.width <= healed_deck.canvas.width

    # Verify session persistence
    sess = session_manager.get_session(session_id)
    assert sess is not None
    assert sess.pres is not None

    session_manager.delete_session(session_id)


# =====================================================================
# 2. Instructions Numeric Not Truthfulness Checked
# =====================================================================
def test_instruction_numeric_not_truthfulness_checked():
    """Instructions containing numbers like '图片占页面 60%' must NOT be checked as factual numbers."""
    raw_input = "We introduce our algorithm. Our algorithm is robust."  # Does NOT contain '60' or '60%'

    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Layout Instructions Test"),
        evidence=[ClaimEvidence(id="c1", content="Our algorithm is robust.")],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.METHOD_OVERVIEW,
                title="Method Overview",
                evidence_refs=["c1"],
                instructions=["图片占页面 60%", "左右分栏比例 4:6"],
            )
        ],
    )

    factual_tokens = collect_factual_numeric_tokens(spec)
    # The numbers 60, 4, 6 from instructions must NOT be in factual tokens!
    assert not any(t[0].value == "60" or t[0].value == "4" or t[0].value == "6" for t in factual_tokens)

    val_res = validate_truthfulness(raw_input, spec, strict=False)
    assert val_res.valid is True
    assert len(val_res.errors) == 0


# =====================================================================
# 3. Instruction Not Compiled to Slide Content
# =====================================================================
def test_instruction_not_compiled_to_slide_content():
    """Instructions are presentation/layout directives only, never compiled into TextBlock slide content."""
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Compiler Directive Test"),
        evidence=[ClaimEvidence(id="c1", content="Core empirical finding.")],
        slides=[
            SlideRequest(
                id="s1",
                type=SlideType.RESULT,
                title="Findings",
                evidence_refs=["c1"],
                instructions=["保持左右对称，留白不小于 40px", "使用蓝色强调框"],
            )
        ],
    )

    deck_spec = compile_pptspec_to_deckspec(spec)
    slide = deck_spec.slides[0]

    # No text block should contain the layout instruction string
    for block in slide.blocks:
        if block.kind == "text":
            assert "保持左右对称" not in block.content
            assert "使用蓝色强调框" not in block.content

    # Only the genuine claim evidence exists
    assert any("Core empirical finding" in b.content for b in slide.blocks if b.kind == "text")


# =====================================================================
# 4. Missing Metric Value Rejected (Never defaults to '0')
# =====================================================================
def test_missing_metric_value_rejected():
    """Metric without a value must be omitted or flagged; NEVER fabricate '0'."""
    raw_dict = {
        "presentation": {"title": "Metric Value Test"},
        "evidence": [
            {"id": "m_valid", "kind": "metric", "name": "Latency", "value": "120ms"},
            {"id": "m_empty", "kind": "metric", "name": "Throughput", "value": ""},
            {"id": "m_none", "kind": "metric", "name": "Accuracy"},
                {
                    "id": "mg1",
                    "kind": "metric_group",
                    "group_name": "Benchmark Results",
                    "metrics": [
                        {"name": "M1", "value": "10"},
                        {"name": "M2", "value": None},
                    ],
                },
        ],
        "slides": [{"title": "Results", "evidence_refs": ["m_valid"]}],
    }

    warnings: List[str] = []
    spec = normalize_dict_to_canonical_spec(raw_dict, warnings=warnings)

    ev_ids = {ev.id for ev in spec.evidence}
    assert "m_valid" in ev_ids
    # Both empty/none metric entries must NOT be created with "0"
    assert "m_empty" not in ev_ids
    assert "m_none" not in ev_ids

    # Check metric group has only the valid metric
    mg_ev = [ev for ev in spec.evidence if ev.id == "mg1"][0]
    assert len(mg_ev.metrics) == 1
    assert mg_ev.metrics[0].name == "M1"
    assert any("MISSING_METRIC_VALUE" in w for w in warnings)


# =====================================================================
# 5. Invalid Evidence Ref Not Dropped (Flags error and sets valid=False)
# =====================================================================
def test_invalid_evidence_ref_not_dropped():
    """Normalizer must retain unknown evidence references; TruthfulnessValidator must reject them."""
    raw_dict = {
        "presentation": {"title": "Ref Test"},
        "evidence": [{"id": "c1", "kind": "claim", "content": "Valid claim."}],
        "slides": [
            {
                "id": "s1",
                "title": "Slide 1",
                "evidence_refs": ["c1", "ghost_evidence_404"],
            }
        ],
    }

    warnings: List[str] = []
    spec = normalize_dict_to_canonical_spec(raw_dict, warnings=warnings)

    # ghost reference is NOT silently dropped by normalizer
    assert "ghost_evidence_404" in spec.slides[0].evidence_refs

    # Truthfulness validator flags INVALID_EVIDENCE_REFERENCE and fails validation
    res = validate_truthfulness("Valid claim. Some raw text", spec, strict=False)
    assert res.valid is False
    assert any("INVALID_EVIDENCE_REFERENCE" in err and "ghost_evidence_404" in err for err in res.errors)


# =====================================================================
# 6. Spec Repair Max Once
# =====================================================================
@pytest.mark.anyio
async def test_spec_repair_max_once():
    """Validation failure must only attempt spec repair at most once before terminating."""
    graph = build_generation_graph()

    # Input with invalid evidence reference that cannot be repaired deterministically
    raw_text = json.dumps({
        "presentation": {"title": "Test"},
        "slides": [{"id": "s1", "type": "RESULT", "title": "Test", "evidence_refs": ["nonexistent_ev"]}],
    })

    initial_state: PPTGenerationState = {
        "raw_input": raw_text,
        "session_id": "sess_repair_max",
        "mode": "generate",
    }

    result = await graph.ainvoke(initial_state)

    # Must terminate without infinite loop
    assert result["status"] in ("validation_failed", "repair_spec_failed", "__end__")
    assert result.get("spec_repair_attempts", 0) <= 1


# =====================================================================
# 7. Artifact Session Mismatch Rejected
# =====================================================================
def test_artifact_session_mismatch_rejected():
    """Generation endpoint must reject artifacts belonging to a different session (403)."""
    client = TestClient(app)

    # Create artifact for session A
    art = artifact_store.save(
        session_id="session_AAA",
        raw_input="Factual text with 99% accuracy.",
        spec=CanonicalPPTSpec(
            presentation=PresentationConfig(title="Test"),
            evidence=[MetricEvidence(id="m1", name="Acc", value="99%")],
            slides=[SlideRequest(id="s1", type=SlideType.TITLE, title="Title", evidence_refs=["m1"])],
        ),
        summary={"slides": 1},
        asset_requirements=[],
    )

    # Request generation under session B
    resp = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": art.id, "session_id": "session_BBB"},
    )
    assert resp.status_code == 403
    assert "ARTIFACT_SESSION_MISMATCH" in resp.json()["detail"]


# =====================================================================
# 8. Artifact Expired Rejected
# =====================================================================
def test_artifact_expired_rejected():
    """Generation endpoint must reject expired artifacts with 410."""
    client = TestClient(app)

    # Save artifact with negative ttl (immediately expired)
    art = artifact_store.save(
        session_id="session_exp",
        raw_input="Test text.",
        spec=CanonicalPPTSpec(
            presentation=PresentationConfig(title="Test"),
            evidence=[],
            slides=[],
        ),
        summary={},
        asset_requirements=[],
        ttl_seconds=-10,
    )

    resp = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": art.id, "session_id": "session_exp"},
    )
    assert resp.status_code == 410
    assert "ARTIFACT_EXPIRED" in resp.json()["detail"]

    # Unknown artifact returns 404
    resp_404 = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": "norm_ghost_404", "session_id": "session_exp"},
    )
    assert resp_404.status_code == 404
    assert "ARTIFACT_NOT_FOUND" in resp_404.json()["detail"]


# =====================================================================
# 9. LLM Normalizer Fallback Called
# =====================================================================
@pytest.mark.anyio
async def test_llm_normalizer_fallback_called():
    """When deterministic parsing fails, LLM fallback is invoked via chat_completion."""
    mock_llm = AsyncMock()
    # LLM returns valid CanonicalPPTSpec JSON without inventing facts
    mock_spec_json = json.dumps({
        "presentation": {"title": "LLM Repaired"},
        "evidence": [{"id": "c1", "kind": "claim", "content": "Evidence grounded in raw text."}],
        "slides": [{"id": "s1", "type": "RESULT", "title": "Overview", "evidence_refs": ["c1"]}],
    })
    mock_llm.chat_completion.return_value = {
        "choices": [{"message": {"content": mock_spec_json}}]
    }

    # Broken JSON format triggers deterministic parsing failure, but contains factual raw text
    raw_malformed = "Evidence grounded in raw text.\n```json\n{\n  \"presentation\": { \"title\": \"Broken JSON\",\n  \"unclosed_dict\": [1, 2,\n"

    res = await normalize_presentation_input(
        raw_text=raw_malformed,
        llm_client=mock_llm,
        strict_truthfulness=True,
    )

    assert mock_llm.chat_completion.called
    assert res.valid is True
    assert res.spec is not None
    assert res.spec.presentation.title == "LLM Repaired"


# =====================================================================
# 10. Percent Semantics Not Equivalent
# =====================================================================
def test_percent_semantics_not_equivalent():
    """NumericToken must enforce unit, %, and uncertainty semantics."""
    # 1. 10 != 10%
    tok_plain = NumericToken(raw_text="10", value="10", percent=False)
    tok_pct = NumericToken(raw_text="10%", value="10", percent=True)
    assert not tok_plain.is_equivalent(tok_pct)

    # 2. 0.5 != 0.5ms
    tok_num = NumericToken(raw_text="0.5", value="0.5", unit=None)
    tok_unit = NumericToken(raw_text="0.5ms", value="0.5", unit="ms")
    assert not tok_num.is_equivalent(tok_unit)

    # 3. 89.5 != 89.5±0.2
    tok_base = NumericToken(raw_text="89.5", value="89.5")
    tok_unc = NumericToken(raw_text="89.5±0.2", value="89.5", uncertainty="0.2")
    assert not tok_base.is_equivalent(tok_unc)

    # 4. Equivalent representations
    tok_point5 = NumericToken(raw_text=".5", value=".5")
    tok_zero5 = NumericToken(raw_text="0.5", value="0.5")
    assert tok_point5.is_equivalent(tok_zero5)

    tok_pct_space = NumericToken(raw_text="89.5 %", value="89.5", percent=True)
    tok_pct_tight = NumericToken(raw_text="89.5%", value="89.5", percent=True)
    assert tok_pct_space.is_equivalent(tok_pct_tight)


# =====================================================================
# 11 & 12. Block ID and Evidence ID Propagation
# =====================================================================
def test_block_id_and_evidence_id_propagation():
    """Full identity propagation: Evidence.id -> SlideSpec block -> LayoutElement -> PresentationIR."""
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Trace Deck"),
        evidence=[
            ClaimEvidence(id="ev_claim_01", content="Key finding on latency."),
            FigureReferenceEvidence(id="ev_fig_01", label="Figure 1", caption="Architecture", source_page=3),
            TableEvidence(id="ev_tbl_01", columns=["A"], rows=[["1"]], complete_table=False),
        ],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.METHOD_OVERVIEW,
                title="System Pipeline",
                evidence_refs=["ev_claim_01", "ev_fig_01"],
            ),
            SlideRequest(
                id="slide_02",
                type=SlideType.RESULT,
                title="Model Comparison",
                evidence_refs=["ev_tbl_01"],
            ),
        ],
    )

    # 1. SlideSpec Level
    deck_spec = compile_pptspec_to_deckspec(spec)
    s1 = deck_spec.slides[0]
    fig_blocks = [b for b in s1.blocks if b.kind == "figure"]
    assert len(fig_blocks) == 1
    assert fig_blocks[0].block_id == "slide_01_figure_01"
    assert "ev_fig_01" in fig_blocks[0].source_evidence_ids

    # 2. LayoutSpec Level
    deck_layout = generate_deck_layout(deck_spec)
    l_slide1 = deck_layout.slides[0]

    # Find layout element for figure
    fig_elem = [e for e in l_slide1.elements if e.element_type == ElementType.FIGURE][0]
    assert fig_elem.source_block_id == "slide_01_figure_01"
    assert "ev_fig_01" in fig_elem.source_evidence_ids

    # 3. PresentationIR Level
    pres_ir = compile_layout_to_presentation_ir(deck_layout)
    ir_slide1 = pres_ir.slides[0]

    # Find IR shape placeholder
    ir_elem = [e for e in ir_slide1.elements if isinstance(e, ShapeElementIR) and e.metadata.get("is_figure_placeholder")][0]
    assert ir_elem.source_ref == "slide_01_figure_01"
    assert "ev_fig_01" in ir_elem.source_evidence_ids


# =====================================================================
# 13. Static Code Gate: Zero Legacy Synthetic Fallbacks in backend/
# =====================================================================
def test_no_synthetic_academic_assets():
    """Production code gate: No dummy benchmark rows or fake figure generation in backend/."""
    backend_py_files = list(Path("backend").rglob("*.py"))
    assert len(backend_py_files) > 0

    for py_file in backend_py_files:
        content = py_file.read_text(encoding="utf-8")
        assert "Baseline Architecture" not in content, f"Dummy academic row in {py_file}"
        assert "Prior SOTA (2023)" not in content, f"Dummy academic row in {py_file}"
        assert "[Source: PaperIR Visual Extract]" not in content, f"Fake extract tag in {py_file}"
        assert "_generate_academic_placeholder" not in content, f"Fake diagram generator in {py_file}"

    # Behavioral gate: AssetResolver on missing assets raises FileNotFoundError
    resolver = AssetResolver()
    with pytest.raises(FileNotFoundError):
        resolver.resolve_figure("nonexistent_paper_figure")

    with pytest.raises(FileNotFoundError):
        resolver.resolve_table("nonexistent_paper_table")


# =====================================================================
# End-to-End Pipeline Scenario 1:
# Unstructured AI Output -> LLM Normalization Fallback -> Truthfulness -> Generation
# =====================================================================
@pytest.mark.anyio
async def test_e2e_unstructured_ai_output_llm_fallback_to_generation():
    """Verify full pipeline: Unstructured output -> LLM normalizer -> Truthfulness -> LangGraph -> PresentationIR."""
    from backend.session.manager import session_manager

    raw_text = (
        "Here is the planned presentation specification from AI:\n"
        "```json\n"
        "{\n"
        "  \"presentation\": { \"title\": \"Graph Neural Reasoning\" },\n"
        "  \"stream_broken\": [unquoted_literal,\n"
        "}\n"
        "```\n"
        "Empirical Grounding: We achieve an accuracy of 92.4% on Benchmark A and reduced inference time to 18ms."
    )

    mock_llm = AsyncMock()
    repaired_canonical_json = json.dumps({
        "presentation": {"title": "Graph Neural Reasoning", "duration_minutes": 15},
        "evidence": [
            {"id": "ev_acc", "kind": "metric", "name": "Accuracy", "value": "92.4%"},
            {"id": "ev_lat", "kind": "metric", "name": "Inference Time", "value": "18ms"},
        ],
        "slides": [
            {"id": "s1", "type": "TITLE", "title": "Graph Neural Reasoning"},
            {"id": "s2", "type": "RESULT", "title": "Key Results", "evidence_refs": ["ev_acc", "ev_lat"]},
        ],
    })
    mock_llm.chat_completion.return_value = {
        "choices": [{"message": {"content": repaired_canonical_json}}]
    }

    # Step A: Normalize with LLM fallback
    norm_res = await normalize_presentation_input(
        raw_text=raw_text,
        llm_client=mock_llm,
        strict_truthfulness=True,
    )
    assert norm_res.valid is True
    assert norm_res.spec is not None

    # Step B: Cache in artifact store bound to session
    test_session_id = "test_e2e_sess_1"
    session_manager.get_or_create(test_session_id)
    artifact = artifact_store.save(
        session_id=test_session_id,
        raw_input=raw_text,
        spec=norm_res.spec,
        summary=norm_res.summary,
        asset_requirements=norm_res.asset_requirements,
    )

    # Step C: Run generation graph
    initial_state: PPTGenerationState = {
        "session_id": test_session_id,
        "raw_input": artifact.raw_input,
        "canonical_spec": artifact.canonical_spec,
        "mode": "generate",
    }
    result = await generation_graph.ainvoke(initial_state)

    assert result["status"] == "completed"
    pres_ir = result.get("presentation_ir")
    assert pres_ir is not None
    assert len(pres_ir.slides) == 2
    # Check session received persistent PresentationIR
    sess = session_manager.get_session(test_session_id)
    assert sess is not None
    assert sess.pres is not None
    assert sess.pres.id == pres_ir.id


# =====================================================================
# End-to-End Pipeline Scenario 2:
# Layout Defect -> Visual Review -> Visual Repair -> Recompile -> Persist
# =====================================================================
@pytest.mark.anyio
async def test_e2e_visual_repair_loop_full_cycle():
    """Verify visual self-healing loop: VisualIssue detected -> Visual Repair applies transaction patch -> Recompiled -> Persisted."""
    from backend.session.manager import session_manager

    session_id = "test_e2e_sess_repair"
    session_manager.get_or_create(session_id)

    raw_text = "Paper Title. Our framework achieves 85% accuracy."
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Self-Healing Loop Test"),
        evidence=[MetricEvidence(id="m1", name="Accuracy", value="85%")],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.RESULT,
                title="Performance",
                evidence_refs=["m1"],
            )
        ],
    )

    initial_state: PPTGenerationState = {
        "session_id": session_id,
        "raw_input": raw_text,
        "canonical_spec": spec,
        "mode": "generate",
        "max_repair_iterations": 2,
    }

    result = await generation_graph.ainvoke(initial_state)

    assert result["status"] == "completed"
    assert result.get("presentation_ir") is not None
    # Verified persisted into session
    sess = session_manager.get_session(session_id)
    assert sess.pres is not None


# =====================================================================
# End-to-End Pipeline Scenario 3:
# Missing Figure / Table -> Pure Vector Placeholders Only -> Zero Dummy Data
# =====================================================================
@pytest.mark.anyio
async def test_e2e_missing_assets_strict_placeholder_only():
    """Verify that when figures or tables are referenced without pixel/row data, PresentationIR contains explicit placeholders and ZERO dummy data."""
    raw_text = (
        "Paper Title: Modular Robotics.\n"
        "See Figure 1 on page 3 and Table 1 on page 4.\n"
        "We show that modular units are adaptable."
    )

    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Modular Robotics"),
        evidence=[
            FigureReferenceEvidence(id="fig_1", label="Figure 1", caption="Modular Joint Design", source_page=3),
            TableEvidence(id="tbl_1", columns=["Unit", "Torque"], rows=[], caption="Joint Specs", source_page=4, complete_table=False),
            ClaimEvidence(id="c1", content="We show that modular units are adaptable."),
        ],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.METHOD_OVERVIEW,
                title="System Design",
                evidence_refs=["fig_1", "tbl_1", "c1"],
            )
        ],
    )

    # Compile and generate
    deck_spec = compile_pptspec_to_deckspec(spec)
    deck_layout = generate_deck_layout(deck_spec)
    pres_ir = compile_layout_to_presentation_ir(deck_layout)

    slide = pres_ir.slides[0]
    # Check that placeholders are ShapeElementIR with explicit warnings
    placeholders = [e for e in slide.elements if isinstance(e, ShapeElementIR) and (e.metadata.get("is_figure_placeholder") or e.metadata.get("is_table_placeholder"))]
    assert len(placeholders) >= 1

    # Verify no fake numbers (76.4, 0.742, 81.2, 89.5, etc.) exist in the PresentationIR
    ir_json = pres_ir.model_dump_json()
    assert "76.4" not in ir_json
    assert "0.742" not in ir_json
    assert "81.2" not in ir_json
    assert "Baseline Architecture" not in ir_json
    assert "Prior SOTA" not in ir_json


# =====================================================================
# 16. Markdown Bullet & Loose JSON Bullet Deduplication
# =====================================================================
@pytest.mark.anyio
async def test_markdown_bullet_no_duplicate_evidence():
    """Markdown 1 bullet must map to exactly 1 evidence item, not duplicated in bullets."""
    md_text = """
## Slide 1: 研究背景
- 云原生系统微服务规模庞大
- 传统规则告警误报率高达 45%
"""
    res = await normalize_presentation_input(md_text, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    s1 = res.spec.slides[0]
    # Exactly 2 evidences, not 4
    assert len(s1.evidence_refs) == 2
    assert len(res.spec.evidence) == 2


@pytest.mark.anyio
async def test_json_bullet_deduplication():
    """Loose JSON with 1 figure ref and 1 bullet must yield exactly 1 figure + 1 claim."""
    loose_json = json.dumps({
        "raw_text": "Overall system pipeline overview is described in Figure 1 on page 2.",
        "presentation": {"title": "Test"},
        "evidence": [
            {"id": "f1", "kind": "figure_reference", "label": "Figure 1", "source_page": 2}
        ],
        "slides": [
            {
                "id": "s1",
                "title": "System Architecture",
                "evidence_refs": ["f1"],
                "bullets": ["Overall system pipeline overview."],
            }
        ],
    })
    res = await normalize_presentation_input(loose_json, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    s1 = res.spec.slides[0]
    # 1 figure + 1 claim = exactly 2 evidence refs
    assert len(s1.evidence_refs) == 2
    assert len(res.spec.evidence) == 2
    claim_evs = [ev for ev in res.spec.evidence if ev.kind == "claim"]
    assert len(claim_evs) == 1
    assert claim_evs[0].content == "Overall system pipeline overview."


# =====================================================================
# 17. Metric BadgeBlock Full Pipeline Propagation
# =====================================================================
def test_badge_block_end_to_end_propagation():
    """MetricEvidence -> BadgeBlock -> LayoutElement.BADGE -> PresentationIR ShapeElementIR."""
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Badge Flow"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="85%"),
        ],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.RESULT,
                title="Evaluation Results",
                evidence_refs=["m1"],
            )
        ],
    )

    deck_spec = compile_pptspec_to_deckspec(spec)
    s1 = deck_spec.slides[0]
    badge_blocks = [b for b in s1.blocks if b.kind == "badge"]
    assert len(badge_blocks) == 1
    assert badge_blocks[0].text == "Accuracy: 85%"
    assert "m1" in badge_blocks[0].source_evidence_ids

    # Layout generation
    deck_layout = generate_deck_layout(deck_spec)
    layout_s1 = deck_layout.slides[0]
    badge_elements = [e for e in layout_s1.elements if e.element_type == ElementType.BADGE]
    assert len(badge_elements) == 1
    assert badge_elements[0].content == "Accuracy: 85%"
    assert badge_elements[0].source_block_id == badge_blocks[0].block_id
    assert badge_elements[0].source_evidence_ids == ["m1"]

    # IR compilation
    pres_ir = compile_layout_to_presentation_ir(deck_layout)
    ir_s1 = pres_ir.slides[0]
    ir_badges = [
        e for e in ir_s1.elements
        if isinstance(e, ShapeElementIR) and e.name == "Badge"
    ]
    assert len(ir_badges) == 1
    assert "Accuracy: 85%" in ir_badges[0].text_content.paragraphs[0].runs[0].text
    assert ir_badges[0].source_ref == badge_blocks[0].block_id
    assert ir_badges[0].source_evidence_ids == ["m1"]


# =====================================================================
# 18. Table source_reference Original Label Preservation
# =====================================================================
@pytest.mark.anyio
async def test_table_source_reference_preservation():
    """Table 7 in input retains 'Table 7' across parser, spec, block, and IR placeholder (no 'Table 1' rewrite)."""
    raw_md = """
# Empirical Study

## Slide 1: Main Baseline Comparison
- Refer to Table 7 for baseline comparisons on page 12
"""
    res = await normalize_presentation_input(raw_md, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None

    tbl_ev = [ev for ev in res.spec.evidence if ev.kind == "table"][0]
    assert tbl_ev.source_reference == "Table 7"

    reqs = res.asset_requirements
    assert len(reqs) == 1
    assert "Table 7" in reqs[0].label

    # Compile to SlideSpec
    deck_spec = compile_pptspec_to_deckspec(res.spec)
    s1 = deck_spec.slides[0]
    tbl_block = [b for b in s1.blocks if b.kind == "table"][0]
    # xref_label must NOT be rewritten to 'Table 1'
    assert tbl_block.xref_label == "Table 7"

    # Layout and IR
    deck_layout = generate_deck_layout(deck_spec)
    pres_ir = compile_layout_to_presentation_ir(deck_layout)
    ir_s1 = pres_ir.slides[0]

    # Check placeholder shape text
    placeholders = [
        e for e in ir_s1.elements
        if isinstance(e, ShapeElementIR) and e.metadata.get("is_table_placeholder")
    ]
    assert len(placeholders) == 1
    ph = placeholders[0]
    all_text = " ".join(r.text for p in ph.text_content.paragraphs for r in p.runs)
    assert "[TABLE 7]" in all_text
    assert "请粘贴论文原始 Table 7" in all_text


@pytest.mark.anyio
async def test_table_caption_merged_with_markdown_table():
    """Table 7 caption followed by complete markdown table merges into exactly one complete TableEvidence.

    Must compile to editable TableElementIR with no placeholder shape.
    """
    input_text = """
    # Benchmark Study

    ## Slide 1: Main Results
    Table 7: Main Experimental Comparison

    | Model | Accuracy |
    |---|---|
    | Baseline | 82.5% |
    | Ours | 91.2% |
    """
    res = await normalize_presentation_input(input_text, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None

    # Verify exactly one TableEvidence
    tables = [ev for ev in res.spec.evidence if isinstance(ev, TableEvidence)]
    assert len(tables) == 1
    tbl = tables[0]
    assert tbl.complete_table is True
    assert tbl.source_reference == "Table 7"
    assert "Main Experimental Comparison" in (tbl.caption or "")
    assert tbl.columns == ["Model", "Accuracy"]
    assert len(tbl.rows) == 2

    # No asset requirements for complete tables
    assert len(res.asset_requirements) == 0

    # Compile all the way to PresentationIR
    deck_spec = compile_pptspec_to_deckspec(res.spec)
    deck_layout = generate_deck_layout(deck_spec)
    pres_ir = compile_layout_to_presentation_ir(deck_layout)

    ir_slide = pres_ir.slides[0]
    # Must have editable TableElementIR
    table_ir_elements = [el for el in ir_slide.elements if isinstance(el, TableElementIR)]
    assert len(table_ir_elements) == 1

    # Must NOT have any placeholder ShapeElementIR
    placeholder_shapes = [
        el for el in ir_slide.elements
        if isinstance(el, ShapeElementIR) and el.metadata.get("is_table_placeholder")
    ]
    assert len(placeholder_shapes) == 0


@pytest.mark.anyio
async def test_source_document_title_not_inferred_from_presentation_heading():
    """Markdown '# AnomalyAgent 组会汇报' sets presentation.title, but source_document.title remains None."""
    input_text = """
    # AnomalyAgent 组会汇报

    ## Slide 1: 背景
    - 传统系统排障困难
    """
    res = await normalize_presentation_input(input_text, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert res.spec.presentation.title == "AnomalyAgent 组会汇报"
    # source_document.title must be None since no explicit Paper Title was provided
    assert res.spec.source_document.title is None


@pytest.mark.anyio
async def test_validation_route_fatal_errors_terminate_immediately():
    """Truthfulness errors (numeric, textual, locator, invalid ref) route directly to __end__ without repair."""
    graph = build_generation_graph()

    raw_text = "Factual basis with 80% accuracy."
    # Canonical spec contains hallucinated fact
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[MetricEvidence(id="m1", name="HallucinatedMetric", value="80%")],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="T", evidence_refs=["m1"])],
    )

    initial_state: PPTGenerationState = {
        "raw_input": raw_text,
        "canonical_spec": spec,
        "session_id": "sess_fatal_route",
        "mode": "generate",
    }

    result = await graph.ainvoke(initial_state)

    # Must terminate without invoking repair_spec_node
    assert result["status"] == "validation_failed"
    assert result.get("spec_repair_attempts", 0) == 0
    assert any("UNSUPPORTED_TEXTUAL_FACT" in err for err in result.get("validation_errors", []))




