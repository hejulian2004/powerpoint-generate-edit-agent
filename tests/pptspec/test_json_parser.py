"""Unit tests for JSON & Fenced JSON Parsing (PR13 Step 2)."""

import json
import pytest
from backend.pptspec.parser import InputFormat, detect_format, extract_json_payload, parse_presentation_input
from backend.pptspec.normalizer import normalize_presentation_input


@pytest.mark.anyio
async def test_standard_json_input():
    raw = json.dumps({
        "presentation": {
            "title": "Diffusion Models for Audio Synthesis",
            "duration_minutes": 15,
        },
        "evidence": [
            {"id": "ev_1", "kind": "metric", "name": "PESQ", "value": "4.25"},
            {"id": "ev_2", "kind": "claim", "content": "Outperforms GAN-based baselines."},
        ],
        "slides": [
            {"id": "s1", "type": "TITLE", "title": "Audio Diffusion"},
            {"id": "s2", "type": "RESULT", "title": "Performance", "evidence_refs": ["ev_1", "ev_2"]},
        ],
    })

    fmt = detect_format(raw)
    assert fmt == InputFormat.JSON

    res = await normalize_presentation_input(raw, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert len(res.spec.slides) == 2
    assert res.summary["metrics"] == 1
    assert res.summary["claims"] == 1


@pytest.mark.anyio
async def test_json_fenced_markdown():
    payload = {
        "presentation": {"title": "Fenced Spec"},
        "evidence": [{"id": "ev1", "kind": "claim", "content": "Verified."}],
        "slides": [{"id": "s1", "type": "TITLE", "title": "Fenced Title", "evidence_refs": ["ev1"]}],
    }
    raw = f"Here is the planned presentation specification:\n\n```json\n{json.dumps(payload, indent=2)}\n```\n\nLet me know if you need changes."

    fmt = detect_format(raw)
    assert fmt == InputFormat.JSON_FENCE

    res = await normalize_presentation_input(raw, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert res.spec.presentation.title == "Fenced Spec"


@pytest.mark.anyio
async def test_json_with_conversational_text_around_it():
    payload = {
        "title": "Conversational Spec",
        "evidence": [{"id": "ev1", "kind": "claim", "content": "Zero-shot transfer works."}],
        "slides": [{"id": "s1", "title": "Intro", "evidence_refs": ["ev1"]}],
    }
    raw = f"以下是经过大模型阅读分析后的 PPT 规划结果：\n\n{json.dumps(payload)}\n\n希望对您的汇报有所帮助，祝汇报顺利！"

    fmt = detect_format(raw)
    assert fmt in (InputFormat.JSON_LIKE, InputFormat.JSON)

    res = await normalize_presentation_input(raw, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert res.spec.presentation.title == "Conversational Spec"


@pytest.mark.anyio
async def test_minor_field_variations():
    """Test alias normalization: pages -> slides, heading -> title, facts -> evidence."""
    raw = json.dumps({
        "metadata": {"title": "Aliased Title"},
        "facts": [
            {"id": "f1", "content": "Fact 1"},
            {"id": "m1", "name": "Accuracy", "value": "91.5%"},
        ],
        "pages": [
            {"heading": "Title Slide", "purpose": "Opening"},
            {"heading": "Main Results", "evidences": ["f1", "m1"]},
        ],
    })

    res = await normalize_presentation_input(raw, strict_truthfulness=True)
    assert res.valid is True
    assert res.spec is not None
    assert len(res.spec.slides) == 2
    assert res.spec.slides[0].title == "Title Slide"
    assert res.spec.slides[1].title == "Main Results"
    assert "m1" in res.spec.slides[1].evidence_refs
