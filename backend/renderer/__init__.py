"""Academic PPTX Renderer & OOXML Export Layer (PR11).

Provides high-fidelity, deterministic rendering from DeckLayoutSpec into
PowerPoint (.pptx) presentations, strictly preserving geometry, typography,
academic theme tokens, and source asset traceability.
"""

from .assets import AssetResolver
from .pptx_builder import PPTXBuilder
from .renderer import render_pptx
from .schema import EMU_PER_PX, EMU_PER_PT, FidelityCheckItem, FidelityReport, RenderConfig
from .theme import AcademicTheme, FontToken, ThemeColors, ThemeFonts, ThemeSpacing, hex_to_rgb
from .validators import render_slide_screenshots, validate_pptx_fidelity

__all__ = [
    # Core Renderer
    "render_pptx",
    # Builder
    "PPTXBuilder",
    # Asset Resolver
    "AssetResolver",
    # Theme & Tokens
    "AcademicTheme",
    "ThemeFonts",
    "ThemeColors",
    "ThemeSpacing",
    "FontToken",
    "hex_to_rgb",
    # Schema & Config
    "RenderConfig",
    "FidelityReport",
    "FidelityCheckItem",
    "EMU_PER_PX",
    "EMU_PER_PT",
    # Validation & Visual Export
    "validate_pptx_fidelity",
    "render_slide_screenshots",
]
