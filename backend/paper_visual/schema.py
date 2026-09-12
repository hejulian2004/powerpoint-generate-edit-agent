"""Paper visual (multimodal) intermediate representation.

``PaperVisualIR`` is the visual counterpart to the textual ``PaperIR``. It is
produced by rendering the canonical pages (pypdfium2) and asking a vision model
to describe the *visual structure* of each page.

Factual authority boundary
--------------------------
``PaperIR`` remains the sole factual authority. ``PaperVisualIR`` is visual
evidence: region descriptions describe layout / figure / table structure and
must never introduce numeric or scientific claims. Numbers, metrics and
experimental results may only enter the deck from ``PaperIR`` and are validated
by ``backend.agent.grounding`` / ``backend.pptspec.validator``.

Coordinate contract
-------------------
- ``PaperIR.BBox``  -> pdfplumber PDF points, top-left origin.
- ``VisualRegion.bbox`` -> normalized ``[x0, y0, x1, y1]`` in ``[0, 1]``,
  page-relative, top-left origin, matching the pypdfium2 raster.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

RegionType = Literal[
    "figure",
    "table",
    "diagram",
    "equation",
    "chart",
    "code",
    "algorithm",
    "other",
]


class PaperPageAsset(BaseModel):
    """A single canonical rasterized page produced by pypdfium2."""

    page_number: int = Field(..., ge=1, description="1-based page number")
    image_path: str = Field(..., description="Path to the rendered page image")
    width: int = Field(..., ge=1, description="Rendered image width in pixels")
    height: int = Field(..., ge=1, description="Rendered image height in pixels")
    dpi: int = Field(..., ge=1, description="Rasterization DPI")
    sha256: str = Field("", description="SHA-256 of the rendered image bytes")


class VisualRegion(BaseModel):
    """A visually meaningful region on a page (figure / table / diagram ...)."""

    region_id: str = Field(..., description="Stable id, e.g. 'page_005_region_001'")
    page_number: int = Field(..., ge=1, description="1-based source page")
    region_type: RegionType = Field(..., description="Visual region category")

    bbox: List[float] = Field(
        ..., description="Normalized [x0, y0, x1, y1] in [0, 1], top-left origin"
    )

    description: str = Field("", description="Visual-structural description (no facts)")

    importance: float = Field(0.0, ge=0.0, le=1.0, description="Visual importance 0..1")
    ppt_usefulness: float = Field(
        0.0, ge=0.0, le=1.0, description="Usefulness for a presentation slide 0..1"
    )

    source_figure_id: Optional[str] = Field(
        None, description="Matched PaperIR figure id (e.g. 'figure2')"
    )
    source_table_id: Optional[str] = Field(
        None, description="Matched PaperIR table id (e.g. 'table3')"
    )

    crop_path: Optional[str] = Field(None, description="Deterministic crop image path")

    @field_validator("bbox")
    @classmethod
    def _validate_bbox(cls, value: List[float]) -> List[float]:
        if len(value) != 4:
            raise ValueError("bbox must contain exactly [x0, y0, x1, y1]")
        x0, y0, x1, y1 = (float(v) for v in value)
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return [
            max(0.0, min(1.0, x0)),
            max(0.0, min(1.0, y0)),
            max(0.0, min(1.0, x1)),
            max(0.0, min(1.0, y1)),
        ]


class PaperPageVisual(BaseModel):
    """The visual understanding of a single paper page."""

    page_number: int = Field(..., ge=1, description="1-based page number")
    page_asset: PaperPageAsset = Field(..., description="Rendered page asset")

    visual_summary: str = Field("", description="One-line visual summary of the page")
    visual_importance: float = Field(
        0.0, ge=0.0, le=1.0, description="Visual importance of the page 0..1"
    )
    density: Literal["low", "medium", "high"] = Field(
        "medium", description="Visual density of the page"
    )

    regions: List[VisualRegion] = Field(
        default_factory=list, description="Visually meaningful regions"
    )
    design_observations: List[str] = Field(
        default_factory=list, description="Observations useful for slide design"
    )


class PaperVisualIR(BaseModel):
    """Visual IR for a whole paper: pages + regions + provenance."""

    source_filename: str = Field("", description="Original PDF file name")
    source_sha256: str = Field("", description="SHA-256 of the source PDF")

    pages: List[PaperPageVisual] = Field(
        default_factory=list, description="Page-level visual understanding in order"
    )

    vision_model: Optional[str] = Field(
        None, description="Vision model used, or None when vision was unavailable"
    )
    analysis_version: str = Field("1.0.0", description="Analyzer semantics version")
    warnings: List[str] = Field(
        default_factory=list, description="Non-fatal degradation notes"
    )

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def visual_evidence_ids(self) -> List[str]:
        """All region ids across the paper (used as visual evidence handles)."""
        return [region.region_id for page in self.pages for region in page.regions]

    def page_by_number(self, page_number: int) -> Optional[PaperPageVisual]:
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "PaperVisualIR":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "PaperPageAsset",
    "VisualRegion",
    "PaperPageVisual",
    "PaperVisualIR",
    "RegionType",
]
