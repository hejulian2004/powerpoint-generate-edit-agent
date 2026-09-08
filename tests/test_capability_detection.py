"""OOXML Capability Matrix & Detection tests (PR6.1 Task 1).

Verifies:
- CapabilityDetector flags which OOXML features a real deck uses.
- Parser surfaces `PresentationIR.capabilities` + capability warnings in metadata.
- check_support returns structured verdicts (no silent mis-parse of unsupported features).
"""

import os
from pathlib import Path
import pytest

from backend.fidelity.capability import (
    FidelityCapability,
    CapabilityDetector,
    SUPPORTED_FEATURES,
    DETECT_ONLY_FEATURES,
)
from backend.fidelity import OOXMLParser

REAL_WORLD_DIR = Path(__file__).resolve().parent / "assets" / "real_world"

# Inputs required by the PR6.1 acceptance criteria: SmartArt / chart / theme decks.
_REQUIRED = ["SmartArt.pptx", "chart-slide-bg.pptx", "themes.pptx"]


def _require_deck(name: str) -> Path:
    path = REAL_WORLD_DIR / name
    if not path.exists():
        pytest.skip(f"Corpus not fetched: {path}")
    return path


# =====================================================================
# FidelityCapability structure
# =====================================================================

def test_engine_supported_matrix_defaults():
    cap = FidelityCapability.engine_supported()
    assert cap.shape is True
    assert cap.text is True
    assert cap.image is True
    assert cap.group is True
    assert cap.table is True
    # Detect-only by default
    assert cap.chart is False
    assert cap.smartart is False
    assert cap.animation is False
    assert cap.master_slide is False


def test_unsupported_present_reports_detect_only_features():
    cap = FidelityCapability(shape=True, chart=True, smartart=True, animation=False)
    unsupported = cap.unsupported_present()
    assert "chart" in unsupported
    assert "smartart" in unsupported
    assert "shape" not in unsupported
    warnings = cap.unsupported_warnings()
    assert any("chart" in w for w in warnings)


def test_check_support_verdicts():
    assert CapabilityDetector.check_support("text") == {"supported": True, "reason": ""}
    assert CapabilityDetector.check_support("table")["supported"] is True
    chart = CapabilityDetector.check_support("chart")
    assert chart == {"supported": False, "reason": "unsupported_feature"}
    smartart = CapabilityDetector.check_support("smartart")
    assert smartart == {"supported": False, "reason": "unsupported_feature"}
    assert CapabilityDetector.check_support("nonsense") == {
        "supported": False, "reason": "unknown_feature"}


def test_support_feature_sets_cover_all_fields():
    fields = set(FidelityCapability().to_dict().keys())
    assert SUPPORTED_FEATURES | DETECT_ONLY_FEATURES == fields


# =====================================================================
# Detection over real decks
# =====================================================================

@pytest.mark.real_world
def test_smartart_deck_detected():
    deck = _require_deck("SmartArt.pptx")
    cap = CapabilityDetector.detect(deck)
    assert cap.smartart is True
    assert cap.chart is False


@pytest.mark.real_world
def test_chart_deck_detected():
    deck = _require_deck("chart-slide-bg.pptx")
    cap = CapabilityDetector.detect(deck)
    assert cap.chart is True


@pytest.mark.real_world
def test_theme_deck_detected():
    deck = _require_deck("themes.pptx")
    cap = CapabilityDetector.detect(deck)
    assert cap.theme is True


@pytest.mark.real_world
def test_backgrounds_deck_has_no_unsupported_features():
    deck = _require_deck("backgrounds.pptx")
    cap = CapabilityDetector.detect(deck)
    # master_slide is structural (present in virtually every PPTX) and is not a warning;
    # assert the actionable unsupported features (chart/smartart/animation) are absent.
    assert cap.chart is False
    assert cap.smartart is False
    assert cap.animation is False
    assert cap.unsupported_warnings() == []


# =====================================================================
# Parser wiring: PresentationIR.capabilities + warnings
# =====================================================================

@pytest.mark.real_world
def test_parser_populates_capabilities_and_warnings():
    deck = _require_deck("SmartArt.pptx")
    pres = OOXMLParser(deck).parse()
    assert pres.capabilities.get("smartart") is True
    assert pres.capabilities.get("shape") is True
    warnings = pres.metadata.get("capability_warnings", [])
    assert any("smartart" in w for w in warnings)


@pytest.mark.real_world
def test_parser_surfaces_capability_warnings_in_metadata():
    deck = _require_deck("chart-slide-bg.pptx")
    pres = OOXMLParser(deck).parse()
    assert pres.capabilities.get("chart") is True
    assert any("chart" in w for w in pres.metadata.get("parser_warnings", []))