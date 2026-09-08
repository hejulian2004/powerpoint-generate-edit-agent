"""RemediationRunner Integration Test Suite (Task 7).

Verifies the production hardening of the visual self-healing runtime:
1. Confidence & criticality execution gating policy (>= 0.9 + CRITICAL)
2. Priority-based sorting (container/text sizing precedes global layout transforms)
3. Conflict detection and deduplication
4. Transaction rollback on quality score degradation
5. Configurable iteration limit enforcement
6. Successful multi-fix execution and metadata tracking
"""

import copy
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ElementStyleIR, FillStyle, TextContentIR, FontIR
)
from backend.ir.patch import HistoryManager
from backend.eval.remediation import (
    FixAction, FixActionType, DefectCategory, RemediationPlan
)
from backend.agent.remediation_runner import RemediationRunner
from backend.eval.layout_diff import LayoutDiffEngine


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

    # Plan with 3 actions:
    # 1. Critical with confidence 0.98 -> should run
    # 2. Critical with low confidence 0.50 -> should be filtered
    # 3. Structural (alignment) with confidence 0.85 -> should be filtered when only_critical=True
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

    plan = RemediationPlan(
        actions=[act_auto, act_low_conf, act_structural],
        has_critical=True
    )

    res = RemediationRunner.apply_plan(
        pres=pres,
        history=history,
        plan=plan,
        slide_id="slide_gate",
        only_critical=True
    )

    assert res["success"] is True
    assert res["applied_count"] == 1
    assert res["applied_records"][0]["args"]["element_id"] == "e_clip"
    assert e1.x == 1100.0
    # e2 should remain unchanged
    assert e2.x == 200.0


def test_priority_based_execution_sorting():
    """Verify that container resizing (prio 10) precedes viewport clamp (prio 9) and separation (prio 8)."""
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

    # Intentionally provide in reverse order: clamp (9) before resize (10)
    plan = RemediationPlan(actions=[act_clamp, act_resize], has_critical=True)

    res = RemediationRunner.apply_plan(pres, history, plan, slide_id="slide_prio", only_critical=True)

    assert res["success"] is True
    assert res["applied_count"] == 2
    # First applied action must be resize_container due to priority 10 > 9
    assert res["applied_records"][0]["action_type"] == "resize_container"
    assert res["applied_records"][1]["action_type"] == "clamp_viewport"


def test_conflict_resolution_deduplication():
    """Verify that when two actions touch the same target element, the higher-priority one wins."""
    pres = PresentationIR(title="Conflict Deck")
    slide = SlideIR(id="slide_conflict", slide_num=1, width=1280, height=720)
    elem = ShapeElementIR(id="conflict_e", x=100.0, y=100.0, width=100.0, height=100.0)
    slide.add_element(elem)
    pres.slides = [slide]

    history = HistoryManager()

    # Action 1: prio 10, confidence 0.95
    act1 = FixAction(
        action_type=FixActionType.RESIZE_CONTAINER,
        category=DefectCategory.CRITICAL,
        target_ids=["conflict_e"],
        parameters={"element_id": "conflict_e", "height": 180.0},
        reason="First fix",
        priority=10,
        confidence=0.95
    )
    # Action 2: prio 8, confidence 0.92 targeting SAME element
    act2 = FixAction(
        action_type=FixActionType.SEPARATE_ELEMENTS,
        category=DefectCategory.CRITICAL,
        target_ids=["conflict_e"],
        parameters={"element_id": "conflict_e", "x": 500.0},
        reason="Second fix conflicting with first",
        priority=8,
        confidence=0.92
    )

    plan = RemediationPlan(actions=[act2, act1], has_critical=True)
    res = RemediationRunner.apply_plan(pres, history, plan, slide_id="slide_conflict", only_critical=True)

    assert res["success"] is True
    assert res["applied_count"] == 1
    # Only act1 should execute
    assert res["applied_records"][0]["action_type"] == "resize_container"
    assert elem.height == 180.0
    assert elem.x == 100.0  # act2 skipped


def test_transaction_rollback_on_score_degradation():
    """Verify that if an action degrades layout score, transaction rolls back cleanly."""
    pres = PresentationIR(title="Degradation Deck")
    slide = SlideIR(id="slide_deg", slide_num=1, width=1280, height=720)
    e = ShapeElementIR(id="normal_e", x=100.0, y=100.0, width=100.0, height=100.0)
    slide.add_element(e)
    pres.slides = [slide]

    history = HistoryManager()
    before = copy.deepcopy(pres)
    initial_history_len = len(history.undo_stack)

    # Action pushes normal element outside the canvas (causing viewport clipping defect)
    act_bad = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["normal_e"],
        parameters={"element_id": "normal_e", "x": 1500.0},  # creates clipping defect!
        reason="Bad shift",
        priority=9,
        confidence=0.95
    )

    plan = RemediationPlan(actions=[act_bad], has_critical=True)
    res = RemediationRunner.apply_plan(pres, history, plan, slide_id="slide_deg", only_critical=True)

    assert res["success"] is False
    assert res["rolled_back"] is True
    # State restored
    assert pres == before
    assert pres.slides[0].elements[0].x == 100.0
    assert len(history.undo_stack) == initial_history_len


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

    # With max_iterations=3, should reject since visual_fix_iterations is already 3
    res = RemediationRunner.apply_plan(
        pres, history, plan, slide_id="slide_iter", only_critical=True, max_iterations=3
    )

    assert res["success"] is False
    assert "已达到最大自愈迭代次数限制" in res["error"]
    assert e.x == 1250.0  # unchanged


def test_telemetry_event_protocol():
    """Verify that apply_plan broadcasts structured visual_remediation telemetry events."""
    pres = PresentationIR(title="Telemetry Deck")
    slide = SlideIR(id="slide_telemetry", slide_num=1, width=1280, height=720)
    e = ShapeElementIR(id="e_tel", x=1220.0, y=100.0, width=100.0, height=100.0)
    slide.add_element(e)
    pres.slides = [slide]

    history = HistoryManager()
    events = []

    def on_event(ev):
        events.append(ev)

    act = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e_tel"],
        parameters={"element_id": "e_tel", "x": 1100.0},
        reason="Clamp within canvas",
        priority=9,
        confidence=0.98
    )
    plan = RemediationPlan(actions=[act], has_critical=True)

    res = RemediationRunner.apply_plan(
        pres, history, plan, slide_id="slide_telemetry", only_critical=True, on_event=on_event
    )

    assert res["success"] is True
    # Verify events
    assert len(events) >= 2
    phases = [ev.get("phase") for ev in events]
    assert "fixing" in phases
    assert "committed" in phases

    fixing_ev = next(ev for ev in events if ev.get("phase") == "fixing")
    assert fixing_ev["type"] == "visual_remediation"
    assert fixing_ev["slide_id"] == "slide_telemetry"
    assert fixing_ev["action"]["action_type"] == "clamp_viewport"

    committed_ev = next(ev for ev in events if ev.get("phase") == "committed")
    assert committed_ev["type"] == "visual_remediation"
    assert "quality_score_before" in committed_ev
    assert "quality_score_after" in committed_ev
    assert committed_ev["score_after"] >= committed_ev["score_before"]

