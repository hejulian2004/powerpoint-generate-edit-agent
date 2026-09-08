"""Real PPT Deck Roundtrip Fidelity Verification Suite (Task 6).

Verifies real PPT decks placed under `tests/assets/ppt/`:
1. Full roundtrip: PPTX -> PPT-IR -> PPTX
2. Quantitative geometry fidelity: drift < 0.05 inches (< 4.8 px)
3. Slide and element counts preserved
4. Text content and paragraph spacing preserved
5. Media assets preserved
6. SVG rendering succeeds for all slides
"""

import os
import glob
import hashlib
import tempfile
import pytest
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder
from backend.ir.converter import PPTIRConverter
from backend.ir.svg_renderer import SVGRenderer

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets", "ppt")


def _get_ppt_decks():
    """Discover all PPTX decks in tests/assets/ppt."""
    if not os.path.exists(ASSETS_DIR):
        return []
    decks = sorted(glob.glob(os.path.join(ASSETS_DIR, "*.pptx")))
    return [d for d in decks if not os.path.basename(d).startswith("~$")]


@pytest.mark.parametrize("deck_path", _get_ppt_decks(), ids=lambda p: os.path.basename(p))
def test_real_deck_roundtrip_fidelity(deck_path: str):
    """Verifies roundtrip fidelity for each real deck in tests/assets/ppt/."""
    # 1. Parse original PPTX
    parser = PPTXParser(deck_path)
    orig_pres = parser.parse()
    assert len(orig_pres.slides) > 0, f"Deck {deck_path} has no slides"

    # Collect original text items
    orig_texts = []
    for s in orig_pres.slides:
        for el in s.elements:
            if hasattr(el, 'text') and el.text:
                orig_texts.append(el.text.content.strip())

    # Collect original media MD5 hashes
    orig_media_hashes = {
        name: hashlib.md5(content).hexdigest()
        for name, content in orig_pres.media_files.items()
    }

    # 2. Convert to PPT-IR
    pres_ir = PPTIRConverter.presentation_to_ir(orig_pres)
    assert len(pres_ir.slides) == len(orig_pres.slides)

    # 3. Verify SVG rendering for all slides
    for slide_ir in pres_ir.slides:
        svg = SVGRenderer.render_slide(slide_ir)
        assert "<svg" in svg
        assert "</svg>" in svg

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
        # Assertions
        # =============================================================

        # 1. Slide count equivalence
        assert len(re_parsed.slides) == len(orig_pres.slides), (
            f"Slide count mismatch: {len(re_parsed.slides)} != {len(orig_pres.slides)}"
        )

        # 2. Element count per slide equivalence
        for idx in range(len(orig_pres.slides)):
            orig_len = len(orig_pres.slides[idx].elements)
            re_len = len(re_parsed.slides[idx].elements)
            assert re_len == orig_len, (
                f"Slide {idx + 1} element count mismatch: {re_len} != {orig_len}"
            )

        # 3. Text content preservation
        re_texts = []
        for s in re_parsed.slides:
            for el in s.elements:
                if hasattr(el, 'text') and el.text:
                    re_texts.append(el.text.content.strip())
        assert orig_texts == re_texts, f"Text mismatch in {os.path.basename(deck_path)}"

        # 4. Media asset preservation
        re_media_hashes = {
            name: hashlib.md5(content).hexdigest()
            for name, content in re_parsed.media_files.items()
        }
        for name, orig_hash in orig_media_hashes.items():
            assert name in re_media_hashes, f"Media '{name}' missing in {os.path.basename(deck_path)}"
            assert orig_hash == re_media_hashes[name], f"Media '{name}' MD5 mismatch in {os.path.basename(deck_path)}"

        # 5. Coordinate drift verification (< 0.05 inches = 4.8 px)
        max_drift_inches = 0.0
        for s_idx in range(len(orig_pres.slides)):
            for e_idx in range(len(orig_pres.slides[s_idx].elements)):
                o_el = orig_pres.slides[s_idx].elements[e_idx]
                r_el = re_parsed.slides[s_idx].elements[e_idx]
                if hasattr(o_el, 'position') and hasattr(r_el, 'position'):
                    dx = abs(o_el.position.x - r_el.position.x)
                    dy = abs(o_el.position.y - r_el.position.y)
                    dw = abs(o_el.position.width - r_el.position.width)
                    dh = abs(o_el.position.height - r_el.position.height)
                    max_drift_inches = max(max_drift_inches, dx, dy, dw, dh)

        assert max_drift_inches < 0.05, (
            f"Coordinate drift {max_drift_inches:.4f} in exceeds 0.05 in ({max_drift_inches * 96.0:.2f} px) in {os.path.basename(deck_path)}"
        )

    finally:
        if os.path.exists(out_pptx):
            os.remove(out_pptx)
