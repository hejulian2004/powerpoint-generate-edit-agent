"""PPT Agent Runtime: Multi-step Observe-Think-Plan-Execute-Review Loop."""

from __future__ import annotations
import json
import logging
from typing import Dict, Any, List, Optional, Callable, AsyncIterator
from .llm import LLMClient
from .tools import tools
from .memory import AgentMemory
from .vision import VisionEngine
from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..config import settings

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Orchestrates Agent perception, reasoning, tool execution, and vision feedback."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.memory = AgentMemory()

    def _build_system_prompt(self, pres: PresentationIR) -> str:
        active_slide = pres.get_active_slide()
        slide_info = []
        for s in pres.slides:
            slide_info.append(f"Slide #{s.slide_num} (ID: '{s.id}', Title: '{s.title or 'Untitled'}', Elements: {len(s.elements)})")

        elements_detail = []
        if active_slide:
            for el in active_slide.elements:
                desc = f"ID: '{el.id}', Type: {el.type}, Rect: ({el.x}, {el.y}, {el.width}x{el.height})"
                if hasattr(el, "text_content") and el.text_content:
                    desc += f", Text: '{el.text_content.plain_text[:40]}'"
                elements_detail.append(f"  - {desc}")

        elements_str = "\n".join(elements_detail) if elements_detail else "  （当前页尚无元素）"
        memory_str = self.memory.build_system_context()

        return f"""你是一位世界顶级的 AI PPT 演示文稿设计与编辑专家（PPT-Agent-Studio）。
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
1. 当用户要求修改、添加、排版时，务必调用对应的工具函数（如 add_text, add_shape, add_connector, update_element, optimize_layout 等）。
2. 画布基准为 1280x720 像素。排版需保证层次分明、对比合理、色彩和谐、无重叠错位。
3. 工具调用后请用精炼亲切的中文向用户总结完成的工作和关键设计决策。
"""

    async def run_turn(
        self,
        user_message: str,
        pres: PresentationIR,
        history: HistoryManager,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        max_iterations: int = 5
    ) -> Dict[str, Any]:
        """Runs an interactive turn with multi-step tool calling."""
        system_prompt = self._build_system_prompt(pres)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        executed_tools_summary: List[Dict[str, Any]] = []
        final_reply = ""

        if on_event:
            await on_event({"type": "agent_thinking", "status": "thinking", "text": "正在分析当前幻灯片与用户需求..."})

        for iteration in range(max_iterations):
            # Request LLM completion with tools
            try:
                response = await self.llm.chat_completion(
                    messages=messages,
                    tools=tools.schemas,
                    role="reasoning"
                )
            except Exception as e:
                logger.error(f"Agent LLM error: {e}")
                final_reply = f"调用大模型服务时发生异常: {str(e)}"
                break

            choice = response["choices"][0]
            msg = choice["message"]
            messages.append(msg)

            # Check if tools are requested
            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                final_reply = msg.get("content", "处理完成。")
                break

            # Execute tool calls
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                args_str = tc["function"].get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except Exception:
                    args = {}

                if on_event:
                    await on_event({
                        "type": "tool_executing",
                        "tool": fn_name,
                        "arguments": args
                    })

                # Run tool handler
                result = tools.execute(fn_name, args, pres, history)

                executed_tools_summary.append({
                    "tool": fn_name,
                    "arguments": args,
                    "result": result
                })

                if on_event:
                    await on_event({
                        "type": "tool_completed",
                        "tool": fn_name,
                        "result": result,
                        "presentation_version": pres.version
                    })

                # Append tool result to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": fn_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })

            # Record in memory
            self.memory.log_action(f"用户指令: '{user_message[:30]}' -> 调用了 {len(tool_calls)} 个工具")

        # Optional Vision Review if multiple changes occurred or requested
        vision_critique = None
        active_slide = pres.get_active_slide()
        if settings.enable_vision_loop and active_slide and len(executed_tools_summary) > 0:
            if on_event:
                await on_event({"type": "vision_loop", "status": "reviewing", "text": "正在进行 Vision Loop 视觉多模态校验..."})
            try:
                vision_critique = await VisionEngine.review_slide_visually(active_slide, self.llm)
            except Exception as e:
                logger.warning(f"Vision review skipped: {e}")

        if on_event:
            await on_event({
                "type": "agent_finished",
                "summary": final_reply,
                "tools_executed": executed_tools_summary,
                "vision_critique": vision_critique,
                "presentation_version": pres.version
            })

        return {
            "reply": final_reply,
            "tools_executed": executed_tools_summary,
            "vision_critique": vision_critique,
            "version": pres.version
        }
