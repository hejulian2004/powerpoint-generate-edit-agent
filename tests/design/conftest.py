"""Shared fixtures for LLM-native design tests."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

import pytest

from backend.design.schema import (
    ColorDirection,
    DeckArtDirection,
    SemanticColorBinding,
)
from backend.paper_visual.schema import (
    PaperPageAsset,
    PaperPageVisual,
    PaperVisualIR,
    VisualRegion,
)
from backend.presentation.schema import PresentationPlan, SlidePlan, SlideType
from backend.slidespec.schema import (
    BadgeBlock,
    BlockRole,
    DeckSpec,
    SlideSpec,
    TextBlock,
    VisualIntent,
)

_SLIDE_RE = re.compile(r"SLIDE\s+(\d+)")


def _user_text(messages: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
    return "\n".join(parts)


def _slide_id_from_messages(messages: List[Dict[str, Any]], default: str = "slide_1") -> str:
    match = _SLIDE_RE.search(_user_text(messages))
    return f"slide_{match.group(1)}" if match else default


_BLOCK_RE = re.compile(
    r"\{'kind': '(?P<kind>[^']*)'[^}]*'block_id': '(?P<block_id>[^']+)'"
)


def blocks_from_messages(messages: List[Dict[str, Any]]) -> List[tuple]:
    """Extract ``(block_id, kind)`` pairs from the slide layout context text."""
    blocks: List[tuple] = []
    seen = set()
    for line in _user_text(messages).splitlines():
        match = _BLOCK_RE.search(line)
        if not match:
            continue
        block_id = match.group("block_id")
        if block_id in seen:
            continue
        seen.add(block_id)
        blocks.append((block_id, match.group("kind")))
    return blocks


def valid_layout_payload(
    slide_id: str = "slide_1",
    blocks: Optional[List[tuple]] = None,
) -> Dict[str, Any]:
    """A layout that passes hard validation and binds every provided content block.

    ``blocks`` is a list of ``(block_id, kind)``; content values are placeholders
    because the compiler backfills them canonically from the SlideSpec.
    """
    block_list = list(blocks) if blocks else [("b1", "text")]
    elements: List[Dict[str, Any]] = [
        {
            "element_id": "title",
            "source_block_id": "header_title",
            "element_type": "TEXT",
            "x": 80,
            "y": 40,
            "width": 1120,
            "height": 80,
            "z_index": 2,
            "content": "A Research Title",
            "font_size": 32,
            "font_weight": "bold",
            "text_color": "#16181D",
            "alignment": "left",
            "vertical_alignment": "middle",
            "opacity": 1.0,
        }
    ]
    y = 150.0
    for position, (block_id, kind) in enumerate(block_list, start=1):
        element: Dict[str, Any] = {
            "element_id": f"el_{position}",
            "source_block_id": block_id,
            "x": 80,
            "y": y,
            "z_index": 1,
            "opacity": 1.0,
        }
        if kind == "figure":
            element.update(
                {"element_type": "FIGURE", "width": 500, "height": 220, "content": {}}
            )
            y += 240
        elif kind == "table":
            element.update(
                {"element_type": "TABLE", "width": 700, "height": 220, "content": {}}
            )
            y += 240
        elif kind == "badge":
            element.update(
                {
                    "element_type": "BADGE",
                    "width": 240,
                    "height": 56,
                    "content": "SOTA",
                    "font_size": 14,
                }
            )
            y += 76
        else:
            element.update(
                {
                    "element_type": "TEXT",
                    "width": 1120,
                    "height": 110,
                    "content": "Key point",
                    "font_size": 20,
                    "text_color": "#5A6472",
                }
            )
            y += 130
        elements.append(element)
    return {
        "slide_id": slide_id,
        "design_rationale": "hero title over supporting points",
        "visual_focal_point": "title",
        "reading_flow": "top to bottom",
        "elements": elements,
    }


def invalid_layout_payload(slide_id: str = "slide_1") -> Dict[str, Any]:
    """A layout that fails hard validation (overflows right canvas edge)."""
    return {
        "slide_id": slide_id,
        "elements": [
            {
                "element_id": "title",
                "element_type": "TEXT",
                "x": 1200,
                "y": 80,
                "width": 400,
                "height": 120,
                "content": "Too wide",
                "font_size": 32,
            }
        ],
    }


def always_valid_builder(kind: str = "layout") -> Callable[[List[Dict[str, Any]], str], str]:
    def _builder(messages, role="reasoning"):
        if kind == "layout":
            return json.dumps(
                valid_layout_payload(
                    _slide_id_from_messages(messages),
                    blocks_from_messages(messages),
                )
            )
        return json.dumps(art_direction_payload())

    return _builder


def repair_after_feedback_builder(messages, role="reasoning"):
    """Invalid on first attempt, valid once repair feedback is present."""
    slide_id = _slide_id_from_messages(messages)
    text = _user_text(messages)
    if "VALIDATION FEEDBACK" in text:
        return json.dumps(
            valid_layout_payload(slide_id, blocks_from_messages(messages))
        )
    return json.dumps(invalid_layout_payload(slide_id))


def always_invalid_builder(messages, role="reasoning"):
    return json.dumps(invalid_layout_payload(_slide_id_from_messages(messages)))


def art_direction_payload() -> Dict[str, Any]:
    return {
        "art_direction": {
            "design_concept": "editorial technical",
            "visual_language": "clean editorial",
            "typography_strategy": "strong title, quiet body",
            "spacing_strategy": "generous margins",
            "figure_strategy": "one hero figure",
            "table_strategy": "compact",
            "chart_strategy": "highlight primary",
            "decoration_strategy": "hairline rules",
            "consistency_rules": ["max 2 accents per slide"],
            "color_direction": {
                "background_strategy": "off-white",
                "surface_strategy": "subtle surfaces",
                "primary_text": "#16181D",
                "secondary_text": "#5A6472",
                "primary_accent": "#C2410C",
                "secondary_accent": None,
                "semantic_positive": "#15803D",
                "semantic_negative": "#B91C1C",
                "semantic_warning": "#B45309",
                "rationale": "warm accent on neutral ground",
                "bindings": [
                    {"semantic_key": "ours", "color": "#C2410C", "rationale": "primary"}
                ],
            },
        },
        "slides": [
            {
                "index": 1,
                "slide_type": "TITLE",
                "title": "A Research Title",
                "objective": "Introduce the work",
                "key_messages": ["Paper: A Research Title"],
                "source_pages": [1],
                "design_goal": "title dominates",
                "visual_priority": "text",
            },
            {
                "index": 2,
                "slide_type": "METHOD_OVERVIEW",
                "title": "Method Overview",
                "objective": "Explain the pipeline",
                "key_messages": ["Three-stage pipeline"],
                "source_figures": ["figure1"],
                "source_pages": [2],
                "design_goal": "figure dominates",
                "visual_priority": "figure",
            },
        ],
    }


def art_director_builder(messages, role="reasoning"):
    return json.dumps(art_direction_payload())


def paper_pipeline_builder(messages, role="reasoning"):
    """Route art-director calls vs layout-designer calls by system prompt."""
    system = ""
    if messages and isinstance(messages[0], dict):
        system = str(messages[0].get("content", ""))
    if "art_direction" in system:
        return json.dumps(art_direction_payload())
    return json.dumps(
        valid_layout_payload(
            _slide_id_from_messages(messages),
            blocks_from_messages(messages),
        )
    )


class FakeDesignClient:
    """Minimal stand-in for ``LLMClient`` driven by a response builder."""

    def __init__(
        self,
        builder: Optional[Callable[[List[Dict[str, Any]], str], str]] = None,
        api_key: str = "fake-design-key",
    ) -> None:
        self.api_key = api_key
        self.calls: List[Dict[str, Any]] = []
        self._builder = builder or always_valid_builder("layout")

    def get_model_for_role(self, role: str = "default") -> str:
        return "fake-design-model"

    async def chat_completion(self, messages, role="default", max_tokens=4096, **kwargs):
        self.calls.append({"messages": messages, "role": role, "max_tokens": max_tokens})
        content = self._builder(messages, role)
        return {"choices": [{"message": {"content": content}}]}

    @property
    def roles(self) -> List[str]:
        return [call["role"] for call in self.calls]


@pytest.fixture
def design_client_cls():
    return FakeDesignClient


@pytest.fixture
def art_direction_response_builder():
    return art_director_builder


@pytest.fixture
def repair_response_builder():
    return repair_after_feedback_builder


@pytest.fixture
def invalid_response_builder():
    return always_invalid_builder


@pytest.fixture
def valid_response_builder():
    return always_valid_builder("layout")


@pytest.fixture
def paper_pipeline_response_builder():
    return paper_pipeline_builder


@pytest.fixture
def paper_ir_fixture():
    from backend.paper.schema import PaperFigure, PaperIR, PaperMetadata, PaperSection

    return PaperIR(
        source_filename="paper.pdf",
        metadata=PaperMetadata(title="A Research Title", authors=["A. Author"], page_count=2),
        abstract="We present a concise method for research.",
        sections=[
            PaperSection(
                number="1",
                title="Introduction",
                page=1,
                paragraphs=["Prior work has limitations that motivate our approach."],
            ),
            PaperSection(
                number="2",
                title="Method",
                page=2,
                paragraphs=["Our method combines three stages into one pipeline."],
            ),
        ],
        figures=[
            PaperFigure(
                id="figure1",
                xref_label="Figure 1",
                caption="Three-stage pipeline overview",
                page=2,
            )
        ],
    )


@pytest.fixture
def deck_spec_two_slides() -> DeckSpec:
    return DeckSpec(
        title="A Research Title",
        profile="research_15min",
        slides=[
            SlideSpec(
                index=1,
                slide_type=SlideType.TITLE,
                visual_intent=VisualIntent.TITLE_HERO,
                title="A Research Title",
                subtitle="A. Author",
                blocks=[
                    TextBlock(
                        block_id="b1",
                        role=BlockRole.HEADING,
                        content="A Research Title",
                    )
                ],
            ),
            SlideSpec(
                index=2,
                slide_type=SlideType.METHOD_OVERVIEW,
                visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
                title="Method Overview",
                blocks=[
                    TextBlock(
                        block_id="b1",
                        role=BlockRole.LEAD_SUMMARY,
                        content="Three-stage pipeline",
                    ),
                    BadgeBlock(block_id="badge1", text="SOTA"),
                ],
            ),
        ],
    )


@pytest.fixture
def presentation_plan_two_slides() -> PresentationPlan:
    return PresentationPlan(
        title="A Research Title",
        profile="llm_research",
        slides=[
            SlidePlan(
                index=1,
                slide_type=SlideType.TITLE,
                title="A Research Title",
                objective="Introduce the work",
                key_messages=["Paper: A Research Title"],
                source_pages=[1],
                design_goal="title dominates",
                visual_priority="text",
            ),
            SlidePlan(
                index=2,
                slide_type=SlideType.METHOD_OVERVIEW,
                title="Method Overview",
                objective="Explain the pipeline",
                key_messages=["Three-stage pipeline"],
                source_figures=["figure1"],
                source_pages=[2],
                design_goal="figure dominates",
                visual_priority="figure",
            ),
        ],
    )


@pytest.fixture
def paper_visual_ir_fixture() -> PaperVisualIR:
    asset = PaperPageAsset(
        page_number=1,
        image_path="page_001.png",
        width=1280,
        height=720,
        dpi=144,
    )
    region = VisualRegion(
        region_id="page_001_region_001",
        page_number=1,
        region_type="figure",
        bbox=[0.1, 0.1, 0.5, 0.5],
        description="A structural figure block",
        importance=0.9,
        ppt_usefulness=0.9,
        source_figure_id="figure1",
    )
    return PaperVisualIR(
        source_filename="paper.pdf",
        pages=[
            PaperPageVisual(
                page_number=1,
                page_asset=asset,
                visual_summary="Single figure page",
                visual_importance=0.8,
                regions=[region],
            )
        ],
    )


@pytest.fixture
def art_direction() -> DeckArtDirection:
    from backend.design.art_director import default_art_direction

    return default_art_direction()
