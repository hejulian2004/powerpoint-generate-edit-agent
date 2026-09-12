"""State definition for LangGraph PPT Generation Pipeline (PR13 Step 5).

Strictly named PPTGenerationState to decouple from interactive PPTAgentState.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

from ...evaluation.schema import VisualIssue
from ...ir.models import PresentationIR
from ...layout.schema import DeckLayoutSpec
from ...pptspec.schema import AssetRequirement, CanonicalPPTSpec
from ...slidespec.schema import DeckSpec


class PPTGenerationState(TypedDict, total=False):
    """Complete TypedDict state for PPT generation LangGraph execution."""

    session_id: str
    mode: Literal["generate", "edit"]
    source_type: str  # "pptspec" (default) | "paper"

    raw_input: str
    input_format: str

    canonical_spec: Optional[CanonicalPPTSpec]
    normalization_warnings: List[str]
    validation_errors: List[str]

    deck_spec: Optional[DeckSpec]
    deck_layout: Optional[DeckLayoutSpec]
    presentation_ir: Optional[PresentationIR]

    # Paper -> PPT inputs (S4). When ``source_type == "paper"`` the graph plans and
    # designs the deck directly from PaperIR + PaperVisualIR.
    paper_ir: Optional[Any]
    paper_visual_ir: Optional[Any]
    paper_cache_dir: Optional[str]
    presentation_plan: Optional[Any]
    user_prompt: str
    duration_minutes: int

    # Paper-branch truthfulness gate (S4): Art Director output is validated against
    # PaperIR before any design work; one targeted repair round, then hard fail.
    paper_truthfulness_attempts: int
    paper_truthfulness_errors: List[str]

    # LLM-native design path inputs (S2). When ``llm_layout_plans`` is present and
    # ``LLM_NATIVE_LAYOUT_ENABLED`` is on, layout_node compiles free-form plans
    # instead of the deterministic template engine.
    llm_layout_plans: List[Any]
    deck_art_direction: Optional[Any]

    # Provenance recorded on PresentationIR.metadata["generation"].
    generation_mode: str
    layout_source: str
    fallback_reason: Optional[str]

    visual_issues: List[VisualIssue]

    # Source-aware visual review (S3) + deck-level review (S4 / Phase 9).
    slide_rasters: Dict[str, str]
    deck_review: Optional[Any]
    slides_to_revisit: List[int]
    deck_revisit_round: int
    max_deck_revisit_rounds: int

    # Document identity captured when generation starts. The final persist commits
    # only if the live session still matches, so a generation run can never
    # overwrite edits the user made while it was running.
    base_document_epoch: Optional[str]
    base_revision: Optional[int]

    spec_repair_attempts: int
    max_spec_repair_attempts: int

    repair_iteration: int
    max_repair_iterations: int

    asset_requirements: List[AssetRequirement]

    status: str
    error: Optional[str]
