"""LLM-native presentation design subsystem.

Two-stage, free-form design pipeline:

1. ``art_director``: deck-level design language + presentation plan.
2. ``layout_designer``: per-slide absolute geometry with a hard-validated repair loop.

Legacy template layout remains available as a per-slide fallback only.
"""

from __future__ import annotations

from .art_director import (
    build_plan_and_direction,
    default_art_direction,
    default_color_direction,
    design_deck,
)
from .aesthetic_refiner import refine_deck_aesthetics, summarize_critiques
from .color_validator import (
    ColorIssue,
    ColorValidationReport,
    validate_color_direction,
    validate_deck_colors,
)
from .layout_compiler import (
    LAYOUT_PLAN_VERSION,
    compile_llm_deck_layout,
    compile_llm_layout,
    hard_validate_layout,
)
from .layout_context import SlideLayoutContext, build_slide_layout_context
from .layout_designer import (
    DeckDesignResult,
    design_deck_layouts,
    design_slide_layout,
)
from .layout_schema import LayoutElementPlan, LLMLayoutPlan
from .schema import ColorDirection, DeckArtDirection, SemanticColorBinding
from .validator_feedback import format_layout_validation_feedback
from .visual_critic import (
    SlideCritique,
    critique_deck,
    critique_slide,
    format_critique_feedback,
    format_layout_manifest,
)

__all__ = [
    # schemas
    "SemanticColorBinding",
    "ColorDirection",
    "DeckArtDirection",
    "LayoutElementPlan",
    "LLMLayoutPlan",
    # art direction
    "design_deck",
    "build_plan_and_direction",
    "default_art_direction",
    "default_color_direction",
    # per-slide layout
    "design_slide_layout",
    "design_deck_layouts",
    "DeckDesignResult",
    "build_slide_layout_context",
    "SlideLayoutContext",
    "format_layout_validation_feedback",
    # compiler
    "compile_llm_layout",
    "compile_llm_deck_layout",
    "hard_validate_layout",
    "LAYOUT_PLAN_VERSION",
    # critic + color + refinement
    "SlideCritique",
    "critique_slide",
    "critique_deck",
    "format_critique_feedback",
    "format_layout_manifest",
    "ColorIssue",
    "ColorValidationReport",
    "validate_color_direction",
    "validate_deck_colors",
    "refine_deck_aesthetics",
    "summarize_critiques",
]
