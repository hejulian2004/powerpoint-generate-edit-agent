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
    async def capture_slide_snapshot(cls, slide: SlideIR) -> str:
        """Returns base64 data URI for the slide (PNG or SVG)."""
        svg_code = SVGRenderer.render_slide(slide)

        if _playwright_available:
            try:
                png_bytes = await cls._render_with_playwright(svg_code)
                b64 = base64.b64encode(png_bytes).decode("utf-8")
                return f"data:image/png;base64,{b64}"
            except Exception as e:
                logger.warning(f"Playwright snapshot failed, falling back to SVG data URI: {e}")

        # Fallback: base64 encoded SVG image
        b64_svg = base64.b64encode(svg_code.encode("utf-8")).decode("utf-8")
        return f"data:image/svg+xml;base64,{b64_svg}"

    @classmethod
    async def _render_with_playwright(cls, svg_code: str) -> bytes:
        html_wrapper = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 1280px; height: 720px; overflow: hidden; background: transparent; }}
  </style>
</head>
<body>
  {svg_code}
</body>
</html>"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 720})
            await page.set_content(html_wrapper)
            png_bytes = await page.screenshot(type="png")
            await browser.close()
            return png_bytes

    @classmethod
    async def review_slide_visually(
        cls,
        slide: SlideIR,
        client: Any,
        prompt: str = "请分析当前 PPT 页面的排版布局，检查是否有文字重叠、元素拥挤或边距失衡问题，并给出简明优化意见。"
    ) -> str:
        """Sends visual snapshot to Vision Model for analysis."""
        snapshot_uri = await cls.capture_slide_snapshot(slide)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
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
            return f"视觉检查跳过 ({str(e)})"
