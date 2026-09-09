"""Fidelity Validator and Visual Exporter (PR11).

Validates the roundtrip precision and content completeness between DeckLayoutSpec
and the generated OOXML PowerPoint presentation file.
Provides automated screenshot export via PowerPoint COM or headless LibreOffice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from ..layout.schema import DeckLayoutSpec, ElementType, LayoutElement, LayoutSpec
from .schema import EMU_PER_PX, FidelityCheckItem, FidelityReport


def validate_pptx_fidelity(
    deck_layout: DeckLayoutSpec,
    pptx_path: Union[str, Path],
    max_allowed_geom_error_pct: float = 1.0,
) -> FidelityReport:
    """Perform rigorous fidelity inspection between DeckLayoutSpec and the rendered PPTX.

    Checks:
      1. File readable and valid OOXML
      2. Exact slide count matches
      3. Shape count matches per slide
      4. Geometric coordinates match within < 1.0% tolerance
      5. Text element contents exist in corresponding shapes
      6. Figure elements produce valid picture shapes
    """
    path = Path(pptx_path).resolve()
    checks: List[FidelityCheckItem] = []
    errors: List[str] = []
    warnings: List[str] = []

    # 1. File existence and OOXML parsing
    if not path.is_file():
        err = f"PPTX file does not exist at {path}"
        return FidelityReport(
            is_valid=False,
            slide_count=0,
            checks=[FidelityCheckItem(category="file", target_id=str(path), passed=False, expected="file exists", actual="missing", message=err)],
            max_geometry_error_pct=100.0,
            errors=[err],
            warnings=[],
        )

    try:
        prs = Presentation(str(path))
    except Exception as e:
        err = f"Failed to parse generated PPTX as valid presentation: {e}"
        return FidelityReport(
            is_valid=False,
            slide_count=0,
            checks=[FidelityCheckItem(category="file_parsing", target_id=str(path), passed=False, expected="valid OOXML", actual=str(e), message=err)],
            max_geometry_error_pct=100.0,
            errors=[err],
            warnings=[],
        )

    # 2. Slide Count check
    actual_slide_count = len(prs.slides)
    expected_slide_count = len(deck_layout.slides)
    slide_count_match = actual_slide_count == expected_slide_count

    checks.append(
        FidelityCheckItem(
            category="slide_count",
            target_id="deck",
            passed=slide_count_match,
            expected=expected_slide_count,
            actual=actual_slide_count,
            message=None if slide_count_match else f"Slide count mismatch: expected {expected_slide_count}, got {actual_slide_count}",
        )
    )
    if not slide_count_match:
        errors.append(f"Slide count mismatch: expected {expected_slide_count}, got {actual_slide_count}")

    # 3. Slide-by-slide verification
    max_geom_err = 0.0

    for idx, slide_spec in enumerate(deck_layout.slides):
        if idx >= actual_slide_count:
            break

        ppt_slide = prs.slides[idx]
        shapes = list(ppt_slide.shapes)

        # A. Shape Count check
        expected_shape_count = len(slide_spec.elements)
        actual_shape_count = len(shapes)
        shape_match = (actual_shape_count == expected_shape_count)

        checks.append(
            FidelityCheckItem(
                category="element_count",
                target_id=slide_spec.slide_id,
                passed=shape_match,
                expected=expected_shape_count,
                actual=actual_shape_count,
                message=None if shape_match else f"Shape count mismatch on slide {idx + 1}: expected {expected_shape_count}, got {actual_shape_count}",
            )
        )
        if not shape_match:
            warnings.append(f"Slide {idx + 1} shape count mismatch: layout has {expected_shape_count} elements, PPT has {actual_shape_count} shapes")

        # B. Geometry and Content checks
        # Sort elements by z_index matching builder order
        sorted_elements = sorted(slide_spec.elements, key=lambda el: el.z_index)

        # Match shapes in order or by best geometric overlap
        for el_idx, el in enumerate(sorted_elements):
            if el_idx >= len(shapes):
                break
            shape = shapes[el_idx]

            # Convert shape geometry back to canvas pixels
            canvas_x = shape.left / EMU_PER_PX
            canvas_y = shape.top / EMU_PER_PX
            canvas_w = shape.width / EMU_PER_PX
            canvas_h = shape.height / EMU_PER_PX

            err_x = abs(canvas_x - el.geometry.x) / max(el.geometry.x, 10.0) * 100.0
            err_y = abs(canvas_y - el.geometry.y) / max(el.geometry.y, 10.0) * 100.0
            err_w = abs(canvas_w - el.geometry.width) / max(el.geometry.width, 10.0) * 100.0
            err_h = abs(canvas_h - el.geometry.height) / max(el.geometry.height, 10.0) * 100.0

            cur_max_err = max(err_x, err_y, err_w, err_h)
            if cur_max_err > max_geom_err:
                max_geom_err = cur_max_err

            geom_passed = cur_max_err <= max_allowed_geom_error_pct
            checks.append(
                FidelityCheckItem(
                    category="geometry",
                    target_id=el.element_id,
                    passed=geom_passed,
                    expected=f"x={el.geometry.x:.1f}, y={el.geometry.y:.1f}, w={el.geometry.width:.1f}, h={el.geometry.height:.1f}",
                    actual=f"x={canvas_x:.1f}, y={canvas_y:.1f}, w={canvas_w:.1f}, h={canvas_h:.1f}",
                    difference=round(cur_max_err, 4),
                    message=None if geom_passed else f"Geometry drift {cur_max_err:.2f}% exceeds {max_allowed_geom_error_pct}%",
                )
            )
            if not geom_passed:
                errors.append(f"Element {el.element_id} geometry drift {cur_max_err:.2f}% exceeds limit")

            # C. Content Text Fidelity check
            if el.element_type == ElementType.TEXT and el.content:
                if isinstance(el.content, list):
                    expected_str = " ".join(str(x) for x in el.content)
                else:
                    expected_str = str(el.content).strip()

                actual_text = shape.text_frame.text.strip() if shape.has_text_frame else ""
                # Normalize spaces
                norm_expected = " ".join(expected_str.split())
                norm_actual = " ".join(actual_text.split())

                text_passed = (norm_expected in norm_actual) or (norm_actual in norm_expected)
                checks.append(
                    FidelityCheckItem(
                        category="text_fidelity",
                        target_id=el.element_id,
                        passed=text_passed,
                        expected=norm_expected[:50],
                        actual=norm_actual[:50],
                        message=None if text_passed else f"Text content mismatch for element {el.element_id}",
                    )
                )
                if not text_passed:
                    warnings.append(f"Text mismatch on element {el.element_id}: expected '{norm_expected[:30]}...', got '{norm_actual[:30]}...'")

            # D. Figure fidelity check (PICTURE or explicit placeholder AUTO_SHAPE)
            elif el.element_type == ElementType.FIGURE:
                is_pic = (shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
                is_placeholder = (shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE)
                passed = is_pic or is_placeholder
                checks.append(
                    FidelityCheckItem(
                        category="figure_fidelity",
                        target_id=el.element_id,
                        passed=passed,
                        expected="PICTURE or AUTO_SHAPE placeholder",
                        actual=str(shape.shape_type),
                        message=None if passed else f"Expected PICTURE or AUTO_SHAPE placeholder, got {shape.shape_type}",
                    )
                )
                if not passed:
                    errors.append(f"Figure element {el.element_id} was not rendered as PICTURE or placeholder shape")

            # E. Table fidelity check
            elif el.element_type == ElementType.TABLE:
                is_table = shape.has_table
                checks.append(
                    FidelityCheckItem(
                        category="table_fidelity",
                        target_id=el.element_id,
                        passed=is_table,
                        expected="TABLE",
                        actual="TABLE" if is_table else "NON_TABLE",
                        message=None if is_table else f"Expected TABLE shape type for element {el.element_id}",
                    )
                )
                if not is_table:
                    errors.append(f"Table element {el.element_id} was not rendered as TABLE shape")

    is_valid = len(errors) == 0

    return FidelityReport(
        is_valid=is_valid,
        slide_count=actual_slide_count,
        checks=checks,
        max_geometry_error_pct=round(max_geom_err, 4),
        errors=errors,
        warnings=warnings,
    )


def render_slide_screenshots(
    pptx_path: Union[str, Path],
    output_dir: Union[str, Path],
) -> List[Path]:
    """Export slide screenshots to PNG format for visual verification.

    Attempts PowerPoint COM automation first (native on Windows with MS Office).
    Falls back to headless LibreOffice if available.
    Returns list of paths to generated PNG screenshots.
    """
    in_path = Path(pptx_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_images: List[Path] = []

    if not in_path.is_file():
        return generated_images

    def _natural_slide_sort(paths: List[Path]) -> List[Path]:
        def _key(p: Path) -> int:
            stem = p.stem.split("_")[-1]
            return int(stem) if stem.isdigit() else 0
        return sorted(paths, key=_key)

    # 1. Try Windows PowerPoint COM automation via PowerShell
    safe_in_path = str(in_path).replace("'", "''")
    safe_out_dir = str(out_dir).replace("'", "''")
    ps_script = f"""
$ErrorActionPreference = 'Stop'
$ppt = $null
$pres = $null
try {{
    $ppt = New-Object -ComObject PowerPoint.Application
    $pres = $ppt.Presentations.Open('{safe_in_path}', [Microsoft.Office.Core.MsoTriState]::msoTrue, [Microsoft.Office.Core.MsoTriState]::msoFalse, [Microsoft.Office.Core.MsoTriState]::msoFalse)
    for ($i = 1; $i -le $pres.Slides.Count; $i++) {{
        $slidePath = Join-Path '{safe_out_dir}' ("slide_" + $i + ".png")
        $pres.Slides.Item($i).Export($slidePath, "PNG")
    }}
    Write-Host "COM_EXPORT_SUCCESS"
}} catch {{
    Write-Host ("COM_EXPORT_ERROR: " + $_.Exception.Message)
}} finally {{
    if ($pres) {{
        try {{ $pres.Close() }} catch {{}}
        try {{ [System.Runtime.Interopservices.Marshal]::ReleaseComObject($pres) | Out-Null }} catch {{}}
    }}
    if ($ppt) {{
        try {{ $ppt.Quit() }} catch {{}}
        try {{ [System.Runtime.Interopservices.Marshal]::ReleaseComObject($ppt) | Out-Null }} catch {{}}
    }}
}}
"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=40,
        )
        if "COM_EXPORT_SUCCESS" in proc.stdout:
            pngs = _natural_slide_sort(list(out_dir.glob("slide_*.png")))
            if pngs:
                return pngs
    except Exception:
        pass

    # 2. Try LibreOffice CLI if present
    soffice_path = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice_path:
        try:
            pdf_dir = out_dir / "temp_pdf"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [soffice_path, "--headless", "--convert-to", "pdf", str(in_path), "--outdir", str(pdf_dir)],
                check=True,
                timeout=45,
            )
            pdf_file = pdf_dir / f"{in_path.stem}.pdf"
            if pdf_file.is_file():
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(pdf_file)
                for page_idx in range(len(pdf)):
                    page = pdf[page_idx]
                    bitmap = page.render(scale=2.0)
                    img = bitmap.to_pil()
                    dest_png = out_dir / f"slide_{page_idx + 1}.png"
                    img.save(dest_png)
                    generated_images.append(dest_png)
                return _natural_slide_sort(generated_images)
        except Exception:
            pass

    return _natural_slide_sort(list(out_dir.glob("slide_*.png")))
