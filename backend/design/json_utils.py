"""Defensive JSON extraction for LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def extract_json(text: str) -> Any:
    """Best-effort extraction of a JSON object/array from model output.

    Handles raw JSON, fenced code blocks, and prose-wrapped JSON. Raises
    ``ValueError`` when nothing parseable is found.
    """
    if not text or not text.strip():
        raise ValueError("empty model response")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except Exception:
                continue
    raise ValueError("no parseable JSON in model response")


def clamp_unit(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["extract_json", "clamp_unit", "as_float"]
