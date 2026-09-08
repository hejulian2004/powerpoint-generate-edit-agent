"""Minimal end-to-end regression gate for PPTX -> PPT-IR -> PPTX roundtrip.

Verifies:
1. Output file exists
2. Output PowerPoint package is a valid zip archive
3. presentation.xml exists and is well-formed
4. Slide count is preserved
5. Text content is preserved
"""

import os
from pathlib import Path
import pytest
from pptx_agent_converter.validation import validate_pptx
from backend.ir import import_pptx, export_pptx, ConversionReport, PPTIRConverter
from pptx_agent_converter.extractor.pptx_parser import PPTXParser


def test_demo_pptx_roundtrip(tmp_path: Path):
    """Verify minimal end-to-end roundtrip pipeline regression gate on demo_input.pptx."""
    source = Path("demo_input.pptx")
    assert source.exists(), "demo_input.pptx fixture must exist in project root"

    # 1. PPTX -> OOXML Extractor -> PPT-IR
    ir = import_pptx(source)
    assert ir is not None
    assert len(ir.slides) > 0

    # Collect source plain texts
    source_texts = []
    for s in ir.slides:
        for el in s.elements:
            if hasattr(el, "text_content") and el.text_content and el.text_content.plain_text:
                source_texts.append(el.text_content.plain_text.strip())

    # 2. PPT-IR -> OOXML Renderer -> output.pptx
    output_path = tmp_path / "roundtrip_output.pptx"
    output = export_pptx(ir, output_path)

    # 3. Verify output file existence
    assert output.exists()
    assert output.stat().st_size > 0

    # 4. Validate output OOXML package structure
    validation = validate_pptx(output)
    assert validation["valid"] is True, f"Validation failed with errors: {validation['errors']}"
    assert validation["slides"] == len(ir.slides)
    assert len(validation["errors"]) == 0

    # 5. Re-import and verify text content preservation
    re_ir = import_pptx(output)
    assert len(re_ir.slides) == len(ir.slides)

    re_texts = []
    for s in re_ir.slides:
        for el in s.elements:
            if hasattr(el, "text_content") and el.text_content and el.text_content.plain_text:
                re_texts.append(el.text_content.plain_text.strip())

    for txt in source_texts:
        if txt:
            # Check that source text snippet is present in re-imported elements
            assert any(txt in rt for rt in re_texts), f"Text snippet '{txt}' was lost during roundtrip"


@pytest.mark.parametrize("fixture_name", [
    "simple.pptx",
    "academic.pptx",
    "diagram.pptx",
    "image-heavy.pptx"
])
def test_fixtures_roundtrip(tmp_path: Path, fixture_name: str):
    """Verify end-to-end roundtrip pipeline across diverse real-world fixtures (academic paper, diagram, image)."""
    source = Path("tests/fixtures") / fixture_name
    assert source.exists(), f"Fixture {fixture_name} must exist in tests/fixtures/"

    # 1. PPTX -> OOXML Extractor -> PPT-IR with conversion report
    parser = PPTXParser(str(source))
    pres = parser.parse()
    ir, in_report = PPTIRConverter.convert_presentation_with_report(pres)
    assert ir is not None
    assert len(ir.slides) == len(pres.slides)
    assert in_report.converted_elements > 0

    # Collect source plain texts
    source_texts = []
    for s in ir.slides:
        for el in s.elements:
            if hasattr(el, "text_content") and el.text_content and el.text_content.plain_text:
                for line in el.text_content.plain_text.splitlines():
                    trimmed = line.strip()
                    if len(trimmed) > 5:
                        source_texts.append(trimmed)

    # 2. PPT-IR -> OOXML Renderer -> output.pptx
    output_path = tmp_path / f"roundtrip_{fixture_name}"
    output = export_pptx(ir, output_path)

    # 3. Verify output file existence & zip archive integrity
    assert output.exists()
    assert output.stat().st_size > 0

    validation = validate_pptx(output)
    assert validation["valid"] is True, f"Validation failed for {fixture_name}: {validation['errors']}"
    assert validation["slides"] == len(ir.slides)
    assert len(validation["errors"]) == 0

    # 4. Re-import and verify slide count & text preservation
    re_ir = import_pptx(output)
    assert len(re_ir.slides) == len(ir.slides)

    re_texts = []
    for s in re_ir.slides:
        for el in s.elements:
            if hasattr(el, "text_content") and el.text_content and el.text_content.plain_text:
                re_texts.append(el.text_content.plain_text.strip())

    re_corpus = "\n".join(re_texts)
    for txt in source_texts:
        assert txt in re_corpus, f"Text snippet '{txt}' was lost during roundtrip of {fixture_name}"


def test_validation_utility_edge_cases(tmp_path: Path):
    """Verify validate_pptx handles invalid, missing, and empty files gracefully."""
    # 1. Non-existent file
    missing = tmp_path / "does_not_exist.pptx"
    res1 = validate_pptx(missing)
    assert res1["valid"] is False
    assert any("not found" in err.lower() for err in res1["errors"])

    # 2. Empty file (0 bytes)
    empty = tmp_path / "empty.pptx"
    empty.touch()
    res2 = validate_pptx(empty)
    assert res2["valid"] is False
    assert any("0 bytes" in err.lower() or "empty" in err.lower() for err in res2["errors"])

    # 3. Corrupt file (not a zip)
    corrupt = tmp_path / "corrupt.pptx"
    corrupt.write_bytes(b"NOT_A_ZIP_HEADER_CORRUPTION_DATA")
    res3 = validate_pptx(corrupt)
    assert res3["valid"] is False
    assert any("not a valid zip" in err.lower() for err in res3["errors"])


def test_conversion_report_tracking():
    """Verify ConversionReport records converted items, skipped items, and warnings without silent failure."""
    source = Path("demo_input.pptx")
    parser = PPTXParser(str(source))
    pres = parser.parse()

    # Convert with report
    ir, report = PPTIRConverter.convert_presentation_with_report(pres)
    assert isinstance(report, ConversionReport)
    assert report.converted_elements > 0
    assert isinstance(report.warnings, list)
    rep_dict = report.to_dict()
    assert "converted_elements" in rep_dict
    assert "skipped_elements" in rep_dict
    assert "warnings" in rep_dict

    # Verify critical corruption throws
    with pytest.raises(ValueError, match="Critical corruption"):
        PPTIRConverter.presentation_to_ir(None)


def test_conversion_report_no_double_counting_in_groups():
    """Verify ConversionReport counts leaf elements once without duplicate group container counting."""
    from pptx_agent_converter.model.slide import Slide, SlideSize, Presentation
    from pptx_agent_converter.model.shape import ShapeElement, GroupElement, Position

    s1 = ShapeElement(id="s1", name="Standalone Shape", position=Position(x=1, y=1, width=2, height=1))
    child1 = ShapeElement(id="c1", name="Group Child 1", position=Position(x=1, y=3, width=2, height=1))
    child2 = ShapeElement(id="c2", name="Group Child 2", position=Position(x=3, y=3, width=2, height=1))
    grp = GroupElement(id="g1", name="Group Container", position=Position(x=1, y=3, width=4, height=1), elements=[child1, child2])
    unsupported = ShapeElement(id="unsupp", name="SmartArt Node", shape_type="smartArt", position=Position(x=5, y=5, width=2, height=2))

    slide = Slide(slide_id=1, slide_num=1, elements=[s1, grp, unsupported])
    pres = Presentation(name="GroupTest", size=SlideSize(width=13.333, height=7.5), slides=[slide])

    ir, report = PPTIRConverter.convert_presentation_with_report(pres)

    # In Slide IR v2, hierarchical groups are preserved (s1, grp), with 3 leaf shapes
    assert len(ir.slides[0].elements) == 2
    assert len(ir.slides[0].leaf_elements()) == 3
    assert len(ir.slides[0].all_elements()) == 4
    # converted_elements must be exactly 3, not 4 (outer group must not be double counted)
    assert report.converted_elements == 3, f"Expected 3 converted elements, got {report.converted_elements}"
    # skipped_elements must be exactly 1 for the smartArt node
    assert report.skipped_elements == 1
    assert any("smartArt" in w for w in report.warnings)

    # Reverse direction: PPT-IR -> OOXML Model
    ooxml_pres, rev_report = PPTIRConverter.ir_to_presentation_with_report(ir)
    assert len(ooxml_pres.slides[0].elements) == 2
    assert rev_report.converted_elements == 3
    assert rev_report.skipped_elements == 0
