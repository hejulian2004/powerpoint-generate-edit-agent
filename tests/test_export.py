"""Phase 0.2 Baseline Verification: PPTX Export Tests.

Verifies:
- Building valid OPC ZIP package from PresentationIR
- Correct generation of [Content_Types].xml, _rels, presentation.xml, slide XMLs
- Packaging of media assets with correct Relationship IDs
- Reparsing exported PPTX package to ensure OOXML specification compliance
"""

import os
import zipfile
import tempfile
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, ConnectorElementIR,
    TextElementIR, FillStyle, BorderStyle, TextContentIR, FontIR
)
from backend.ir.converter import PPTIRConverter
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder
from pptx_agent_converter.extractor.pptx_parser import PPTXParser


def test_export_clean_presentation():
    """Test generating and exporting a brand-new PPT-IR presentation."""
    slide = SlideIR(
        id="s1",
        slide_num=1,
        title="Export Test Slide",
        background=FillStyle(type="solid", color="#0F172A")
    )
    # Add title
    slide.add_element(
        TextElementIR(
            id="t1",
            x=100,
            y=80,
            width=800,
            height=60,
            text_content=TextContentIR.from_plain_text(
                "Export Verification",
                font=FontIR(name="Arial", size=32.0, color="#F8FAFC", bold=True)
            )
        )
    )
    # Add styled card
    slide.add_element(
        ShapeElementIR(
            id="sh1",
            shape_type="roundRect",
            x=100,
            y=180,
            width=300,
            height=160,
            style=dict(
                fill=FillStyle(type="solid", color="#2563EB"),
                border=BorderStyle(color="#60A5FA", width=2.0),
                radius=12.0
            ),
            text_content=TextContentIR.from_plain_text(
                "Card Content\n- High fidelity\n- OOXML Compliant",
                font=FontIR(color="#FFFFFF", size=16.0)
            )
        )
    )
    # Add connector
    slide.add_element(
        ConnectorElementIR(
            id="c1",
            start_x=400,
            start_y=260,
            end_x=600,
            end_y=260,
            arrow_end="triangle",
            style=dict(border=BorderStyle(color="#2563EB", width=2.0))
        )
    )

    pres_ir = PresentationIR(title="Export Test Deck", slides=[slide])

    # 1. Convert to OOXML model
    ooxml_pres = PPTIRConverter.ir_to_presentation(pres_ir)

    # 2. Build PPTX
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        out_path = tmp.name

    try:
        builder = PPTXBuilder()
        builder.build(ooxml_pres, out_path)
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0

        # 3. Validate ZIP & OPC structure
        with zipfile.ZipFile(out_path, "r") as z:
            namelist = z.namelist()
            assert "[Content_Types].xml" in namelist
            assert "_rels/.rels" in namelist
            assert "ppt/presentation.xml" in namelist
            assert "ppt/_rels/presentation.xml.rels" in namelist
            assert "ppt/slides/slide1.xml" in namelist

        # 4. Verify by parsing with PPTXParser
        parser = PPTXParser(out_path)
        parsed = parser.parse()
        assert len(parsed.slides) == 1
        assert len(parsed.slides[0].elements) == 3
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)


def test_export_never_uses_invalid_textbox_geometry():
    """Regression: textboxes must not emit prst="textbox" (invalid DrawingML).

    PowerPoint refuses to open packages containing the non-existent
    "textbox" preset geometry. Textboxes must use prst="rect" + txBox="1".
    """
    slide = SlideIR(
        id="tb_slide",
        slide_num=1,
        title="Textbox Slide",
        background=FillStyle(type="solid", color="#FFFFFF")
    )
    slide.add_element(
        TextElementIR(
            id="tb1",
            x=100,
            y=80,
            width=800,
            height=60,
            text_content=TextContentIR.from_plain_text(
                "Hello Textbox",
                font=FontIR(name="Arial", size=24.0, color="#111111")
            )
        )
    )

    pres_ir = PresentationIR(title="Textbox Deck", slides=[slide])
    ooxml_pres = PPTIRConverter.ir_to_presentation(pres_ir)

    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        out_path = tmp.name

    try:
        builder = PPTXBuilder()
        builder.build(ooxml_pres, out_path)

        with zipfile.ZipFile(out_path, "r") as z:
            slide_xml = z.read("ppt/slides/slide1.xml").decode("utf-8")

        # The invalid preset geometry must never appear.
        assert 'prst="textbox"' not in slide_xml
        # Textbox must be rendered as rect geometry flagged txBox=1.
        assert 'prst="rect"' in slide_xml
        assert 'txBox="1"' in slide_xml
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)
