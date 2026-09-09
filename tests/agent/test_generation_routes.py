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
    res_norm = client.post("/api/pptspec/normalize", json={"content": raw_valid})
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
    # Notice: the raw input has "99.99%", so if the spec has "99.99%", it is supported.
    # But if we pass raw input WITHOUT the number:
    res_bad = client.post(
        "/api/pptspec/normalize",
        json={"content": "Empty paper text without any numbers."}
    )
    # The normalizer on empty text creates default slides without numbers, which is valid.
    # To test unsupported numeric rejection in normalize, let's create a spec that has a number not in raw input:
    from backend.pptspec.schema import CanonicalPPTSpec, PresentationConfig, MetricEvidence, SlideRequest
    from backend.pptspec.artifact import artifact_store
    fake_spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Fake"),
        evidence=[MetricEvidence(id="m1", name="Acc", value="99.8%")],
        slides=[SlideRequest(id="s1", type="RESULT", title="Res", evidence_refs=["m1"])],
    )
    # Save an artifact whose raw_input does NOT contain 99.8%
    fake_artifact = artifact_store.save(
        raw_input="We report no numbers here.",
        spec=fake_spec,
        summary={"slides": 1},
        asset_requirements=[],
    )
    # Call /generate with this tampered artifact: server must reject with 422!
    res_gen_fail = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": fake_artifact.id}
    )
    assert res_gen_fail.status_code == 422
    assert "Truthfulness validation failed" in res_gen_fail.json()["detail"]


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

    res_norm = client.post("/api/pptspec/normalize", json={"content": raw_text})
    assert res_norm.status_code == 200
    norm_data = res_norm.json()
    assert norm_data["valid"] is True
    norm_id = norm_data["normalization_id"]
    assert norm_id is not None

    test_sid = "test_route_gen_sess"
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
