"""PR6.5 Repair Agent Integration Tests.

Validates:
1. FidelityRemediationGenerator generates FIX_GEOMETRY, FIX_FONT, FIX_COLOR, FIX_THEME_REF.
2. RemediationRunner.apply_fidelity_repair executes repairs inside PresentationTransaction.
3. Transaction rollback protection if fidelity score degrades.
4. Semantic instruction resolution: targeting 'title' and resolving theme color tokens.
"""

import copy
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ElementStyleIR, FillStyle, BorderStyle, FontIR, TextContentIR, ParagraphIR, RunIR
)
from backend.ir.patch import HistoryManager
from backend.eval.remediation import (
    FixActionType, DefectCategory, FidelityRemediationGenerator
)
from backend.eval.fidelity import FidelityEvaluator
from backend.agent.remediation_runner import RemediationRunner
from backend.agent.action import ActionResolver, AgentAction


def _create_baseline_presentation():
    pres = PresentationIR(title="Baseline Template Presentation")
    slide = SlideIR(id="slide_baseline_1", slide_num=1, title="Executive Overview")

    # Title
    title = TextElementIR(
        id="elem_base_title",
        name="Slide Title",
        x=80.0,
        y=50.0,
        width=700.0,
        height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Quarterly Performance Review",
            font=FontIR(name="Segoe UI", size=26.0, bold=True, color="#0F172A")
        )
    )
    slide.add_element(title)

    # Subtitle
    subtitle = TextElementIR(
        id="elem_base_subtitle",
        name="Subtitle",
        x=80.0,
        y=110.0,
        width=600.0,
        height=30.0,
        text_content=TextContentIR.from_plain_text(
            "Strategic Initiatives and Financial Metrics",
            font=FontIR(name="Segoe UI", size=16.0, color="#64748B")
        )
    )
    slide.add_element(subtitle)

    # KPI Card
    card = ShapeElementIR(
        id="elem_base_kpi_card",
        name="KPI Card Container",
        shape_type="roundRect",
        x=80.0,
        y=160.0,
        width=300.0,
        height=140.0,
        style=ElementStyleIR(
            fill=FillStyle(type="solid", color="#2563EB"),
            border=BorderStyle(style="solid", color="#1D4ED8", width=1.5),
            radius=8.0
        )
    )
    slide.add_element(card)

    pres.slides.append(slide)
    return pres


def test_fidelity_remediation_plan_generation():
    """Verifies that deliberate geometric, typographic, and color drifts generate targeted FixActions."""
    pres = _create_baseline_presentation()
    baseline_slide = pres.slides[0]

    # Create mutated slide with 3 distinct drifts
    mutated_slide = copy.deepcopy(baseline_slide)

    # 1. Geometry drift on KPI card (> 2px)
    mut_card = mutated_slide.get_element("elem_base_kpi_card")
    mut_card.x = 120.0  # +40px drift
    mut_card.y = 190.0  # +30px drift

    # 2. Typography drift on Title
    mut_title = mutated_slide.get_element("elem_base_title")
    mut_title.text_content.paragraphs[0].runs[0].font.name = "Times New Roman"
    mut_title.text_content.paragraphs[0].runs[0].font.size = 14.0

    # 3. Color drift on KPI card fill
    mut_card.style.fill.color = "#DC2626"

    # Generate plan
    plan = FidelityRemediationGenerator.generate_plan(baseline_slide, mutated_slide)

    assert plan.has_critical is True
    action_types = [a.action_type for a in plan.actions]
    assert FixActionType.FIX_GEOMETRY in action_types
    assert FixActionType.FIX_FONT in action_types
    assert FixActionType.FIX_COLOR in action_types

    # Validate action parameters
    geom_act = next(a for a in plan.actions if a.action_type == FixActionType.FIX_GEOMETRY)
    assert geom_act.parameters["x"] == 80.0
    assert geom_act.parameters["y"] == 160.0
    assert geom_act.confidence >= 0.9

    font_act = next(a for a in plan.actions if a.action_type == FixActionType.FIX_FONT)
    assert font_act.parameters["font_family"] == "Segoe UI"
    assert font_act.parameters["font_size"] == 26.0

    color_act = next(a for a in plan.actions if a.action_type == FixActionType.FIX_COLOR)
    assert color_act.parameters["fill_color"] == "#2563EB"


def test_remediation_runner_apply_fidelity_repair_success():
    """Verifies that apply_fidelity_repair automatically restores degraded slide to >=95% fidelity."""
    pres = _create_baseline_presentation()
    baseline_slide = copy.deepcopy(pres.slides[0])
    history = HistoryManager()

    # Introduce drift on active presentation
    active_slide = pres.slides[0]
    active_card = active_slide.get_element("elem_base_kpi_card")
    active_card.x = 150.0  # 70px drift
    active_card.style.fill.color = "#FF0000"

    score_before = FidelityEvaluator.evaluate_slides(baseline_slide, active_slide)
    assert score_before.total < 95.0

    # Execute fidelity self-healing loop
    res = RemediationRunner.apply_fidelity_repair(
        pres=pres,
        history=history,
        baseline_slide=baseline_slide,
        current_slide_id=active_slide.id
    )

    assert res["success"] is True
    assert res["rolled_back"] is False
    assert res["score_after"] > res["score_before"]
    assert res["score_after"] >= 95.0

    # Verify element attributes are restored on slide
    repaired_card = active_slide.get_element("elem_base_kpi_card")
    assert abs(repaired_card.x - 80.0) < 1.0
    assert repaired_card.style.fill.color == "#2563EB"


def test_remediation_runner_rollback_on_degradation():
    """Verifies that an atomic transaction automatically rolls back if repair degrades fidelity score."""
    pres = _create_baseline_presentation()
    baseline_slide = copy.deepcopy(pres.slides[0])
    history = HistoryManager()

    active_slide = pres.slides[0]

    # Evaluate baseline score
    score_orig = FidelityEvaluator.evaluate_slides(baseline_slide, active_slide)
    assert score_orig.total >= 95.0

    # Intentionally trigger an update that lowers score inside a transaction
    with pres.transaction("malicious_or_faulty_repair", history=history) as tx:
        active_slide.get_element("elem_base_kpi_card").x = 900.0  # massive drift
        score_after = FidelityEvaluator.evaluate_slides(baseline_slide, active_slide)
        if score_after.total < score_orig.total:
            tx.rollback("Score degraded")

    # Verify rollback restored original position
    assert active_slide.get_element("elem_base_kpi_card").x == 80.0


def test_semantic_instruction_theme_preservation():
    """Verifies user instruction 'change title to blue keeping template style' targets title & resolves theme token."""
    pres = _create_baseline_presentation()

    # User intention mapped to AgentAction
    action = AgentAction(
        action_type="format_text",
        target="title",
        parameters={
            "font_color": "accent1"
        }
    )

    tool_call = ActionResolver.action_to_tool_call(action, pres)
    assert tool_call is not None
    assert tool_call["name"] == "format_text"
    # Target should be resolved to the slide title element ID
    assert tool_call["arguments"]["element_id"] == "elem_base_title"
    # 'accent1' should be resolved to standard theme accent color hex (e.g. #4472C4 or #2563EB)
    assert tool_call["arguments"]["font_color"].startswith("#")

    # Execute tool call
    from backend.agent.tools import tools
    history = HistoryManager()
    res = tools.execute(tool_call["name"], tool_call["arguments"], pres, history)
    assert res["success"] is True

    # Title element text color updated
    title_elem = pres.slides[0].get_element("elem_base_title")
    curr_font_color = title_elem.text_content.paragraphs[0].runs[0].font.color
    assert curr_font_color == tool_call["arguments"]["font_color"]
