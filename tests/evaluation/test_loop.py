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
    # Clamped to margin - x = 20 - 10 = +10, so x + dx >= 20.0
    dx = patches[0].parameters["dx"]
    assert 10.0 + dx >= 20.0


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



