"""Slide Semantic IR (SlideSpec) Data Models (PR9).

Defines the structured semantic representation of academic slides before layout
constraint solving and PPTX rendering.

Decoupling Principle:
PresentationPlan (What to say) -> SlideSpec (Semantic Visual Contract) -> Layout Engine -> PPTX
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

from ..presentation.schema import SlideType


class VisualIntent(str, Enum):
    """Categorical visual arrangement intent for an academic slide."""

    TITLE_HERO = "TITLE_HERO"
    PIPELINE_ARCHITECTURE = "PIPELINE_ARCHITECTURE"
    BENCHMARK_COMPARISON = "BENCHMARK_COMPARISON"
    TWO_COLUMN_CONTRAST = "TWO_COLUMN_CONTRAST"
    METRIC_CARD_GRID = "METRIC_CARD_GRID"
    KEY_TAKEAWAY_LIST = "KEY_TAKEAWAY_LIST"


class BlockRole(str, Enum):
    """Semantic purpose of a content block within a slide."""

    HEADING = "HEADING"
    SUBHEADING = "SUBHEADING"
    LEAD_SUMMARY = "LEAD_SUMMARY"
    BULLET_ITEM = "BULLET_ITEM"
    CAPTION = "CAPTION"
    BADGE = "BADGE"
    CALLOUT = "CALLOUT"


class TextBlock(BaseModel):
    """Textual semantic unit."""

    kind: Literal["text"] = "text"
    role: BlockRole = BlockRole.BULLET_ITEM
    content: str = Field(..., description="Text content")
    emphasis: bool = Field(default=False, description="Whether this block should be visually emphasized")


class FigureBlock(BaseModel):
    """Visual asset block referencing an extracted figure from PaperIR."""

    kind: Literal["figure"] = "figure"
    source_figure_id: str = Field(..., description="Figure identifier from PaperIR (e.g. 'figure1')")
    caption: str = Field(default="", description="Figure caption")
    xref_label: str = Field(default="", description="Printed reference label (e.g. 'Fig. 1')")


class TableBlock(BaseModel):
    """Structured table block referencing an extracted table from PaperIR."""

    kind: Literal["table"] = "table"
    source_table_id: str = Field(..., description="Table identifier from PaperIR (e.g. 'table1')")
    caption: str = Field(default="", description="Table caption")
    xref_label: str = Field(default="", description="Printed reference label (e.g. 'Table 1')")
    highlight_cells: List[str] = Field(default_factory=list, description="Cell references to highlight")


class BadgeBlock(BaseModel):
    """Small categorical badge or key benchmark metric callout."""

    kind: Literal["badge"] = "badge"
    text: str = Field(..., description="Badge label text")
    variant: Literal["primary", "success", "accent", "neutral"] = Field(
        default="primary", description="Visual styling variant"
    )


ContentBlock = Annotated[
    Union[TextBlock, FigureBlock, TableBlock, BadgeBlock],
    Field(discriminator="kind"),
]


class SlideSpec(BaseModel):
    """Semantic intermediate representation of an individual slide."""

    index: int = Field(..., ge=1, description="1-based slide index")
    slide_type: SlideType = Field(..., description="Academic slide category from PresentationPlan")
    visual_intent: VisualIntent = Field(..., description="High-level visual layout archetype")
    title: str = Field(..., description="Slide heading")
    subtitle: Optional[str] = Field(default=None, description="Optional supporting subtitle or lead")
    blocks: List[ContentBlock] = Field(default_factory=list, description="Semantic content blocks")
    speaker_notes: Optional[str] = Field(default=None, description="Speaker notes or presentation tips")
    provenance: Dict[str, Any] = Field(
        default_factory=dict,
        description="Source trace metadata (source_sections, source_figures, source_tables)",
    )

    def get_blocks_by_kind(self, kind: str) -> List[ContentBlock]:
        """Return all content blocks of a specific kind."""
        return [b for b in self.blocks if b.kind == kind]


class DeckSpec(BaseModel):
    """Full deck specification composed of SlideSpec instances."""

    title: str = Field(..., description="Deck presentation title")
    profile: str = Field(default="research_15min", description="Template profile used")
    slides: List[SlideSpec] = Field(default_factory=list, description="Ordered sequence of slide specifications")

    @property
    def slide_count(self) -> int:
        return len(self.slides)

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        """Serialize deck spec to dictionary."""
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        """Serialize deck spec as a deterministic pretty-printed JSON file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "DeckSpec":
        """Deserialize DeckSpec from a JSON file."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
