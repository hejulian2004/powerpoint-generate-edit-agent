"""Generate deterministic academic-paper PDF fixtures for the PR7.1 paper parser.

Produces ``tests/fixtures/paper/anomaly_agent.pdf`` (single-column LaTeX-like layout)
with:
  - a distinct title, an Abstract, numbered sections (1..6 incl. References),
  - 3 embedded raster figures with "Fig. 1:" style captions,
  - 2 tables with "Table 1:" / "Table 2:" captions and simple grids.

Committed as a binary fixture so the parser tests are fully offline & deterministic.

Usage:
    python scripts/create_paper_fixtures.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image as PILImage, ImageDraw
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FIXTURES_DIR = Path("tests/fixtures/paper")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

TITLE = "AnomalyAgent: Tool-Augmented Reinforcement Learning for Industrial Anomaly Synthesis"
AUTHORS = ["J. Researcher", "S. Engineer", "L. Supervisor"]

BODY_FONT = "Helvetica"
BODY_SIZE = 11
SECTION_SIZE = 15
TITLE_SIZE = 17

WIDTH, HEIGHT = letter
MARGIN = 1.0 * inch


def build_style_sheet():
    ss = getSampleStyleSheet()
    title = ParagraphStyle(
        "PaperTitle",
        parent=ss["Title"],
        fontName=BODY_FONT,
        fontSize=TITLE_SIZE,
        leading=TITLE_SIZE + 4,
        alignment=1,
        spaceAfter=6,
    )
    author = ParagraphStyle(
        "PaperAuthor",
        parent=ss["Normal"],
        fontName=BODY_FONT,
        fontSize=12,
        leading=15,
        alignment=1,
        textColor=colors.HexColor("#222222"),
    )
    section = ParagraphStyle(
        "PaperSection",
        parent=ss["Heading1"],
        fontName=BODY_FONT,
        fontSize=SECTION_SIZE,
        leading=SECTION_SIZE + 4,
        spaceBefore=14,
        spaceAfter=6,
        textColor=colors.black,
    )
    abstract_head = ParagraphStyle(
        "AbstractHead",
        parent=ss["Heading2"],
        fontName=BODY_FONT,
        fontSize=12,
        leading=15,
        alignment=1,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.black,
    )
    body = ParagraphStyle(
        "PaperBody",
        parent=ss["BodyText"],
        fontName=BODY_FONT,
        fontSize=BODY_SIZE,
        leading=BODY_SIZE + 3,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
    )
    caption = ParagraphStyle(
        "PaperCaption",
        parent=ss["BodyText"],
        fontName=BODY_FONT,
        fontSize=10,
        leading=12,
        alignment=0,
        spaceBefore=2,
        spaceAfter=8,
    )
    return title, author, section, abstract_head, body, caption


def draw_figure(width_px: float, height_px: float, label: str) -> PILImage.Image:
    """A deterministic, self-contained vector figure rasterized into the PDF."""
    w = int(width_px)
    h = int(height_px)
    img = PILImage.new("RGB", (w, h), "#EEF2FF")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline="#2563EB", width=2)
    # three nodes with connecting arrows
    nodes = [(0.25, 0.55), (0.5, 0.55), (0.75, 0.55)]
    fills = ["#2563EB", "#38BDF8", "#818CF8"]
    for (fx, fy), color in zip(nodes, fills):
        d.ellipse([w * fx - 18, h * fy - 18, w * fx + 18, h * fy + 18], fill=color, outline="#1D4ED8")
    for (ax, ay), (bx, by) in zip(nodes, nodes[1:]):
        d.line([w * ax + 18, h * ay, w * bx - 18, h * by], fill="#1E293B", width=3)
    d.text((w * 0.25, h * 0.25), label, fill="#1E293B")
    return img


def build_story():
    title, author, section, abstract_head, body, caption = build_style_sheet()

    story = [
        Paragraph(TITLE, title),
        Paragraph(" ".join(AUTHORS), author),
        Spacer(1, 6),
        Paragraph("Abstract", abstract_head),
        Paragraph(
            "Industrial anomaly detection is critical for manufacturing quality control, "
            "yet existing approaches struggle with scarce defect data and rigid domain "
            "assumptions. We present AnomalyAgent, a tool-augmented reinforcement learning "
            "framework that synthesizes realistic industrial anomalies while jointly training "
            "a detection policy. Our method achieves a 12.4% improvement in AUROC over "
            "strong baselines across three manufacturing benchmarks.",
            body,
        ),
        Spacer(1, 8),
    ]

    content = [
        ("1", "Introduction",
         [
            "Deep learning has driven rapid progress in visual anomaly detection for industrial settings.",
            "However, most pipelines assume access to large, clean defect corpora that are expensive to collect.",
            "In this work we address the data-hunger problem by framing anomaly synthesis as a decision-making task.",
            "We introduce AnomalyAgent, which couples a generative tool suite with a reinforcement learning controller.",
         ]),
        ("2", "Related Work",
         [
            "Prior methods in anomaly localization rely on reconstruction-based or feature-matching objectives.",
            "Recent work explores synthetic augmentation, but often produces artifacts that mislead downstream detectors.",
            "Unlike these, our agent learns which tool to invoke given the target defect type and operating region.",
         ]),
        ("3", "Problem Definition",
         [
            "We formalize anomaly synthesis as a sequential decision problem over a discrete tool set.",
            "The agent observes the current image region and chooses a tool action to maximize detection utility.",
            "We define a reward signal based on downstream detector confidence and visual realism.",
         ]),
        ("4", "Method",
         [
            "Our framework couples a bank of industrial operators with a policy network trained via reinforcement learning.",
            "The policy selects tool combinations while a world model predicts their effect on the detector.",
            "We apply conservative reward shaping to avoid degenerate synthetic textures.",
         ]),
        ("5", "Experiments",
         [
            "We evaluate AnomalyAgent on three benchmarks: PCB, bearing, and surface-fabric datasets.",
            "Our agent consistently outperforms fixed augmentation policies and reconstruction baselines.",
            "Ablation studies confirm that the tool-augmented reward is essential for stable training.",
         ]),
        ("6", "Conclusion",
         [
            "We presented AnomalyAgent, a tool-augmented RL approach to industrial anomaly synthesis.",
            "Results show significant gains in detection accuracy with markedly less annotated defect data.",
            "Future work will extend the tool set to multi-modal sensory inputs.",
         ]),
    ]

    for num, sec_title, paras in content:
        story.append(Paragraph(f"{num}. {sec_title}", section))
        for p in paras:
            story.append(Paragraph(p, body))

        if num == "1":
            story.append(Spacer(1, 6))
            fig1 = _pillow_image(draw_figure(180, 100, "Agent"))
            story.append(Image(fig1, width=3.2 * inch, height=1.8 * inch))
            story.append(Paragraph("Fig. 1: Overview of the AnomalyAgent framework and its tool-augmented loop.", caption))

        if num == "4":
            story.append(Spacer(1, 6))
            fig2 = _pillow_image(draw_figure(200, 100, "Policy Network"))
            story.append(Image(fig2, width=3.4 * inch, height=1.7 * inch))
            story.append(Paragraph("Fig. 2: The policy network with tool-selection head and world model.", caption))
            story.append(Spacer(1, 4))
            fig3 = _pillow_image(draw_figure(180, 90, "Reward Curve"))
            story.append(Image(fig3, width=3.0 * inch, height=1.5 * inch))
            story.append(Paragraph("Fig. 3: Training reward curve across tool-augmented episodes.", caption))

        if num == "5":
            story.append(Spacer(1, 6))
            story.append(Paragraph("Table 1: Detection AUROC (%) comparison across benchmarks.", caption))
            t1 = [
                ["Method", "PCB", "Bearing", "Surface"],
                ["Reconstruction", "89.1", "87.4", "85.9"],
                ["Fixed Augment", "91.2", "90.1", "88.7"],
                ["AnomalyAgent", "96.5", "95.8", "94.2"],
            ]
            story.append(Table(t1, style=_table_style()))
            story.append(Spacer(1, 8))
            story.append(Paragraph("Table 2: Ablation of reward components (AUROC on PCB).", caption))
            t2 = [
                ["Configuration", "AUROC"],
                ["No world model", "92.0"],
                ["No realism reward", "93.1"],
                ["Full reward", "96.5"],
            ]
            story.append(Table(t2, style=_table_style()))
            story.append(Spacer(1, 8))

    story.append(Paragraph("References", section))
    for ref in [
        "R1. A. Author, Visual anomaly detection in manufacturing, Proc. CVPR 2022.",
        "R2. B. Author, Generative augmentation for defect synthesis, Proc. ICLR 2021.",
        "R3. C. Author, Reinforcement learning for synthetic data generation, NeurIPS 2023.",
    ]:
        story.append(Paragraph(ref, body))

    return story


def _pillow_image(img: PILImage.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _table_style():
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E0E7FF")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]
    )


def main() -> None:
    out = FIXTURES_DIR / "anomaly_agent.pdf"
    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=TITLE,
    )
    doc.build(build_story())
    print(f"Wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()