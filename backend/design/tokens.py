"""Single slide-design contract shared by compilers, templates, and renderers.

The frontend mirror is ``frontend/src/theme/slideTokens.ts``. Change both together.
Radius is pixels. ``0`` is a sharp corner, not an unset value.
"""

from __future__ import annotations

MAX_CARD_RADIUS = 3.0

SHADOW_DX = 2.0
SHADOW_DY = 4.0
SHADOW_STD_DEVIATION = 4.0
SHADOW_FLOOD_OPACITY = 0.15


def clamp_radius(value: object) -> float:
    """Clamp a card radius into ``[0, MAX_CARD_RADIUS]`` pixels."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number <= 0.0:
        return 0.0
    if number > MAX_CARD_RADIUS:
        return MAX_CARD_RADIUS
    return number
