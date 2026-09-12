"""Tests for chat attachment routing, the add_image tool, and /api/chat/drive."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from fastapi.testclient import TestClient

from backend.agent import attachment_router as router
from backend.agent.attachment_context import build_attachment_context
from backend.agent.attachment_router import (
    ACTION_CHAT,
    ACTION_IMAGE,
    ACTION_IMPORT,
    ACTION_PAPER,
    ACTION_TEXT,
    KIND_IMAGE,
    KIND_PDF,
    KIND_PPTX,
    KIND_TEXT,
    KIND_UNKNOWN,
    classify_intent,
    detect_kind,
    fallback_action,
)
from backend.agent.runtime import AgentRuntime
from backend.agent.tools import tools
from backend.api import routes
from backend.ir.models import PresentationIR
from backend.main import app
from backend.session.manager import session_manager
from backend.session.session import PPTSession
from backend.state.store import create_default_demo_presentation, store

client = TestClient(app)

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _seed_default_demo():
    session = session_manager.get_or_create("default")
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def _stamps(session) -> dict:
    return {
        "expected_epoch": session.document_epoch,
        "expected_revision": session.document.presentation.version,
    }


class _FakeLLM:
    def __init__(self, action: str):
        self._action = action
        self.calls = 0

    async def chat_completion(self, messages, role=None, max_tokens=None):
        self.calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"action": "%s", "reason": "test"}' % self._action
                    }
                }
            ]
        }


# ---------------------------------------------------------------------------
# Kind detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,content_type,expected",
    [
        ("paper.PDF", None, KIND_PDF),
        ("deck.pptx", None, KIND_PPTX),
        ("slides.ppt", None, KIND_PPTX),
        ("figure.png", None, KIND_IMAGE),
        ("notes.md", None, KIND_TEXT),
        ("blob", "application/pdf", KIND_PDF),
        ("blob", "image/jpeg", KIND_IMAGE),
        ("blob", "text/plain", KIND_TEXT),
        ("blob", "application/octet-stream", KIND_UNKNOWN),
    ],
)
def test_detect_kind(name, content_type, expected):
    assert detect_kind(name, content_type) == expected


# ---------------------------------------------------------------------------
# Structural fallback (no keywords)
# ---------------------------------------------------------------------------

def test_fallback_action_maps_single_kind():
    assert fallback_action([KIND_PDF]) == ACTION_PAPER
    assert fallback_action([KIND_PPTX]) == ACTION_IMPORT
    assert fallback_action([KIND_IMAGE]) == ACTION_IMAGE
    assert fallback_action([KIND_TEXT]) == ACTION_TEXT
    assert fallback_action([KIND_UNKNOWN]) == ACTION_CHAT


def test_fallback_action_multiple_kinds_uses_priority():
    assert fallback_action([KIND_TEXT, KIND_PDF]) == ACTION_PAPER


# ---------------------------------------------------------------------------
# LLM intent routing (LLM is the decider)
# ---------------------------------------------------------------------------

def test_classify_intent_uses_llm_message_not_kind():
    # A PDF the user only wants to discuss must NOT be force-routed to generation.
    llm = _FakeLLM(ACTION_CHAT)
    assert asyncio.run(classify_intent(llm, "先看看这篇讲了什么", [KIND_PDF])) == ACTION_CHAT
    assert llm.calls == 1


def test_classify_intent_llm_can_override_kind_default():
    llm = _FakeLLM(ACTION_IMAGE)
    # Even though only a PDF is attached, the LLM's decision is authoritative
    # only when the kind can satisfy it; here it cannot, so we fall back safely.
    result = asyncio.run(classify_intent(llm, "把这张图插进去", [KIND_PDF]))
    assert result == fallback_action([KIND_PDF])


def test_classify_intent_accepts_legal_llm_action():
    llm = _FakeLLM(ACTION_IMAGE)
    assert asyncio.run(classify_intent(llm, "把这张图放到当前页", [KIND_IMAGE])) == ACTION_IMAGE


def test_classify_intent_no_llm_uses_structural_fallback():
    assert asyncio.run(classify_intent(None, "随便说点什么", [KIND_TEXT])) == ACTION_TEXT


# ---------------------------------------------------------------------------
# add_image tool
# ---------------------------------------------------------------------------

def test_add_image_tool_inserts_element():
    from backend.ir.patch import HistoryManager

    pres = create_default_demo_presentation()
    history = HistoryManager()
    slide_id = pres.slides[0].id
    result = tools.execute(
        "add_image",
        {"slide_id": slide_id, "src": "data:image/png;base64,AAAA", "width": 10, "height": 10},
        pres,
        history,
    )
    assert result["success"] is True
    slide = pres.get_slide(slide_id)
    added = [e for e in slide.elements if e.id == result["element_id"]]
    assert len(added) == 1
    assert added[0].type == "image"


def test_add_image_requires_src():
    pres = create_default_demo_presentation()
    from backend.ir.patch import HistoryManager

    result = tools.execute("add_image", {"src": ""}, pres, HistoryManager())
    assert result["success"] is False


# ---------------------------------------------------------------------------
# /api/chat/drive dispatch
# ---------------------------------------------------------------------------

def test_chat_drive_image_insert(monkeypatch):
    session = _seed_default_demo()
    monkeypatch.setattr(
        router, "classify_intent", lambda llm, message, kinds: _async_return(ACTION_IMAGE)
    )
    resp = client.post(
        "/api/chat/drive",
        data={"message": "把这张图放到当前页", "session_id": "default", **_stamps(session)},
        files=[("files", ("figure.png", PNG_BYTES, "image/png"))],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == ACTION_IMAGE
    session = session_manager.get_session("default")
    slide = session.document.presentation.slides[0]
    assert any(e.type == "image" for e in slide.elements)


def test_chat_drive_image_insert_requires_stamp(monkeypatch):
    session = _seed_default_demo()
    monkeypatch.setattr(
        router, "classify_intent", lambda llm, message, kinds: _async_return(ACTION_IMAGE)
    )
    resp = client.post(
        "/api/chat/drive",
        data={"message": "把这张图放到当前页", "session_id": "default"},
        files=[("files", ("figure.png", PNG_BYTES, "image/png"))],
    )
    assert resp.status_code == 409
    assert "MISSING_REPLACEMENT_STAMP" in resp.text


def test_chat_drive_image_insert_stale_stamp_is_rejected(monkeypatch):
    session = _seed_default_demo()
    monkeypatch.setattr(
        router, "classify_intent", lambda llm, message, kinds: _async_return(ACTION_IMAGE)
    )
    elements_before = len(session.document.presentation.slides[0].elements)
    resp = client.post(
        "/api/chat/drive",
        data={
            "message": "把这张图放到当前页",
            "session_id": "default",
            "expected_epoch": session.document_epoch,
            # The client's observed revision is behind the live deck.
            "expected_revision": session.document.presentation.version + 100,
        },
        files=[("files", ("figure.png", PNG_BYTES, "image/png"))],
    )
    assert resp.status_code == 409, resp.text
    assert "STALE_IMAGE_INSERT" in resp.text
    assert len(session.document.presentation.slides[0].elements) == elements_before


def test_chat_drive_unknown_only_returns_chat(monkeypatch):
    _seed_default_demo()
    monkeypatch.setattr(
        router, "classify_intent", lambda llm, message, kinds: _async_return(ACTION_CHAT)
    )
    resp = client.post(
        "/api/chat/drive",
        data={"message": "这是什么", "session_id": "default"},
        files=[("files", ("blob.bin", b"\x00\x01", "application/octet-stream"))],
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == ACTION_CHAT


def test_chat_drive_paper_requires_pdf(monkeypatch):
    session = _seed_default_demo()
    monkeypatch.setattr(
        router, "classify_intent", lambda llm, message, kinds: _async_return(ACTION_PAPER)
    )
    resp = client.post(
        "/api/chat/drive",
        data={"message": "做成PPT", "session_id": "default", **_stamps(session)},
        files=[("files", ("figure.png", PNG_BYTES, "image/png"))],
    )
    assert resp.status_code == 400
    assert "PDF_REQUIRED_FOR_PAPER" in resp.text


def _patch_router(monkeypatch, action: str):
    monkeypatch.setattr(
        router, "classify_intent", lambda llm, message, kinds: _async_return(action)
    )


def test_chat_drive_paper_generate(monkeypatch):
    session = _seed_default_demo()
    stamps = _stamps(session)
    _patch_router(monkeypatch, ACTION_PAPER)
    captured = {}

    async def fake_analyze(file, session_id=None, force=False):
        captured["analyze_filename"] = file.filename
        return {"cache_key": "ck_1", "page_count": 3, "vision_model": None, "source_filename": "p.pdf"}

    async def fake_paper_gen(payload):
        captured["paper_payload"] = payload
        return {"success": True, "session_id": "default", "presentation": {"slides": []}}

    monkeypatch.setattr(routes, "analyze_paper", fake_analyze)
    monkeypatch.setattr(routes, "api_generate_from_paper", fake_paper_gen)

    resp = client.post(
        "/api/chat/drive",
        data={"message": "把这篇论文做成PPT", "session_id": "default", **stamps},
        files=[("files", ("paper.pdf", b"%PDF-1.4 fake", "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == ACTION_PAPER
    assert captured["analyze_filename"] == "paper.pdf"
    assert captured["paper_payload"]["cache_key"] == "ck_1"
    assert captured["paper_payload"]["user_prompt"] == "把这篇论文做成PPT"
    # The frozen caller stamp is forwarded to the generation persist.
    assert captured["paper_payload"]["expected_epoch"] == stamps["expected_epoch"]
    assert captured["paper_payload"]["expected_revision"] == stamps["expected_revision"]


def test_chat_drive_text_generate(monkeypatch):
    session = _seed_default_demo()
    stamps = _stamps(session)
    _patch_router(monkeypatch, ACTION_TEXT)
    captured = {}

    async def fake_normalize(payload):
        captured["raw_text"] = payload["content"]
        return {"valid": True, "normalization_id": "nid_1", "summary": "s", "warnings": [], "errors": []}

    async def fake_gen(payload):
        captured["norm_id"] = payload["normalization_id"]
        captured["gen_payload"] = payload
        return {"success": True, "session_id": "default", "presentation": {"slides": []}}

    monkeypatch.setattr(routes, "api_normalize_pptspec", fake_normalize)
    monkeypatch.setattr(routes, "api_generate_from_pptspec", fake_gen)

    resp = client.post(
        "/api/chat/drive",
        data={"message": "根据文档生成幻灯片", "session_id": "default", **stamps},
        files=[("files", ("outline.txt", "产品大纲".encode("utf-8"), "text/plain"))],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == ACTION_TEXT
    assert captured["raw_text"] == "产品大纲"
    assert captured["norm_id"] == "nid_1"
    assert captured["gen_payload"]["expected_epoch"] == stamps["expected_epoch"]
    assert captured["gen_payload"]["expected_revision"] == stamps["expected_revision"]


def test_chat_drive_pptx_import(monkeypatch):
    _seed_default_demo()
    _patch_router(monkeypatch, ACTION_IMPORT)
    captured = {}

    async def fake_upload(file, session_id=None, expected_epoch=None, expected_revision=None):
        captured["stamp"] = (expected_epoch, expected_revision)
        captured["filename"] = file.filename
        return {"success": True, "session_id": "default", "presentation": {"slides": []}}

    monkeypatch.setattr(routes, "upload_pptx", fake_upload)

    resp = client.post(
        "/api/chat/drive",
        data={
            "message": "导入这个模板",
            "session_id": "default",
            "expected_epoch": "epoch_A",
            "expected_revision": 7,
        },
        files=[("files", ("deck.pptx", b"PK\x03\x04fake", "application/vnd.openxmlformats-officedocument.presentationml.presentation"))],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == ACTION_IMPORT
    assert captured["stamp"] == ("epoch_A", 7)
    assert captured["filename"] == "deck.pptx"


def test_chat_drive_pptx_import_requires_stamp(monkeypatch):
    _seed_default_demo()
    _patch_router(monkeypatch, ACTION_IMPORT)
    resp = client.post(
        "/api/chat/drive",
        data={"message": "导入", "session_id": "default", "expected_epoch": "", "expected_revision": 0},
        files=[("files", ("deck.pptx", b"PK\x03\x04fake", "application/octet-stream"))],
    )
    assert resp.status_code == 409
    assert "MISSING_REPLACEMENT_STAMP" in resp.text


async def _async_return(value):
    return value


# ---------------------------------------------------------------------------
# ACTION_CHAT: attachment content must actually reach the LLM
# ---------------------------------------------------------------------------

class _SpyLLM:
    def __init__(self, reply: str = "好的"):
        self.reply = reply
        self.calls = []

    async def chat_completion(self, messages, role="default", **kwargs):
        self.calls.append({"messages": messages, "role": role})
        return {"choices": [{"message": {"content": self.reply}}]}


def _new_session(session_id: str) -> PPTSession:
    return PPTSession(session_id=session_id, pres=PresentationIR(title="D"))


def test_chat_with_attachments_text_uses_reasoning_and_keeps_transcript_clean():
    session = _new_session("sess_attach_text")
    spy = _SpyLLM("这是摘要")
    runtime = AgentRuntime(llm_client=spy)
    attachments = [
        {
            "name": "outline.txt",
            "content_type": "text/plain",
            "content": "产品大纲：A、B、C".encode("utf-8"),
            "kind": KIND_TEXT,
        }
    ]
    context = asyncio.run(build_attachment_context(session, attachments))
    result = asyncio.run(
        runtime.chat_with_attachments(session, "总结一下", context)
    )

    assert result["role"] == "reasoning"
    assert result["has_images"] is False
    assert spy.calls[0]["role"] == "reasoning"
    assert "产品大纲" in json.dumps(spy.calls[0]["messages"], ensure_ascii=False)
    # Durable transcript stores plain text only - no digest.
    assert [m["content"] for m in session.memory.messages] == ["总结一下", "这是摘要"]


def test_chat_with_attachments_image_uses_vision_role():
    session = _new_session("sess_attach_image")
    spy = _SpyLLM("风格很简洁")
    runtime = AgentRuntime(llm_client=spy)
    attachments = [
        {
            "name": "figure.png",
            "content_type": "image/png",
            "content": PNG_BYTES,
            "kind": KIND_IMAGE,
        }
    ]
    context = asyncio.run(build_attachment_context(session, attachments))
    assert context.has_images is True
    result = asyncio.run(
        runtime.chat_with_attachments(session, "这张图是什么风格", context)
    )

    assert result["role"] == "vision"
    assert spy.calls[0]["role"] == "vision"
    assert "image_url" in json.dumps(spy.calls[0]["messages"], ensure_ascii=False)


def test_chat_with_attachments_pdf_digest_reaches_model():
    session = _new_session("sess_attach_pdf")
    spy = _SpyLLM("论文讲的是 X")
    runtime = AgentRuntime(llm_client=spy)
    paper_ir = {
        "metadata": {"title": "A Paper"},
        "abstract": "We study X.",
        "sections": [{"title": "1 Intro", "paragraphs": ["Hello world"]}],
        "figures": [],
        "tables": [],
    }

    async def fake_analyze(name, content_type, content):
        return {
            "paper_ir": paper_ir,
            "paper_visual_ir": {"pages": []},
            "page_count": 1,
            "vision_model": None,
            "source_filename": name,
        }

    attachments = [
        {
            "name": "p.pdf",
            "content_type": "application/pdf",
            "content": b"%PDF-1.4 fake",
            "kind": KIND_PDF,
        }
    ]
    context = asyncio.run(
        build_attachment_context(session, attachments, analyze_pdf=fake_analyze)
    )
    assert "A Paper" in context.text_digest
    result = asyncio.run(
        runtime.chat_with_attachments(session, "这篇讲什么", context)
    )

    # Text-only PDF digest -> reasoning, and the content is in the request.
    assert result["role"] == "reasoning"
    assert "We study X." in json.dumps(spy.calls[0]["messages"], ensure_ascii=False)


def test_chat_drive_chat_answers_with_attachment_in_context(monkeypatch):
    _seed_default_demo()
    spy = _SpyLLM("根据大纲，内容是 A、B、C")
    monkeypatch.setattr(store.agent_runtime, "llm", spy)
    _patch_router(monkeypatch, ACTION_CHAT)

    resp = client.post(
        "/api/chat/drive",
        data={"message": "总结这段文字", "session_id": "default"},
        files=[
            ("files", ("outline.txt", "产品大纲：A、B、C".encode("utf-8"), "text/plain"))
        ],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == ACTION_CHAT
    assert body["message"] == "根据大纲，内容是 A、B、C"
    assert "产品大纲" in json.dumps(spy.calls[0]["messages"], ensure_ascii=False)
