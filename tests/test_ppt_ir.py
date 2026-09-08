"""Tests for PPT-IR models, bidirectional converter, SVG renderer, and patch history."""

import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, FillStyle, BorderStyle, ShadowStyle,
    FontIR, ParagraphIR, RunIR, TextContentIR
)
from backend.ir.converter import PPTIRConverter
from backend.ir.svg_renderer import SVGRenderer
from backend.ir.patch import HistoryManager
from pptx_agent_converter.model.slide import Slide, Presentation, DEFAULT_WIDTH, DEFAULT_HEIGHT
from pptx_agent_converter.model.shape import ShapeElement, ConnectorElement, Position
from pptx_agent_converter.model.style import Fill, Line, Shadow
from pptx_agent_converter.model.text import TextBlock, Paragraph, Run, Font


def test_ppt_ir_model_creation():
    slide = SlideIR(
        id="slide_01",
        slide_num=1,
        title="Test Slide",
        background=FillStyle(type="solid", color="#0F172A")
    )
    elem = ShapeElementIR(
        id="shape_1",
        shape_type="roundRect",
        x=100.0,
        y=150.0,
        width=300.0,
        height=120.0,
        style=dict(fill=FillStyle(type="solid", color="#3B82F6"), radius=0.1)
    )
    slide.add_element(elem)

    assert len(slide.elements) == 1
    assert slide.elements[0].id == "shape_1"
    assert slide.elements[0].x == 100.0


def test_svg_renderer():
    slide = SlideIR(
        id="slide_01",
        slide_num=1,
        background=FillStyle(type="solid", color="#FFFFFF")
    )
    shape = ShapeElementIR(
        id="shape_1",
        shape_type="roundRect",
        x=50.0,
        y=50.0,
        width=200.0,
        height=80.0,
        style=dict(
            fill=FillStyle(type="solid", color="#2563EB"),
            border=BorderStyle(color="#1D4ED8", width=2.0),
            radius=8.0
        ),
        text_content=TextContentIR.from_plain_text("Hello PPT-IR", font=FontIR(color="#FFFFFF", size=20.0))
    )
    connector = ConnectorElementIR(
        id="conn_1",
        start_x=250.0,
        start_y=90.0,
        end_x=450.0,
        end_y=90.0,
        arrow_end="triangle"
    )
    slide.add_element(shape)
    slide.add_element(connector)

    svg_output = SVGRenderer.render_slide(slide)
    assert "<svg" in svg_output
    assert "</svg>" in svg_output
    assert 'viewBox="0 0 1280 720"' in svg_output
    assert "Hello PPT-IR" in svg_output
    assert "marker-arrow-end" in svg_output


def test_bidirectional_conversion():
    # 1. Create native PPTX Slide
    orig_slide = Slide(
        slide_id=1,
        slide_num=1,
        elements=[
            ShapeElement(
                id="box1",
                shape_type="roundRect",
                position=Position(x=1.0, y=1.5, width=4.0, height=2.0),
                fill=Fill(type="solid", color="#3366FF"),
                line=Line(color="#000000", width=1.5),
                shadow=Shadow(enabled=True, blur=4.0),
                text=TextBlock(paragraphs=[
                    Paragraph(runs=[Run(text="Roundtrip Test", font=Font(name="Arial", size=18.0, color="#FFFFFF"))])
                ])
            ),
            ConnectorElement(
                id="c1",
                start=(5.0, 2.5),
                end=(8.0, 2.5),
                line=Line(color="#FF0000", width=2.0),
                arrow_end="triangle"
            )
        ]
    )
    orig_pres = Presentation(name="Roundtrip Pres", slides=[orig_slide])

    # 2. Convert to PPT-IR
    pres_ir = PPTIRConverter.presentation_to_ir(orig_pres)
    assert len(pres_ir.slides) == 1
    slide_ir = pres_ir.slides[0]
    assert len(slide_ir.elements) == 2

    box_ir = slide_ir.elements[0]
    assert isinstance(box_ir, ShapeElementIR)
    # 1.0 inch * 96 DPI = 96 px
    assert pytest.approx(box_ir.x, 0.1) == 96.0
    assert pytest.approx(box_ir.width, 0.1) == 384.0

    conn_ir = slide_ir.elements[1]
    assert isinstance(conn_ir, ConnectorElementIR)
    assert pytest.approx(conn_ir.start_x, 0.1) == 480.0

    # 3. Convert back to PPTX Model
    restored_pres = PPTIRConverter.ir_to_presentation(pres_ir)
    assert len(restored_pres.slides) == 1
    restored_slide = restored_pres.slides[0]
    assert len(restored_slide.elements) == 2

    restored_box = restored_slide.elements[0]
    assert pytest.approx(restored_box.position.x, 0.05) == 1.0
    assert pytest.approx(restored_box.position.width, 0.05) == 4.0
    assert restored_box.text.paragraphs[0].runs[0].text == "Roundtrip Test"


def test_history_manager_undo_redo():
    history = HistoryManager()
    pres = PresentationIR(title="History Test")
    slide = SlideIR(id="s1", slide_num=1)
    pres.slides.append(slide)

    elem = ShapeElementIR(id="el_1", shape_type="rectangle", x=10.0, y=10.0, width=50.0, height=50.0)
    slide.add_element(elem)

    # Record element creation
    history.record(
        action="add_element",
        description="Add box",
        slide_id="s1",
        element_id="el_1",
        after=elem.model_dump()
    )

    # Undo
    assert history.can_undo()
    history.undo(pres)
    assert len(slide.elements) == 0

    # Redo
    assert history.can_redo()
    history.redo(pres)
    assert len(slide.elements) == 1
    assert slide.elements[0].id == "el_1"
