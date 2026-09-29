"""One CJK/ASCII text-width estimate for layout and IR review.

Chinese characters are about ``1.05 × font size``. ASCII is about ``0.55 × font size``.
"""

from __future__ import annotations

import math
import re

CJK_RE = re.compile(r"[一-鿿]")
CJK_WIDTH_RATIO = 1.05
ASCII_WIDTH_RATIO = 0.55


def text_pixel_width(text: str, font_size: float) -> float:
    """Estimated pixel width of one line of ``text`` at ``font_size``."""
    if not text or font_size <= 0:
        return 0.0
    cjk_chars = len(CJK_RE.findall(text))
    ascii_chars = len(text) - cjk_chars
    return (cjk_chars * font_size * CJK_WIDTH_RATIO) + (ascii_chars * font_size * ASCII_WIDTH_RATIO)


def estimate_text_lines(
    text: str,
    box_width: float,
    font_size: float,
    padding: float = 0.0,
) -> int:
    """Line count for ``text`` wrapped inside ``box_width`` after horizontal padding."""
    usable_width = max(10.0, box_width - 2.0 * padding)
    total_lines = 0
    for paragraph in (text or "").split("\n"):
        if not paragraph:
            total_lines += 1
            continue
        width = text_pixel_width(paragraph, font_size)
        if width <= 0:
            total_lines += 1
        else:
            total_lines += max(1, math.ceil(width / usable_width))
    return total_lines
