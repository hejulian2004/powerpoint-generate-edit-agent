"""Format hard-validation failures into LLM repair feedback."""

from __future__ import annotations

from typing import Any, List


def format_layout_validation_feedback(report: Any, layout_spec: Any = None) -> str:
    """Turn a ``ValidationReport`` (or issue list) into concise repair instructions."""
    errors: List[str] = list(getattr(report, "errors", []) or [])
    warnings: List[str] = list(getattr(report, "warnings", []) or [])

    lines: List[str] = []
    if errors:
        lines.append("HARD ERRORS (must fix; layout would be rejected):")
        lines.extend(f"- {e}" for e in errors[:12])
    if warnings:
        lines.append("WARNINGS (should improve):")
        lines.extend(f"- {w}" for w in warnings[:8])

    if not lines:
        lines.append("No hard errors detected.")

    lines.append(
        "Return the COMPLETE replacement layout as strict JSON. "
        "Every element must stay inside 0..1280 x 0..720, have positive width/height, "
        "and not overlap other foreground elements. Keep readable font sizes."
    )
    return "\n".join(lines)


__all__ = ["format_layout_validation_feedback"]
