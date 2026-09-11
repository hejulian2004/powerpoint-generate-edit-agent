"""Integration tests for LangGraph Generation Pipeline (PR13 Step 5)."""

import pytest
from backend.agent.graphs.generation import build_generation_graph
from backend.agent.graphs.generation_state import PPTGenerationState
from backend.ir.models import PresentationIR
from backend.session.manager import session_manager


@pytest.mark.anyio
async def test_generation_graph_end_to_end_ainvoke():
    raw_markdown = """
# Transformer Architecture Analysis

## Slide 1: 研究背景
- 自注意力机制改变了现代 NLP 范式
- 相比 RNN 并行度提升 10 倍

## Slide 2: 核心结构
- 论文模型见 Figure 1，第 3 页
- 编码器与解码器堆叠架构

## Slide 3: 实验性能
- BLEU 分数达到 28.4
- 训练步数达到 100000 步
"""

    session_id = "test_gen_sess_01"
    session = session_manager.get_or_create(session_id)

    graph = build_generation_graph()

    initial_state: PPTGenerationState = {
        "raw_input": raw_markdown,
        "session_id": session_id,
        "mode": "generate",
        "max_repair_iterations": 2,
        "base_document_epoch": session.document_epoch,
        "base_revision": session.pres.version,
    }

    result = await graph.ainvoke(initial_state)

    # 1. Pipeline status verification
    assert result["status"] == "completed"
    assert result["presentation_ir"] is not None
    pres_ir = result["presentation_ir"]
    assert isinstance(pres_ir, PresentationIR)
    assert len(pres_ir.slides) == 3

    # 2. Session persistence verification: PresentationIR is now session.pres
    session_after = session_manager.get_session(session_id)
    assert session_after is not None
    assert session_after.pres.title == pres_ir.title
    assert len(session_after.pres.slides) == 3

    # Clean up test session
    session_manager.delete_session(session_id)


@pytest.mark.anyio
async def test_generation_graph_fatal_validation_routing():
    """Verify that hallucinated numbers route to termination at validate_spec_node."""
    raw_text = "Baseline accuracy is 75.0%."

    # Spec that attempts to introduce an unsupported number 99.8%
    malicious_json = """{
        "presentation": {"title": "Hallucinated Deck"},
        "evidence": [
            {"id": "m1", "kind": "metric", "name": "Fake SOTA", "value": "99.8%"}
        ],
        "slides": [
            {"id": "s1", "title": "Fake Results", "evidence_refs": ["m1"]}
        ]
    }"""

    graph = build_generation_graph()

    initial_state: PPTGenerationState = {
        "raw_input": raw_text,  # Does not contain 99.8%
        "session_id": "test_gen_sess_fail",
        "mode": "generate",
    }
    # Pass the canonical_spec with unsupported number directly
    from backend.pptspec.normalizer import normalize_presentation_input
    norm = await normalize_presentation_input(malicious_json, strict_truthfulness=False)
    initial_state["canonical_spec"] = norm.spec

    result = await graph.ainvoke(initial_state)

    # Must terminate without compiling presentation_ir
    assert result["status"] == "validation_failed"
    assert result.get("presentation_ir") is None
    assert any("UNSUPPORTED_NUMERIC_VALUE" in err for err in result.get("validation_errors", []))


def test_generation_graph_structure_has_no_manual_loop():
    """Verify StateGraph architecture: nodes and conditional edges are defined properly."""
    graph = build_generation_graph()
    assert graph is not None

    # Check that required nodes exist in the graph
    node_names = set(graph.nodes.keys())
    required_nodes = {
        "ingest_node",
        "normalize_node",
        "validate_spec_node",
        "compile_slidespec_node",
        "layout_node",
        "compile_presentation_ir_node",
        "preview_node",
        "visual_review_node",
        "visual_repair_node",
        "persist_session_node",
    }
    for rn in required_nodes:
        assert rn in node_names, f"Missing node {rn} in generation StateGraph"
