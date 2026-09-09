"""REST API integration tests for PPTSpec & Generation Endpoints (PR13 Step 6)."""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.session.manager import session_manager

client = TestClient(app)


def test_get_prompts_and_schema():
    # 1. General prompt
    res_gen = client.get("/api/pptspec/prompts/general")
    assert res_gen.status_code == 200
    data_gen = res_gen.json()
    assert "prompt" in data_gen
    assert "严禁捏造任何事实" in data_gen["prompt"]

    # 2. Strict prompt
    res_str = client.get("/api/pptspec/prompts/strict")
    assert res_str.status_code == 200
    data_str = res_str.json()
    assert "prompt" in data_str
    assert "properties" in data_str["prompt"]

    # 3. Schema
    res_sch = client.get("/api/pptspec/schema")
    assert res_sch.status_code == 200
    data_sch = res_sch.json()
    assert "properties" in data_sch
    assert "spec_version" in data_sch["properties"]


def test_normalize_valid_and_unsupported_numeric():
    # A. Valid Markdown
    raw_valid = """
    # Graph Neural Networks

    ## Slide 1: 概述
    - 图表示学习基石
    - 准确率达到 84.5%
    """
    test_sid = "test_norm_sid"
    res_norm = client.post("/api/pptspec/normalize", json={"content": raw_valid, "session_id": test_sid})
    assert res_norm.status_code == 200
    data = res_norm.json()
    assert data["valid"] is True
    assert data["normalization_id"] is not None
    assert data["summary"]["slides"] >= 1
    assert data["summary"]["metrics"] >= 1

    # B. Hallucinated numeric value
    raw_malicious = """{
        "presentation": {"title": "Fake Deck"},
        "evidence": [{"id": "m1", "kind": "metric", "name": "Fake Acc", "value": "99.99%"}],
        "slides": [{"id": "s1", "title": "Fake", "evidence_refs": ["m1"]}]
    }"""
    # Create an artifact whose raw_input does NOT contain 99.8%
    from backend.pptspec.schema import CanonicalPPTSpec, PresentationConfig, MetricEvidence, SlideRequest
    from backend.pptspec.artifact import artifact_store
    fake_spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Fake"),
        evidence=[MetricEvidence(id="m1", name="Acc", value="99.8%")],
        slides=[SlideRequest(id="s1", type="RESULT", title="Res", evidence_refs=["m1"])],
    )
    fake_artifact = artifact_store.save(
        session_id=test_sid,
        raw_input="We report no numbers here.",
        spec=fake_spec,
        summary={"slides": 1},
        asset_requirements=[],
    )
    # Call /generate with this tampered artifact: server must reject with 422!
    res_gen_fail = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": fake_artifact.id, "session_id": test_sid}
    )
    assert res_gen_fail.status_code == 422
    assert "Truthfulness validation failed" in res_gen_fail.json()["detail"]
    session_manager.delete_session(test_sid)


def test_generate_from_valid_artifact():
    raw_text = """
    # Vision Transformers
    
    ## Slide 1: 引言
    - 图像切块与自注意力机制
    
    ## Slide 2: 架构
    - 模型架构参见 Figure 1，论文第 4 页
    
    ## Slide 3: 性能评估
    - ImageNet Top-1 准确率达到 88.55%
    """

    test_sid = "test_route_gen_sess"
    res_norm = client.post("/api/pptspec/normalize", json={"content": raw_text, "session_id": test_sid})
    assert res_norm.status_code == 200
    norm_data = res_norm.json()
    assert norm_data["valid"] is True
    norm_id = norm_data["normalization_id"]
    assert norm_id is not None

    res_gen = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": norm_id, "session_id": test_sid}
    )
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    assert gen_data["success"] is True
    assert gen_data["presentation"]["title"] == "Vision Transformers"
    assert len(gen_data["presentation"]["slides"]) == 3

    # Clean up
    session_manager.delete_session(test_sid)


def test_normalize_requires_session_id():
    res = client.post("/api/pptspec/normalize", json={"content": "Valid text but missing session_id."})
    assert res.status_code == 400
    assert "session_id is required" in res.json()["detail"]


def test_generate_requires_session_id():
    res = client.post("/api/pptspec/generate", json={"normalization_id": "any_id"})
    assert res.status_code == 400
    assert "session_id is required" in res.json()["detail"]


def test_read_unknown_session_returns_404():
    non_existent = "sess_non_existent_9999"
    res_pres = client.get(f"/api/presentation?session_id={non_existent}")
    assert res_pres.status_code == 404
    assert "SESSION_NOT_FOUND" in res_pres.json()["detail"]

    res_exp = client.get(f"/api/export?session_id={non_existent}")
    assert res_exp.status_code == 404
    assert "SESSION_NOT_FOUND" in res_exp.json()["detail"]

    res_hist = client.get(f"/api/history?session_id={non_existent}")
    assert res_hist.status_code == 404
    assert "SESSION_NOT_FOUND" in res_hist.json()["detail"]

    res_svg = client.get(f"/api/slide/slide_01/svg?session_id={non_existent}")
    assert res_svg.status_code == 404
    assert "SESSION_NOT_FOUND" in res_svg.json()["detail"]


def test_export_uses_requested_session():
    from backend.state.store import store
    from backend.ir.models import PresentationIR, SlideIR

    # Session default: Deck A
    default_sess = session_manager.get_or_create("default")
    default_sess.pres = PresentationIR(title="Deck A", slides=[SlideIR(id="s_a", slide_num=1, title="Slide A")])

    # Session export: Deck B
    export_sess = session_manager.get_or_create("sess_export")
    export_sess.pres = PresentationIR(title="Deck B", slides=[SlideIR(id="s_b", slide_num=1, title="Slide B")])

    # Request export for sess_export
    res = client.get("/api/export?session_id=sess_export")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.presentationml.presentation" in res.headers["content-type"]
    assert "Deck%20B.pptx" in res.headers["content-disposition"]

    # Verify default session is still Deck A and global store is unaffected
    assert session_manager.get_session("default").pres.title == "Deck A"
    assert store.active_session_id == "default"

    # Clean up
    session_manager.delete_session("sess_export")


def test_presentation_endpoint_uses_requested_session():
    from backend.ir.models import PresentationIR, SlideIR

    sid = "sess_pres_test"
    sess = session_manager.get_or_create(sid)
    sess.pres = PresentationIR(title="Custom Deck Title", slides=[SlideIR(id="s_custom", slide_num=1, title="Custom")])

    res = client.get(f"/api/presentation?session_id={sid}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Custom Deck Title"
    assert len(data["slides"]) == 1
    assert data["slides"][0]["id"] == "s_custom"

    session_manager.delete_session(sid)


def test_rest_undo_uses_requested_session():
    from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR, FontIR

    sid = "sess_undo_test"
    sess = session_manager.get_or_create(sid)
    elem = TextElementIR(
        id="elem_t1",
        x=100,
        y=100,
        width=200,
        height=50,
        text_content=TextContentIR.from_plain_text("Initial", font=FontIR(size=14.0))
    )
    sess.pres = PresentationIR(title="Undo Test Deck", slides=[SlideIR(id="s1", slide_num=1, title="S1", elements=[elem])])

    # Record mutation command
    sess.history.record(
        action="update_element",
        description="Update element text",
        slide_id="s1",
        element_id="elem_t1",
        before={"text_content": {"plain_text": "Initial"}},
        after={"text_content": {"plain_text": "Mutated"}},
    )
    assert sess.history.can_undo() is True

    # Call undo endpoint for this specific session
    res = client.post(f"/api/action/undo?session_id={sid}")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert sess.history.can_undo() is False
    assert sess.history.can_redo() is True

    # Redo
    res_redo = client.post(f"/api/action/redo?session_id={sid}")
    assert res_redo.status_code == 200
    assert res_redo.json()["success"] is True
    assert sess.history.can_undo() is True

    session_manager.delete_session(sid)


def test_upload_uses_requested_session():
    from backend.state.store import store
    from backend.ir.models import PresentationIR, SlideIR

    # Prepare PPTX bytes
    sample_pres = PresentationIR(title="Uploaded Deck", slides=[SlideIR(id="s_up", slide_num=1, title="Upload Slide")])
    pptx_bytes = store.export_pptx_bytes(sample_pres)

    sid = "sess_upload_target"
    sess = session_manager.get_or_create(sid)
    sess.history.record(action="temp", description="temp history", slide_id="s1")
    assert sess.history.can_undo() is True

    res = client.post(
        f"/api/upload?session_id={sid}",
        files={"file": ("new_sample.pptx", pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["session_id"] == sid
    assert data["title"] == "new_sample"

    # Verify session state reset
    assert sess.pres.title == "new_sample"
    assert sess.history.can_undo() is False
    assert sess.last_target_id is None
    assert sess.last_action_type is None

    session_manager.delete_session(sid)


def test_generation_respects_session_mutation_lock(monkeypatch):
    from backend.agent.graphs.generation import generation_graph

    raw_text = """
    # Lock Verification Deck
    
    ## Slide 1: 测试锁
    - 内容要点
    """
    sid = "sess_lock_verify"
    res_norm = client.post("/api/pptspec/normalize", json={"content": raw_text, "session_id": sid})
    assert res_norm.status_code == 200
    norm_id = res_norm.json()["normalization_id"]

    orig_ainvoke = generation_graph.ainvoke
    lock_was_held = False

    async def mock_ainvoke(*args, **kwargs):
        nonlocal lock_was_held
        s = session_manager.get_session(sid)
        lock_was_held = s.mutation_lock.locked()
        return await orig_ainvoke(*args, **kwargs)

    monkeypatch.setattr(generation_graph, "ainvoke", mock_ainvoke)

    res_gen = client.post("/api/pptspec/generate", json={"normalization_id": norm_id, "session_id": sid})
    assert res_gen.status_code == 200
    assert lock_was_held is True

    session_manager.delete_session(sid)


def test_generation_clears_old_undo_redo_history():
    raw_text = """
    # History Lifecycle Test
    
    ## Slide 1: 崭新页面
    - 验证旧历史被彻底清理
    """
    sid = "sess_history_clear_test"
    sess = session_manager.get_or_create(sid)

    # Populate stale undo/redo and metadata
    sess.history.record(action="add_element", description="old element mutation", slide_id="s0")
    sess.last_target_id = "stale_elem_target_id"
    sess.last_action_type = "add_element"
    assert sess.history.can_undo() is True

    res_norm = client.post("/api/pptspec/normalize", json={"content": raw_text, "session_id": sid})
    assert res_norm.status_code == 200
    norm_id = res_norm.json()["normalization_id"]

    res_gen = client.post("/api/pptspec/generate", json={"normalization_id": norm_id, "session_id": sid})
    assert res_gen.status_code == 200

    # Ensure replaced deck has pristine undo/redo and metadata
    assert sess.history.can_undo() is False
    assert sess.history.can_redo() is False
    assert sess.last_target_id is None
    assert sess.last_action_type is None
    assert len(sess.checkpoints) >= 1
    assert "Generated from CanonicalPPTSpec" in sess.checkpoints[-1].description

    session_manager.delete_session(sid)
