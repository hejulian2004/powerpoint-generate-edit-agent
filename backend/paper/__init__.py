"""backend.paper: Research Paper Understanding Package (PR7.1).

Converts a paper PDF into a structured ``PaperIR`` via deterministic heuristics
(text / reading-order / heading / caption extraction), with an optional LLM
enrichment layer for semantic fields.

External consumers should depend ONLY on the stable facade below; the internal
modules ``section_extractor.py`` / ``parser.py`` / ``enricher.py`` are not part of
the stable public API.
"""

from .schema import (
    BBox,
    ExtractionMeta,
    PaperFigure,
    PaperIR,
    PaperMetadata,
    PaperSection,
    PaperTable,
)
from .parser import extract_paper, EXTRACTOR_VERSION
from .enricher import enrich_paper, aenrich_paper, apply_enrichment

__all__ = [
    "BBox",
    "ExtractionMeta",
    "PaperFigure",
    "PaperIR",
    "PaperMetadata",
    "PaperSection",
    "PaperTable",
    "extract_paper",
    "EXTRACTOR_VERSION",
    "enrich_paper",
    "aenrich_paper",
    "apply_enrichment",
]
