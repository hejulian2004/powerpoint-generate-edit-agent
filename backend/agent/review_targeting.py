"""Resolve the slides a user wants visually reviewed from natural language.

`/review` with no argument means "all non-empty slides". With an argument the
LLM decides which slides the user means (by page number, title, or content); a
bare page-number parse is the only fallback when no LLM is available.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _slide_title(slide: Any) -> str:
    for element in getattr(slide, "elements", []) or []:
        text_content = getattr(element, "text_content", None)
        if text_content is None:
            continue
        try:
            text = text_content.plain_text.strip()
        except Exception:
            text = ""
        if text:
            return text[:24]
    return ""


def build_slide_manifest(session: Any) -> List[Dict[str, Any]]:
    """Ordered manifest of non-empty slides: page number, id and a short title."""
    presentation = session.document.presentation if session is not None else None
    slides = getattr(presentation, "slides", []) or []
    manifest: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not getattr(slide, "elements", None):
            continue
        manifest.append(
            {"index": index, "slide_id": slide.id, "title": _slide_title(slide)}
        )
    return manifest


_SYSTEM_PROMPT = """You select which slides to visually review.
You receive the slide manifest (page number, slide_id, title) and the user's request.
Reply with STRICT JSON: {"slide_ids": ["<id>", ...]}.
Use only slide_ids from the manifest. If the user wants every slide, list all ids."""


def _extract_ids(content: str) -> List[str]:
    match = re.search(r"\{.*\}", content or "", re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return []
    ids = parsed.get("slide_ids") if isinstance(parsed, dict) else None
    if not isinstance(ids, list):
        return []
    return [str(i) for i in ids]


async def resolve_review_targets(
    llm_client: Any,
    target_text: Optional[str],
    manifest: List[Dict[str, Any]],
) -> List[str]:
    """Returns the ordered slide ids to review."""
    if not target_text or not target_text.strip():
        return [m["slide_id"] for m in manifest]
    if not manifest:
        return []

    valid_ids = {m["slide_id"] for m in manifest}
    if llm_client is not None and hasattr(llm_client, "chat_completion"):
        manifest_lines = "\n".join(
            f"- page {m['index']}: id={m['slide_id']} title={m['title'] or '(untitled)'}"
            for m in manifest
        )
        try:
            response = await llm_client.chat_completion(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Manifest:\n{manifest_lines}\n\nUser request: {target_text}",
                    },
                ],
                role="fast",
                max_tokens=200,
            )
            content = response["choices"][0]["message"].get("content", "")
            resolved = [sid for sid in _extract_ids(content) if sid in valid_ids]
            if resolved:
                ordered = [m["slide_id"] for m in manifest if m["slide_id"] in resolved]
                return ordered
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Review target resolution failed: %s", exc)

    numbers = set(re.findall(r"\d+", target_text))
    by_number = [m["slide_id"] for m in manifest if str(m["index"]) in numbers]
    return by_number or [m["slide_id"] for m in manifest]


__all__ = ["build_slide_manifest", "resolve_review_targets"]
