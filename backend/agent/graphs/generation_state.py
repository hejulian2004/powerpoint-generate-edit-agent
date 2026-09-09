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

    raw_input: str
    input_format: str

    canonical_spec: Optional[CanonicalPPTSpec]
    normalization_warnings: List[str]
    validation_errors: List[str]

    deck_spec: Optional[DeckSpec]
    deck_layout: Optional[DeckLayoutSpec]
    presentation_ir: Optional[PresentationIR]

    visual_issues: List[VisualIssue]

    repair_iteration: int
    max_repair_iterations: int

    asset_requirements: List[AssetRequirement]

    status: str
    error: Optional[str]
