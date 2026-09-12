"""On-demand visual review: LLM target resolution + read-only review run."""

from __future__ import annotations

import asyncio
import json

from backend.agent.review_targeting import build_slide_manifest, resolve_review_targets
from backend.agent.runtime import AgentRuntime
from backend.quality.service import QualityService
from backend.session.session import PPTSession
from backend.state.store import create_default_demo_presentation


class _FakeLLM:
    def __init__(self, ids):
        self._ids = ids

    async def chat_completion(self, messages, role=None, max_tokens=None):
        return {"choices": [{"message": {"content": json.dumps({"slide_ids": self._ids})}}]}


def _session() -> PPTSession:
    pres = create_default_demo_presentation()
    return PPTSession(session_id="sess_review", pres=pres)


def test_build_slide_manifest_lists_non_empty_slides():
    manifest = build_slide_manifest(_session())
    assert len(manifest) >= 1
    assert all({"index", "slide_id", "title"} <= set(m) for m in manifest)


def test_resolve_review_targets_empty_means_all():
    session = _session()
    manifest = build_slide_manifest(session)
    result = asyncio.run(resolve_review_targets(None, "", manifest))
    assert result == [m["slide_id"] for m in manifest]


def test_resolve_review_targets_numeric_fallback_without_llm():
    session = _session()
    manifest = build_slide_manifest(session)
    result = asyncio.run(resolve_review_targets(None, "请审查第 2 页", manifest))
    assert result == [manifest[1]["slide_id"]]


def test_resolve_review_targets_uses_llm_selection():
    session = _session()
    manifest = build_slide_manifest(session)
    target_id = manifest[-1]["slide_id"]
    result = asyncio.run(
        resolve_review_targets(_FakeLLM([target_id]), "我觉得最后那页排版有问题", manifest)
    )
    assert result == [target_id]


def test_review_visuals_is_read_only(monkeypatch):
    session = _session()
    version_before = session.document.presentation.version
    element_counts_before = [len(s.elements) for s in session.document.presentation.slides]

    class FakeReport:
        def __init__(self, slide_id):
            self.slide_id = slide_id

        def to_dict(self):
            return {
                "score": 88.0,
                "defects_count": 1,
                "needs_auto_correction": False,
                "critique_summary": f"ok {self.slide_id}",
                "multimodal_feedback": None,
            }

    async def fake_review_slide(slide, llm_client=None, include_multimodal=True, on_event=None):
        return FakeReport(slide.id)

    monkeypatch.setattr(QualityService, "review_slide", fake_review_slide)

    events = []

    async def on_ev(ev):
        events.append(ev)

    result = asyncio.run(AgentRuntime().review_visuals(session, target=None, on_event=on_ev))

    assert result["success"] is True
    assert len(result["slide_reviews"]) >= 1
    assert result["overall"]["score"] == 88.0
    assert any(e.get("type") == "vision_review_result" for e in events)

    # Deck untouched.
    assert session.document.presentation.version == version_before
    assert [len(s.elements) for s in session.document.presentation.slides] == element_counts_before
