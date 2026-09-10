"""Independent Executor Subagent.

Responsible for planning deterministic and tool-based slide manipulation
operations. The subagent is strictly a PLANNER: it produces an `ExecutorPlan`
(tool calls) from the user intent, plan description, and canvas context.

It has NO tool execution authority. All mutations are committed by the graph's
`mutation_node` through `MutationGateway`, which enforces risk gating, schema
validation, confirmation, and transaction safety. This keeps the safety gate on
the only path that can write to the PresentationIR.
"""

from __future__ import annotations
import inspect
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from ...ir.models import PresentationIR
from ..memory import AgentMemory
from ..llm import LLMClient
from .. import tools

logger = logging.getLogger(__name__)

# Bounded context window for the executor planning prompt. The full transcript is
# already token-managed by ContextCompressor; this keeps the executor call concise.
MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 1200


def _split_conversation_context(
    conversation_context: Optional[List[Dict[str, Any]]],
    current_user_query: str = "",
) -> tuple[str, List[Dict[str, Any]]]:
    """Splits model-facing context into a compressed anchor and recent chat turns.

    - `system` messages (e.g. the compressor's history anchor) become an anchor text.
    - `user`/`assistant` turns are tail-windowed and length-capped.
    - The current user turn (already embedded in the execution directive) is dropped
      to avoid duplicating it in the prompt.
    """
    messages = list(conversation_context or [])
    anchors = [
        str(m.get("content", "")).strip()
        for m in messages
        if m.get("role") == "system" and str(m.get("content", "")).strip()
    ]
    chat: List[Dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        chat.append({"role": role, "content": content[:MAX_CONTEXT_CHARS]})

    if chat and current_user_query:
        last = chat[-1]
        if last["role"] == "user" and last["content"].strip() == current_user_query.strip():
            chat.pop()

    return ("\n".join(anchors[-1:])), chat[-MAX_CONTEXT_MESSAGES:]


@dataclass
class ExecutorPlan:
    """Proposed tool calls for the MutationGateway. Execution is not implied."""

    tool_calls: List[Dict[str, Any]]
    summary_message: str
    subagent_info: Dict[str, Any] = field(default_factory=lambda: {
        "subagent_name": "ExecutorSubagent",
        "context_isolated": True,
        "role": "slide_production_planner"
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_calls": self.tool_calls,
            "summary_message": self.summary_message,
            "subagent_info": self.subagent_info,
        }


@dataclass
class ExecutorReport:
    """Detailed report assembled after the gateway commits an execution plan."""
    success: bool
    tool_results: List[Dict[str, Any]]
    executed_tools: List[str]
    presentation_version: int
    last_target_id: Optional[str]
    summary_message: str
    error: Optional[str] = None
    subagent_info: Dict[str, Any] = field(default_factory=lambda: {
        "subagent_name": "ExecutorSubagent",
        "context_isolated": True,
        "role": "slide_production_executor"
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tool_results": self.tool_results,
            "executed_tools": self.executed_tools,
            "presentation_version": self.presentation_version,
            "last_target_id": self.last_target_id,
            "summary_message": self.summary_message,
            "error": self.error,
            "subagent_info": self.subagent_info
        }


class ExecutorSubagent:
    """Independent Executor Subagent for slide authoring operations."""

    @classmethod
    async def plan_task(
        cls,
        intent: str,
        user_query: str,
        plan_desc: str,
        pres: Optional[PresentationIR],
        memory: Optional[AgentMemory] = None,
        llm_client: Optional[LLMClient] = None,
        last_target_id: Optional[str] = None,
        session: Optional[Any] = None,
        on_event: Optional[Callable] = None,
        conversation_context: Optional[List[Dict[str, Any]]] = None,
        rework_directive: Optional[Dict[str, Any]] = None,
        grounding: Optional[Dict[str, Any]] = None
    ) -> ExecutorPlan:
        """Builds an execution plan (tool calls) without mutating the presentation."""
        # 1. Broadcast lifecycle start: Main agent pauses waiting for executor subagent
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "started",
                "subagent": "ExecutorSubagent",
                "main_agent_status": "paused_waiting",
                "intent": intent,
                "text": "主 Agent 已暂停等候，独立制作执行 Subagent 介入执行图元编排与操作..."
            })

        # 2. Determine tool calls (LLM tool-calling or heuristic deterministic planner)
        has_live_llm = (
            llm_client
            and getattr(llm_client, "api_key", None)
            and not str(llm_client.api_key).startswith("mock_")
            and not str(llm_client.api_key).startswith("loop_mock_")
        )
        tool_calls: List[Dict[str, Any]] = []
        rework_desc = cls._build_rework_directive_text(rework_directive)

        if has_live_llm:
            from ..graph import _build_llm_system_prompt
            system_prompt = _build_llm_system_prompt(pres, memory)
            anchor_text, context_messages = _split_conversation_context(
                conversation_context, current_user_query=user_query
            )
            if anchor_text:
                system_prompt += f"\n\n【历史会话压缩摘要】:\n{anchor_text}"
            if grounding and grounding.get("enforce_numeric_grounding"):
                source_excerpt = (grounding.get("source_text") or "").strip()[:2000]
                system_prompt += (
                    "\n\n【真实性约束 (硬性)】: 只允许使用用户在对话中提供的数字与事实，"
                    "严禁编造、外推或自行补充任何数值、指标、百分比、时间与专有名词；"
                    "资料不足时改用定性表述，不要调用包含臆造数字的工具参数。"
                )
                if source_excerpt:
                    system_prompt += f"\n【用户资料原文】:\n{source_excerpt}"
            # Combine plan and query into concise execution directive
            exec_prompt = f"任务意图: {intent}\n规划要求: {plan_desc}\n用户输入: {user_query}{rework_desc}"
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(context_messages)
            messages.append({"role": "user", "content": exec_prompt})
            try:
                resp = await llm_client.chat_completion(
                    messages=messages,
                    tools=tools.schemas,
                    role="reasoning"
                )
                raw_tc = resp["choices"][0]["message"].get("tool_calls", [])
                for tc in raw_tc:
                    fn_name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"].get("arguments", "{}"))
                    except Exception:
                        args = {}
                    tool_calls.append({
                        "name": fn_name,
                        "arguments": args,
                        "id": tc.get("id", f"call_{uuid.uuid4().hex[:6]}")
                    })
            except Exception as e:
                logger.warning(f"ExecutorSubagent LLM call error: {e}, using heuristic planner")
                from ..graph import _heuristic_tool_planner
                tool_calls = _heuristic_tool_planner(intent, user_query, pres, last_target_id=last_target_id)

        if not has_live_llm or not tool_calls:
            from ..graph import _heuristic_tool_planner
            tool_calls = _heuristic_tool_planner(intent, user_query, pres, last_target_id=last_target_id)

        # A content rework must be precise: never regenerate the whole deck.
        if rework_directive:
            tool_calls = [
                tc for tc in tool_calls
                if tc.get("name") not in ("generate_presentation",)
            ]

        tool_names = [tc.get("name", "") for tc in tool_calls if isinstance(tc, dict)]
        tool_summary_desc = ', '.join(n for n in tool_names if n) if tool_names else '无具体工具'
        summary = f"执行 Subagent 已完成操作规划，计划运行: {tool_summary_desc}。"

        return ExecutorPlan(tool_calls=tool_calls, summary_message=summary)

    @staticmethod
    def _build_rework_directive_text(rework_directive: Optional[Dict[str, Any]]) -> str:
        """Formats a ContentCritic rework directive for the execution prompt."""
        if not rework_directive:
            return ""
        defects = "; ".join(
            str(d) for d in (rework_directive.get("defects") or [])[:4] if str(d).strip()
        )
        recommendations = "; ".join(
            str(r) for r in (rework_directive.get("recommendations") or [])[:4] if str(r).strip()
        )
        target_ids = ", ".join(rework_directive.get("target_ids") or [])
        return (
            "\n\n【返工模式（内容评审未通过）】请只做精准文本修正，"
            "严禁重新生成整份演示文稿或整页布局。\n"
            f"- 目标页: {rework_directive.get('slide_id') or '当前页'}\n"
            f"- 可修改图元: {target_ids or '相关文本图元'}\n"
            f"- 缺陷: {defects or '文案冗余或格式问题'}\n"
            f"- 修改建议: {recommendations or '按评审建议精炼文案'}"
        )

    @classmethod
    async def emit_completed(
        cls,
        executed_tools: List[str],
        on_event: Optional[Callable],
        error: Optional[str] = None
    ) -> None:
        """Broadcasts the lifecycle completion event after the gateway commits the plan."""
        tool_summary_desc = ', '.join(executed_tools) if executed_tools else '无具体工具'
        if error:
            text = f"制作执行 Subagent 汇报完成 [已执行: {tool_summary_desc}]，存在异常: {error}"
        else:
            text = f"制作执行 Subagent 汇报完成 [已执行: {tool_summary_desc}]，唤醒主 Agent 继续调度"
        await cls._safe_emit(on_event, {
            "type": "subagent_lifecycle",
            "phase": "completed",
            "subagent": "ExecutorSubagent",
            "main_agent_status": "resumed",
            "executed_tools": executed_tools,
            "error": error,
            "text": text
        })

    @staticmethod
    async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]):
        if not on_event:
            return
        try:
            if inspect.iscoroutinefunction(on_event):
                await on_event(data)
            else:
                res = on_event(data)
                if inspect.isawaitable(res):
                    await res
        except Exception as e:
            logger.debug(f"Executor Subagent event emission ignored: {e}")
