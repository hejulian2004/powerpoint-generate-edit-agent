"""Layout Patch Engine (PR12).

Applies deterministic geometric and stylistic patches to LayoutSpec and DeckLayoutSpec
instances without mutating the underlying SlideSpec or bypassing layout constraints.
"""

from __future__ import annotations

import copy
from typing import List, Optional

from ..layout.schema import DeckLayoutSpec, LayoutElement, LayoutSpec, Rect, TextStyle
from .schema import LayoutPatch, PatchOperation


def apply_patch(
    layout_spec: LayoutSpec,
    patch: LayoutPatch,
) -> LayoutSpec:
    """Apply a single LayoutPatch to a LayoutSpec, returning a modified deep copy."""
    # Ensure patch targets this slide
    if patch.slide_id != layout_spec.slide_id:
        return layout_spec

    # Deep copy layout spec to maintain immutability
    new_spec = layout_spec.model_copy(deep=True)
    target = new_spec.get_element(patch.target_element)
    if target is None:
        return new_spec

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


def apply_patches(
    layout_spec: LayoutSpec,
    patches: List[LayoutPatch],
) -> LayoutSpec:
    """Apply an ordered sequence of patches to a LayoutSpec."""
    curr = layout_spec
    for patch in patches:
        curr = apply_patch(curr, patch)
    return curr


def apply_deck_patches(
    deck_spec: DeckLayoutSpec,
    patches: List[LayoutPatch],
) -> DeckLayoutSpec:
    """Apply patches across matching slides in a DeckLayoutSpec."""
    if not patches:
        return deck_spec

    new_deck = deck_spec.model_copy(deep=True)
    patches_by_slide: dict[str, List[LayoutPatch]] = {}
    for p in patches:
        patches_by_slide.setdefault(p.slide_id, []).append(p)

    updated_slides: List[LayoutSpec] = []
    for slide in new_deck.slides:
        if slide.slide_id in patches_by_slide:
            slide_patches = patches_by_slide[slide.slide_id]
            updated_slides.append(apply_patches(slide, slide_patches))
        else:
            updated_slides.append(slide)

    new_deck.slides = updated_slides
    return new_deck
