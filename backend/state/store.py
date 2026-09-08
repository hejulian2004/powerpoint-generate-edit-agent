"""Session and Application State Store.

Manages:
- Active PresentationIR instance and slide selection
- HistoryManager (undo / redo)
- PPTX import via PPTXParser and export via PPTXBuilder
- WebSocket connection broadcasting
"""

from __future__ import annotations
import os
import io
import tempfile
import logging
from typing import Dict, Any, List, Optional
from fastapi import WebSocket

from ..ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, FillStyle, BorderStyle, ShadowStyle,
    FontIR, TextContentIR, ParagraphIR, RunIR
)
from ..ir.converter import PPTIRConverter
from ..ir.patch import HistoryManager
from ..agent.runtime import AgentRuntime
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder

logger = logging.getLogger(__name__)


def create_default_demo_presentation() -> PresentationIR:
    """Creates a beautifully crafted default presentation with title & cards."""
    # Slide 1: Welcome & Overview
    slide1 = SlideIR(
        id="slide_01",
        slide_num=1,
        title="AI 驱动的 PPT 智能生成与编辑平台",
        background=FillStyle(type="solid", color="#0B0F19", alpha=1.0),
        elements=[
            TextElementIR(
                id="title_main",
                name="Title",
                x=120,
                y=90,
                width=1040,
                height=70,
                text_content=TextContentIR.from_plain_text(
                    "PPT-Agent-Studio 智能演示平台",
                    font=FontIR(name="Segoe UI", size=38.0, color="#F8FAFC", bold=True),
                    align="center"
                )
            ),
            TextElementIR(
                id="subtitle_main",
                name="Subtitle",
                x=160,
                y=170,
                width=960,
                height=40,
                text_content=TextContentIR.from_plain_text(
                    "基于 PPT-IR 中间表示 · 双向 OOXML 原生转换 · Vision Loop 视觉自省",
                    font=FontIR(name="Segoe UI", size=18.0, color="#94A3B8", bold=False),
                    align="center"
                )
            ),
            # Card 1: IR Core
            ShapeElementIR(
                id="card_ir",
                name="IR Card",
                shape_type="roundRect",
                x=120,
                y=260,
                width=320,
                height=300,
                style=dict(
                    fill=FillStyle(type="solid", color="#1E293B", alpha=0.9),
                    border=BorderStyle(color="#3B82F6", width=2.0),
                    shadow=ShadowStyle(enabled=True, blur=8.0, alpha=0.3),
                    radius=16.0
                ),
                text_content=TextContentIR.from_plain_text(
                    "① PPT-IR 核心抽象\n\n以 1280x720 像素基准为核心状态，解耦具体文件格式。\n支持细粒度元素增删改与补丁差异追踪。",
                    font=FontIR(name="Segoe UI", size=16.0, color="#E2E8F0"),
                    align="left"
                )
            ),
            # Card 2: Agent Tools
            ShapeElementIR(
                id="card_agent",
                name="Agent Card",
                shape_type="roundRect",
                x=480,
                y=260,
                width=320,
                height=300,
                style=dict(
                    fill=FillStyle(type="solid", color="#1E293B", alpha=0.9),
                    border=BorderStyle(color="#10B981", width=2.0),
                    shadow=ShadowStyle(enabled=True, blur=8.0, alpha=0.3),
                    radius=16.0
                ),
                text_content=TextContentIR.from_plain_text(
                    "② AI Agent 运行时\n\n通过自然语言驱动 Tool Calling，自动化完成图形排版、色彩搭配与文本重写。\n支持多模型协作路由与上下文记忆。",
                    font=FontIR(name="Segoe UI", size=16.0, color="#E2E8F0"),
                    align="left"
                )
            ),
            # Card 3: Live Preview & OOXML
            ShapeElementIR(
                id="card_preview",
                name="Export Card",
                shape_type="roundRect",
                x=840,
                y=260,
                width=320,
                height=300,
                style=dict(
                    fill=FillStyle(type="solid", color="#1E293B", alpha=0.9),
                    border=BorderStyle(color="#8B5CF6", width=2.0),
                    shadow=ShadowStyle(enabled=True, blur=8.0, alpha=0.3),
                    radius=16.0
                ),
                text_content=TextContentIR.from_plain_text(
                    "③ 实时渲染与无损导出\n\n毫秒级 SVG 实时重绘与双向 WebSocket 推送。\n底层直连 OOXML 引擎，实现原生 .pptx 高保真导入导出。",
                    font=FontIR(name="Segoe UI", size=16.0, color="#E2E8F0"),
                    align="left"
                )
            ),
            # Arrows connecting cards
            ConnectorElementIR(
                id="conn_1_2",
                start_x=440,
                start_y=410,
                end_x=480,
                end_y=410,
                arrow_end="triangle",
                style=dict(border=BorderStyle(color="#60A5FA", width=2.5))
            ),
            ConnectorElementIR(
                id="conn_2_3",
                start_x=800,
                start_y=410,
                end_x=840,
                end_y=410,
                arrow_end="triangle",
                style=dict(border=BorderStyle(color="#34D399", width=2.5))
            )
        ]
    )

    # Slide 2: Workflow
    slide2 = SlideIR(
        id="slide_02",
        slide_num=2,
        title="Agent 闭环架构与执行链路",
        background=FillStyle(type="solid", color="#0B0F19", alpha=1.0),
        elements=[
            TextElementIR(
                id="s2_title",
                x=120,
                y=80,
                width=1040,
                height=60,
                text_content=TextContentIR.from_plain_text(
                    "Agent 循环与 Vision Loop 视觉自省",
                    font=FontIR(name="Segoe UI", size=32.0, color="#F8FAFC", bold=True),
                    align="left"
                )
            ),
            ShapeElementIR(
                id="step_observe",
                shape_type="roundRect",
                x=120,
                y=220,
                width=220,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#1E293B"), border=BorderStyle(color="#38BDF8", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("1. Observe\n感知幻灯片结构与元素", font=FontIR(color="#FFFFFF", size=16.0), align="center")
            ),
            ShapeElementIR(
                id="step_think",
                shape_type="roundRect",
                x=420,
                y=220,
                width=220,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#1E293B"), border=BorderStyle(color="#818CF8", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("2. Think & Plan\n推理意图与规划工具集", font=FontIR(color="#FFFFFF", size=16.0), align="center")
            ),
            ShapeElementIR(
                id="step_exec",
                shape_type="roundRect",
                x=720,
                y=220,
                width=220,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#1E293B"), border=BorderStyle(color="#34D399", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("3. Tool Execute\n精确修改 PPT-IR 元素", font=FontIR(color="#FFFFFF", size=16.0), align="center")
            ),
            ShapeElementIR(
                id="step_vision",
                shape_type="roundRect",
                x=1020,
                y=220,
                width=200,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#1E293B"), border=BorderStyle(color="#F472B6", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("4. Vision Review\n多模态截图质检与重调", font=FontIR(color="#FFFFFF", size=16.0), align="center")
            )
        ]
    )

    return PresentationIR(
        id="pres_demo_01",
        title="PPT-Agent-Studio 演示文稿",
        slides=[slide1, slide2],
        active_slide_id="slide_01",
        version=1
    )


class PresentationStore:
    """Singleton store managing current presentation state and clients."""

    def __init__(self):
        self.presentation: PresentationIR = create_default_demo_presentation()
        self.history = HistoryManager()
        self.agent_runtime = AgentRuntime()
        self.active_websockets: List[WebSocket] = []

    def get_presentation(self) -> PresentationIR:
        return self.presentation

    def set_active_slide(self, slide_id: str) -> bool:
        if self.presentation.get_slide(slide_id):
            self.presentation.active_slide_id = slide_id
            return True
        return False

    def import_pptx_bytes(self, data: bytes, filename: str = "imported.pptx") -> PresentationIR:
        """Parses native PPTX bytes into PPT-IR."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            parser = PPTXParser(tmp_path)
            ooxml_pres = parser.parse()
            ir_pres = PPTIRConverter.presentation_to_ir(ooxml_pres)
            ir_pres.title = filename.replace(".pptx", "")

            self.presentation = ir_pres
            self.history = HistoryManager()
            return self.presentation
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def export_pptx_bytes(self) -> bytes:
        """Renders PPT-IR into native PPTX binary bytes."""
        ooxml_pres = PPTIRConverter.ir_to_presentation(self.presentation)
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            builder = PPTXBuilder()
            builder.build(ooxml_pres, tmp_path)
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def undo(self) -> Optional[Dict[str, Any]]:
        patch = self.history.undo(self.presentation)
        return patch.model_dump() if patch else None

    def redo(self) -> Optional[Dict[str, Any]]:
        patch = self.history.redo(self.presentation)
        return patch.model_dump() if patch else None

    # WebSocket registration
    async def connect_ws(self, ws: WebSocket):
        await ws.accept()
        self.active_websockets.append(ws)

    def disconnect_ws(self, ws: WebSocket):
        if ws in self.active_websockets:
            self.active_websockets.remove(ws)

    async def broadcast(self, message: Dict[str, Any]):
        for ws in list(self.active_websockets):
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Error sending to ws client: {e}")
                self.disconnect_ws(ws)


store = PresentationStore()
