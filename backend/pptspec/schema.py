"""Canonical PPTSpec Data Models (PR13).

Strict internal specification generated from external AI presentation plans.
Follows the principle: 'Loose at the boundary, strict inside'.
Internal schema explicitly forbids extra attributes (model_config = ConfigDict(extra="forbid")).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..presentation.schema import SlideType
from ..slidespec.schema import VisualIntent


class EvidenceKind(str, Enum):
    CLAIM = "claim"
    METRIC = "metric"
    METRIC_GROUP = "metric_group"
    TABLE = "table"
    FIGURE_REFERENCE = "figure_reference"
    EQUATION = "equation"
    QUOTE = "quote"


class SourcePolicy(BaseModel):
    """Factual strictness policy. Normalized spec enforces safe defaults."""

    model_config = ConfigDict(extra="forbid")

    allow_external_knowledge: bool = False
    allow_inferred_facts: bool = False
    allow_invented_numbers: bool = False
    allow_synthetic_figures: bool = False
    missing_information_policy: str = "omit"


class SourceDocument(BaseModel):
    """Metadata regarding the source research paper or document."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    venue: Optional[str] = None
    year: Optional[int] = None
    authors: List[str] = Field(default_factory=list)


class PresentationConfig(BaseModel):
    """Overall presentation metadata and formatting guidelines."""

    model_config = ConfigDict(extra="forbid")

    title: str
    language: str = "zh-CN"
    audience: str = "计算机专业研究生组会"
    duration_minutes: int = 15
    style: str = "academic_clean"
    aspect_ratio: Literal["16:9"] = "16:9"


# =====================================================================
# Evidence Models
# =====================================================================

class BaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: EvidenceKind
    source_reference: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Literal["explicit", "unknown"] = "explicit"


class ClaimEvidence(BaseEvidence):
    kind: Literal[EvidenceKind.CLAIM] = EvidenceKind.CLAIM
    content: str


class MetricEvidence(BaseEvidence):
    """Scalar or comparative metric value represented as string to preserve symbols."""

    kind: Literal[EvidenceKind.METRIC] = EvidenceKind.METRIC
    name: str
    value: str = Field(..., description="String representation preserving ±, %, <, >, scientific notation")
    unit: Optional[str] = None
    method: Optional[str] = None


class MetricEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str
    unit: Optional[str] = None


class MetricGroupEvidence(BaseEvidence):
    """Group of multiple related metrics (e.g. multi-task benchmark)."""

    kind: Literal[EvidenceKind.METRIC_GROUP] = EvidenceKind.METRIC_GROUP
    group_name: str
    metrics: List[MetricEntry] = Field(default_factory=list)


class TableEvidence(BaseModel):
    """Structured table extracted from user input."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal[EvidenceKind.TABLE] = EvidenceKind.TABLE
    source_reference: Optional[str] = None
    source_page: Optional[int] = None
    confidence: Literal["explicit", "unknown"] = "explicit"
    columns: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    caption: Optional[str] = None
    complete_table: bool = True

    @model_validator(mode="after")
    def validate_table_dimensions(self) -> TableEvidence:
        """If rows length does not match column length, table cannot be complete."""
        col_count = len(self.columns)
        if col_count == 0 or len(self.rows) == 0:
            self.complete_table = False
            return self

        for row in self.rows:
            if len(row) != col_count:
                self.complete_table = False
                break
        return self


class FigureReferenceEvidence(BaseEvidence):
    """Strict figure reference. Synthetic graphics or generated images are prohibited."""

    kind: Literal[EvidenceKind.FIGURE_REFERENCE] = EvidenceKind.FIGURE_REFERENCE
    label: str = Field(..., description="E.g. 'Figure 3' or 'Fig. 1'")
    caption: Optional[str] = None
    source_page: Optional[int] = None


class EquationEvidence(BaseEvidence):
    kind: Literal[EvidenceKind.EQUATION] = EvidenceKind.EQUATION
    latex: str
    description: Optional[str] = None


class QuoteEvidence(BaseEvidence):
    kind: Literal[EvidenceKind.QUOTE] = EvidenceKind.QUOTE
    content: str
    speaker_or_section: Optional[str] = None


EvidenceItem = Annotated[
    Union[
        ClaimEvidence,
        MetricEvidence,
        MetricGroupEvidence,
        TableEvidence,
        FigureReferenceEvidence,
        EquationEvidence,
        QuoteEvidence,
    ],
    Field(discriminator="kind"),
]


# =====================================================================
# Slide Request & Canonical Spec
# =====================================================================

class SlideRequest(BaseModel):
    """Explicit request for an individual slide, referring to Evidence IDs."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: SlideType
    title: str
    objective: Optional[str] = None
    visual_intent: Optional[VisualIntent] = None
    evidence_refs: List[str] = Field(default_factory=list, description="IDs of evidence items to render")
    instructions: List[str] = Field(default_factory=list, description="Specific layout/formatting guidelines")
    speaker_notes: Optional[str] = None


class AssetRequirement(BaseModel):
    """Notice indicating a paper visual asset that the user should manually paste into PPTX."""

    model_config = ConfigDict(extra="forbid")

    slide_id: str
    asset_type: Literal["figure", "table"]
    label: str
    page: Optional[int] = None
    caption: Optional[str] = None


class CanonicalPPTSpec(BaseModel):
    """Canonical Intermediate Specification for presentation generation."""

    model_config = ConfigDict(extra="forbid")

    spec_version: Literal["1.0"] = "1.0"
    presentation: PresentationConfig
    source_policy: SourcePolicy = Field(default_factory=SourcePolicy)
    source_document: SourceDocument = Field(default_factory=SourceDocument)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    slides: List[SlideRequest] = Field(default_factory=list)

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceItem]:
        """Find an evidence item by its ID."""
        for ev in self.evidence:
            if ev.id == evidence_id:
                return ev
        return None

    def get_asset_requirements(self) -> List[AssetRequirement]:
        """Identify all figures and incomplete tables that need user manual insertion."""
        requirements: List[AssetRequirement] = []
        # Build evidence map
        ev_map = {ev.id: ev for ev in self.evidence}

        for slide in self.slides:
            for ev_id in slide.evidence_refs:
                ev = ev_map.get(ev_id)
                if ev is None:
                    continue
                if isinstance(ev, FigureReferenceEvidence):
                    requirements.append(
                        AssetRequirement(
                            slide_id=slide.id,
                            asset_type="figure",
                            label=ev.label,
                            page=ev.source_page,
                            caption=ev.caption,
                        )
                    )
                elif isinstance(ev, TableEvidence) and not ev.complete_table:
                    requirements.append(
                        AssetRequirement(
                            slide_id=slide.id,
                            asset_type="table",
                            label=ev.source_reference or ev.caption or f"Table ({ev.id})",
                            page=ev.source_page,
                            caption=ev.caption,
                        )
                    )
        return requirements
