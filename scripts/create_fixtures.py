"""Script to generate realistic test fixtures for PPT-Agent-Studio:
1. tests/fixtures/simple.pptx
2. tests/fixtures/academic.pptx
3. tests/fixtures/diagram.pptx
4. tests/fixtures/image-heavy.pptx
"""

import os
import io
import base64
from pathlib import Path
from pptx_agent_converter.model.slide import Presentation, Slide, SlideSize, ThemeInfo, DEFAULT_WIDTH, DEFAULT_HEIGHT
from pptx_agent_converter.model.shape import (
    ShapeElement, ConnectorElement, ImageElement, GroupElement, Position
)
from pptx_agent_converter.model.text import TextBlock, Paragraph, Run
from pptx_agent_converter.model.style import Fill, Line, Shadow, Font, ParagraphStyle
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder
from pptx_agent_converter.validation import validate_pptx


FIXTURES_DIR = Path("tests/fixtures")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


# 1x1 transparent/colored PNG generator helper
def create_sample_png_bytes(color_hex: str = "#3B82F6") -> bytes:
    # Minimal 1x1 valid PNG
    raw_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    return base64.b64decode(raw_b64)


def make_text_block(text: str, font_size: float = 14.0, bold: bool = False, color: str = "#FFFFFF", align: str = "left") -> TextBlock:
    return TextBlock(
        paragraphs=[
            Paragraph(
                runs=[
                    Run(
                        text=line,
                        font=Font(name="Segoe UI", size=font_size, bold=bold, color=color)
                    )
                ],
                style=ParagraphStyle(align=align)
            )
            for line in text.split("\n")
        ]
    )


def create_simple_fixture() -> Path:
    """Creates tests/fixtures/simple.pptx: clean 1-slide baseline presentation."""
    s1 = Slide(
        slide_id=1,
        slide_num=1,
        background=Fill(type="solid", color="#0F172A"),
        elements=[
            ShapeElement(
                id="title",
                name="Title",
                shape_type="textbox",
                position=Position(x=1.0, y=0.8, width=11.33, height=1.0),
                text=make_text_block("Simple Presentation Fixture", font_size=32.0, bold=True, color="#F8FAFC", align="center")
            ),
            ShapeElement(
                id="card1",
                name="Card 1",
                shape_type="roundRect",
                position=Position(x=1.5, y=2.5, width=4.5, height=3.5),
                radius=12.0,
                fill=Fill(type="solid", color="#1E293B"),
                line=Line(color="#334155", width=1.5),
                shadow=Shadow(enabled=True, blur=6.0, alpha=0.3),
                text=make_text_block("Baseline Card A\n\n- Quick overview\n- Standard shape properties\n- High fidelity verification", font_size=16.0, color="#CBD5E1")
            ),
            ShapeElement(
                id="card2",
                name="Card 2",
                shape_type="roundRect",
                position=Position(x=7.33, y=2.5, width=4.5, height=3.5),
                radius=12.0,
                fill=Fill(type="solid", color="#1E293B"),
                line=Line(color="#334155", width=1.5),
                shadow=Shadow(enabled=True, blur=6.0, alpha=0.3),
                text=make_text_block("Baseline Card B\n\n- Connected target\n- Text runs and paragraphs\n- Coordinate fidelity", font_size=16.0, color="#CBD5E1")
            ),
            ConnectorElement(
                id="conn1",
                name="Connector 1->2",
                start=(6.0, 4.25),
                end=(7.33, 4.25),
                line=Line(color="#60A5FA", width=2.0),
                arrow_end="triangle"
            )
        ]
    )

    pres = Presentation(
        name="simple",
        size=SlideSize(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT),
        slides=[s1]
    )

    out_path = FIXTURES_DIR / "simple.pptx"
    builder = PPTXBuilder()
    builder.build(pres, str(out_path))
    return out_path


def create_academic_fixture() -> Path:
    """Creates tests/fixtures/academic.pptx: a 5-slide realistic paper presentation deck."""
    # Slide 1: Title & Authors
    s1 = Slide(
        slide_id=1,
        slide_num=1,
        background=Fill(type="solid", color="#090D16"),
        elements=[
            ShapeElement(
                id="badge",
                name="Conference Badge",
                shape_type="roundRect",
                position=Position(x=1.0, y=0.8, width=4.0, height=0.4),
                radius=6.0,
                fill=Fill(type="solid", color="#1E3A8A"),
                line=Line(color="#3B82F6", width=1.0),
                text=make_text_block("NEURIPS 2026 · ORAL PRESENTATION", font_size=11.0, bold=True, color="#93C5FD", align="center")
            ),
            ShapeElement(
                id="main_title",
                name="Paper Title",
                shape_type="textbox",
                position=Position(x=1.0, y=1.5, width=11.33, height=1.6),
                text=make_text_block("Towards Scalable Vision-Language Reasoning in Autonomous Slide Synthesis", font_size=36.0, bold=True, color="#FFFFFF")
            ),
            ShapeElement(
                id="authors",
                name="Authors",
                shape_type="textbox",
                position=Position(x=1.0, y=3.2, width=11.33, height=0.6),
                text=make_text_block("Alice Smith¹*, Bob Jones²*, Carol Wang¹ · ¹Stanford AI Lab  ²MIT CSAIL (* Equal Contribution)", font_size=15.0, color="#94A3B8")
            ),
            ShapeElement(
                id="abstract_card",
                name="Abstract Card",
                shape_type="roundRect",
                position=Position(x=1.0, y=4.1, width=11.33, height=2.4),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#1F2937", width=1.5),
                shadow=Shadow(enabled=True, blur=8.0, alpha=0.4),
                text=make_text_block("Abstract:\nWe present AgentStudio, a principled framework for multi-modal spatial reasoning and presentation synthesis. By grounding intermediate representations (PPT-IR) into standard geometric coordinate spaces, our approach eliminates semantic drift and layout hallucinations common in unconstrained LLM slide generation. Extensive experiments across 500 academic decks demonstrate 99.4% package validity and superior visual fidelity.", font_size=14.0, color="#D1D5DB")
            )
        ]
    )

    # Slide 2: Theoretical Motivation & Problem Formulation
    s2 = Slide(
        slide_id=2,
        slide_num=2,
        background=Fill(type="solid", color="#090D16"),
        elements=[
            ShapeElement(
                id="s2_title",
                name="Section Title",
                shape_type="textbox",
                position=Position(x=1.0, y=0.7, width=11.33, height=0.8),
                text=make_text_block("1. Theoretical Motivation & Problem Formulation", font_size=28.0, bold=True, color="#FFFFFF")
            ),
            ShapeElement(
                id="card_challenge_1",
                name="Spatial Distortion Card",
                shape_type="roundRect",
                position=Position(x=1.0, y=1.8, width=3.5, height=4.8),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#374151", width=1.5),
                text=make_text_block("Challenge A: Spatial Distortion\n\n• Autoregressive tokenizers lack 2D geometric priors.\n• Text overflowing and shape bounding collisions (error > 45px).\n• Inability to resolve visual hierarchy automatically.", font_size=13.0, color="#E5E7EB")
            ),
            ShapeElement(
                id="card_challenge_2",
                name="Semantic Drift Card",
                shape_type="roundRect",
                position=Position(x=4.91, y=1.8, width=3.5, height=4.8),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#374151", width=1.5),
                text=make_text_block("Challenge B: Semantic Drift\n\n• Unconstrained generation mutates domain formulas (∇_θ L(x)).\n• Loss of academic citation structures.\n• Inconsistent typography styles between adjacent slides.", font_size=13.0, color="#E5E7EB")
            ),
            ShapeElement(
                id="card_challenge_3",
                name="OOXML Brittleness Card",
                shape_type="roundRect",
                position=Position(x=8.83, y=1.8, width=3.5, height=4.8),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#374151", width=1.5),
                text=make_text_block("Challenge C: OOXML Brittleness\n\n• Raw XML string generation leads to corrupted zip packages.\n• Schema violations under ECMA-376 specification.\n• Incomplete drawingML relationship mappings.", font_size=13.0, color="#E5E7EB")
            )
        ]
    )

    # Slide 3: Method Architecture (With GroupElements and Connectors)
    g1_child_bg = ShapeElement(id="g1_bg", name="Perception Box", position=Position(x=1.0, y=2.2, width=3.2, height=3.6), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#38BDF8", width=1.5), radius=8.0)
    g1_child_txt = ShapeElement(id="g1_txt", name="Perception Text", shape_type="textbox", position=Position(x=1.2, y=2.4, width=2.8, height=3.2), text=make_text_block("Perception Module\n\n- OOXML Extractor\n- DrawingML Parser\n- PPT-IR Model Mapper", font_size=14.0, bold=False, color="#F1F5F9"))
    group_perception = GroupElement(id="grp_perception", name="Perception Group", position=Position(x=1.0, y=2.2, width=3.2, height=3.6), elements=[g1_child_bg, g1_child_txt])

    g2_child_bg = ShapeElement(id="g2_bg", name="Reasoning Box", position=Position(x=5.06, y=2.2, width=3.2, height=3.6), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#818CF8", width=1.5), radius=8.0)
    g2_child_txt = ShapeElement(id="g2_txt", name="Reasoning Text", shape_type="textbox", position=Position(x=5.26, y=2.4, width=2.8, height=3.2), text=make_text_block("LangGraph Planner\n\n- StateGraph Engine\n- Intent Router\n- Archetype Layout Planner", font_size=14.0, bold=False, color="#F1F5F9"))
    group_planning = GroupElement(id="grp_planning", name="Planning Group", position=Position(x=5.06, y=2.2, width=3.2, height=3.6), elements=[g2_child_bg, g2_child_txt])

    g3_child_bg = ShapeElement(id="g3_bg", name="Execution Box", position=Position(x=9.13, y=2.2, width=3.2, height=3.6), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#34D399", width=1.5), radius=8.0)
    g3_child_txt = ShapeElement(id="g3_txt", name="Execution Text", shape_type="textbox", position=Position(x=9.33, y=2.4, width=2.8, height=3.2), text=make_text_block("Execution & Review\n\n- Atomic IR Tool Suite\n- History Patch Engine\n- High-fidelity OOXML Builder", font_size=14.0, bold=False, color="#F1F5F9"))
    group_execution = GroupElement(id="grp_execution", name="Execution Group", position=Position(x=9.13, y=2.2, width=3.2, height=3.6), elements=[g3_child_bg, g3_child_txt])

    s3 = Slide(
        slide_id=3,
        slide_num=3,
        background=Fill(type="solid", color="#090D16"),
        elements=[
            ShapeElement(
                id="s3_title",
                name="Architecture Title",
                shape_type="textbox",
                position=Position(x=1.0, y=0.7, width=11.33, height=0.8),
                text=make_text_block("2. System Architecture & Closed-Loop Pipeline", font_size=28.0, bold=True, color="#FFFFFF")
            ),
            group_perception,
            group_planning,
            group_execution,
            ConnectorElement(
                id="conn_p_to_r",
                name="Perception to Planning",
                start=(4.2, 4.0),
                end=(5.06, 4.0),
                line=Line(color="#60A5FA", width=2.0),
                arrow_end="triangle"
            ),
            ConnectorElement(
                id="conn_r_to_e",
                name="Planning to Execution",
                start=(8.26, 4.0),
                end=(9.13, 4.0),
                line=Line(color="#60A5FA", width=2.0),
                arrow_end="triangle"
            ),
            ConnectorElement(
                id="conn_feedback",
                name="Feedback Loop",
                start=(9.13, 5.0),
                end=(4.2, 5.0),
                connector_type="curved",
                line=Line(color="#F43F5E", width=1.8),
                arrow_end="triangle"
            )
        ]
    )

    # Slide 4: Empirical Benchmark Evaluation & Quantitative Metrics
    s4 = Slide(
        slide_id=4,
        slide_num=4,
        background=Fill(type="solid", color="#090D16"),
        elements=[
            ShapeElement(
                id="s4_title",
                name="Benchmark Title",
                shape_type="textbox",
                position=Position(x=1.0, y=0.7, width=11.33, height=0.8),
                text=make_text_block("3. Empirical Evaluation on 500 Academic Decks", font_size=28.0, bold=True, color="#FFFFFF")
            ),
            # Metric 1
            ShapeElement(
                id="metric_1",
                name="Metric 1 Card",
                shape_type="roundRect",
                position=Position(x=1.0, y=1.8, width=3.5, height=2.2),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#3B82F6", width=2.0),
                text=make_text_block("99.4%\n\nOOXML Package Validity\n(Zero corruption errors)", font_size=24.0, bold=True, color="#60A5FA", align="center")
            ),
            # Metric 2
            ShapeElement(
                id="metric_2",
                name="Metric 2 Card",
                shape_type="roundRect",
                position=Position(x=4.91, y=1.8, width=3.5, height=2.2),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#10B981", width=2.0),
                text=make_text_block("0.918\n\nStructural SSIM Score\n(High-fidelity vector match)", font_size=24.0, bold=True, color="#34D399", align="center")
            ),
            # Metric 3
            ShapeElement(
                id="metric_3",
                name="Metric 3 Card",
                shape_type="roundRect",
                position=Position(x=8.83, y=1.8, width=3.5, height=2.2),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#8B5CF6", width=2.0),
                text=make_text_block("+34.2%\n\nExpert Blind Preference\n(vs. raw LLM prompt baseline)", font_size=24.0, bold=True, color="#A78BFA", align="center")
            ),
            # Summary Table Container Card
            ShapeElement(
                id="table_summary",
                name="Comparison Summary",
                shape_type="roundRect",
                position=Position(x=1.0, y=4.4, width=11.33, height=2.3),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#374151", width=1.5),
                text=make_text_block("Benchmark Highlights:\n• Direct XML Prompting: 41.2% validity, frequent unclosed tags, broken relationships.\n• Commercial API Wrapper: 86.5% validity, rigid templates, no visual revision.\n• AgentStudio (Ours): 99.4% validity, full roundtrip preservation, sub-second latency.", font_size=14.0, color="#E2E8F0")
            )
        ]
    )

    # Slide 5: Conclusion & Future Work
    s5 = Slide(
        slide_id=5,
        slide_num=5,
        background=Fill(type="solid", color="#090D16"),
        elements=[
            ShapeElement(
                id="s5_title",
                name="Conclusion Title",
                shape_type="textbox",
                position=Position(x=1.0, y=0.7, width=11.33, height=0.8),
                text=make_text_block("4. Summary & Research Contributions", font_size=28.0, bold=True, color="#FFFFFF")
            ),
            ShapeElement(
                id="card_contrib",
                name="Contributions Card",
                shape_type="roundRect",
                position=Position(x=1.0, y=1.8, width=5.4, height=4.8),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#374151", width=1.5),
                text=make_text_block("Key Contributions:\n\n1. PPT-IR Abstraction:\nA standard 1280×720 coordinate representation decoupling semantic content from binary presentation formats.\n\n2. LangGraph State Machine:\nDeterministic state transitions eliminating hallucination and infinite tool execution loops.\n\n3. High-Fidelity OOXML Engine:\nClosed-loop roundtrip pipeline with explicit conversion accounting and zero silent drops.", font_size=13.5, color="#F8FAFC")
            ),
            ShapeElement(
                id="card_future",
                name="Future Work Card",
                shape_type="roundRect",
                position=Position(x=6.93, y=1.8, width=5.4, height=4.8),
                radius=10.0,
                fill=Fill(type="solid", color="#111827"),
                line=Line(color="#374151", width=1.5),
                text=make_text_block("Future Work & Roadmap:\n\n1. Vision Self-Correction Benchmark:\nAutomated rendering differential (SSIM / OCR) with multimodal LLM visual feedback.\n\n2. Native MathML & LaTeX Rendering:\nDirect conversion of equation blocks into native PowerPoint drawingML equations.\n\n3. Collaborative Agent Swarms:\nSpecialized agent roles for content drafting, visual styling, and layout auditing.", font_size=13.5, color="#F8FAFC")
            )
        ]
    )

    pres = Presentation(
        name="academic",
        size=SlideSize(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT),
        slides=[s1, s2, s3, s4, s5]
    )

    out_path = FIXTURES_DIR / "academic.pptx"
    builder = PPTXBuilder()
    builder.build(pres, str(out_path))
    return out_path


def create_diagram_fixture() -> Path:
    """Creates tests/fixtures/diagram.pptx: focused on shapes, groups, and complex connector flows."""
    g_a1 = ShapeElement(id="da1", name="Stage 1 Box", position=Position(x=1.0, y=2.0, width=2.2, height=1.8), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#38BDF8", width=1.5), radius=6.0)
    g_a2 = ShapeElement(id="da2", name="Stage 1 Text", shape_type="textbox", position=Position(x=1.1, y=2.1, width=2.0, height=1.6), text=make_text_block("Input Data\n(OOXML Package)", font_size=14.0, bold=True, color="#F8FAFC", align="center"))
    grp1 = GroupElement(id="g_stage1", name="Stage 1 Group", position=Position(x=1.0, y=2.0, width=2.2, height=1.8), elements=[g_a1, g_a2])

    g_b1 = ShapeElement(id="db1", name="Stage 2 Box", position=Position(x=4.0, y=2.0, width=2.2, height=1.8), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#818CF8", width=1.5), radius=6.0)
    g_b2 = ShapeElement(id="db2", name="Stage 2 Text", shape_type="textbox", position=Position(x=4.1, y=2.1, width=2.0, height=1.6), text=make_text_block("PPT-IR Model\n(1280×720 Canvas)", font_size=14.0, bold=True, color="#F8FAFC", align="center"))
    grp2 = GroupElement(id="g_stage2", name="Stage 2 Group", position=Position(x=4.0, y=2.0, width=2.2, height=1.8), elements=[g_b1, g_b2])

    g_c1 = ShapeElement(id="dc1", name="Stage 3 Box", position=Position(x=7.0, y=2.0, width=2.2, height=1.8), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#34D399", width=1.5), radius=6.0)
    g_c2 = ShapeElement(id="dc2", name="Stage 3 Text", shape_type="textbox", position=Position(x=7.1, y=2.1, width=2.0, height=1.6), text=make_text_block("Agent Mutation\n(Patch Engine)", font_size=14.0, bold=True, color="#F8FAFC", align="center"))
    grp3 = GroupElement(id="g_stage3", name="Stage 3 Group", position=Position(x=7.0, y=2.0, width=2.2, height=1.8), elements=[g_c1, g_c2])

    g_d1 = ShapeElement(id="dd1", name="Stage 4 Box", position=Position(x=10.0, y=2.0, width=2.2, height=1.8), fill=Fill(type="solid", color="#1E293B"), line=Line(color="#F43F5E", width=1.5), radius=6.0)
    g_d2 = ShapeElement(id="dd2", name="Stage 4 Text", shape_type="textbox", position=Position(x=10.1, y=2.1, width=2.0, height=1.6), text=make_text_block("Reconstructed\nPowerPoint PPTX", font_size=14.0, bold=True, color="#F8FAFC", align="center"))
    grp4 = GroupElement(id="g_stage4", name="Stage 4 Group", position=Position(x=10.0, y=2.0, width=2.2, height=1.8), elements=[g_d1, g_d2])

    s1 = Slide(
        slide_id=1,
        slide_num=1,
        background=Fill(type="solid", color="#0A0F1D"),
        elements=[
            ShapeElement(id="d_title", name="Title", shape_type="textbox", position=Position(x=1.0, y=0.6, width=11.33, height=0.8), text=make_text_block("Sequential Dataflow & Reversible Patch Pipeline", font_size=26.0, bold=True, color="#FFFFFF")),
            grp1, grp2, grp3, grp4,
            ConnectorElement(id="c1_2", name="C1->2", start=(3.2, 2.9), end=(4.0, 2.9), line=Line(color="#60A5FA", width=2.0), arrow_end="triangle"),
            ConnectorElement(id="c2_3", name="C2->3", start=(6.2, 2.9), end=(7.0, 2.9), line=Line(color="#60A5FA", width=2.0), arrow_end="triangle"),
            ConnectorElement(id="c3_4", name="C3->4", start=(9.2, 2.9), end=(10.0, 2.9), line=Line(color="#60A5FA", width=2.0), arrow_end="triangle"),
            # Diamond decision node
            ShapeElement(id="d_decision", name="Validation Gate", shape_type="diamond", position=Position(x=5.5, y=4.5, width=2.33, height=1.8), fill=Fill(type="solid", color="#312E81"), line=Line(color="#818CF8", width=1.5), text=make_text_block("Valid\nECMA-376?", font_size=13.0, bold=True, color="#FFFFFF", align="center")),
            ConnectorElement(id="c_to_gate", name="C3->Gate", start=(8.1, 3.8), end=(6.66, 4.5), connector_type="curved", line=Line(color="#818CF8", width=1.5), arrow_end="triangle"),
            ConnectorElement(id="c_gate_pass", name="Gate->Pass", start=(7.83, 5.4), end=(10.0, 2.9), connector_type="curved", line=Line(color="#34D399", width=1.5), arrow_end="triangle")
        ]
    )

    pres = Presentation(
        name="diagram",
        size=SlideSize(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT),
        slides=[s1]
    )

    out_path = FIXTURES_DIR / "diagram.pptx"
    builder = PPTXBuilder()
    builder.build(pres, str(out_path))
    return out_path


def create_image_heavy_fixture() -> Path:
    """Creates tests/fixtures/image-heavy.pptx: slides with multiple image media assets."""
    sample_png = create_sample_png_bytes()
    media_files = {
        "fig1.png": sample_png,
        "fig2.png": sample_png,
        "fig3.png": sample_png
    }

    s1 = Slide(
        slide_id=1,
        slide_num=1,
        background=Fill(type="solid", color="#0F172A"),
        elements=[
            ShapeElement(id="img_title", name="Title", shape_type="textbox", position=Position(x=1.0, y=0.7, width=11.33, height=0.8), text=make_text_block("Multi-Asset Qualitative Visual Inspection", font_size=28.0, bold=True, color="#FFFFFF")),
            # Image 1
            ImageElement(id="img_1", name="Figure 1", position=Position(x=1.0, y=1.8, width=3.5, height=3.0), src="fig1.png", original_name="fig1.png"),
            ShapeElement(id="cap_1", name="Caption 1", shape_type="textbox", position=Position(x=1.0, y=4.9, width=3.5, height=1.0), text=make_text_block("Figure 1: Attention Map\nSpatial weight distribution across layers.", font_size=12.0, color="#94A3B8")),
            # Image 2
            ImageElement(id="img_2", name="Figure 2", position=Position(x=4.91, y=1.8, width=3.5, height=3.0), src="fig2.png", original_name="fig2.png"),
            ShapeElement(id="cap_2", name="Caption 2", shape_type="textbox", position=Position(x=4.91, y=4.9, width=3.5, height=1.0), text=make_text_block("Figure 2: Vector Reconstruction\nDirect OOXML DrawingML fidelity comparison.", font_size=12.0, color="#94A3B8")),
            # Image 3
            ImageElement(id="img_3", name="Figure 3", position=Position(x=8.83, y=1.8, width=3.5, height=3.0), src="fig3.png", original_name="fig3.png"),
            ShapeElement(id="cap_3", name="Caption 3", shape_type="textbox", position=Position(x=8.83, y=4.9, width=3.5, height=1.0), text=make_text_block("Figure 3: Ablation Results\nStructural layout balance under visual feedback.", font_size=12.0, color="#94A3B8"))
        ]
    )

    pres = Presentation(
        name="image-heavy",
        size=SlideSize(width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT),
        slides=[s1],
        media_files=media_files
    )

    out_path = FIXTURES_DIR / "image-heavy.pptx"
    builder = PPTXBuilder()
    builder.build(pres, str(out_path))
    return out_path


def main():
    print("Generating test fixtures...")
    fixtures = [
        ("simple.pptx", create_simple_fixture),
        ("academic.pptx", create_academic_fixture),
        ("diagram.pptx", create_diagram_fixture),
        ("image-heavy.pptx", create_image_heavy_fixture)
    ]

    for name, gen_fn in fixtures:
        path = gen_fn()
        v = validate_pptx(path)
        print(f"[{name}] Generated: {path} ({path.stat().st_size} bytes, {v['slides']} slides, valid={v['valid']})")
        assert v["valid"] is True, f"Validation failed for {name}: {v['errors']}"

    print("All fixtures successfully generated and validated!")


if __name__ == "__main__":
    main()
