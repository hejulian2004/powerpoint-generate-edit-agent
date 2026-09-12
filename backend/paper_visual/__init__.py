"""backend.paper_visual: multimodal paper visual understanding.

Turns a paper PDF into a canonical, deterministic visual representation that
complements the textual ``PaperIR``:

    PDF
      |  pypdfium2  (sole canonical rasterizer)
      v  pages/page_001.webp ...          (PaperPageAsset)
      |  vision LLM (role="vision")       (PaperVisualIR)
      v  PaperPageVisual / VisualRegion
      |  Pillow                           (deterministic crops)
      v  crops/page_005_region_001.webp

Architecture invariants (frozen for this subsystem):

1. pypdfium2 is the ONLY page rasterizer. pdfplumber remains the text / line /
   bbox structural extractor and never renders pages. Pillow only crops and
   re-encodes.
2. ``PaperIR`` (text) remains the factual authority. ``PaperVisualIR`` is visual
   evidence only: it describes visual structure and never introduces numeric or
   scientific facts.
3. Vision always receives normalized [0, 1] page-relative coordinates; PaperIR
   PDF-point bboxes are normalized against the pypdfium2 page size with the
   effective page rotation applied before any region matching.
4. Vision is optional: when unavailable the subsystem degrades to page assets +
   textual PaperIR without raising.

The internal modules are not yet part of the stable facade; external callers
should depend on this package's exports.
"""

from __future__ import annotations

from .analyzer import analyze_paper_visual
from .cache import (
    compute_cache_key,
    load_or_render,
    load_visual_ir,
    paper_cache_dir,
    save_visual_ir,
)
from .constants import ANALYSIS_VERSION, RENDERER_VERSION, VISION_PROMPT_VERSION
from .context import SlideVisualContext, select_visual_context_for_slide
from .crops import crop_regions
from .errors import PaperRenderError, PaperVisualAnalysisError
from .renderer import RenderResult, render_pdf_pages
from .schema import (
    PaperPageAsset,
    PaperPageVisual,
    PaperVisualIR,
    VisualRegion,
)

__all__ = [
    "ANALYSIS_VERSION",
    "RENDERER_VERSION",
    "VISION_PROMPT_VERSION",
    "PaperRenderError",
    "PaperVisualAnalysisError",
    "PaperPageAsset",
    "PaperPageVisual",
    "PaperVisualIR",
    "VisualRegion",
    "RenderResult",
    "render_pdf_pages",
    "compute_cache_key",
    "paper_cache_dir",
    "load_or_render",
    "save_visual_ir",
    "load_visual_ir",
    "crop_regions",
    "SlideVisualContext",
    "select_visual_context_for_slide",
    "analyze_paper_visual",
]
