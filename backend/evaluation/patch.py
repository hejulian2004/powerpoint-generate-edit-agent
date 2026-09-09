"""Layout Patch Engine (PR12).

Applies deterministic geometric and stylistic patches to LayoutSpec and DeckLayoutSpec
instances with transaction rollback and layout constraint verification.
"""

from __future__ import annotations

import copy
from typing import Callable, List, Optional, Tuple

from ..layout.schema import DeckLayoutSpec, ElementStyle, LayoutElement, LayoutSpec, Rect, TextStyle
from ..layout.validator import ValidationReport, validate_layout
from .schema import LayoutPatch, PatchOperation, PatchResult


def apply_patch(
    layout_spec: LayoutSpec,
    patch: LayoutPatch,
) -> LayoutSpec:
    """Apply a single LayoutPatch to a LayoutSpec, returning a modified deep copy without validation."""
    # Ensure patch targets this slide
    if patch.slide_id != layout_spec.slide_id:
        return layout_spec

    # Deep copy layout spec to maintain immutability
    new_spec = layout_spec.model_copy(deep=True)
    target = new_spec.get_element(patch.target_element)
    if target is None:
        return new_spec

    if target.style is None:
        target.style = ElementStyle()

    op = patch.operation
    params = patch.parameters
    geo = target.geometry

    if op == PatchOperation.MOVE:
        dx = float(params.get("dx", 0.0))
        dy = float(params.get("dy", 0.0))
        new_geo = Rect(
            x=geo.x + dx,
            y=geo.y + dy,
            width=geo.width,
            height=geo.height,
        )
        target.geometry = new_geo

    elif op == PatchOperation.RESIZE:
        scale = params.get("scale")
        if scale is not None:
            scale_f = float(scale)
            new_w = max(10.0, geo.width * scale_f)
            new_h = max(10.0, geo.height * scale_f)
        else:
            scale_x = float(params.get("scale_x", 1.0))
            scale_y = float(params.get("scale_y", 1.0))
            new_w = float(params.get("width", geo.width * scale_x))
            new_h = float(params.get("height", geo.height * scale_y))

        keep_center = bool(params.get("keep_center", False))
        if keep_center:
            new_x = geo.center_x - new_w / 2.0
            new_y = geo.center_y - new_h / 2.0
        else:
            new_x = geo.x
            new_y = geo.y

        target.geometry = Rect(
            x=new_x,
            y=new_y,
            width=new_w,
            height=new_h,
        )

    elif op == PatchOperation.CHANGE_FONT_SIZE:
        current_fs = 18.0
        if target.style and target.style.text and target.style.text.font_size:
            current_fs = target.style.text.font_size

        if "delta" in params:
            new_fs = max(6.0, current_fs + float(params["delta"]))
        elif "font_size" in params:
            new_fs = max(6.0, float(params["font_size"]))
        else:
            new_fs = current_fs

        if target.style.text is None:
            target.style.text = TextStyle(font_size=new_fs)
        else:
            target.style.text = target.style.text.model_copy(update={"font_size": new_fs})

    elif op == PatchOperation.CHANGE_PADDING:
        current_pad = target.style.padding or 0.0
        if "delta" in params:
            new_pad = max(0.0, current_pad + float(params["delta"]))
        else:
            new_pad = max(0.0, float(params.get("padding", current_pad)))
        target.style.padding = new_pad

    elif op == PatchOperation.CLAMP_TO_CANVAS:
        margin = float(params.get("margin", 20.0))
        canvas = new_spec.canvas
        clamped_x = max(margin, min(geo.x, canvas.width - margin - geo.width))
        clamped_y = max(margin, min(geo.y, canvas.height - margin - geo.height))
        # If width or height exceeds available bounds
        clamped_w = min(geo.width, canvas.width - 2 * margin)
        clamped_h = min(geo.height, canvas.height - 2 * margin)
        target.geometry = Rect(
            x=clamped_x,
            y=clamped_y,
            width=clamped_w,
            height=clamped_h,
        )

    elif op == PatchOperation.SET_COORDINATES:
        new_x = float(params.get("x", geo.x))
        new_y = float(params.get("y", geo.y))
        new_w = float(params.get("width", geo.width))
        new_h = float(params.get("height", geo.height))
        target.geometry = Rect(x=new_x, y=new_y, width=new_w, height=new_h)

    return new_spec


def apply_patch_transaction(
    layout_spec: LayoutSpec,
    patch: LayoutPatch,
    validator_fn: Optional[Callable[[LayoutSpec], ValidationReport]] = None,
) -> Tuple[LayoutSpec, PatchResult]:
    """Apply a patch transactionally with geometric constraint verification.

    If the candidate patch introduces new critical constraint errors (e.g. collision,
    negative coordinates, or canvas overflow), the patch is rejected and the layout
    is rolled back to its original state.
    """
    validator = validator_fn or (lambda s: validate_layout(s, strict=False))

    # Pre-validation
    report_before = validator(layout_spec)
    errors_before = list(report_before.errors)

    # Candidate mutation
    candidate_spec = apply_patch(layout_spec, patch)

    # Post-validation
    report_after = validator(candidate_spec)
    errors_after = list(report_after.errors)

    # Detect newly introduced structured constraint violations
    violations_before = {
        (c.constraint_type, tuple(sorted(c.target_element_ids or [])))
        for c in report_before.evaluated_constraints
        if not c.satisfied
    }
    violations_after = {
        (c.constraint_type, tuple(sorted(c.target_element_ids or [])))
        for c in report_after.evaluated_constraints
        if not c.satisfied
    }
    new_violations = violations_after - violations_before

    # Detect newly introduced unstructured errors (excluding messages generated by structured constraints,
    # which change coordinate values as elements move closer to compliance)
    structured_msgs_before = {c.message for c in report_before.evaluated_constraints if c.message}
    structured_msgs_after = {c.message for c in report_after.evaluated_constraints if c.message}

    unstructured_before = [err for err in errors_before if err not in structured_msgs_before]
    unstructured_after = [err for err in errors_after if err not in structured_msgs_after]
    new_unstructured_errors = [err for err in unstructured_after if err not in unstructured_before]

    if new_violations or new_unstructured_errors:
        # Transaction rollback: reject candidate patch
        detail_msg = []
        if new_violations:
            detail_msg.append(f"{len(new_violations)} structured constraint violation(s) {list(new_violations)[:2]}")
        if new_unstructured_errors:
            detail_msg.append(f"{len(new_unstructured_errors)} error(s): {'; '.join(new_unstructured_errors[:2])}")
        rejection_msg = f"Patch rejected: introduced {'; '.join(detail_msg)}"
        patch_res = PatchResult(
            success=False,
            patch=patch,
            before_valid=report_before.is_valid,
            after_valid=False,
            errors_before=errors_before,
            errors_after=errors_after,
            rejected_reason=rejection_msg,
        )
        return layout_spec, patch_res

    # Transaction commit
    patch_res = PatchResult(
        success=True,
        patch=patch,
        before_valid=report_before.is_valid,
        after_valid=report_after.is_valid,
        errors_before=errors_before,
        errors_after=errors_after,
        rejected_reason=None,
    )
    return candidate_spec, patch_res


def apply_patches(
    layout_spec: LayoutSpec,
    patches: List[LayoutPatch],
    enforce_transaction: bool = True,
) -> Tuple[LayoutSpec, List[PatchResult]]:
    """Apply an ordered sequence of patches to a LayoutSpec, optionally with transaction validation."""
    curr = layout_spec
    results: List[PatchResult] = []
    for patch in patches:
        if enforce_transaction:
            curr, res = apply_patch_transaction(curr, patch)
            results.append(res)
        else:
            curr = apply_patch(curr, patch)
            results.append(
                PatchResult(
                    success=True,
                    patch=patch,
                    before_valid=True,
                    after_valid=True,
                )
            )
    return curr, results


def apply_deck_patches(
    deck_spec: DeckLayoutSpec,
    patches: List[LayoutPatch],
    enforce_transaction: bool = True,
) -> Tuple[DeckLayoutSpec, List[PatchResult]]:
    """Apply patches across matching slides in a DeckLayoutSpec with transactional validation."""
    if not patches:
        return deck_spec, []

    new_deck = deck_spec.model_copy(deep=True)
    patches_by_slide: dict[str, List[LayoutPatch]] = {}
    for p in patches:
        patches_by_slide.setdefault(p.slide_id, []).append(p)

    all_results: List[PatchResult] = []
    updated_slides: List[LayoutSpec] = []
    for slide in new_deck.slides:
        if slide.slide_id in patches_by_slide:
            slide_patches = patches_by_slide[slide.slide_id]
            updated_slide, results = apply_patches(slide, slide_patches, enforce_transaction=enforce_transaction)
            updated_slides.append(updated_slide)
            all_results.extend(results)
        else:
            updated_slides.append(slide)

    new_deck.slides = updated_slides
    return new_deck, all_results
