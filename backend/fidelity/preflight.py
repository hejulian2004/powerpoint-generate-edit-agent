"""Export preflight: honest lossy/unsupported write-back reporting (PR6-hardening r2).

Production export must not silently degrade native OOXML features. Before rendering,
inspect the IR for features whose export is lossy (native table -> flattened group)
or unsupported, and surface structured warnings to the caller/API.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .capability import CapabilityDetector


class LossyWritebackError(ValueError):
    """Raised when an export would silently degrade features and was not allowed."""

    def __init__(self, preflight: "ExportPreflight"):
        self.preflight = preflight
        features = ", ".join(f["feature"] for f in preflight.lossy_features)
        super().__init__(
            f"Export would be lossy for: {features}. "
            "Pass allow_lossy=True to accept the degradation."
        )


@dataclass
class ExportPreflight:
    """Structured export preflight result."""

    lossy_features: List[Dict[str, str]] = field(default_factory=list)
    unsupported_features: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_lossy(self) -> bool:
        return bool(self.lossy_features)

    @property
    def has_unsupported(self) -> bool:
        return bool(self.unsupported_features)

    @property
    def clean(self) -> bool:
        return not self.has_lossy and not self.has_unsupported

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lossy_features": [dict(f) for f in self.lossy_features],
            "unsupported_features": list(self.unsupported_features),
            "warnings": list(self.warnings),
            "has_lossy": self.has_lossy,
            "has_unsupported": self.has_unsupported,
            "clean": self.clean,
        }


def evaluate_export_preflight(pres: Any) -> ExportPreflight:
    """Computes export degradation warnings for a PresentationIR."""
    detected = CapabilityDetector.detect_from_ir(pres)
    engine = CapabilityDetector.engine_capabilities()

    lossy: List[Dict[str, str]] = []
    unsupported: List[str] = []
    for feature in detected.present_features():
        verdict = engine.writeback_status(feature)
        if verdict["status"] == "lossy":
            lossy.append({"feature": feature, "reason": str(verdict["reason"])})
        elif verdict["status"] == "unsupported":
            unsupported.append(feature)

    warnings = list(detected.lossy_warnings()) + list(detected.unsupported_warnings())
    return ExportPreflight(
        lossy_features=lossy,
        unsupported_features=unsupported,
        warnings=warnings,
    )
