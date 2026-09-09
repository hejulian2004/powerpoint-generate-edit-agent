"""Tests for Visual Self-Healing Closed Loop (PR12 Test 5)."""

from pathlib import Path

from backend.evaluation.evaluator import RuleBasedEvaluator
from backend.evaluation.repair import evaluate_and_repair
from backend.evaluation.schema import IssueSeverity, IssueType, VisualIssue
from backend.evaluation.screenshot import FallbackScreenshotBackend, ScreenshotRenderer
from backend.layout.schema import (
    Canvas,
    DeckLayoutSpec,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from backend.slidespec.schema import VisualIntent


def test_self_healing_loop_healthy_deck(tmp_path: Path) -> None:
    """Verify that a cleanly spaced deck converges on iteration 1 without unnecessary patches."""
    healthy_deck = DeckLayoutSpec(
        title="Healthy Presentation",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_clean",
                slide_index=1,
                visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
                elements=[
                    LayoutElement(
                        element_id="title",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=50.0, width=900.0, height=70.0),
                        style=ElementStyle(text=TextStyle(font_size=28.0)),
                        content="Clean Academic Presentation Title",
                    ),
                    LayoutElement(
                        element_id="body",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=160.0, width=900.0, height=350.0),
                        style=ElementStyle(text=TextStyle(font_size=18.0)),
                        content="Key takeaway point 1\nKey takeaway point 2\nKey takeaway point 3",
                    ),
                ],
            )
        ],
    )

    out_pptx = tmp_path / "healthy.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    result = evaluate_and_repair(
        deck_layout=healthy_deck,
        output_pptx_path=out_pptx,
        screenshot_renderer=renderer,
        max_iterations=3,
    )

    assert result.converged is True
    assert result.iterations_run == 1
    assert len(result.history) == 1
    assert len(result.history[0].patches_applied) == 0
    assert out_pptx.is_file()


def test_self_healing_loop_repairs_overflow_and_converges(tmp_path: Path) -> None:
    """Test 5: LayoutSpec -> PPTX -> PNG -> Issue -> Patch -> Patched LayoutSpec."""
    # Create a slide with canvas overflow (x=1220 on width=1280, width=150 extends past boundary)
    flawed_deck = DeckLayoutSpec(
        title="Flawed Deck for Self Healing",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_repair",
                slide_index=1,
                visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
                elements=[
                    LayoutElement(
                        element_id="title_main",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=50.0, width=900.0, height=70.0),
                        style=ElementStyle(text=TextStyle(font_size=28.0)),
                        content="Pipeline Architecture",
                    ),
                    LayoutElement(
                        element_id="overflowing_card",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=1200.0, y=200.0, width=160.0, height=120.0),
                        style=ElementStyle(text=TextStyle(font_size=16.0)),
                        content="Card pushed off canvas boundary",
                    ),
                ],
            )
        ],
    )

    out_pptx = tmp_path / "repaired.pptx"
    shots_dir = tmp_path / "repaired_shots"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    result = evaluate_and_repair(
        deck_layout=flawed_deck,
        output_pptx_path=out_pptx,
        output_screenshots_dir=shots_dir,
        screenshot_renderer=renderer,
        max_iterations=3,
    )

    # Must converge
    assert result.converged is True
    assert result.iterations_run >= 1

    # Verify that patches were applied during the process
    total_patches = sum(len(h.patches_applied) for h in result.history)
    assert total_patches >= 1
    applied_ops = [p.operation.value for h in result.history for p in h.patches_applied]
    assert "CLAMP_TO_CANVAS" in applied_ops

    # Final screenshots and PPTX must exist
    assert out_pptx.is_file()
    assert len(result.final_screenshot_paths) >= 1
    assert all(Path(p).is_file() for p in result.final_screenshot_paths)


def test_self_healing_loop_respects_max_iterations_bound(tmp_path: Path) -> None:
    """Verify that loop strictly terminates when max_iterations is reached."""
    # Stubborn flawed deck
    stubborn_deck = DeckLayoutSpec(
        title="Stubborn Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_stubborn",
                slide_index=1,
                visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
                elements=[
                    LayoutElement(
                        element_id="stubborn_box",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=1250.0, y=100.0, width=200.0, height=50.0),
                        content="Extreme overflow",
                    )
                ],
            )
        ],
    )

    out_pptx = tmp_path / "stubborn.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    result = evaluate_and_repair(
        deck_layout=stubborn_deck,
        output_pptx_path=out_pptx,
        screenshot_renderer=renderer,
        max_iterations=2,
    )

    assert result.iterations_run <= 2
    assert len(result.history) <= 2


def test_generate_patches_for_all_issue_types() -> None:
    """Verify generate_patches_for_issues produces appropriate patches for all defect categories."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="slide_patches_gen",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="el_overflow",
                element_type=ElementType.TEXT,
                geometry=Rect(x=1200, y=100, width=200, height=50),
                content="Text",
            ),
            LayoutElement(
                element_id="el_text_over",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100, y=100, width=500, height=30),
                style=ElementStyle(text=TextStyle(font_size=20.0)),
                content="Very long text " * 10,
            ),
            LayoutElement(
                element_id="el_tiny_fig",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=100, y=300, width=100, height=80),
                content={"figure_id": "fig_1"},
            ),
            LayoutElement(
                element_id="el_distorted_fig",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=100, y=400, width=600, height=60),
                content={"figure_id": "fig_2"},
            ),
            LayoutElement(
                element_id="el_dense",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100, y=500, width=200, height=80),
                content="Dense text",
            ),
        ],
    )

    issues = [
        VisualIssue(slide="slide_patches_gen", issue=IssueType.OVERFLOW, element="el_overflow", description="out"),
        VisualIssue(slide="slide_patches_gen", issue=IssueType.TEXT_OVERFLOW, element="el_text_over", description="txt"),
        VisualIssue(slide="slide_patches_gen", issue=IssueType.TOO_SMALL, element="el_tiny_fig", description="small"),
        VisualIssue(slide="slide_patches_gen", issue=IssueType.WRONG_SCALE, element="el_distorted_fig", description="scale"),
        VisualIssue(slide="slide_patches_gen", issue=IssueType.TEXT_DENSITY_HIGH, element="el_dense", description="dense"),
    ]

    patches = generate_patches_for_issues(issues, slide)
    assert len(patches) == 5
    ops = {p.target_element: p.operation.value for p in patches}
    assert ops["el_overflow"] == "CLAMP_TO_CANVAS"
    assert ops["el_text_over"] == "CHANGE_FONT_SIZE"
    assert ops["el_tiny_fig"] == "RESIZE"
    assert ops["el_distorted_fig"] == "RESIZE"
    assert ops["el_dense"] == "CHANGE_FONT_SIZE"


def test_overlap_repair_direction_and_separation_axis() -> None:
    """Verify OVERLAP repair shifts elements along the minimal separation axis in the correct direction."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="slide_overlap_dir",
        slide_index=1,
        visual_intent=VisualIntent.TWO_COLUMN_CONTRAST,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="col_left",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100, y=100, width=300, height=400),
                content="Left",
            ),
            LayoutElement(
                element_id="col_right",
                element_type=ElementType.TEXT,
                geometry=Rect(x=380, y=100, width=300, height=400),
                content="Right",
            ),
        ],
    )

    # Collision where overlap width is 20px, height is 400px (horizontal collision)
    horiz_issue = VisualIssue(
        slide="slide_overlap_dir",
        issue=IssueType.OVERLAP,
        element="col_right",
        description="Collision with col_left",
        evidence={
            "element_a": "col_left",
            "element_b": "col_right",
            "intersection": {"width": 20.0, "height": 400.0},
        },
    )

    patches = generate_patches_for_issues([horiz_issue], slide)
    assert len(patches) == 1
    assert patches[0].operation.value == "MOVE"
    # Must shift along X axis (dx > 0 since col_right is to the right of col_left)
    assert patches[0].parameters["dx"] > 0
    assert patches[0].parameters["dy"] == 0.0


def test_tall_figure_aspect_ratio_repair_expands_width() -> None:
    """Verify that an excessively tall figure (aspect ratio < 0.25) expands width rather than collapsing height."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="slide_tall_fig",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="tall_fig",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=100, y=100, width=60.0, height=400.0),  # ratio = 0.15
                content={"figure_id": "fig_strip"},
            )
        ],
    )

    issue = VisualIssue(
        slide="slide_tall_fig",
        issue=IssueType.WRONG_SCALE,
        element="tall_fig",
        description="Distorted aspect ratio",
    )

    patches = generate_patches_for_issues([issue], slide)
    assert len(patches) == 1
    assert patches[0].operation.value == "RESIZE"
    # Must expand width to fix ratio
    assert "width" in patches[0].parameters
    assert patches[0].parameters["width"] > 100.0


def test_severe_text_overflow_proportional_reduction() -> None:
    """Verify that severe text overflow computes proportional font size reduction directly."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="slide_severe",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="overflow_title",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100, y=50, width=600, height=20),
                style=ElementStyle(text=TextStyle(font_size=24.0)),
                content="Long title",
            )
        ],
    )

    issue = VisualIssue(
        slide="slide_severe",
        issue=IssueType.TEXT_OVERFLOW,
        element="overflow_title",
        description="Text overflow",
        evidence={"required_height": 200.0, "actual_height": 20.0},
    )

    patches = generate_patches_for_issues([issue], slide)
    assert len(patches) == 1
    assert patches[0].operation.value == "CHANGE_FONT_SIZE"
    # Proportional font size reduction should jump directly to a small font size (e.g. 8.0 - 12.0) rather than just -2pt
    assert "font_size" in patches[0].parameters
    assert patches[0].parameters["font_size"] <= 12.0


def test_overlap_shift_left_and_top_margins_clamped() -> None:
    """Verify that shifting overlapping elements never pushes them into negative coordinates."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="slide_edge_overlap",
        slide_index=1,
        visual_intent=VisualIntent.TWO_COLUMN_CONTRAST,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="left_edge_el",
                element_type=ElementType.TEXT,
                geometry=Rect(x=10.0, y=10.0, width=200, height=200),
                content="Edge Left",
            ),
            LayoutElement(
                element_id="right_el",
                element_type=ElementType.TEXT,
                geometry=Rect(x=150.0, y=10.0, width=200, height=200),
                content="Edge Right",
            ),
        ],
    )

    issue = VisualIssue(
        slide="slide_edge_overlap",
        issue=IssueType.OVERLAP,
        element="left_edge_el",
        description="Collision near left margin",
        evidence={
            "element_a": "left_edge_el",
            "element_b": "right_el",
            "intersection": {"width": 60.0, "height": 200.0},
        },
    )

    patches = generate_patches_for_issues([issue], slide)
    assert len(patches) == 1
    # Desired shift would be -(60 + 8) = -68, which from x=10 would be x=-58
    # Clamped to canvas left bound so 10.0 + dx >= 0.0 and dx <= 0.0 (never invert into right_el)
    dx = patches[0].parameters["dx"]
    assert 10.0 + dx >= 0.0
    assert dx <= 0.0


def test_resize_height_clamp_at_bottom_margin() -> None:
    """Verify expanding height near canvas bottom never pushes element outside canvas."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="slide_bottom_edge",
        slide_index=1,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="bottom_box",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=650.0, width=500.0, height=40.0),
                style=ElementStyle(text=TextStyle(font_size=8.0)),  # already small, will trigger height expansion
                content="Bottom overflow",
            )
        ],
    )

    issue = VisualIssue(
        slide="slide_bottom_edge",
        issue=IssueType.TEXT_OVERFLOW,
        element="bottom_box",
        description="Overflow near bottom edge",
        evidence={"required_height": 100.0, "actual_height": 40.0},
    )

    patches = generate_patches_for_issues([issue], slide)
    assert len(patches) == 1
    assert patches[0].operation.value == "RESIZE"
    # Canvas height is 720, y is 650, margin is 20 -> max allowed height is 720 - 650 - 20 = 50
    new_h = patches[0].parameters["height"]
    assert 650.0 + new_h <= 700.0


def test_repair_convergence_stops_when_no_further_improvements(tmp_path: Path) -> None:
    """Must-have Test 3: Repair loop terminates within <= 3 iterations and stops as soon as oscillation or no-improvement is detected."""
    # Deck with unfixable or fixed issue
    deck = DeckLayoutSpec(
        title="Convergence Test Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_conv",
                slide_index=1,
                visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
                elements=[
                    LayoutElement(
                        element_id="title",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=50.0, width=900.0, height=70.0),
                        content="Normal Title",
                    )
                ],
            )
        ],
    )

    out_pptx = tmp_path / "conv_test.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        screenshot_renderer=renderer,
        max_iterations=3,
    )

    assert res.iterations_run <= 3
    assert res.converged is True


def test_repair_loop_fails_on_vlm_timeout(tmp_path: Path) -> None:
    """Reviewer P1: VLM API timeout must set converged=False, evaluation_failed=True, never false-converged."""
    from backend.evaluation.evaluator import OpenAICompatibleVisionEvaluator

    def timeout_client(payload):
        raise TimeoutError("Simulated OpenAI API gateway timeout")

    failing_evaluator = OpenAICompatibleVisionEvaluator(api_key="sk-test", client_fn=timeout_client)

    deck = DeckLayoutSpec(
        title="Timeout Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_to",
                slide_index=1,
                visual_intent=VisualIntent.TITLE_HERO,
                elements=[
                    LayoutElement(
                        element_id="title",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=50.0, width=900.0, height=70.0),
                        content="Test Title",
                    )
                ],
            )
        ],
    )

    out_pptx = tmp_path / "timeout.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        evaluator=failing_evaluator,
        screenshot_renderer=renderer,
        max_iterations=3,
    )

    assert res.converged is False
    assert res.evaluation_failed is True
    assert res.stop_reason == "evaluation_failed"
    assert "timeout" in str(res.error).lower()


def test_repair_loop_fails_on_vlm_malformed_json(tmp_path: Path) -> None:
    """Reviewer P1: VLM returning malformed/unparseable JSON must set converged=False, evaluation_failed=True."""
    from backend.evaluation.evaluator import OpenAICompatibleVisionEvaluator

    def malformed_json_client(payload):
        return {"choices": [{"message": {"content": "Sorry, I am an AI and cannot format this in JSON."}}]}

    failing_evaluator = OpenAICompatibleVisionEvaluator(api_key="sk-test", client_fn=malformed_json_client)

    deck = DeckLayoutSpec(
        title="Malformed JSON Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_mal",
                slide_index=1,
                visual_intent=VisualIntent.TITLE_HERO,
                elements=[
                    LayoutElement(
                        element_id="title",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=50.0, width=900.0, height=70.0),
                        content="Test Title",
                    )
                ],
            )
        ],
    )

    out_pptx = tmp_path / "malformed.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        evaluator=failing_evaluator,
        screenshot_renderer=renderer,
        max_iterations=3,
    )

    assert res.converged is False
    assert res.evaluation_failed is True
    assert res.stop_reason == "evaluation_failed"
    assert "not valid json" in str(res.error).lower()


def test_repair_rollback_and_stop_early_on_worsening(tmp_path: Path) -> None:
    """Reviewer P1: If iteration 2 introduces more errors than iteration 1, loop rolls back to iteration 1 deck and stops."""
    from backend.evaluation.evaluator import VisualEvaluator

    # Mock evaluator that reports 2 errors on iteration 1, and 3 different errors on iteration 2
    class DegradingEvaluator(VisualEvaluator):
        def __init__(self):
            self.call_count = 0

        def evaluate(self, slide_image, layout_spec):
            self.call_count += 1
            if self.call_count == 1:
                return [
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el_overflow",
                        description="Initial overflow error",
                    ),
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.TEXT_OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el_text",
                        description="Initial text overflow error",
                    ),
                ]
            else:
                # Iteration 2 produces 3 worse errors
                return [
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el1",
                        description="Worse overflow 1",
                    ),
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el2",
                        description="Worse overflow 2",
                    ),
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERLAP,
                        severity=IssueSeverity.ERROR,
                        element="el3",
                        description="Worse overlap 3",
                    ),
                ]

    deck = DeckLayoutSpec(
        title="Worsening Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="slide_worse",
                slide_index=1,
                visual_intent=VisualIntent.TITLE_HERO,
                elements=[
                    LayoutElement(
                        element_id="el_overflow",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=1200.0, y=100.0, width=200.0, height=50.0),
                        content="Overflow",
                    ),
                    LayoutElement(
                        element_id="el_text",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=100.0, y=200.0, width=300.0, height=30.0),
                        content="Text overflow content",
                    ),
                ],
            )
        ],
    )

    out_pptx = tmp_path / "worse.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())
    evaluator = DegradingEvaluator()

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        evaluator=evaluator,
        screenshot_renderer=renderer,
        max_iterations=3,
    )

    # Must stop at iteration 2 due to worsening (not continuing to iteration 3)
    assert res.iterations_run == 2
    assert res.stop_reason == "worsened"
    assert res.converged is False


def test_repair_final_output_is_best_deck_when_last_iteration_worsens(tmp_path: Path) -> None:
    """Reviewer P1: If the last allowed iteration creates a worse layout, final output PPTX must still render best_deck."""
    import pptx
    from backend.evaluation.evaluator import VisualEvaluator

    recorded_renders: list[float] = []

    def mock_renderer(deck: DeckLayoutSpec, path: Path):
        # Record x-coordinate of el_test across renders
        x_val = deck.slides[0].elements[0].geometry.x
        recorded_renders.append(x_val)
        # Create valid empty presentation file
        prs = pptx.Presentation()
        prs.save(str(path))

    class TwoStepWorseningEvaluator(VisualEvaluator):
        def __init__(self):
            self.eval_count = 0

        def evaluate(self, slide_image, layout_spec):
            self.eval_count += 1
            if self.eval_count == 1:
                # Iteration 1: 1 error
                return [
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el_test",
                        description="Single error",
                    )
                ]
            else:
                # Iteration 2: 2 errors (worse)
                return [
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el_test",
                        description="Error 1",
                    ),
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERLAP,
                        severity=IssueSeverity.ERROR,
                        element="el_test",
                        description="Error 2",
                    ),
                ]

    deck = DeckLayoutSpec(
        title="Last Step Worse Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="s1",
                slide_index=1,
                visual_intent=VisualIntent.TITLE_HERO,
                elements=[
                    LayoutElement(
                        element_id="el_test",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=1200.0, y=100.0, width=200.0, height=50.0),
                        content="Test",
                    )
                ],
            )
        ],
    )

    out_pptx = tmp_path / "last_step.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        evaluator=TwoStepWorseningEvaluator(),
        renderer_fn=mock_renderer,
        screenshot_renderer=renderer,
        max_iterations=2,
    )

    # Initial x is 1200.0 (Iteration 1: 1 error -> best deck).
    # Iteration 1 patches x to clamped ~1056.0.
    # Iteration 2 evaluates the clamped deck, sees 2 errors -> worsening!
    # Final render MUST render best_deck (x=1200.0), not the worse state.
    final_render_x = recorded_renders[-1]
    assert final_render_x == 1200.0
    assert res.stop_reason == "worsened"


def test_max_iterations_one_preserves_accepted_patches(tmp_path: Path) -> None:
    """Reviewer High Bug 1: Running with max_iterations=1 must preserve accepted patches, not discard them."""
    deck = DeckLayoutSpec(
        title="Single Iteration Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="s1",
                slide_index=1,
                visual_intent=VisualIntent.TITLE_HERO,
                elements=[
                    LayoutElement(
                        element_id="title",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=80.0, y=50.0, width=900.0, height=70.0),
                        content="Title",
                    ),
                    LayoutElement(
                        element_id="overflowing_card",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=1200.0, y=200.0, width=160.0, height=120.0),  # extends to 1360 (> 1280)
                        content="Overflowing card",
                    ),
                ],
            )
        ],
    )

    out_pptx = tmp_path / "max_iter_one.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        screenshot_renderer=renderer,
        max_iterations=1,
    )

    # Must be converged or have fixed the overflow in the final output
    assert res.iterations_run == 1
    assert res.converged is True
    assert len(res.history[0].patches_applied) == 1
    # Check that final issues do NOT contain overflow
    overflow_issues = [iss for iss in res.final_issues if iss.issue_type == IssueType.OVERFLOW]
    assert len(overflow_issues) == 0


def test_final_evaluation_crash_marks_failed(tmp_path: Path) -> None:
    """Reviewer High Bug 2: Unhandled exception in final post-loop evaluation marks evaluation_failed=True, converged=False."""
    from backend.evaluation.evaluator import VisualEvaluator
    from backend.evaluation.schema import VisualEvaluationError

    class CrashOnFinalEvaluator(VisualEvaluator):
        def __init__(self):
            self.eval_count = 0

        def evaluate(self, slide_image, layout_spec):
            self.eval_count += 1
            if self.eval_count == 1:
                return [
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element="el_overflow",
                        description="Error to trigger patch",
                    )
                ]
            else:
                # Crash during post-loop evaluation
                raise VisualEvaluationError("VLM connection dropped during final verification")

    deck = DeckLayoutSpec(
        title="Final Crash Deck",
        canvas=Canvas(width=1280, height=720),
        slides=[
            LayoutSpec(
                slide_id="s1",
                slide_index=1,
                visual_intent=VisualIntent.TITLE_HERO,
                elements=[
                    LayoutElement(
                        element_id="el_overflow",
                        element_type=ElementType.TEXT,
                        geometry=Rect(x=1200.0, y=100.0, width=200.0, height=50.0),
                        content="Crash test",
                    )
                ],
            )
        ],
    )

    out_pptx = tmp_path / "final_crash.pptx"
    renderer = ScreenshotRenderer(backend=FallbackScreenshotBackend())

    res = evaluate_and_repair(
        deck_layout=deck,
        output_pptx_path=out_pptx,
        evaluator=CrashOnFinalEvaluator(),
        screenshot_renderer=renderer,
        max_iterations=1,
    )

    assert res.converged is False
    assert res.evaluation_failed is True
    assert res.stop_reason == "evaluation_failed"
    assert "dropped during final verification" in str(res.error)


def test_overlap_repair_does_not_invert_direction_near_margin() -> None:
    """Reviewer Medium Bug 5: Overlap repair heuristic when element is near or past margin must not invert direction."""
    from backend.evaluation.repair import generate_patches_for_issues

    slide = LayoutSpec(
        slide_id="s1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[
            # el_left is at x=10 (inside margin=20), el_right is at x=20
            LayoutElement(
                element_id="el_left",
                element_type=ElementType.TEXT,
                geometry=Rect(x=10.0, y=100.0, width=50.0, height=50.0),
                content="Left",
            ),
            LayoutElement(
                element_id="el_right",
                element_type=ElementType.TEXT,
                geometry=Rect(x=20.0, y=100.0, width=50.0, height=50.0),
                content="Right",
            ),
        ],
    )

    issue = VisualIssue(
        slide="s1",
        issue=IssueType.OVERLAP,
        severity=IssueSeverity.ERROR,
        element="el_left",
        description="Overlap between el_left and el_right",
        evidence={
            "element_a": "el_left",
            "element_b": "el_right",
            "intersection": {"width": 40.0, "height": 50.0},
        },
    )

    patches = generate_patches_for_issues([issue], slide)
    assert len(patches) == 1
    # desired_dx was negative (move further left away from el_right).
    # Clamping must ensure dx <= 0.0, never positive (which would move into el_right)!
    dx = patches[0].parameters.get("dx", 0.0)
    assert dx <= 0.0






