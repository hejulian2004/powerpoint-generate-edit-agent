"""Session and Application State Store.

Manages:
- Active PresentationIR instance and slide selection
- HistoryManager (undo / redo)
- PPTX import via FidelityEngine/OOXMLParser (production) and export via PPTXBuilder
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
from ..ir.converter import PPTIRConverter, import_pptx
from ..ir.patch import HistoryManager
from ..agent.runtime import AgentRuntime
from ..session.manager import session_manager, SessionManager
from ..session.session import PPTSession
from pptx_agent_converter.renderer.pptx_builder import PPTXBuilder

logger = logging.getLogger(__name__)


def create_default_demo_presentation() -> PresentationIR:
    """Creates a beautifully crafted default presentation with white background & crisp cards."""
    # Slide 1: Welcome & Overview
    slide1 = SlideIR(
        id="slide_01",
        slide_num=1,
        title="AI 驱动的 PPT 智能生成与编辑平台",
        background=FillStyle(type="solid", color="#FFFFFF", alpha=1.0),
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
                    font=FontIR(name="Segoe UI", size=38.0, color="#0F172A", bold=True),
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
                    font=FontIR(name="Segoe UI", size=18.0, color="#475569", bold=False),
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
                    fill=FillStyle(type="solid", color="#F8FAFC", alpha=1.0),
                    border=BorderStyle(color="#E2E8F0", width=1.5),
                    shadow=ShadowStyle(enabled=True, blur=12.0, alpha=0.08),
                    radius=12.0
                ),
                text_content=TextContentIR.from_plain_text(
                    "① PPT-IR 核心抽象\n\n以 1280x720 像素基准为核心状态，解耦具体文件格式。\n支持细粒度元素增删改与补丁差异追踪。",
                    font=FontIR(name="Segoe UI", size=15.0, color="#334155"),
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
                    fill=FillStyle(type="solid", color="#F8FAFC", alpha=1.0),
                    border=BorderStyle(color="#E2E8F0", width=1.5),
                    shadow=ShadowStyle(enabled=True, blur=12.0, alpha=0.08),
                    radius=12.0
                ),
                text_content=TextContentIR.from_plain_text(
                    "② AI Agent 运行时\n\n通过自然语言驱动 Tool Calling，自动化完成图形排版、色彩搭配与文本重写。\n支持多模型协作路由与上下文记忆。",
                    font=FontIR(name="Segoe UI", size=15.0, color="#334155"),
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
                    fill=FillStyle(type="solid", color="#F8FAFC", alpha=1.0),
                    border=BorderStyle(color="#E2E8F0", width=1.5),
                    shadow=ShadowStyle(enabled=True, blur=12.0, alpha=0.08),
                    radius=12.0
                ),
                text_content=TextContentIR.from_plain_text(
                    "③ 实时渲染与高保真导出\n\n毫秒级 SVG 实时重绘与双向 WebSocket 推送。\n底层直连 OOXML 引擎，实现原生 .pptx 核心元素高保真导入导出。",
                    font=FontIR(name="Segoe UI", size=15.0, color="#334155"),
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
                style=dict(border=BorderStyle(color="#94A3B8", width=2.0))
            ),
            ConnectorElementIR(
                id="conn_2_3",
                start_x=800,
                start_y=410,
                end_x=840,
                end_y=410,
                arrow_end="triangle",
                style=dict(border=BorderStyle(color="#94A3B8", width=2.0))
            )
        ]
    )

    # Slide 2: Workflow
    slide2 = SlideIR(
        id="slide_02",
        slide_num=2,
        title="Agent 闭环架构与执行链路",
        background=FillStyle(type="solid", color="#FFFFFF", alpha=1.0),
        elements=[
            TextElementIR(
                id="s2_title",
                x=120,
                y=80,
                width=1040,
                height=60,
                text_content=TextContentIR.from_plain_text(
                    "Agent 循环与 Vision Loop 视觉自省",
                    font=FontIR(name="Segoe UI", size=32.0, color="#0F172A", bold=True),
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
                style=dict(fill=FillStyle(type="solid", color="#F8FAFC"), border=BorderStyle(color="#CBD5E1", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("1. Observe\n感知幻灯片结构与元素", font=FontIR(color="#0F172A", size=15.0), align="center")
            ),
            ShapeElementIR(
                id="step_think",
                shape_type="roundRect",
                x=420,
                y=220,
                width=220,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#F8FAFC"), border=BorderStyle(color="#CBD5E1", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("2. Think & Plan\n推理意图与规划工具集", font=FontIR(color="#0F172A", size=15.0), align="center")
            ),
            ShapeElementIR(
                id="step_exec",
                shape_type="roundRect",
                x=720,
                y=220,
                width=220,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#F8FAFC"), border=BorderStyle(color="#CBD5E1", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("3. Tool Execute\n精确修改 PPT-IR 元素", font=FontIR(color="#0F172A", size=15.0), align="center")
            ),
            ShapeElementIR(
                id="step_vision",
                shape_type="roundRect",
                x=1020,
                y=220,
                width=200,
                height=140,
                style=dict(fill=FillStyle(type="solid", color="#F8FAFC"), border=BorderStyle(color="#CBD5E1", width=1.5), radius=12.0),
                text_content=TextContentIR.from_plain_text("4. Vision Review\n多模态截图质检与重调", font=FontIR(color="#0F172A", size=15.0), align="center")
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
    """Singleton store managing current presentation state, sessions, and clients."""

    def __init__(self):
        self.session_manager: SessionManager = session_manager
        self.active_session_id: str = SessionManager.DEFAULT_SESSION_ID
        default_pres = create_default_demo_presentation()
        self.session_manager.get_or_create(self.active_session_id, pres_factory=lambda: default_pres)
        self.agent_runtime = AgentRuntime()
        self.active_websockets: List[WebSocket] = []
        self.session_websockets: Dict[str, List[WebSocket]] = {}
        self.ws_session_map: Dict[WebSocket, str] = {}

    @property
    def active_session(self) -> PPTSession:
        return self.session_manager.get_or_create(
            self.active_session_id,
            pres_factory=create_default_demo_presentation
        )

    @property
    def presentation(self) -> PresentationIR:
        return self.active_session.pres

    @presentation.setter
    def presentation(self, pres: PresentationIR):
        self.active_session.pres = pres

    @property
    def history(self):
        return self.active_session.history

    @history.setter
    def history(self, h):
        self.active_session.history = h

    def get_presentation(self) -> PresentationIR:
        return self.active_session.pres

    def set_active_slide(self, slide_id: str) -> bool:
        return self.active_session.set_active_slide(slide_id)

    def import_pptx_bytes(
        self,
        data: bytes,
        filename: str = "imported.pptx",
        session: Optional[PPTSession] = None,
    ) -> PresentationIR:
        """Parses native PPTX bytes into PPT-IR for the given session (or active_session)."""
        target_session = session or self.active_session
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            # Production import path: FidelityEngine/OOXMLParser (via import_pptx)
            ir_pres = import_pptx(tmp_path)
            ir_pres.title = filename.replace(".pptx", "")

            target_session.pres = ir_pres
            target_session.history.clear()
            target_session.last_target_id = None
            target_session.last_action_type = None
            target_session.checkpoint_mgr.clear()
            target_session.create_checkpoint(description=f"Imported from {filename}")
            return target_session.pres
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def export_pptx_bytes(self, pres: Optional[PresentationIR] = None) -> bytes:
        """Renders PPT-IR into native PPTX binary bytes.
        
        Accepts explicit PresentationIR or defaults to current active presentation.
        """
        target_pres = pres if pres is not None else self.presentation
        ooxml_pres = PPTIRConverter.ir_to_presentation(target_pres)
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

    def export_pptx_bytes_for_session(self, session_id: str) -> bytes:
        """Renders target session's PPT-IR into native PPTX binary bytes."""
        sess = self.session_manager.get_session(session_id)
        if not sess:
            raise KeyError(f"Session '{session_id}' not found")
        return self.export_pptx_bytes(pres=sess.pres)

    def undo(self) -> Optional[Dict[str, Any]]:
        patch = self.active_session.undo()
        if not patch:
            return None
        if hasattr(patch, "model_dump"):
            return patch.model_dump()
        elif hasattr(patch, "to_dict"):
            return patch.to_dict()
        return dict(patch)

    def redo(self) -> Optional[Dict[str, Any]]:
        patch = self.active_session.redo()
        if not patch:
            return None
        if hasattr(patch, "model_dump"):
            return patch.model_dump()
        elif hasattr(patch, "to_dict"):
            return patch.to_dict()
        return dict(patch)

    # WebSocket registration with session isolation
    async def connect_ws(self, ws: WebSocket, session_id: Optional[str] = None):
        await ws.accept()
        sid = session_id or self.active_session_id
        if ws not in self.active_websockets:
            self.active_websockets.append(ws)
        self.ws_session_map[ws] = sid
        if sid not in self.session_websockets:
            self.session_websockets[sid] = []
        if ws not in self.session_websockets[sid]:
            self.session_websockets[sid].append(ws)

    def disconnect_ws(self, ws: WebSocket):
        if ws in self.active_websockets:
            self.active_websockets.remove(ws)
        sid = self.ws_session_map.pop(ws, None)
        if sid and sid in self.session_websockets:
            if ws in self.session_websockets[sid]:
                self.session_websockets[sid].remove(ws)
            if not self.session_websockets[sid]:
                del self.session_websockets[sid]

    async def broadcast(self, message: Dict[str, Any], session_id: Optional[str] = None):
        sid = session_id or message.get("session_id")
        if sid:
            targets = list(self.session_websockets.get(sid, []))
        else:
            targets = list(self.active_websockets)

        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"Error sending to ws client: {e}")
                self.disconnect_ws(ws)


store = PresentationStore()
