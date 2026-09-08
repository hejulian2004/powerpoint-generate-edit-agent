"""Parser failure recovery tests (PR6.1 Task 7).

Verifies the OOXML parser degrades gracefully when individual package parts are corrupt:
- corrupt theme.xml / rels / media / slide.xml / presentation.xml must NOT crash the import.
- The result is a partial PresentationIR with structured warnings:
    metadata.parse_status = "partial", metadata.parser_warnings = [...]
- A package that is not a valid zip must still raise (total failure is not swallowed).
- Unsupported features (e.g. SmartArt) surface a structured supported:false verdict.
"""

import zipfile
from pathlib import Path
import pytest

from backend.ir.models import PresentationIR, SlideIR, TextElementIR, ImageElementIR, TextContentIR
from backend.ir import export_pptx
from backend.fidelity import OOXMLParser
from backend.fidelity.capability import CapabilityDetector

CORRUPT_XML = b"<broken-ooxml-part"
CORRUPT_BIN = b"\x00\x01\x02corrupt-relationship-data"


def _build_valid_pptx(tmp_path: Path) -> Path:
    pres = PresentationIR(title="Base")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="elem_title",
        x=80.0, y=50.0, width=400.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Partial import title")
    ))
    # Include an image so the package carries a ppt/media/ part for corruption tests.
    import base64
    png_b64 = base64.b64encode(
        bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"fake-image-data"
    ).decode("ascii")
    pres.assets["image1.png"] = f"data:image/png;base64,{png_b64}"
    slide.add_element(ImageElementIR(
        id="elem_img", x=500.0, y=50.0, width=120.0, height=80.0,
        asset_id="image1.png", src=pres.assets["image1.png"]
    ))
    pres.slides.append(slide)
    out = tmp_path / "base.pptx"
    export_pptx(pres, str(out))
    return out


def _corrupt_part(src: Path, dst: Path, part_prefix: str, corrupt_bytes: bytes) -> None:
    """Rewrites the archive replacing every entry whose name starts with part_prefix."""
    replaced = False
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename.startswith(part_prefix):
                data = corrupt_bytes
                replaced = True
            zout.writestr(info, data)
    assert replaced, f"no part matched prefix {part_prefix}"


def _parse_with_part_corrupted(tmp_path: Path, part_prefix: str, corrupt_bytes: bytes):
    base = _build_valid_pptx(tmp_path)
    corrupted = tmp_path / f"corrupt_{part_prefix.replace('/', '_').replace('.', '_')}.pptx"
    _corrupt_part(base, corrupted, part_prefix, corrupt_bytes)
    pres = OOXMLParser(corrupted).parse()
    assert pres.metadata.get("parse_status") == "partial"
    assert len(pres.metadata.get("parser_warnings", [])) >= 1
    return pres


def test_corrupt_theme_xml_no_crash(tmp_path):
    _parse_with_part_corrupted(tmp_path, "ppt/theme/theme1.xml", CORRUPT_XML)


def test_corrupt_presentation_rels_no_crash(tmp_path):
    pres = _parse_with_part_corrupted(tmp_path, "ppt/_rels/presentation.xml.rels", CORRUPT_BIN)
    # Without rels the fallback slide discovery still locates slide1.xml
    assert len(pres.slides) >= 1


def test_corrupt_slide_xml_no_crash_keeps_other_slides(tmp_path):
    pres = _parse_with_part_corrupted(tmp_path, "ppt/slides/slide1.xml", CORRUPT_XML)
    # The only slide was skipped; import still succeeds with an empty (partial) deck.
    assert len(pres.slides) == 0


def test_corrupt_media_no_crash(tmp_path):
    _parse_with_part_corrupted(tmp_path, "ppt/media/", CORRUPT_BIN)


def test_corrupt_presentation_xml_no_crash(tmp_path):
    pres = _parse_with_part_corrupted(tmp_path, "ppt/presentation.xml", CORRUPT_XML)
    # presentation.xml unreadable -> defaults used, slides still discovered via fallback
    assert len(pres.slides) >= 1


def test_invalid_package_still_raises(tmp_path):
    junk = tmp_path / "not_a_zip.pptx"
    junk.write_bytes(b"this is definitely not a zip archive")
    with pytest.raises(Exception):
        OOXMLParser(junk).parse()


def test_unsupported_feature_structured_verdict():
    verdict = CapabilityDetector.check_support("smartart")
    assert verdict == {"supported": False, "reason": "unsupported_feature"}
    verdict = CapabilityDetector.check_support("chart")
    assert verdict == {"supported": False, "reason": "unsupported_feature"}