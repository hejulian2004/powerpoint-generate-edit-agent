"""Exceptions for the paper visual (multimodal) understanding subsystem.

The two failure domains are deliberately separated so a page-rasterization
failure never masquerades as a textual parse failure (and vice versa):

- ``PaperRenderError``: the PDF could not be opened / a canonical page could not
  be rasterized by pypdfium2.
- ``PaperVisualAnalysisError``: the vision model could not be invoked or its
  structured response could not be parsed.

The parser (``backend.paper.parser``) raises neither: text/structural extraction
remains independently usable when vision is unavailable.
"""

from __future__ import annotations

from typing import List, Optional


class PaperRenderError(RuntimeError):
    """Raised when canonical PDF page rasterization fails irrecoverably."""

    def __init__(self, message: str, warnings: Optional[List[str]] = None):
        super().__init__(message)
        self.warnings = warnings or []


class PaperVisualAnalysisError(RuntimeError):
    """Raised when multimodal paper visual analysis fails irrecoverably."""

    def __init__(self, message: str, warnings: Optional[List[str]] = None):
        super().__init__(message)
        self.warnings = warnings or []


__all__ = ["PaperRenderError", "PaperVisualAnalysisError"]
