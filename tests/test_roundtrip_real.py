"""Phase 0.2 Baseline Verification: Full Real PPTX Roundtrip Tests.

Tests the full closed loop:
original.pptx -> import() -> PPT-IR -> export() -> compare()

Strictly verifies:
1. Slide count equivalence
2. Element count per slide equivalence
3. Text content / hash preservation
4. Image media assets MD5 hash preservation
5. Coordinate accuracy: position and size error < 2px
"""

import os
import hashlib
import tempfile
import pytest
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
from backend.ir.converter import PPTIRConverter
from backend.ir.svg_renderer import SVGRenderer
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder

DEMO_PPTX = "demo_input.pptx"
ANOMALY_PPTX = "output/AnomalyAgent_导师汇报_论文原图版/rebuild.pptx"


def _run_roundtrip_verification(input_pptx: str):
    assert os.path.exists(input_pptx), f"File not found: {input_pptx}"

    # 1. Parse original PPTX
    parser = PPTXParser(input_pptx)
    orig_pres = parser.parse()

    # Collect original text hashes and content
    orig_texts = []
    for s in orig_pres.slides:
        for el in s.elements:
            if hasattr(el, 'text') and el.text:
                orig_texts.append(el.text.content)
    orig_text_hash = hashlib.sha256("\n".join(orig_texts).encode("utf-8")).hexdigest()

    # Collect original image hashes
    orig_media_hashes = {
        name: hashlib.md5(content).hexdigest()
        for name, content in orig_pres.media_files.items()
    }

    # 2. Convert to PPT-IR
    pres_ir = PPTIRConverter.presentation_to_ir(orig_pres)

    # 3. Verify SVG Preview generation without errors
    for slide_ir in pres_ir.slides:
        svg_code = SVGRenderer.render_slide(slide_ir)
        assert "<svg" in svg_code
        assert "</svg>" in svg_code

    # 4. Reconstruct OOXML model from PPT-IR
    re_pres = PPTIRConverter.ir_to_presentation(pres_ir)

    # 5. Export to temporary PPTX file
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        out_pptx = tmp.name

    try:
        builder = PPTXBuilder()
        builder.build(re_pres, out_pptx)
        assert os.path.exists(out_pptx)
        assert os.path.getsize(out_pptx) > 0

        # 6. Re-parse the rebuilt PPTX
        re_parser = PPTXParser(out_pptx)
        re_parsed = re_parser.parse()

        # =============================================================
        # Strict Verification Assertions
        # =============================================================

        # 1. Slide count comparison
        assert len(re_parsed.slides) == len(orig_pres.slides), (
            f"Slide count mismatch: {len(re_parsed.slides)} != {len(orig_pres.slides)}"
        )

        # 2. Element count per slide
        for idx in range(len(orig_pres.slides)):
            orig_len = len(orig_pres.slides[idx].elements)
            re_len = len(re_parsed.slides[idx].elements)
            assert re_len == orig_len, (
                f"Slide {idx+1} element count mismatch: {re_len} != {orig_len}"
            )

        # 3. Text content & hash comparison
        re_texts = []
        for s in re_parsed.slides:
            for el in s.elements:
                if hasattr(el, 'text') and el.text:
                    re_texts.append(el.text.content)
        re_text_hash = hashlib.sha256("\n".join(re_texts).encode("utf-8")).hexdigest()
        assert orig_texts == re_texts, "Text content mismatch between original and rebuilt PPTX"
        assert orig_text_hash == re_text_hash, "Text SHA256 hash mismatch"

        # 4. Image assets MD5 comparison
        re_media_hashes = {
            name: hashlib.md5(content).hexdigest()
            for name, content in re_parsed.media_files.items()
        }
        for name, orig_hash in orig_media_hashes.items():
            assert name in re_media_hashes, f"Media asset '{name}' missing in exported PPTX"
            assert orig_hash == re_media_hashes[name], f"Media asset '{name}' MD5 hash mismatch"

        # 5. Coordinate error (< 2px threshold, 1px = 1/96 inch ≈ 0.0104 inch)
        # Threshold: 2px = 2.0 / 96.0 ≈ 0.02083 inches
        max_pixel_error = 0.0
        for s_idx in range(len(orig_pres.slides)):
            for e_idx in range(len(orig_pres.slides[s_idx].elements)):
                o_el = orig_pres.slides[s_idx].elements[e_idx]
                r_el = re_parsed.slides[s_idx].elements[e_idx]
                if hasattr(o_el, 'position') and hasattr(r_el, 'position'):
                    dx = abs(o_el.position.x - r_el.position.x) * 96.0
                    dy = abs(o_el.position.y - r_el.position.y) * 96.0
                    dw = abs(o_el.position.width - r_el.position.width) * 96.0
                    dh = abs(o_el.position.height - r_el.position.height) * 96.0
                    max_pixel_error = max(max_pixel_error, dx, dy, dw, dh)

        assert max_pixel_error < 2.0, (
            f"Coordinate error exceeds 2px: max error is {max_pixel_error:.3f} px"
        )

    finally:
        if os.path.exists(out_pptx):
            os.remove(out_pptx)


def test_roundtrip_demo_input():
    """Verify demo_input.pptx roundtrip reliability."""
    _run_roundtrip_verification(DEMO_PPTX)


def test_roundtrip_complex_multislide_deck():
    """Verify real-world 13-slide deck with images, shapes, text, and connectors."""
    if not os.path.exists(ANOMALY_PPTX):
        pytest.skip("Complex presentation deck not found")
    _run_roundtrip_verification(ANOMALY_PPTX)
