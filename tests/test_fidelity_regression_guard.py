"""FidelityRegressionGuard tests (PR6.1 Task 3).

The composite FidelityScore may rise while a sub-dimension regresses. The guard encodes:

    after.total >= before.total
    AND geometry drops <= 5 pts
    AND text (typography) drops <= 10 pts
    AND style drops <= 10 pts
    AND visual drops <= 10 pts
    AND no sub-dimension falls below the critical floor (85)
"""

import pytest

from backend.eval.fidelity import (
    FidelityRegressionGuard,
    FidelityDelta,
    DEFAULT_DIMENSION_LIMITS,
)
from backend.eval.fidelity.fidelity_score import FidelityScore


def _score(**overrides):
    base = dict(geometry=100.0, text=100.0, style=100.0, visual=100.0, total=100.0)
    base.update(overrides)
    return FidelityScore(**base)


def _guard(**overrides):
    limits = dict(DEFAULT_DIMENSION_LIMITS)
    limits.update(overrides)
    return FidelityRegressionGuard(dimension_limits=limits)


# =====================================================================
# Acceptance
# =====================================================================

def test_accepts_identical_scores():
    guard = FidelityRegressionGuard()
    before = _score()
    after = _score()
    accepted, reasons = guard.accepts(before, after)
    assert accepted is True
    assert reasons == []


def test_accepts_small_gain():
    guard = FidelityRegressionGuard()
    before = _score(geometry=92.0, text=90.0, style=95.0, visual=88.0, total=91.4)
    after = _score(geometry=94.0, text=92.0, style=95.0, visual=90.0, total=93.0)
    accepted, reasons = guard.accepts(before, after)
    assert accepted is True


def test_accepts_geometry_drop_within_limit():
    # geometry -4 pts (<= 5) while total rises -> accepted
    guard = FidelityRegressionGuard()
    before = _score(geometry=100.0, text=80.0, style=90.0, visual=90.0, total=91.0)
    after = _score(geometry=96.0, text=90.0, style=90.0, visual=90.0, total=92.4)
    accepted, reasons = guard.accepts(before, after)
    assert accepted is True


# =====================================================================
# Rejection
# =====================================================================

def test_rejects_total_regression():
    guard = FidelityRegressionGuard()
    before = _score(total=93.0)
    after = _score(geometry=99.0, text=99.0, style=99.0, visual=80.0, total=92.4)
    accepted, reasons = guard.accepts(before, after)
    assert accepted is False
    assert any("total" in r for r in reasons)


def test_rejects_geometry_drop_over_limit_even_if_total_rises():
    """Spec example: font +20 but layout -30 must be rejected."""
    guard = FidelityRegressionGuard()
    before = _score(geometry=100.0, text=80.0, style=80.0, visual=80.0, total=88.0)
    after = _score(geometry=70.0, text=100.0, style=100.0, visual=100.0, total=92.0)
    accepted, reasons = guard.accepts(before, after)
    assert accepted is False
    assert any("geometry" in r for r in reasons)


def test_rejects_typography_drop_over_limit():
    guard = FidelityRegressionGuard()
    before = _score(geometry=95.0, text=100.0, style=95.0, visual=95.0, total=96.0)
    after = _score(geometry=96.0, text=86.0, style=95.0, visual=95.0, total=93.6)
    # text dropped 100 -> 86 (> 10) but total rose? no: 96 -> 93.6 -> also total regression
    accepted, reasons = guard.accepts(before, after)
    assert accepted is False


def test_rejects_critical_floor_violation():
    guard = FidelityRegressionGuard()
    before = _score(geometry=100.0, total=95.0)
    after = _score(geometry=84.0, total=95.0)
    accepted, reasons = guard.accepts(before, after)
    assert accepted is False
    assert any("floor" in r for r in reasons)


# =====================================================================
# FidelityDelta
# =====================================================================

def test_fidelity_delta_reports_per_dimension_changes():
    before = _score(geometry=90.0, text=85.0, style=88.0, visual=92.0, total=89.2)
    after = _score(geometry=95.0, text=80.0, style=88.0, visual=92.0, total=89.0)
    delta = FidelityDelta(before=before, after=after)
    d = delta.deltas()
    assert d["geometry"] == 5.0
    assert d["text"] == -5.0
    assert d["style"] == 0.0


def test_analyze_uses_delta():
    guard = FidelityRegressionGuard()
    delta = FidelityDelta(before=_score(), after=_score(geometry=80.0, total=92.0))
    accepted, reasons = guard.analyze(delta)
    assert accepted is False
    assert any("geometry" in r for r in reasons)