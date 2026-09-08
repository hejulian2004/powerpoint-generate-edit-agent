"""Quantitative PPT Roundtrip Fidelity & Precision Suite (Task 4/6 Modular Test).

Validates:
1. Quantitative geometry drift bounds (< 0.05 inches / < 4.8 pixels).
2. Rich typography and style preservation (line spacing, space before/after, runs, fonts, borders).
"""

from pathlib import Path
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    GroupElementIR, FillStyle, BorderStyle, TextContentIR,
    ParagraphIR, RunIR, FontIR
)
from backend.ir import export_pptx, import_pptx
from pptx_agent_converter.validation import validate_pptx


def test_quantitative_geometry_drift_bounds(tmp_path: Path):
    """Verifies that coordinates across PPTX export and re-import drift by < 0.05 inches (4.8px)."""
    pres = PresentationIR(title="Quantitative Drift Benchmark")
    slide = SlideIR(id="slide_geom_bench", slide_num=1, title="Geometry Benchmark")

    # Standard shapes with known pixel coordinates (1280x720 canvas)
    # 1 inch = 96 px
    s1 = ShapeElementIR(
        id="s_rect",
        name="Benchmark Rect",
        shape_type="rect",
        x=100.0,
        y=150.0,
        width=300.0,
        height=180.0,
        style=dict(fill=FillStyle(type="solid", color="#2563EB"))
    )
    s2 = TextElementIR(
        id="s_txt",
        name="Benchmark Text",
        x=450.0,
        y=150.0,
        width=350.0,
        height=100.0,
        text_content=TextContentIR.from_plain_text("Quantitative Precision Text")
    )
    # Nested Group
    g_child1 = ShapeElementIR(
        id="gc1",
        shape_type="roundRect",
        x=850.0,
        y=150.0,
        width=160.0,
        height=90.0,
        style=dict(radius=8.0)
    )
    g_child2 = ShapeElementIR(
        id="gc2",
        shape_type="roundRect",
        x=1050.0,
        y=150.0,
        width=160.0,
        height=90.0,
        style=dict(radius=8.0)
    )
    group = GroupElementIR(
        id="bench_grp",
        name="Benchmark Group",
        x=850.0,
        y=150.0,
        width=360.0,
        height=90.0,
        children=[g_child1, g_child2]
    )

    slide.add_element(s1)
    slide.add_element(s2)
    slide.add_element(group)
    pres.slides.append(slide)

    out_file = tmp_path / "geom_drift_benchmark.pptx"
    export_pptx(pres, out_file)
    assert out_file.exists()

    re_pres = import_pptx(out_file)
    re_slide = re_pres.slides[0]

    # Map before elements by ID
    before_elements = {el.id: el for el in slide.all_elements(recursive=True)}
    after_elements = {el.id: el for el in re_slide.all_elements(recursive=True)}

    # Maximum permissible tolerance in pixels (0.05 inches * 96 px/in = 4.8 px)
    MAX_DRIFT_PX = 4.8

    for eid, el_before in before_elements.items():
        if eid not in after_elements:
            continue
        el_after = after_elements[eid]

        dx = abs(el_after.x - el_before.x)
        dy = abs(el_after.y - el_before.y)
        dw = abs(el_after.width - el_before.width)
        dh = abs(el_after.height - el_before.height)

        assert dx < MAX_DRIFT_PX, f"Element '{eid}' X drift {dx:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"
        assert dy < MAX_DRIFT_PX, f"Element '{eid}' Y drift {dy:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"
        assert dw < MAX_DRIFT_PX, f"Element '{eid}' Width drift {dw:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"
        assert dh < MAX_DRIFT_PX, f"Element '{eid}' Height drift {dh:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"


def test_rich_typography_and_style_preservation(tmp_path: Path):
    """Verifies paragraph line spacing, space before/after, runs, and border styles roundtrip."""
    pres = PresentationIR(title="Typography Fidelity")
    slide = SlideIR(id="slide_typo", slide_num=1)

    para = ParagraphIR(
        line_spacing=1.35,
        space_before=8.0,
        space_after=14.0,
        align="center",
        runs=[
            RunIR(text="Primary Title", font=FontIR(name="Georgia", size=24.0, bold=True, color="#1E3A8A")),
            RunIR(text=" Subtitle Note", font=FontIR(name="Arial", size=16.0, italic=True, color="#059669"))
        ]
    )
    txt_elem = TextElementIR(
        id="typo_elem",
        x=120.0,
        y=100.0,
        width=600.0,
        height=180.0,
        text_content=TextContentIR(paragraphs=[para]),
        style=dict(
            fill=FillStyle(type="solid", color="#F8FAFC"),
            border=BorderStyle(color="#CBD5E1", width=2.0, style="solid")
        )
    )
    slide.add_element(txt_elem)
    pres.slides.append(slide)

    out_file = tmp_path / "typo_roundtrip.pptx"
    export_pptx(pres, out_file)
    assert validate_pptx(out_file)["valid"] is True

    re_pres = import_pptx(out_file)
    matching_elements = [
        e for e in re_pres.slides[0].elements
        if getattr(e, "text_content", None) and "Primary Title" in e.text_content.plain_text
    ]
    assert len(matching_elements) == 1
    re_elem = matching_elements[0]
    assert re_elem.text_content is not None
    assert len(re_elem.text_content.paragraphs) >= 1

    re_para = re_elem.text_content.paragraphs[0]
    assert re_para.align == "center"
    assert abs(re_para.line_spacing - 1.35) < 0.15
    assert "Primary Title" in re_elem.text_content.plain_text
    assert "Subtitle Note" in re_elem.text_content.plain_text
