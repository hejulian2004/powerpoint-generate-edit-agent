"""Visual Self-Healing Loop and Deterministic Repair Engine (PR12).

Orchestrates the closed-loop evaluation and repair workflow:
LayoutSpec -> Render PPTX -> Screenshots -> Visual Evaluation -> Generate Patches -> Apply Patches (Transactional) -> Re-evaluate.
Guarantees convergence bounds with max_iterations limit and monotonic improvement stopping conditions.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from ..layout.schema import DeckLayoutSpec, ElementType, LayoutSpec
from ..renderer.renderer import render_pptx
from .evaluator import RuleBasedEvaluator, VisualEvaluator
from .issues import deduplicate_issues, filter_issues_by_severity, has_blocking_errors
from .patch import apply_deck_patches
from .schema import (
    IssueSeverity,
    IssueType,
    LayoutPatch,
    PatchOperation,
    PatchResult,
    RepairIterationRecord,
    ScreenshotResult,
    SelfHealingResult,
    VisualIssue,
)
from .screenshot import ScreenshotRenderer


def generate_patches_for_issues(
    issues: List[VisualIssue],
    layout_spec: LayoutSpec,
) -> List[LayoutPatch]:
    """Deterministically map visual issues on a slide to actionable LayoutPatches."""
    patches: List[LayoutPatch] = []
    seen_elements: set[str] = set()

    for issue in issues:
        target_id = issue.element_id
        if not target_id:
            continue

        element = layout_spec.get_element(target_id)
        if element is None:
            continue

        # Prevent contradictory patches on the exact same element in a single step
        if target_id in seen_elements:
            continue

        if issue.issue_type == IssueType.OVERFLOW:
            patches.append(
                LayoutPatch(
                    slide_id=layout_spec.slide_id,
                    target_element=target_id,
                    operation=PatchOperation.CLAMP_TO_CANVAS,
                    parameters={"margin": 24.0},
                    description=f"Clamp overflowing element '{target_id}' inside canvas",
                )
            )
            seen_elements.add(target_id)

        elif issue.issue_type == IssueType.TEXT_OVERFLOW:
            curr_fs = element.style.text.font_size if (element.style and element.style.text) else 18.0
            evidence = issue.evidence or {}
            req_h = float(evidence.get("required_height", element.geometry.height * 1.5))
            act_h = float(evidence.get("actual_height", element.geometry.height))

            # Guard against zero or negative values in evidence
            if req_h > 0 and act_h > 0 and req_h > act_h * 1.5 and curr_fs > 10.0:
                prop_fs = max(8.0, curr_fs * (act_h / req_h) * 1.1)
                patches.append(
                    LayoutPatch(
                        slide_id=layout_spec.slide_id,
                        target_element=target_id,
                        operation=PatchOperation.CHANGE_FONT_SIZE,
                        parameters={"font_size": round(prop_fs, 1)},
                        description=f"Proportionally reduce font size to alleviate text overflow in '{target_id}'",
                    )
                )
            elif curr_fs > 10.0:
                patches.append(
                    LayoutPatch(
                        slide_id=layout_spec.slide_id,
                        target_element=target_id,
                        operation=PatchOperation.CHANGE_FONT_SIZE,
                        parameters={"delta": -2.0},
                        description=f"Reduce font size to alleviate text overflow in '{target_id}'",
                    )
                )
            else:
                # If font size is already small, expand box height cleanly within canvas bounds
                max_canvas_h = max(act_h, layout_spec.canvas.height - element.geometry.y - 20.0)
                desired_h = max(act_h * 1.3, req_h * 1.15)
                max_allowed_h = min(desired_h, max_canvas_h)
                patches.append(
                    LayoutPatch(
                        slide_id=layout_spec.slide_id,
                        target_element=target_id,
                        operation=PatchOperation.RESIZE,
                        parameters={"height": round(max_allowed_h, 1)},
                        description=f"Expand height of text container '{target_id}'",
                    )
                )
            seen_elements.add(target_id)

        elif issue.issue_type == IssueType.TEXT_DENSITY_HIGH:
            patches.append(
                LayoutPatch(
                    slide_id=layout_spec.slide_id,
                    target_element=target_id,
                    operation=PatchOperation.CHANGE_FONT_SIZE,
                    parameters={"delta": -1.5},
                    description=f"Reduce font size for high text density in '{target_id}'",
                )
            )
            seen_elements.add(target_id)

        elif issue.issue_type in (IssueType.TOO_SMALL, IssueType.UNDER_UTILIZED_SPACE):
            if element.element_type == ElementType.FIGURE:
                patches.append(
                    LayoutPatch(
                        slide_id=layout_spec.slide_id,
                        target_element=target_id,
                        operation=PatchOperation.RESIZE,
                        parameters={"scale": 1.25},
                        description=f"Scale up undersized figure '{target_id}'",
                    )
                )
                seen_elements.add(target_id)

        elif issue.issue_type == IssueType.OVERLAP:
            evidence = issue.evidence or {}
            inter = evidence.get("intersection", {})
            inter_w = float(inter.get("width", 20.0))
            inter_h = float(inter.get("height", 20.0))

            other_id = evidence.get("element_b") if evidence.get("element_a") == target_id else evidence.get("element_a")
            other_el = layout_spec.get_element(other_id) if other_id else None

            canvas_w = layout_spec.canvas.width
            canvas_h = layout_spec.canvas.height
            margin = 20.0

            if inter_w < inter_h:
                # Minimal separation along horizontal axis
                if other_el and element.geometry.center_x < other_el.geometry.center_x:
                    desired_dx = -(inter_w + 8.0)
                    # Clamp so element doesn't go below left margin
                    dx = max(desired_dx, margin - element.geometry.x)
                else:
                    desired_dx = (inter_w + 8.0)
                    # Clamp so element doesn't exceed right canvas bound
                    dx = min(desired_dx, (canvas_w - margin) - element.geometry.right)
                dy = 0.0
            else:
                # Minimal separation along vertical axis
                if other_el and element.geometry.center_y < other_el.geometry.center_y:
                    desired_dy = -(inter_h + 8.0)
                    # Move upward clamped to top margin
                    dy = max(desired_dy, margin - element.geometry.y)
                else:
                    desired_dy = (inter_h + 8.0)
                    # Clamp so element doesn't exceed bottom canvas bound
                    dy = min(desired_dy, (canvas_h - margin) - element.geometry.bottom)
                dx = 0.0

            patches.append(
                LayoutPatch(
                    slide_id=layout_spec.slide_id,
                    target_element=target_id,
                    operation=PatchOperation.MOVE,
                    parameters={"dx": round(dx, 1), "dy": round(dy, 1)},
                    description=f"Shift overlapping element '{target_id}' along separation axis",
                )
            )
            seen_elements.add(target_id)

        elif issue.issue_type == IssueType.WRONG_SCALE:
            if element.element_type == ElementType.FIGURE:
                curr_ratio = element.geometry.aspect_ratio
                if curr_ratio > 4.5:
                    # Excessively wide -> expand height cleanly within canvas bounds
                    target_ratio = 16.0 / 9.0
                    max_canvas_h = max(element.geometry.height, layout_spec.canvas.height - element.geometry.y - 20.0)
                    desired_h = max(element.geometry.height * 1.3, element.geometry.width / target_ratio)
                    new_h = min(desired_h, max_canvas_h)
                    patches.append(
                        LayoutPatch(
                            slide_id=layout_spec.slide_id,
                            target_element=target_id,
                            operation=PatchOperation.RESIZE,
                            parameters={"height": round(new_h, 1)},
                            description=f"Increase height of wide figure '{target_id}'",
                        )
                    )
                elif curr_ratio < 0.25:
                    # Excessively tall -> expand width cleanly within canvas bounds
                    target_ratio = 4.0 / 3.0
                    max_canvas_w = max(element.geometry.width, layout_spec.canvas.width - element.geometry.x - 20.0)
                    desired_w = max(element.geometry.width * 1.3, element.geometry.height * target_ratio)
                    new_w = min(desired_w, max_canvas_w)
                    patches.append(
                        LayoutPatch(
                            slide_id=layout_spec.slide_id,
                            target_element=target_id,
                            operation=PatchOperation.RESIZE,
                            parameters={"width": round(new_w, 1)},
                            description=f"Increase width of tall figure '{target_id}'",
                        )
                    )
                seen_elements.add(target_id)

    return patches


def evaluate_and_repair(
    deck_layout: DeckLayoutSpec,
    output_pptx_path: Union[str, Path],
    output_screenshots_dir: Optional[Union[str, Path]] = None,
    evaluator: Optional[VisualEvaluator] = None,
    renderer_fn: Optional[Callable[[DeckLayoutSpec, Path], Any]] = None,
    screenshot_renderer: Optional[ScreenshotRenderer] = None,
    max_iterations: int = 3,
) -> SelfHealingResult:
    """Execute iterative visual evaluation and layout self-healing closed loop.

    1. Render PPTX from current DeckLayoutSpec.
    2. Capture slide screenshot images with fidelity metadata.
    3. Evaluate slides for visual and geometric defects.
    4. Check convergence (no blocking errors) and monotonicity (no worsening/oscillation).
    5. Generate deterministic LayoutPatches.
    6. Apply patches with transactional validation (rollback on new constraint violations).
    7. Repeat until converged, non-improving, or max_iterations reached.
    """
    out_pptx = Path(output_pptx_path).resolve()
    out_pptx.parent.mkdir(parents=True, exist_ok=True)

    shots_dir = (
        Path(output_screenshots_dir).resolve()
        if output_screenshots_dir
        else out_pptx.parent / f"{out_pptx.stem}_screenshots"
    )
    shots_dir.mkdir(parents=True, exist_ok=True)

    eval_engine = evaluator or RuleBasedEvaluator()
    shot_engine = screenshot_renderer or ScreenshotRenderer()
    actual_render_fn = renderer_fn or (lambda spec, p: render_pptx(spec, p))

    current_deck = deck_layout
    best_deck = deck_layout
    best_error_count = float("inf")
    best_issue_count = float("inf")

    history: List[RepairIterationRecord] = []
    final_screenshots: List[Path] = []
    final_screenshot_result: Optional[ScreenshotResult] = None
    final_issues: List[VisualIssue] = []

    prev_issue_signatures: set[str] = set()

    for iteration in range(1, max_iterations + 1):
        # Step 1: Render PPTX
        actual_render_fn(current_deck, out_pptx)

        # Step 2: Render slide screenshots with metadata
        iter_shots_dir = shots_dir / f"iter_{iteration}"
        iter_shots_dir.mkdir(parents=True, exist_ok=True)
        shot_result = shot_engine.render_detailed(out_pptx, iter_shots_dir)
        final_screenshots = shot_result.image_paths
        final_screenshot_result = shot_result

        # Step 3: Evaluate Deck
        issues = eval_engine.evaluate_deck(shot_result.image_paths, current_deck)
        final_issues = issues

        err_cnt = sum(1 for i in issues if i.severity in (IssueSeverity.ERROR, IssueSeverity.CRITICAL))
        warn_cnt = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)

        # Track best deck state
        if err_cnt < best_error_count or (err_cnt == best_error_count and len(issues) < best_issue_count):
            best_deck = current_deck.model_copy(deep=True)
            best_error_count = err_cnt
            best_issue_count = len(issues)

        # Check convergence: Zero blocking errors
        if not has_blocking_errors(issues):
            history.append(
                RepairIterationRecord(
                    iteration=iteration,
                    issues_detected=issues,
                    patches_applied=[],
                    patch_results=[],
                    screenshot_paths=[str(p) for p in shot_result.image_paths],
                    screenshot_fidelity=shot_result.fidelity,
                    error_count=err_cnt,
                    warning_count=warn_cnt,
                )
            )
            return SelfHealingResult(
                converged=True,
                iterations_run=iteration,
                final_issues=issues,
                history=history,
                final_pptx_path=str(out_pptx),
                final_screenshot_paths=[str(p) for p in shot_result.image_paths],
                final_screenshot_result=shot_result,
            )

        # Monotonicity check: Detect worsening or endless oscillation
        current_sig = "|".join(sorted(f"{i.slide_id}:{i.issue_type}:{i.element_id}" for i in issues))
        if current_sig in prev_issue_signatures:
            # Oscillation detected: no progress made from previous cycle
            history.append(
                RepairIterationRecord(
                    iteration=iteration,
                    issues_detected=issues,
                    patches_applied=[],
                    patch_results=[],
                    screenshot_paths=[str(p) for p in shot_result.image_paths],
                    screenshot_fidelity=shot_result.fidelity,
                    error_count=err_cnt,
                    warning_count=warn_cnt,
                )
            )
            # Revert to best known deck
            current_deck = best_deck
            break

        prev_issue_signatures.add(current_sig)

        # Step 4: Generate Patches per slide
        iteration_patches: List[LayoutPatch] = []
        for slide in current_deck.slides:
            slide_issues = [iss for iss in issues if iss.slide_id == slide.slide_id]
            patches = generate_patches_for_issues(slide_issues, slide)
            iteration_patches.extend(patches)

        if not iteration_patches:
            history.append(
                RepairIterationRecord(
                    iteration=iteration,
                    issues_detected=issues,
                    patches_applied=[],
                    patch_results=[],
                    screenshot_paths=[str(p) for p in shot_result.image_paths],
                    screenshot_fidelity=shot_result.fidelity,
                    error_count=err_cnt,
                    warning_count=warn_cnt,
                )
            )
            break

        # Step 5: Apply Patches transactionally to current DeckLayoutSpec
        patched_deck, patch_results = apply_deck_patches(current_deck, iteration_patches, enforce_transaction=True)
        accepted_patches = [pr.patch for pr in patch_results if pr.success]

        history.append(
            RepairIterationRecord(
                iteration=iteration,
                issues_detected=issues,
                patches_applied=accepted_patches,
                patch_results=patch_results,
                screenshot_paths=[str(p) for p in shot_result.image_paths],
                screenshot_fidelity=shot_result.fidelity,
                error_count=err_cnt,
                warning_count=warn_cnt,
            )
        )

        if not accepted_patches:
            # All candidate patches were rejected by transaction guard; stop early
            break

        current_deck = patched_deck

    # Final re-render & re-evaluation of best deck state
    actual_render_fn(current_deck, out_pptx)
    final_shots_dir = shots_dir / "final"
    final_shots_dir.mkdir(parents=True, exist_ok=True)
    final_shot_result = shot_engine.render_detailed(out_pptx, final_shots_dir)
    final_screenshots = final_shot_result.image_paths
    final_issues = eval_engine.evaluate_deck(final_screenshots, current_deck)

    return SelfHealingResult(
        converged=not has_blocking_errors(final_issues),
        iterations_run=len(history),
        final_issues=final_issues,
        history=history,
        final_pptx_path=str(out_pptx),
        final_screenshot_paths=[str(p) for p in final_screenshots],
        final_screenshot_result=final_shot_result,
    )
