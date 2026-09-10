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
    EngineCapabilities,
    DetectedFeatures,
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
# EngineCapabilities (static support matrix) vs DetectedFeatures (presence)
# =====================================================================

def test_engine_capabilities_support_matrix():
    engine = EngineCapabilities()
    # Editable features
    assert engine.supports_edit("shape") is True
    assert engine.supports_edit("text") is True
    assert engine.supports_edit("image") is True
    assert engine.supports_edit("group") is True
    assert engine.supports_edit("table") is True
    assert engine.supports_edit("theme") is True
    # Detect-only features are not editable
    assert engine.supports_edit("chart") is False
    assert engine.supports_edit("smartart") is False
    assert engine.supports_edit("animation") is False
    assert engine.supports_edit("master_slide") is False
    # Table write-back is declared lossy
    assert engine.writeback_status("table") == {
        "status": "lossy", "lossless": False, "reason": "flattened_to_group"
    }


def test_detected_features_default_to_absent():
    """Presence defaults MUST be False: an unparsed/empty deck contains nothing."""
    detected = DetectedFeatures()
    assert detected.present_features() == []
    assert detected.table is False
    assert detected.lossy_warnings() == []
    assert detected.unsupported_present() == []


def test_unsupported_present_reports_detect_only_features():
    cap = DetectedFeatures(shape=True, chart=True, smartart=True, animation=False)
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


def test_check_writeback_tri_state():
    assert CapabilityDetector.check_writeback("table") == {
        "status": "lossy", "lossless": False, "reason": "flattened_to_group"
    }
    assert CapabilityDetector.check_writeback("text") == {
        "status": "lossless", "lossless": True, "reason": ""
    }
    for detect_only in ["chart", "smartart", "animation", "master_slide"]:
        verdict = CapabilityDetector.check_writeback(detect_only)
        assert verdict["status"] == "unsupported"
        assert verdict["lossless"] is False
        assert verdict["reason"] == "unsupported_feature"
    unknown = CapabilityDetector.check_writeback("smartart_v2")
    assert unknown["status"] == "unsupported"
    assert unknown["lossless"] is False
    assert unknown["reason"] == "unknown_feature"


def test_support_feature_sets_cover_all_fields():
    fields = set(DetectedFeatures().to_dict().keys())
    assert SUPPORTED_FEATURES | DETECT_ONLY_FEATURES == fields


def _minimal_pptx(slide_xml: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", slide_xml)
    return buf.getvalue()


def test_zip_without_table_reports_table_false_and_no_lossy_warning():
    """Regression: defaults must not fabricate presence for absent features."""
    pptx = _minimal_pptx(
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld/></p:sld>'
    )
    cap = CapabilityDetector.detect(pptx)
    assert cap.table is False
    assert cap.lossy_warnings() == []
    assert "table" not in cap.present_features()


def test_zip_with_table_reports_table_true_and_lossy_warning():
    pptx = _minimal_pptx(
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:cSld><a:tbl/></p:cSld></p:sld>'
    )
    cap = CapabilityDetector.detect(pptx)
    assert cap.table is True
    assert any("table" in w and "lossy" in w for w in cap.lossy_warnings())


def test_detect_from_ir_merges_without_poisoning_absent_features():
    from backend.ir.models import PresentationIR, SlideIR

    pres = PresentationIR(title="No Table Deck")
    slide = SlideIR(id="s1", slide_num=1)
    pres.slides.append(slide)
    cap = CapabilityDetector.detect_from_ir(pres)
    assert cap.table is False
    assert cap.shape is False
    assert cap.lossy_warnings() == []


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
    # Presence is honest: this deck's slide contains only a detect-only SmartArt
    # graphic, so the engine must NOT claim editable shape/table content exists.
    assert pres.capabilities.get("shape") is False
    assert pres.capabilities.get("table") is False
    warnings = pres.metadata.get("capability_warnings", [])
    assert any("smartart" in w for w in warnings)


@pytest.mark.real_world
def test_parser_surfaces_capability_warnings_in_metadata():
    deck = _require_deck("chart-slide-bg.pptx")
    pres = OOXMLParser(deck).parse()
    assert pres.capabilities.get("chart") is True
    assert any("chart" in w for w in pres.metadata.get("parser_warnings", []))