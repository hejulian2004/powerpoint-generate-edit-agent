"""PPT Agent Runtime: LangGraph-powered Multi-step Observe-Plan-Execute-Critique Loop."""

from __future__ import annotations
import json
import logging
from typing import Dict, Any, List, Optional, Callable
from .llm import LLMClient
from .tools import tools
from .memory import AgentMemory
from .vision import VisionEngine
from .graph import build_ppt_agent_graph, PPTAgentState
from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..config import settings

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Orchestrates Agent perception, reasoning, tool execution, and vision feedback using LangGraph."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.memory = AgentMemory()
        self.graph = build_ppt_agent_graph()

    def _build_system_prompt(self, pres: PresentationIR) -> str:
        """Backward-compatible helper for building system prompt context."""
        active_slide = pres.get_active_slide()
        slide_info = [
            f"Slide #{s.slide_num} (ID: '{s.id}', Title: '{s.title or 'Untitled'}', Elements: {len(s.elements)})"
            for s in pres.slides
        ]

        elements_detail = []
        if active_slide:
            for el in active_slide.elements:
                desc = f"ID: '{el.id}', Type: {el.type}, Rect: ({el.x}, {el.y}, {el.width}x{el.height})"
                if hasattr(el, "text_content") and el.text_content:
                    desc += f", Text: '{el.text_content.plain_text[:40]}'"
                elements_detail.append(f"  - {desc}")

        elements_str = "\n".join(elements_detail) if elements_detail else "  （当前页尚无元素）"
        memory_str = self.memory.build_system_context()

        return f"""你是一位世界顶级的 AI PPT 演示文稿设计与编辑专家（PPT-Agent-Studio，基于 LangGraph 状态图）。
你的核心任务是理解用户意图，通过调用提供的专业 PPT 工具，直接、高精度地创建、修改或优化 PPT-IR（演示文稿中间表示）。

【演示文稿当前状态】:
- 演示文稿标题: {pres.title}
- 幻灯片总数: {len(pres.slides)}
- 列表:
{chr(10).join(f"- {s}" for s in slide_info)}

【当前正编辑的幻灯片 (ID: {active_slide.id if active_slide else 'None'}) 元素清单】:
{elements_str}

{memory_str}

【重要操作准则】:
1. 画布基准严格为 1280x720 像素。排版需层次分明、对比合理、色彩和谐、无重叠错位。
2. 生成多页 PPT 时调用 generate_presentation；生成页面排版调用 generate_slide_layout 或 batch_add_cards。
3. 精确微调图元调用 update_element, format_text, align_elements 或 optimize_layout。
"""

    async def run_turn(
        self,
        user_message: str,
        pres: PresentationIR,
        history: HistoryManager,
        session: Optional[Any] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        max_iterations: int = 5,
        confirmed_tool_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Runs an interactive turn executed through the LangGraph state machine.

        `confirmed_tool_ids` lets a caller explicitly unblock previously flagged
        call ids for this turn (used by the confirmation lifecycle when replaying
        the original pending call through the graph).
        """
        confirmed_ids = list(confirmed_tool_ids or [])
        initial_state: PPTAgentState = {
            "user_query": user_message,
            "messages": [{"role": "user", "content": user_message}],
            "iteration": 0,
            "max_iterations": max_iterations,
            "active_slide_id": pres.active_slide_id,
            "presentation_version": pres.version,
            "tool_calls": [],
            "tool_results": [],
            "confirmed_tool_ids": confirmed_ids,
        }

        config = {
            "configurable": {
                "pres": pres,
                "history": history,
                "session": session,
                "on_event": on_event,
                "llm_client": self.llm,
                "memory": self.memory,
                "confirmed_tool_ids": confirmed_ids,
            }
        }

        try:
            final_state = await self.graph.ainvoke(initial_state, config=config)

            reply = final_state.get("final_summary", "处理完成。")
            executed_tools = final_state.get("tool_results", [])
            vision_critique = final_state.get("vision_critique")
            intent = final_state.get("intent", "chat")
            plan = final_state.get("plan", "")

            return {
                "reply": reply,
                "tools_executed": executed_tools,
                "vision_critique": vision_critique,
                "version": pres.version,
                "intent": intent,
                "plan": plan
            }
        except Exception as e:
            logger.error(f"LangGraph execution error: {e}", exc_info=True)
            err_msg = f"LangGraph 运行异常: {str(e)}"
            if on_event:
                await on_event({"type": "agent_error", "error": err_msg})
            return {
                "reply": err_msg,
                "tools_executed": [],
                "vision_critique": None,
                "version": pres.version,
                "error": str(e)
            }

    # ------------------------------------------------------------------
    # Pending confirmation lifecycle (PR6-hardening round 2)
    # ------------------------------------------------------------------

    async def confirm_pending(
        self,
        session: Any,
        call_id: str,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Executes the ORIGINAL pending call after explicit user confirmation.

        Confirmation is invalidated when the presentation changed since the call was
        blocked: executing it against a newer version could hit a different element.
        """
        record = session.get_pending_confirmation(call_id) if session else None
        if record is None:
            result = {
                "success": False,
                "error": "unknown_confirmation",
                "message": f"未找到待确认的挂起调用（call_id: {call_id}）。",
            }
            if on_event:
                await on_event({"type": "confirmation_failed", "call_id": call_id, **result})
            return result

        current_version = session.pres.version
        if record["presentation_version"] != current_version:
            session.consume_pending_confirmation(call_id)
            result = {
                "success": False,
                "error": "confirmation_invalidated",
                "call_id": call_id,
                "expected_version": record["presentation_version"],
                "current_version": current_version,
                "message": (
                    "演示文稿在等待确认期间已发生变化，该挂起调用已失效，"
                    "请重新发起指令。"
                ),
            }
            if on_event:
                await on_event({"type": "confirmation_invalidated", **result})
            return result

        session.consume_pending_confirmation(call_id)

        if on_event:
            await on_event({
                "type": "confirmation_approved",
                "call_id": call_id,
                "tool": record["tool"],
            })

        res = tools.execute(record["tool"], record["arguments"], session.pres, session.history)
        target_el_id = record["arguments"].get("element_id") or (
            res.get("element_id") if isinstance(res, dict) else None
        )
        if target_el_id and hasattr(session, "last_target_id"):
            session.last_target_id = target_el_id

        if on_event:
            await on_event({
                "type": "tool_completed",
                "tool": record["tool"],
                "result": res,
                "presentation_version": session.pres.version,
                "confirmed_call_id": call_id,
            })
            await on_event({
                "type": "confirmation_resolved",
                "call_id": call_id,
                "tool": record["tool"],
                "success": bool(res.get("success")) if isinstance(res, dict) else False,
            })

        return {
            "success": bool(res.get("success")) if isinstance(res, dict) else False,
            "call_id": call_id,
            "tool": record["tool"],
            "result": res,
            "version": session.pres.version,
        }

    async def cancel_pending(
        self,
        session: Any,
        call_id: str,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Discards a pending call without executing it."""
        record = session.consume_pending_confirmation(call_id) if session else None
        result = {
            "success": record is not None,
            "call_id": call_id,
            "cancelled": record is not None,
            "message": "已取消待确认操作。" if record else f"未找到待确认的挂起调用（call_id: {call_id}）。",
        }
        if on_event:
            await on_event({"type": "confirmation_cancelled", **result})
        return result
