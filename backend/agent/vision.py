"""Vision Loop: Multimodal snapshot generation and layout verification.

Supports dual-mode:
1. Playwright / Chromium headless browser snapshotting (if installed)
2. Lightweight SVG image data URI fallback
"""

from __future__ import annotations
import base64
import logging
from typing import Optional, Dict, Any
from ..ir.models import SlideIR
from ..ir.svg_renderer import SVGRenderer

logger = logging.getLogger(__name__)

# Check Playwright availability
_playwright_available = False
try:
    from playwright.async_api import async_playwright
    _playwright_available = True
except ImportError:
    _playwright_available = False


from ..eval.renderer_snapshot import SlideSnapshotRenderer


class VisionEngine:
    """Manages screenshot generation, layout verification, and visual review loop."""

    @classmethod
    def evaluate_slide_layout(cls, slide: SlideIR) -> Any:
        """Runs the rule-based geometric and accessibility layout evaluation."""
        from ..eval.layout_diff import LayoutDiffEngine
        return LayoutDiffEngine.evaluate_slide(slide)

    @classmethod
    async def audit_and_remediate(
        cls,
        slide: SlideIR,
        client: Optional[Any] = None,
        include_multimodal: bool = True
    ) -> Any:
        """Executes full Visual Critic inspection producing scores and remediation actions."""
        from ..eval.visual_critic import VisualCritic
        return await VisualCritic.review_slide(
            slide=slide,
            llm_client=client,
            include_multimodal=include_multimodal
        )

    @classmethod
    async def capture_slide_snapshot(cls, slide: SlideIR, format: str = "png") -> str:
        """Returns base64 data URI for the slide (PNG or SVG)."""
        if format == "svg":
            svg_code = SlideSnapshotRenderer.render_svg(slide)
            b64_svg = base64.b64encode(svg_code.encode("utf-8")).decode("utf-8")
            return f"data:image/svg+xml;base64,{b64_svg}"

        # Standard deterministic PNG data URI
        return SlideSnapshotRenderer.render_data_uri(slide)

    @classmethod
    def format_slide_element_manifest(cls, slide: SlideIR) -> str:
        """Formats a compact structured layout manifest for LLM vision alignment."""
        lines = [f"Slide #{slide.slide_num} (Canvas: {slide.width}x{slide.height}, Elements: {len(slide.elements)}):"]
        for el in slide.elements:
            desc = f"- [ID: '{el.id}'] Type: {el.type}, Rect: ({el.x:.0f}, {el.y:.0f}, {el.width:.0f}x{el.height:.0f})"
            if hasattr(el, "text_content") and el.text_content and el.text_content.plain_text:
                desc += f", Text: '{el.text_content.plain_text[:30]}'"
            lines.append(desc)
        return "\n".join(lines)

    @classmethod
    async def review_slide_visually(
        cls,
        slide: SlideIR,
        client: Any,
        prompt: str = "请分析当前 PPT 页面的排版布局，检查是否有文字重叠、元素拥挤或边距失衡问题，并给出简明优化意见。"
    ) -> str:
        """Sends visual snapshot to Vision Model for analysis."""
        from ..eval.renderer_snapshot import SlideSnapshotRenderer, RendererMode
        meta = SlideSnapshotRenderer.get_render_metadata(slide, mode=RendererMode.DETERMINISTIC)
        snapshot_uri = await cls.capture_slide_snapshot(slide)
        manifest = cls.format_slide_element_manifest(slide)

        prompt_text = prompt
        if meta.renderer == "pillow" or meta.quality == "geometry_only":
            prompt_text += "\n当前截图可能缺少字体和特效信息。请优先依据element manifest判断结构。"

        full_text_prompt = f"{prompt_text}\n\n【画布图元坐标清单】:\n{manifest}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_text_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": snapshot_uri, "detail": "low"}
                    }
                ]
            }
        ]

        try:
            res = await client.chat_completion(messages, role="vision", max_tokens=600)
            return res["choices"][0]["message"].get("content", "视觉分析完成")
        except Exception as e:
            logger.warning(f"Vision API error in review_slide_visually: {e}")
            raise
