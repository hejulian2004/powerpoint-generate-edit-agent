"""FixPlanner Conflict Resolution & Priority Scheduling Suite.

Validates:
1. Priority-based sorting so high-priority fixes claim targets first (even if unsorted in input).
2. FixAction conflict detection and target deduplication.
3. Confidence and criticality threshold gating (>= 0.9 + CRITICAL).
4. Configurable auto-fix loop limit enforcement.
5. Structured telemetry event protocol.
"""

from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    TextContentIR, FontIR
)
from backend.ir.patch import HistoryManager
from backend.eval.remediation import (
    FixAction, FixActionType, DefectCategory, RemediationPlan
)
from backend.agent.remediation_runner import RemediationRunner


def test_remediation_conflict_resolution_and_deduplication():
    """Verifies that mutually conflicting actions on the same element are deduplicated in priority order."""
    slide = SlideIR(id="slide_conflict", slide_num=1)
    s1 = ShapeElementIR(id="e1", x=0.0, y=0.0, width=100.0, height=100.0)
    s2 = ShapeElementIR(id="e2", x=50.0, y=50.0, width=100.0, height=100.0)
    slide.add_element(s1)
    slide.add_element(s2)

    # Two competing actions both targeting "e1"
    a1 = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e1"],
        parameters={"element_id": "e1", "x": 60.0, "y": 60.0},
        reason="Clamp e1 to margin",
        priority=10
    )
    a2 = FixAction(
        action_type=FixActionType.SEPARATE_ELEMENTS,
        category=DefectCategory.CRITICAL,
        target_ids=["e1"],
        parameters={"element_id": "e1", "x": 200.0},
        reason="Shift e1 away",
        priority=5
    )
    a3 = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e2"],
        parameters={"element_id": "e2", "x": 100.0, "y": 100.0},
        reason="Clamp e2",
        priority=8
    )

    # Intentionally unsorted input: a2 (priority 5) precedes a1 (priority 10)
    # Verifies that _resolve_conflicts internally sorts by priority so a1 wins over a2
    actions = [a2, a1, a3]
    safe = RemediationRunner._resolve_conflicts(slide, actions)

    # Only a1 (priority 10 for e1) and a3 (priority 8 for e2) should survive; a2 should be dropped
    assert len(safe) == 2
    assert safe[0] is a1
    assert safe[1] is a3
    assert a2 not in safe


def test_confidence_and_criticality_gating():
    """Verify that only_critical=True strictly executes actions with category=CRITICAL and confidence >= 0.9."""
    pres = PresentationIR(title="Gating Deck")
    slide = SlideIR(id="slide_gate", slide_num=1, width=1280, height=720)
    e1 = ShapeElementIR(id="e_clip", x=1250.0, y=100.0, width=100.0, height=100.0)
    e2 = ShapeElementIR(id="e_align", x=200.0, y=200.0, width=150.0, height=100.0)
    slide.add_element(e1)
    slide.add_element(e2)
    pres.slides = [slide]

    history = HistoryManager()

    act_auto = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e_clip"],
        parameters={"element_id": "e_clip", "x": 1100.0, "y": 100.0, "width": 100.0, "height": 100.0},
        reason="Fix clipping",
        priority=9,
        confidence=0.98,
        source="geometry_rule"
    )
    act_low_conf = FixAction(
        action_type=FixActionType.SEPARATE_ELEMENTS,
        category=DefectCategory.CRITICAL,
        target_ids=["e_align"],
        parameters={"element_id": "e_align", "x": 300.0},
        reason="Low confidence shift",
        priority=8,
        confidence=0.50,
        source="heuristic"
    )
    act_structural = FixAction(
        action_type=FixActionType.ALIGN_ELEMENTS,
        category=DefectCategory.STRUCTURAL,
        target_ids=["e_align"],
        parameters={"element_ids": ["e_align"], "alignment": "top"},
        reason="Advisory alignment",
        priority=2,
        confidence=0.85,
        source="geometry_rule"
    )

    plan = RemediationPlan(actions=[act_auto, act_low_conf, act_structural], has_critical=True)
    res = RemediationRunner.apply_plan(pres, history, plan, slide_id="slide_gate", only_critical=True)

    assert res["success"] is True
    assert res["applied_count"] == 1
    assert res["applied_records"][0]["args"]["element_id"] == "e_clip"
    assert e1.x == 1100.0
    assert e2.x == 200.0


def test_priority_based_execution_sorting():
    """Verify that container resizing (prio 10) precedes viewport clamp (prio 9)."""
    pres = PresentationIR(title="Priority Deck")
    slide = SlideIR(id="slide_prio", slide_num=1, width=1280, height=720)
    e_text = TextElementIR(
        id="text_elem", x=100.0, y=100.0, width=200.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Long text content", font=FontIR(size=18.0))
    )
    e_box = ShapeElementIR(id="box_clip", x=1220.0, y=100.0, width=100.0, height=100.0)
    slide.add_element(e_text)
    slide.add_element(e_box)
    pres.slides = [slide]

    history = HistoryManager()

    act_clamp = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["box_clip"],
        parameters={"element_id": "box_clip", "x": 1150.0},
        reason="Clamp",
        priority=9,
        confidence=0.98
    )
    act_resize = FixAction(
        action_type=FixActionType.RESIZE_CONTAINER,
        category=DefectCategory.CRITICAL,
        target_ids=["text_elem"],
        parameters={"element_id": "text_elem", "height": 90.0},
        reason="Resize container",
        priority=10,
        confidence=0.96
    )

    # Intentionally provided in reverse priority order
    plan = RemediationPlan(actions=[act_clamp, act_resize], has_critical=True)
    res = RemediationRunner.apply_plan(pres, history, plan, slide_id="slide_prio", only_critical=True)

    assert res["success"] is True
    assert res["applied_count"] == 2
    assert res["applied_records"][0]["action_type"] == "resize_container"
    assert res["applied_records"][1]["action_type"] == "clamp_viewport"


def test_configurable_iteration_limit():
    """Verify that apply_plan respects max_visual_iterations."""
    pres = PresentationIR(title="Iteration Limit Deck")
    slide = SlideIR(id="slide_iter", slide_num=1, width=1280, height=720)
    e = ShapeElementIR(id="e_iter", x=1250.0, y=100.0, width=100.0, height=100.0)
    slide.add_element(e)
    pres.slides = [slide]
    pres.metadata["visual_fix_iterations"] = 3

    history = HistoryManager()

    act = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e_iter"],
        parameters={"element_id": "e_iter", "x": 1100.0},
        reason="Clamp",
        priority=9,
        confidence=0.95
    )
    plan = RemediationPlan(actions=[act], has_critical=True)

    res = RemediationRunner.apply_plan(
        pres, history, plan, slide_id="slide_iter", only_critical=True, max_iterations=3
    )

    assert res["success"] is False
    assert "已达到最大自愈迭代次数限制" in res["error"]
    assert e.x == 1250.0
