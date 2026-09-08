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
