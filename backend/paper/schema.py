"""Paper-IR (Paper Intermediate Representation) Data Models.

The canonical structured understanding of an academic paper extracted from a PDF.
It decouples "what the paper says" from "how it should be presented", and is the
input contract for the Research Presentation Planner (PR7.2+) which later turns a
PaperIR into a research slide report.

Scope (PR7.1):
- Deterministic structural extraction: metadata / abstract / sections / figures / tables.
- Semantic fields (contributions / methodology / experiments / limitations) are left
  empty by the deterministic extractor and optionally filled by the LLM enricher.

Style notes: pydantic v2 models, deterministic field ordering, JSON round-trip safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """Axis-aligned rectangle in PDF page coordinates (top-left origin, points)."""

    x0: float = Field(..., description="Left edge in PDF points")
    top: float = Field(..., description="Top edge in PDF points")
    x1: float = Field(..., description="Right edge in PDF points")
    bottom: float = Field(..., description="Bottom edge in PDF points")

    @property
    def width(self) -> float:
        return max(self.x1 - self.x0, 0.0)

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 0.0)


class PaperMetadata(BaseModel):
    """Front matter of the paper."""

    title: str = Field("", description="Paper title")
    authors: List[str] = Field(default_factory=list, description="Author / affiliation lines")
    year: Optional[str] = Field(None, description="Publication year if detectable")
    venue: Optional[str] = Field(None, description="Venue / conference / journal if detectable")
    page_count: int = Field(0, description="Total number of PDF pages")


class PaperSection(BaseModel):
    """A numbered / titled section with its extracted body paragraphs."""

    number: Optional[str] = Field(None, description="Section number e.g. '1', '2.1', 'A'")
    title: str = Field("", description="Section title text")
    level: int = Field(1, ge=1, le=3, description="Heading depth (1 = top level)")
    page: int = Field(0, ge=0, description="1-based page where the heading appears")
    paragraphs: List[str] = Field(default_factory=list, description="Body text in reading order")


class PaperFigure(BaseModel):
    """A figure discovered via its caption, with optional raster region association."""

    id: str = Field("", description="Stable id: 'figure1', 'figure2', ...")
    xref_label: str = Field("", description="Caption reference as printed: 'Fig. 1', 'Figure 2'")
    caption: str = Field("", description="Caption text after the xref label")
    page: int = Field(0, ge=0, description="1-based page containing the caption")
    kind: Optional[Literal["architecture", "experiment", "ablation", "result", "other"]] = Field(
        None, description="Reserved for PR7.3 figure classification"
    )
    bbox: Optional[BBox] = Field(None, description="Associated raster region on the page")
    is_raster: bool = Field(False, description="True when a raster image region was found")


class PaperTable(BaseModel):
    """A table discovered via its caption, with best-effort grid cells."""

    id: str = Field("", description="Stable id: 'table1', 'table2', ...")
    xref_label: str = Field("", description="Caption reference as printed: 'Table 1', 'TABLE II'")
    caption: str = Field("", description="Caption text after the xref label")
    page: int = Field(0, ge=0, description="1-based page containing the caption")
    header: List[str] = Field(default_factory=list, description="Best-effort header row cells")
    rows: List[List[str]] = Field(default_factory=list, description="Best-effort data rows")
    extracted: bool = Field(False, description="True when grid cells were successfully parsed")


class ExtractionMeta(BaseModel):
    """Provenance describing how the PaperIR was produced."""

    engine: str = Field("pdfplumber", description="Parsing backend used")
    extractor_version: str = Field("1.0.0", description="Version of the deterministic extractor")
    methods: List[str] = Field(default_factory=list, description="Heuristics applied")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal issues encountered")
    semantic_status: Literal["extracted", "enriched", "enrichment_failed"] = Field(
        "extracted", description="Whether LLM semantic enrichment has run"
    )


class PaperIR(BaseModel):
    """Structured understanding of an academic paper (canonical PR7 input)."""

    source_filename: str = Field("", description="Original PDF file name")
    metadata: PaperMetadata = Field(default_factory=PaperMetadata)
    abstract: str = Field("", description="Extracted abstract text (if present)")
    sections: List[PaperSection] = Field(default_factory=list, description="Body sections in reading order")
    figures: List[PaperFigure] = Field(default_factory=list, description="Figures discovered by caption")
    tables: List[PaperTable] = Field(default_factory=list, description="Tables discovered by caption")
    contributions: List[str] = Field(
        default_factory=list, description="Semantic: key contributions (LLM-enriched)"
    )
    methodology: List[str] = Field(
        default_factory=list, description="Semantic: method highlights (LLM-enriched)"
    )
    experiments: List[str] = Field(
        default_factory=list, description="Semantic: experiment highlights (LLM-enriched)"
    )
    limitations: List[str] = Field(
        default_factory=list, description="Semantic: known limitations (LLM-enriched)"
    )
    extraction: ExtractionMeta = Field(default_factory=ExtractionMeta)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def title(self) -> str:
        return self.metadata.title

    def section_map(self) -> Dict[str, PaperSection]:
        """Map section title (lower-cased) -> section for planner lookups."""
        return {s.title.strip().lower(): s for s in self.sections if s.title}

    def body_section_text(self) -> str:
        """Concatenated body paragraphs across all sections (planner / LLM input)."""
        return "\n".join(
            para
            for sec in self.sections
            for para in sec.paragraphs
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        """Write the PaperIR as a deterministic pretty-printed JSON file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "PaperIR":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))
