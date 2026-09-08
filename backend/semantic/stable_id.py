"""Stable element IDs for the semantic graph (PR6.1 Task 5).

Some PPTX files assign unstable element ids (regenerated on each round-trip by other
tooling). `compute_stable_id` derives a deterministic id from stable semantic signals:

    stable_id = hash(role + bbox + text + position)

The id is stable across two parses of the same deck, which supports replay, undo, and
cross-render element tracking even when the underlying OOXML id changes.
"""

from __future__ import annotations
import hashlib
import re
from typing import Any, Optional

from ..ir.models import ElementIR, SlideIR

_HASH_LENGTH = 5


def _normalize_text(element: ElementIR) -> str:
    tc = getattr(element, "text_content", None)
    if tc is None:
        return ""
    text = getattr(tc, "plain_text", "") or ""
    return re.sub(r"\s+", " ", text).strip()[:64]


def compute_stable_id(
    element: ElementIR,
    role: str = "elem",
    slide: Optional[SlideIR] = None,
) -> str:
    """Computes a deterministic, collision-resistant stable id for an element.

    role: semantic role string (e.g. 'slide_title', 'card'); falls back to element type.
    slide: owning slide, used to anchor the id within the deck (slide number).
    """
    if role in ("", "unknown", "elem"):
        role = element.type

    bbox = (
        round(getattr(element, "x", 0.0), 1),
        round(getattr(element, "y", 0.0), 1),
        round(getattr(element, "width", 0.0), 1),
        round(getattr(element, "height", 0.0), 1),
    )
    position = f"{slide.slide_num if slide else 0}:{getattr(element, 'z_index', 0)}"
    text = _normalize_text(element)

    digest = hashlib.sha1(
        f"{role}|{bbox}|{text}|{position}".encode("utf-8")
    ).hexdigest()

    return f"{role}_{digest[:_HASH_LENGTH]}"


def stable_id_for_classified(
    element: ElementIR,
    classification: Any,
    slide: Optional[SlideIR] = None,
) -> str:
    """Convenience wrapper taking an ElementClassification object."""
    role = classification.role.value if classification is not None else element.type
    return compute_stable_id(element, role=role, slide=slide)