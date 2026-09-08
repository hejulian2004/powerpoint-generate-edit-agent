"""RepairAcceptancePolicy: guards fidelity repairs against per-dimension regression.

The composite FidelityScore can rise while an individual sub-dimension (geometry, text,
style, visual) regresses. This policy encodes the PR6.1 rule:

    after.total >= before.total
    AND no sub-dimension drops more than max_per_dimension_regression
    AND no sub-dimension falls below critical_floor

A repair is accepted only if all three conditions hold, otherwise it must be rolled back.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple

from .fidelity_score import FidelityScore


@dataclass
class RepairAcceptancePolicy:
    """Determines whether a fidelity repair may be accepted given before/after scores."""

    max_per_dimension_regression: float = 3.0
    critical_floor: float = 85.0
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
            if a < self.critical_floor:
                reasons.append(
                    f"{dim} fell below critical floor {self.critical_floor} ({b:.1f} -> {a:.1f})"
                )
            elif b - a > self.max_per_dimension_regression:
                reasons.append(
                    f"{dim} regressed more than {self.max_per_dimension_regression} pts "
                    f"({b:.1f} -> {a:.1f})"
                )

        return (len(reasons) == 0, reasons)
