"""Shared fixtures for paper_visual tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

FIXTURE_PDF = Path("tests/fixtures/paper/multicase_10p.pdf")


@pytest.fixture
def multicase_pdf() -> Path:
    assert FIXTURE_PDF.exists(), f"Missing fixture PDF: {FIXTURE_PDF}"
    return FIXTURE_PDF


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "paper_cache"


_PAGES_RE = re.compile(r"pages:\s*\[([0-9,\s]+)\]")


def _page_numbers_from_messages(messages: List[Dict[str, Any]]) -> List[int]:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    match = _PAGES_RE.search(block.get("text", ""))
                    if match:
                        return [int(x) for x in match.group(1).split(",") if x.strip()]
    return []


def default_vision_response(messages: List[Dict[str, Any]]) -> str:
    """A deterministic strict-JSON response keyed to the requested page numbers."""
    import json

    page_numbers = _page_numbers_from_messages(messages)
    pages = []
    for idx, number in enumerate(page_numbers):
        pages.append(
            {
                "page_number": number,
                "visual_summary": f"Page {number} visual structure",
                "visual_importance": 0.5,
                "density": "medium",
                "regions": [
                    {
                        "region_type": "figure",
                        "bbox": [0.1, 0.2, 0.6, 0.6],
                        "description": f"Structural figure region on page {number}",
                        "importance": 0.8,
                        "ppt_usefulness": 0.9,
                    },
                    {
                        "region_type": "other",
                        "bbox": [0.65, 0.1, 0.95, 0.4],
                        "description": "Secondary visual block",
                        "importance": 0.4,
                        "ppt_usefulness": 0.3,
                    },
                ],
                "design_observations": ["Balanced single-column layout"],
            }
        )
    return json.dumps({"pages": pages})


class FakeVisionClient:
    """Minimal stand-in for ``LLMClient`` with a configurable response builder."""

    def __init__(
        self,
        api_key: str = "fake-vision-key",
        response_builder: Optional[Callable[[List[Dict[str, Any]]], str]] = None,
    ) -> None:
        self.api_key = api_key
        self.calls: List[Dict[str, Any]] = []
        self._builder = response_builder or default_vision_response

    def get_model_for_role(self, role: str = "default") -> str:
        return "fake-vision-model"

    async def chat_completion(self, messages, role="default", max_tokens=4096, **kwargs):
        self.calls.append({"messages": messages, "role": role, "max_tokens": max_tokens})
        content = self._builder(messages)
        return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def fake_vision_client() -> FakeVisionClient:
    return FakeVisionClient()


@pytest.fixture
def vision_client_cls():
    """The FakeVisionClient class, so tests can subclass it without importing conftest."""
    return FakeVisionClient


@pytest.fixture
def vision_response_builder():
    """The deterministic default strict-JSON response builder."""
    return default_vision_response
