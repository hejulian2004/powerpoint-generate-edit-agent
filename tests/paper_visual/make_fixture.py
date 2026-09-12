"""Generate the deterministic multi-case benchmark PDF for paper_visual tests.

The fixture is a fixed 10-page synthetic paper covering the visual situations the
multimodal pipeline must handle:

  page 1  title page (no figure)
  page 2  abstract + two-column body
  page 3  architecture figure + caption ("Figure 1")
  page 4  multi-panel figure (two embedded rasters) + caption ("Figure 2")
  page 5  equation / algorithm text block
  page 6  results table + caption ("Table 1")
  page 7  plot-like figure + caption ("Figure 3")
  page 8  long caption figure ("Figure 4")
  page 9  wide (column-spanning) figure + caption ("Figure 5")
  page 10 references / no figure

Run:  python tests/paper_visual/make_fixture.py [output_path]
This script and its output are committed together for reproducibility.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

W, H = letter  # 612 x 792 points

DEFAULT_OUT = Path("tests/fixtures/paper/multicase_10p.pdf")


def _panel_image(seed: int, width: int = 480, height: int = 260) -> ImageReader:
    """A deterministic synthetic raster (colored blocks) as an embedded image."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([4, 4, width - 4, height - 4], outline=(30, 41, 59), width=3)
    for i in range(4):
        x0 = 24 + i * (width - 48) / 4
        y0 = 30 + (seed * 13 + i * 17) % 80
        draw.rectangle([x0, y0, x0 + 70, y0 + 90], fill=(37 + i * 20, 99, 235 - i * 15))
        draw.line([x0, y0 + 100, x0 + 70, y0 + 100], fill=(15, 23, 42), width=2)
    draw.text((24, 12), f"Figure raster {seed}", fill=(15, 23, 42))
    return ImageReader(img)


def _paragraph(c: rl_canvas.Canvas, x: float, y: float, lines: list[str], size: int = 10,
               leading: int = 14, font: str = "Helvetica") -> float:
    c.setFont(font, size)
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _figure_caption(c: rl_canvas.Canvas, x: float, y: float, text: str, size: int = 9) -> float:
    c.setFont("Helvetica-Oblique", size)
    c.drawString(x, y, text)
    return y - 14


def build_pdf(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="multicase_pdf_"))
    c = rl_canvas.Canvas(str(output_path), pagesize=letter)

    # --- page 1: title -------------------------------------------------
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, H - 120, "AnomalyAgent: A Multi-Case Benchmark Paper")
    _paragraph(c, 72, H - 150, ["Alice Researcher, Bob Scientist, Carol Engineer",
                                "Institute for Applied Machine Learning", "Proceedings of the Example Conference, 2025"], size=11)
    c.showPage()

    # --- page 2: abstract + two-column body ---------------------------
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, H - 80, "Abstract")
    _paragraph(c, 72, H - 100, [
        "We present a reference paper used to exercise multimodal slide generation.",
        "This document contains figures, tables, plots and equations in a fixed layout.",
        "All content here is synthetic and carries no real scientific claim.",
    ])
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 180, "1. Introduction")
    left = ["The introduction spans the left column of a two-column paper.",
            "We describe the problem, motivation and contributions in plain text.",
            "Readers should follow the reading order column by column."]
    right = ["The right column continues the narrative of the introduction.",
             "It discusses prior work and positions the contribution.",
             "End of the two-column introduction on this page."]
    _paragraph(c, 72, H - 200, left, size=10)
    _paragraph(c, 330, H - 200, right, size=10)
    c.showPage()

    # --- page 3: architecture figure ----------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "2. Method")
    _paragraph(c, 72, H - 100, ["The architecture is shown in the figure below."])
    c.drawImage(_panel_image(1), 100, H - 380, width=400, height=220, preserveAspectRatio=True, anchor="c")
    _figure_caption(c, 90, H - 400, "Figure 1: Overall architecture of the proposed system pipeline.")
    c.showPage()

    # --- page 4: multi-panel figure ------------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "2.1 Components")
    c.drawImage(_panel_image(2, 240, 200), 80, H - 300, width=210, height=170, preserveAspectRatio=True)
    c.drawImage(_panel_image(3, 240, 200), 320, H - 300, width=210, height=170, preserveAspectRatio=True)
    _figure_caption(c, 80, H - 320, "Figure 2: Multi-panel structure with two component views (a) encoder (b) decoder.")
    c.showPage()

    # --- page 5: equation block ----------------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "3. Formulation")
    _paragraph(c, 72, H - 110, [
        "The objective is defined below.",
        "L(theta) = sum_i loss(x_i, f_theta(x_i)) + lambda * R(theta)",
        "where theta denotes the learnable parameters and lambda is a hyperparameter.",
    ])
    c.showPage()

    # --- page 6: results table -----------------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "4. Results")
    _paragraph(c, 72, H - 100, ["Table 1 reports the comparative results."])
    top = H - 140
    col_x = [80, 240, 360, 480]
    rows = [
        ["Method", "Accuracy", "Latency", "Memory"],
        ["Baseline A", "0.81", "12 ms", "220 MB"],
        ["Baseline B", "0.84", "15 ms", "310 MB"],
        ["Ours", "0.90", "11 ms", "240 MB"],
    ]
    c.setFont("Helvetica", 9)
    for r, row in enumerate(rows):
        y = top - r * 20
        for cidx, cell in enumerate(row):
            c.drawString(col_x[cidx], y, cell)
        c.line(78, y - 4, 540, y - 4)
    _figure_caption(c, 78, top - len(rows) * 20 - 18,
                    "Table 1: Comparative evaluation across methods.")
    c.showPage()

    # --- page 7: plot figure -------------------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "4.1 Trend Analysis")
    c.drawImage(_panel_image(4), 120, H - 380, width=360, height=220, preserveAspectRatio=True)
    _figure_caption(c, 90, H - 400, "Figure 3: Performance trend plot across evaluation settings.")
    c.showPage()

    # --- page 8: long caption ------------------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "4.2 Qualitative Study")
    c.drawImage(_panel_image(5), 150, H - 320, width=300, height=180, preserveAspectRatio=True)
    _figure_caption(c, 72, H - 340,
                    "Figure 4: Qualitative comparison of generated outputs under a long descriptive caption "
                    "that continues across multiple wrapped lines to exercise long-caption handling.")
    c.showPage()

    # --- page 9: wide figure -------------------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "5. Discussion")
    c.drawImage(_panel_image(6, 520, 200), 60, H - 320, width=492, height=190, preserveAspectRatio=True)
    _figure_caption(c, 72, H - 340, "Figure 5: A wide figure spanning the full text width.")
    c.showPage()

    # --- page 10: references (no figure) -------------------------------
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, H - 80, "References")
    _paragraph(c, 72, H - 110, [
        "[1] A. Researcher. A synthetic reference entry.",
        "[2] B. Scientist. Another synthetic reference entry.",
        "[3] C. Engineer. Yet another synthetic reference entry.",
    ])
    c.showPage()

    c.save()
    return output_path


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    build_pdf(out)
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
