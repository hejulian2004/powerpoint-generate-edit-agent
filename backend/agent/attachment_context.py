"""Read-only attachment context for the chat dispatch action.

When an attached file carries no pipeline action the user is asking a question
*about* the file ("这篇论文讲了什么", "这张图是什么风格"). This module builds a
bounded, request-scoped context that is injected into a single read-only LLM
call:

* PDF  -> bounded PaperIR / PaperVisualIR digest (page images only when vision
          is available, so a text-only fallback naturally routes to reasoning).
* PPTX -> read-only PresentationIR text manifest, preferring the active slide.
* Text -> bounded decoded text.
* Image-> ``data:`` image part (forces a vision-role request).

It never mutates the deck and never touches the transcript; the caller injects
the result into one model call and persists only plain user/assistant text.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .attachment_router import (
    KIND_IMAGE,
    KIND_PDF,
    KIND_PPTX,
    KIND_TEXT,
    KIND_UNKNOWN,
)

logger = logging.getLogger(__name__)

# Total digest characters kept across every text-bearing attachment.
MAX_DIGEST_CHARS = 12000
# Maximum number of image parts (attachment images + paper page thumbnails).
MAX_IMAGES = 4
# Maximum paper page thumbnails included when vision is available.
MAX_PDF_PAGE_IMAGES = 2

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


@dataclass
class AttachmentChatContext:
    """Request-scoped attachment material for one read-only chat call."""

    provenance: List[Dict[str, Any]] = field(default_factory=list)
    text_digest: str = ""
    image_parts: List[Dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    # Names of attachments whose format the backend cannot read. They are
    # surfaced to the model as an explicit "not read" notice (mixed requests);
    # an all-unsupported request is rejected before the model is called.
    unsupported: List[str] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return bool(self.image_parts)

    def is_empty(self) -> bool:
        """True when NO model-readable content was produced.

        Unsupported attachments are tracked separately in ``unsupported`` and do
        NOT count here, so an all-unsupported request still fails closed.
        """
        return not self.text_digest and not self.image_parts


def _clip(text: str, limit: int) -> Tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + "\n…[内容已截断]", True


def _mime_for(name: str, content_type: Optional[str]) -> str:
    if content_type and content_type.startswith("image/"):
        return content_type
    return _MIME_BY_EXT.get(os.path.splitext(name or "")[1].lower(), "image/png")


def _image_part(name: str, mime: str, content: bytes) -> Dict[str, Any]:
    data_uri = "data:" + mime + ";base64," + base64.b64encode(content).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": data_uri, "detail": "low"},
    }


def _paper_digest(analysis: Dict[str, Any]) -> str:
    paper_ir = analysis.get("paper_ir") or {}
    visual_ir = analysis.get("paper_visual_ir") or {}
    lines: List[str] = []

    metadata = paper_ir.get("metadata") or {}
    title = metadata.get("title") or analysis.get("source_filename") or ""
    if title:
        lines.append(f"# 论文标题: {title}")
    page_count = analysis.get("page_count") or metadata.get("page_count")
    if page_count:
        lines.append(f"（共 {page_count} 页）")

    abstract = (paper_ir.get("abstract") or "").strip()
    if abstract:
        lines.append("## 摘要\n" + abstract)

    for section in (paper_ir.get("sections") or [])[:24]:
        sec_title = (section.get("title") or "").strip()
        paragraphs = section.get("paragraphs") or []
        body = "\n".join(p for p in paragraphs if isinstance(p, str))
        if sec_title or body:
            lines.append(f"## {sec_title}\n{body}".strip())

    figures = paper_ir.get("figures") or []
    if figures:
        lines.append(
            "## 图表\n"
            + "\n".join(
                f"- {f.get('xref_label', '')} {f.get('caption', '')}".strip()
                for f in figures[:12]
            )
        )
    tables = paper_ir.get("tables") or []
    if tables:
        lines.append(
            "## 表格\n"
            + "\n".join(
                f"- {t.get('xref_label', '')} {t.get('caption', '')}".strip()
                for t in tables[:12]
            )
        )

    for page in (visual_ir.get("pages") or [])[:40]:
        summary = (page.get("visual_summary") or "").strip()
        if summary:
            lines.append(f"- 第{page.get('page_number', '')}页视觉: {summary}")

    return "\n".join(line for line in lines if line)


def _pptx_digest(pres: Any, active_slide_id: Optional[str]) -> str:
    lines: List[str] = [f"# PPTX 文件: {getattr(pres, 'title', '')}（共 {len(pres.slides)} 页）"]
    for index, slide in enumerate(pres.slides, 1):
        marker = " ← 当前页" if slide.id == active_slide_id else ""
        lines.append(f"## 第{index}页{marker}")
        try:
            elements = slide.all_elements(recursive=True)
        except AttributeError:
            elements = list(slide.elements)
        for el in elements:
            text_content = getattr(el, "text_content", None)
            plain = getattr(text_content, "plain_text", None) if text_content else None
            if plain:
                lines.append(f"- {plain}")
    return "\n".join(lines)


def _paper_page_images(
    analysis: Dict[str, Any],
    slots: int,
) -> List[Dict[str, Any]]:
    """Reads up to ``slots`` rendered page thumbnails from the paper cache."""
    parts: List[Dict[str, Any]] = []
    if slots <= 0 or not analysis.get("vision_model"):
        return parts
    pages = analysis.get("pages") or []
    pages = sorted(pages, key=lambda p: p.get("page_number") or 0)
    for page in pages[: min(slots, MAX_PDF_PAGE_IMAGES)]:
        path = page.get("image_path")
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                content = fh.read()
        except OSError:
            continue
        if content:
            parts.append(_image_part(os.path.basename(path), "image/png", content))
    return parts


async def build_attachment_context(
    attachments: List[Dict[str, Any]],
    ui_context: Optional[Any] = None,
    analyze_pdf: Optional[
        Callable[[str, Optional[str], bytes], Awaitable[Dict[str, Any]]]
    ] = None,
    parse_pptx: Optional[Callable[[bytes, str], Any]] = None,
) -> AttachmentChatContext:
    """Builds a bounded, read-only context from the request's attachments.

    ``analyze_pdf`` / ``parse_pptx`` are injected by the caller (the API layer) so
    this module stays free of transport dependencies. PDFs degrade to a text-only
    digest when no analyzer is supplied. An unparseable PPTX yields an explicit
    parse-failure note: it NEVER silently substitutes the session's current deck,
    which would misattribute the answer to the wrong document.
    """
    ctx = AttachmentChatContext()
    sections: List[str] = []
    active_slide_id = getattr(ui_context, "active_slide_id", None)

    for att in attachments:
        kind = att.get("kind")
        name = att.get("name") or ""
        content = att.get("content") or b""
        ctx.provenance.append(
            {
                "name": name,
                "kind": kind,
                "sha256": hashlib.sha256(content).hexdigest()[:16],
                "status": "unsupported" if kind == KIND_UNKNOWN else "supported",
            }
        )

        if kind == KIND_IMAGE:
            if len(ctx.image_parts) < MAX_IMAGES:
                ctx.image_parts.append(
                    _image_part(name, _mime_for(name, att.get("content_type")), content)
                )
            else:
                ctx.truncated = True
        elif kind == KIND_TEXT:
            try:
                decoded = content.decode("utf-8")
            except UnicodeDecodeError:
                decoded = content.decode("utf-8", errors="replace")
            sections.append(f"# 文本附件: {name}\n{decoded}")
        elif kind == KIND_PDF:
            analysis: Dict[str, Any] = {}
            if analyze_pdf is not None:
                try:
                    analysis = await analyze_pdf(name, att.get("content_type"), content)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("PDF attachment analysis failed for chat: %s", exc)
            if analysis:
                sections.append(_paper_digest(analysis))
                remaining = MAX_IMAGES - len(ctx.image_parts)
                ctx.image_parts.extend(_paper_page_images(analysis, remaining))
            else:
                sections.append(f"# PDF 附件: {name}（未能解析内容）")
        elif kind == KIND_PPTX:
            pres = None
            if parse_pptx is not None:
                try:
                    pres = parse_pptx(content, name)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("PPTX attachment parse failed for chat: %s", exc)
            if pres is not None:
                sections.append(_pptx_digest(pres, active_slide_id))
            else:
                # Never fall back to the session's current deck: the user asked
                # about THIS file, so answer from it or say it could not be read.
                sections.append(
                    f"# PPTX 附件: {name}\n附件解析失败，无法读取其中的幻灯片内容。"
                )
        elif kind == KIND_UNKNOWN:
            # Recorded (not inserted into the digest) so a mixed request tells the
            # model this file was not read, while an all-unknown request still
            # produces an empty context and is rejected upstream.
            ctx.unsupported.append(name)

    digest = "\n\n".join(s for s in sections if s)
    ctx.text_digest, clipped = _clip(digest, MAX_DIGEST_CHARS)
    ctx.truncated = ctx.truncated or clipped
    return ctx


__all__ = ["AttachmentChatContext", "build_attachment_context"]
