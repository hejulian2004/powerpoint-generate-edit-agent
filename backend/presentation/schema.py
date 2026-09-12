"""Presentation-Plan Data Models (PR7.2).

The canonical presentation structure planned from a PaperIR.
It decouples "what the talk should cover" from "how each visual slide is drawn",
acting as the bridge between Paper Understanding (PR7.1) and Slide Semantic IR (PR7.3+).

Scope (PR7.2):
- SlideType: standard academic presentation slide taxonomy.
- SlidePlan: a single slide's communicative purpose, target messages, and source paper links.
- PresentationPlan: ordered sequence of slide plans with deck metadata and JSON round-trip.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SlideType(str, Enum):
    """Taxonomy of slide categories in academic / technical presentations."""

    TITLE = "TITLE"
    BACKGROUND = "BACKGROUND"
    PROBLEM = "PROBLEM"
    RELATED_WORK = "RELATED_WORK"
    MOTIVATION = "MOTIVATION"
    METHOD_OVERVIEW = "METHOD_OVERVIEW"
    METHOD_DETAIL = "METHOD_DETAIL"
    EXPERIMENT_SETUP = "EXPERIMENT_SETUP"
    RESULT = "RESULT"
    ABLATION = "ABLATION"
    LIMITATION = "LIMITATION"
    CONCLUSION = "CONCLUSION"


class SlidePlan(BaseModel):
    """Plan for an individual slide within the presentation."""

    index: int = Field(..., ge=1, description="1-based slide index in the presentation")
    slide_type: SlideType = Field(..., description="Categorical type of the slide")
    title: str = Field(..., description="Proposed slide heading / title")
    objective: str = Field(..., description="Communicative objective for this slide")
    key_messages: List[str] = Field(
        default_factory=list,
        description="Key bullet points or takeaways to convey (typically 2-4 items)",
    )
    source_sections: List[str] = Field(
        default_factory=list,
        description="Paper section numbers or titles referenced by this slide",
    )
    source_figures: List[str] = Field(
        default_factory=list,
        description="Figure IDs referenced by this slide (e.g. ['figure1'])",
    )
    source_tables: List[str] = Field(
        default_factory=list,
        description="Table IDs referenced by this slide (e.g. ['table1'])",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Speaker notes or presentation guidance for the presenter",
    )

    # ------------------------------------------------------------------
    # Multimodal design planning (LLM-native pipeline).
    # These are optional so the legacy deterministic planner (which never sets
    # them) keeps producing byte-identical plans.
    # ------------------------------------------------------------------
    source_pages: List[int] = Field(
        default_factory=list,
        description="Paper page numbers this slide draws on (visual context selection)",
    )
    visual_evidence_ids: List[str] = Field(
        default_factory=list,
        description="PaperVisualIR region ids (e.g. ['page_5_region_1']) as visual evidence",
    )
    design_goal: str = Field(
        "", description="Design intent for this slide (e.g. 'the architecture figure dominates')"
    )
    visual_priority: str = Field(
        "", description="What should visually dominate this slide ('figure' | 'text' | 'table' | ...)"
    )
    factual_evidence_ids: List[str] = Field(
        default_factory=list,
        description="Textual evidence handles (PaperIR sections/figures/tables) for fact checking",
    )


class PresentationPlan(BaseModel):
    """Top-level presentation plan generated from PaperIR."""

    title: str = Field(..., description="Title of the presentation")
    audience: str = Field(
        default="Research Lab / Academic Seminar",
        description="Target audience profile",
    )
    duration_minutes: int = Field(
        default=15,
        ge=1,
        description="Estimated presentation duration in minutes",
    )
    profile: str = Field(
        default="research_15min",
        description="Presentation profile used (e.g. 'research_15min', 'research_10min')",
    )
    source_filename: str = Field(
        default="",
        description="Source PDF or document filename",
    )
    slides: List[SlidePlan] = Field(
        default_factory=list,
        description="Ordered sequence of planned slides",
    )

    @property
    def slide_count(self) -> int:
        return len(self.slides)

    def get_slides_by_type(self, slide_type: SlideType) -> List[SlidePlan]:
        """Return all slides matching a specific slide type."""
        return [s for s in self.slides if s.slide_type == slide_type]

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        """Convert plan to a JSON-compatible dictionary."""
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        """Write the PresentationPlan as a deterministic pretty-printed JSON file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "PresentationPlan":
        """Load a PresentationPlan from a JSON file."""
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
