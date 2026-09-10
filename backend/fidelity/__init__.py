"""backend.fidelity: High-Fidelity PPT Reconstruction & Intelligence Package."""

from .theme_engine import ThemeEngine, DEFAULT_COLOR_SCHEME, DEFAULT_FONT_SCHEME
from .font_engine import FontEngine
from .style_resolver import StyleResolver
from .relationship import RelationshipGraph, RelationshipEntry, AssetManager
from .ooxml_parser import OOXMLParser
from .capability import EngineCapabilities, DetectedFeatures, CapabilityDetector
from .fidelity_engine import FidelityEngine
from .fidelity_diff import FidelityDiffEngine, FidelityDiffReport, ElementDrift

__all__ = [
    "ThemeEngine",
    "DEFAULT_COLOR_SCHEME",
    "DEFAULT_FONT_SCHEME",
    "FontEngine",
    "StyleResolver",
    "RelationshipGraph",
    "RelationshipEntry",
    "AssetManager",
    "OOXMLParser",
    "EngineCapabilities",
    "DetectedFeatures",
    "CapabilityDetector",
    "FidelityEngine",
    "FidelityDiffEngine",
    "FidelityDiffReport",
    "ElementDrift",
]
