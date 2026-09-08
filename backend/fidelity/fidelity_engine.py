"""FidelityEngine: stable public facade for the Fidelity Engine (PR6.1 Task 8).

External consumers should depend ONLY on this facade:

    from backend.fidelity import FidelityEngine

and must not reach into ooxml_parser.py / style_resolver.py / relationship.py etc. This
keeps the public API stable while the internals evolve.

Imports from backend.eval.fidelity are deferred to call time to avoid a module-level
circular import (backend.fidelity <-> backend.eval.fidelity.report).
"""

from __future__ import annotations
import io
from typing import TYPE_CHECKING, Any, Dict, Union

from ..ir.models import PresentationIR, SlideIR
from .ooxml_parser import OOXMLParser
from .capability import CapabilityDetector

if TYPE_CHECKING:
    from .fidelity_diff import FidelityDiffReport
    from ..eval.fidelity import FidelityScore, FidelityReport


class FidelityEngine:
    """Facade exposing import, capability detection, evaluation, diff, and reporting."""

    @classmethod
    def import_presentation(cls, source: Union[str, bytes, io.BytesIO]) -> PresentationIR:
        """Imports a PPTX package into PresentationIR with capability detection."""
        return OOXMLParser(source).parse()

    @classmethod
    def import_with_report(cls, source: Union[str, bytes, io.BytesIO]) -> Dict[str, Any]:
        """Imports and returns the presentation plus its parse/capability summary."""
        pres = cls.import_presentation(source)
        warnings = list(pres.metadata.get("parser_warnings", []))
        return {
            "presentation": pres,
            "status": pres.metadata.get("parse_status", "ok"),
            "warnings": warnings,
            "capabilities": dict(pres.capabilities),
            "unsupported": [
                f for f, present in pres.capabilities.items()
                if f != "master_slide"
                and present
                and CapabilityDetector.check_support(f)["supported"] is False
            ],
        }

    @classmethod
    def evaluate(
        cls, orig: SlideIR, recon: SlideIR, scale: float = 0.5
    ) -> "FidelityScore":
        """Evaluates multidimensional fidelity between an original and reconstructed slide."""
        from ..eval.fidelity import FidelityEvaluator
        return FidelityEvaluator.evaluate_slides(orig, recon, scale=scale)

    @classmethod
    def diff(cls, orig: SlideIR, recon: SlideIR) -> "FidelityDiffReport":
        """Computes the structural/stylistic delta between two slides."""
        from .fidelity_diff import FidelityDiffEngine
        return FidelityDiffEngine.compare_slides(orig, recon)

    @classmethod
    def report(
        cls, orig: SlideIR, recon: SlideIR, scale: float = 0.5
    ) -> "FidelityReport":
        """Builds the structured, machine-readable fidelity report."""
        from ..eval.fidelity import build_fidelity_report
        return build_fidelity_report(orig, recon, scale=scale)