"""Renderer schemas and coordinate mapping constants (PR11).

Defines render configuration, coordinate conversion factors between LayoutSpec ViewBox
(1280x720) and OOXML Presentation coordinates (EMU), and fidelity validation reporting models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Coordinate Conversion Constants
# ---------------------------------------------------------------------------
# Standard 16:9 widescreen presentation in PowerPoint:
# Width = 13.333333 inches = 12,192,000 EMUs
# Height = 7.5 inches = 6,858,000 EMUs
# Normalized LayoutSpec canvas: 1280 x 720 px
# Exact scaling: 12,192,000 / 1280 = 9525 EMUs / px
#                6,858,000 / 720  = 9525 EMUs / px
EMU_PER_INCH: int = 914400
EMU_PER_PT: int = 12700
EMU_PER_PX: int = 9525
PT_PER_PX: float = 0.75  # 1 px = 0.75 pt (96 DPI standard)


class RenderConfig(BaseModel):
    """Configuration options for PPTX rendering."""

    widescreen: bool = Field(True, description="Whether to render in 16:9 widescreen")
    validate_fidelity: bool = Field(True, description="Whether to run automatic fidelity validation")
    allow_synthetic_assets: bool = Field(
        True,
        description="Whether to generate synthetic placeholder diagrams when image assets are missing on disk",
    )
    custom_properties: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary PPTX metadata")


class FidelityCheckItem(BaseModel):
    """Single item checked during fidelity inspection."""

    category: str = Field(..., description="Check category: 'slide_count', 'geometry', 'text', 'asset', etc.")
    target_id: Optional[str] = Field(None, description="Element ID or Slide ID being checked")
    passed: bool = Field(..., description="Whether this check passed")
    expected: Any = Field(..., description="Expected value from LayoutSpec")
    actual: Any = Field(..., description="Actual value observed in PPTX")
    difference: Optional[float] = Field(None, description="Difference value or percentage error if applicable")
    message: Optional[str] = Field(None, description="Detailed diagnostic description")


class FidelityReport(BaseModel):
    """Report detailing fidelity verification between LayoutSpec and generated PPTX."""

    is_valid: bool = Field(..., description="True if no hard errors occurred")
    slide_count: int = Field(..., description="Total slides checked")
    checks: List[FidelityCheckItem] = Field(default_factory=list, description="All executed fidelity checks")
    max_geometry_error_pct: float = Field(0.0, description="Maximum observed geometry deviation percentage")
    errors: List[str] = Field(default_factory=list, description="Fatal fidelity mismatch messages")
    warnings: List[str] = Field(default_factory=list, description="Non-fatal fidelity warnings")
