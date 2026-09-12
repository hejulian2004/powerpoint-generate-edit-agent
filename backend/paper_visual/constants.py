"""Version constants for the paper visual subsystem.

These participate in cache keys. Any change to rendering or to the vision prompt
MUST bump the corresponding version so stale cached artifacts are not reused.
"""

from __future__ import annotations

# Bump when the page rasterization output changes (pypdfium2 usage, scale,
# color handling, output format, page-size semantics).
RENDERER_VERSION = "1.0.0"

# Bump when the PaperVisualIR semantics / parsing change.
ANALYSIS_VERSION = "1.0.0"

# Bump when the vision prompt or requested JSON contract changes.
VISION_PROMPT_VERSION = "1.0.0"

__all__ = ["RENDERER_VERSION", "ANALYSIS_VERSION", "VISION_PROMPT_VERSION"]
