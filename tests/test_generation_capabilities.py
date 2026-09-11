"""Phase 6 / Finding 9: generation capabilities must be export-safe."""

from backend.agent.generation_capabilities import (
    EXPORT_SAFE_CAPABILITIES,
    GENERATION_CAPABILITIES,
)
from backend.fidelity.capability import (
    DETECT_ONLY_FEATURES,
    LOSSY_WRITEBACK_FEATURES,
    SUPPORTED_FEATURES,
)


def test_generation_capabilities_subset_of_export_safe():
    assert GENERATION_CAPABILITIES <= EXPORT_SAFE_CAPABILITIES


def test_export_safe_is_editable_minus_lossy():
    assert EXPORT_SAFE_CAPABILITIES == frozenset(SUPPORTED_FEATURES) - frozenset(
        LOSSY_WRITEBACK_FEATURES
    )
    assert not (EXPORT_SAFE_CAPABILITIES & set(LOSSY_WRITEBACK_FEATURES))


def test_generation_never_includes_detect_only_or_lossy_features():
    assert not (GENERATION_CAPABILITIES & set(DETECT_ONLY_FEATURES))
    assert not (GENERATION_CAPABILITIES & set(LOSSY_WRITEBACK_FEATURES))


def test_table_is_not_generation_capable():
    assert "table" not in GENERATION_CAPABILITIES
    assert "table" in LOSSY_WRITEBACK_FEATURES
