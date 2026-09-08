"""Phase 0.2 Baseline Verification: PPTX Import Tests.

Verifies:
- Accurate extraction of presentation dimensions and themes
- Parsing of slides, shapes, text boxes, connectors, and images
- PPT-IR representation fidelity (1280x720 baseline)
"""

import os
import pytest
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
from backend.ir.converter import PPTIRConverter
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR,
    ConnectorElementIR, ImageElementIR, TextElementIR
)

DEMO_PPTX = "demo_input.pptx"
ANOMALY_PPTX = "output/AnomalyAgent_导师汇报_论文原图版/rebuild.pptx"


def test_import_demo_pptx():
    """Test importing standard demo presentation."""
    assert os.path.exists(DEMO_PPTX), f"Missing {DEMO_PPTX}"
    
    # 1. OOXML parser
    parser = PPTXParser(DEMO_PPTX)
    pres = parser.parse()
    assert len(pres.slides) == 1
    assert pres.size.width > 0
    assert pres.size.height > 0
    
    slide = pres.slides[0]
    assert len(slide.elements) == 3

    # 2. Conversion to PPT-IR
    pres_ir = PPTIRConverter.presentation_to_ir(pres)
    assert isinstance(pres_ir, PresentationIR)
    assert len(pres_ir.slides) == 1
    assert pres_ir.width == 1280
    assert pres_ir.height == 720

    slide_ir = pres_ir.slides[0]
    assert len(slide_ir.elements) == 3

    # Verify element types and content
    shapes = [e for e in slide_ir.elements if isinstance(e, ShapeElementIR)]
    conns = [e for e in slide_ir.elements if isinstance(e, ConnectorElementIR)]
    assert len(shapes) == 2
    assert len(conns) == 1

    # Verify text extracted
    texts = [e.text_content.plain_text for e in shapes if e.text_content]
    assert "Image Generation" in texts
    assert "Model Training" in texts


def test_import_complex_presentation():
    """Test importing 13-slide presentation with media images and connectors."""
    if not os.path.exists(ANOMALY_PPTX):
        pytest.skip("Anomaly presentation not present")

    parser = PPTXParser(ANOMALY_PPTX)
    pres = parser.parse()
    assert len(pres.slides) == 13
    assert len(pres.media_files) >= 10

    pres_ir = PPTIRConverter.presentation_to_ir(pres)
    assert len(pres_ir.slides) == 13
    assert len(pres_ir.assets) >= 10

    total_elements = sum(len(s.elements) for s in pres_ir.slides)
    assert total_elements > 300

    # Ensure all slides are 1280x720
    for s in pres_ir.slides:
        assert s.width == 1280
        assert s.height == 720
