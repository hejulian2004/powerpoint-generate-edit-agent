"""FidelityRegressionGuard: per-metric fidelity regression guard for repairs (PR6.1).

The composite FidelityScore can rise while an individual sub-dimension regresses (e.g. a
repair lifts typography +20 but degrades geometry -30). This guard encodes the rule:

    after.total >= before.total
    AND no sub-dimension regresses more than its per-metric limit
        geometry  <= 5 pts
        text      <= 10 pts
        style     <= 10 pts
        visual    <= 10 pts
    AND no sub-dimension falls below critical_floor (85 pts)

A repair is accepted only if all conditions hold, otherwise it must be rolled back.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .fidelity_score import FidelityScore

# Per-metric regression limits (points) per FidelityScore sub-dimension.
DEFAULT_DIMENSION_LIMITS: Dict[str, float] = {
    "geometry": 5.0,
    "text": 10.0,
    "style": 10.0,
    "visual": 10.0,
}

CRITICAL_FLOOR: float = 85.0


@dataclass
class FidelityDelta:
    """Before/after snapshot of a fidelity evaluation for regression analysis."""

    before: FidelityScore
    after: FidelityScore

    def deltas(self) -> Dict[str, float]:
        """Per-dimension before->after change (positive = improvement)."""
        return {
            dim: round(getattr(self.after, dim) - getattr(self.before, dim), 1)
            for dim in ("geometry", "text", "style", "visual", "total")
        }


@dataclass
class FidelityRegressionGuard:
    """Determines whether a fidelity repair may be accepted given before/after scores."""

    dimension_limits: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_DIMENSION_LIMITS)
    )
    critical_floor: float = CRITICAL_FLOOR
    _dimensions: Tuple[str, ...] = ("geometry", "text", "style", "visual")

    def accepts(self, before: FidelityScore, after: FidelityScore) -> Tuple[bool, List[str]]:
        """Returns (accepted, reasons). reasons is empty when accepted."""
        reasons: List[str] = []

        if after.total < before.total:
            reasons.append(
                f"composite total regressed ({before.total:.1f} -> {after.total:.1f})"
            )

        for dim in self._dimensions:
            b = getattr(before, dim)
            a = getattr(after, dim)
            limit = self.dimension_limits.get(dim, 5.0)
            if a < self.critical_floor:
                reasons.append(
                    f"{dim} fell below critical floor {self.critical_floor} ({b:.1f} -> {a:.1f})"
                )
            elif b - a > limit:
                reasons.append(
                    f"{dim} regressed more than {limit} pts ({b:.1f} -> {a:.1f})"
                )

        return (len(reasons) == 0, reasons)

    def analyze(self, delta: FidelityDelta) -> Tuple[bool, List[str]]:
        return self.accepts(delta.before, delta.after)