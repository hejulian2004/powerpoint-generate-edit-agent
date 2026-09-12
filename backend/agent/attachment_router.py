"""Attachment intent routing for the chat composer.

The frontend can attach PDF / PPTX / image / text files to a chat message. The
user's natural-language message decides how the attachment is used, so this
module routes ``(message, kinds)`` to a single dispatch action using the LLM as
the sole intent classifier (a structural, keyword-free fallback exists only for
when no LLM is configured).

The router is intentionally pure: it never touches sessions, tools, or the
document. ``routes.chat_with_attachments`` performs the actual dispatch.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ---- Attachment kinds -------------------------------------------------------
KIND_PDF = "pdf"
KIND_PPTX = "pptx"
KIND_IMAGE = "image"
KIND_TEXT = "text"
KIND_UNKNOWN = "unknown"

# ---- Dispatch actions -------------------------------------------------------
ACTION_PAPER = "paper_generate"
ACTION_IMPORT = "pptx_import"
ACTION_IMAGE = "image_insert"
ACTION_TEXT = "text_generate"
ACTION_CHAT = "chat"

# Every action that consumes at least one attachment.
ATTACHMENT_ACTIONS = frozenset(
    {ACTION_PAPER, ACTION_IMPORT, ACTION_IMAGE, ACTION_TEXT}
)

# Kind -> default action when the message carries no stronger signal.
_KIND_DEFAULT_ACTION = {
    KIND_PDF: ACTION_PAPER,
    KIND_PPTX: ACTION_IMPORT,
    KIND_IMAGE: ACTION_IMAGE,
    KIND_TEXT: ACTION_TEXT,
}

# Priority used when multiple kinds are attached and the message is ambiguous.
_KIND_PRIORITY = (KIND_PDF, KIND_PPTX, KIND_IMAGE, KIND_TEXT)

_PDF_EXTENSIONS = {".pdf"}
_PPTX_EXTENSIONS = {".ppt", ".pptx", ".pptm"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic"}
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".log", ".yaml", ".yml"
}


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def detect_kind(filename: str, content_type: Optional[str] = None) -> str:
    """Best-effort attachment classification from extension then MIME type."""
    ext = _ext(filename)
    if ext in _PDF_EXTENSIONS:
        return KIND_PDF
    if ext in _PPTX_EXTENSIONS:
        return KIND_PPTX
    if ext in _IMAGE_EXTENSIONS:
        return KIND_IMAGE
    if ext in _TEXT_EXTENSIONS:
        return KIND_TEXT

    ctype = (content_type or "").lower()
    if ctype == "application/pdf":
        return KIND_PDF
    if "presentation" in ctype or "powerpoint" in ctype or ctype.endswith("ms-powerpoint"):
        return KIND_PPTX
    if ctype.startswith("image/"):
        return KIND_IMAGE
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
        return KIND_TEXT
    return KIND_UNKNOWN


def fallback_action(kinds: List[str]) -> str:
    """Structural fallback used only when the routing LLM is unavailable.

    This deliberately performs NO keyword matching: intent is the LLM's job. The
    fallback only maps a single attachment kind to its canonical pipeline, and
    resolves multiple kinds by a stable priority so the request is never lost.
    """
    actionable = [k for k in kinds if k != KIND_UNKNOWN]
    if not actionable:
        return ACTION_CHAT
    if len(actionable) == 1:
        return _KIND_DEFAULT_ACTION[actionable[0]]
    for kind in _KIND_PRIORITY:
        if kind in actionable:
            return _KIND_DEFAULT_ACTION[kind]
    return ACTION_CHAT


# The LLM is the sole intent classifier: no hardcoded keyword table decides the
# route. The schema below constrains it to the legal actions and supplies a few
# examples so small/fast models stay well-calibrated.
_ROUTER_SYSTEM_PROMPT = """You are the attachment intent router for an AI slide editor.
Choose exactly ONE action from this closed set:
- paper_generate: turn an attached PDF paper into a slide deck.
- pptx_import: import/replace the current deck with an attached .pptx/.ppt file.
- image_insert: insert an attached image into the current slide.
- text_generate: generate a deck from an attached text/document as source material.
- chat: the attachment needs no pipeline action yet; just answer the user.

Routing is decided by the user's message, not only by the file type. Examples:
- [pdf] "把这篇论文做成汇报PPT" -> paper_generate
- [pdf] "先看看这篇讲了什么" -> chat
- [pptx] "导入这个模板" -> pptx_import
- [pptx] "这个文件里第三页写的什么" -> chat
- [image] "把这张图放到当前页" -> image_insert
- [image] "这张图是什么风格" -> chat
- [txt] "根据这份大纲生成幻灯片" -> text_generate
- [txt] "总结一下这段文字" -> chat
- [pdf, image] "参考论文，并把这张图插进去" -> image_insert

Reply with STRICT JSON only:
{"action": "<one of the closed set>", "reason": "<short reason>"}"""


def _extract_json(content: str) -> dict:
    if not content:
        return {}
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


# An action is legal only when at least one attached kind can satisfy it.
_ACTION_REQUIRED_KIND = {
    ACTION_PAPER: KIND_PDF,
    ACTION_IMPORT: KIND_PPTX,
    ACTION_IMAGE: KIND_IMAGE,
    ACTION_TEXT: KIND_TEXT,
}


async def classify_intent(
    llm_client: Any,
    message: str,
    kinds: List[str],
) -> str:
    """Route attachments to a dispatch action using the LLM as the decider.

    The LLM sees the user's own words plus the attached kinds; a kind-only
    structural fallback is used solely when the LLM is unavailable or returns
    something illegal.
    """
    actionable = [k for k in kinds if k != KIND_UNKNOWN]
    if not actionable:
        return ACTION_CHAT

    fallback = fallback_action(kinds)
    if llm_client is None or not hasattr(llm_client, "chat_completion"):
        return fallback

    user_prompt = (
        f"Attached file kinds: {', '.join(actionable)}\n"
        f"User message: {message or '(no text)'}"
    )
    try:
        response = await llm_client.chat_completion(
            [
                {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            role="fast",
            max_tokens=120,
        )
        content = response["choices"][0]["message"].get("content", "")
        parsed = _extract_json(content)
        action = str(parsed.get("action") or "").strip()
        if action == ACTION_CHAT:
            return ACTION_CHAT
        if action in ATTACHMENT_ACTIONS:
            required = _ACTION_REQUIRED_KIND[action]
            if required in actionable:
                return action
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Attachment intent classification failed: %s", exc)
    return fallback


__all__ = [
    "ACTION_CHAT",
    "ACTION_IMAGE",
    "ACTION_IMPORT",
    "ACTION_PAPER",
    "ACTION_TEXT",
    "ATTACHMENT_ACTIONS",
    "KIND_IMAGE",
    "KIND_PDF",
    "KIND_PPTX",
    "KIND_TEXT",
    "KIND_UNKNOWN",
    "classify_intent",
    "detect_kind",
    "fallback_action",
]
