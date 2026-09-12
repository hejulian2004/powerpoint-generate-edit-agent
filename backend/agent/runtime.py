"""PPT Agent Runtime: LangGraph-powered Multi-step Observe-Plan-Execute-Critique Loop."""

from __future__ import annotations
import json
import uuid
import logging
from typing import Dict, Any, List, Optional, Callable
from .llm import LLMClient
from .memory import AgentMemory
from .vision import VisionEngine
from .graph import build_ppt_agent_graph, PPTAgentState
from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..config import settings
from ..session.services.agent_execution import (
    AGENT_TURN_IN_PROGRESS,
    AgentTurnInProgress,
)

logger = logging.getLogger(__name__)

# Terminal rejection messages for a turn that fails admission.
_ADMISSION_MESSAGES = {
    "request_epoch_mismatch": "演示文稿已被替换，本次指令未执行，已同步到最新版本，请重试。",
    "request_stale": "演示文稿已在您发送后更新，本次指令未执行，已同步到最新版本，请重试。",
    AGENT_TURN_IN_PROGRESS: "演示文稿正被另一个 Agent 任务编辑，请稍后重试。",
}


async def _emit(on_event: Optional[Callable], event: Dict[str, Any]) -> None:
    if not on_event:
        return
    import inspect
    try:
        if inspect.iscoroutinefunction(on_event):
            await on_event(event)
        else:
            result = on_event(event)
            if inspect.isawaitable(result):
                await result
    except Exception as e:
        logger.debug(f"Event emission ignored: {e}")


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

    async def _reject_turn(
        self,
        on_event: Optional[Callable[[Dict[str, Any]], Any]],
        *,
        code: str,
        message: str,
        version: Optional[int],
        document_epoch: Optional[str],
    ) -> Dict[str, Any]:
        """Terminally rejects a turn whose request stamps are stale.

        Emits a `turn_rejected` event and returns without appending to the
        transcript or invoking the graph. The transport attaches the canonical
        snapshot so the client can resync in the same round-trip.
        """
        if on_event:
            try:
                await on_event({
                    "type": "turn_rejected",
                    "error": code,
                    "version": version,
                    "document_epoch": document_epoch,
                })
            except Exception as e:
                logger.debug(f"Failed to emit turn_rejected: {e}")
        return {
            "reply": message,
            "tools_executed": [],
            "vision_critique": None,
            "version": version,
            "intent": "chat",
            "turn_rejected": True,
            "error": code,
        }

    async def run_turn(
        self,
        user_message: str,
        pres: PresentationIR,
        history: HistoryManager,
        session: Optional[Any] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        max_iterations: int = 5,
        confirmed_tool_ids: Optional[List[str]] = None,
        request_document_epoch: Optional[str] = None,
        request_base_revision: Optional[int] = None,
        ui_context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Runs an interactive turn executed through the LangGraph state machine.

        `confirmed_tool_ids` lets a caller explicitly unblock previously flagged
        call ids for this turn (used by the confirmation lifecycle when replaying
        the original pending call through the graph).

        `request_document_epoch` / `request_base_revision` are the document
        identity the CLIENT observed when it issued this request. They are
        distinct from the per-plan `plan_document_epoch` / `plan_base_revision`:
        the transport freezes the request stamp, and the turn is terminally
        invalidated if the document identity changes before any write.

        `ui_context` carries the requesting client's active slide / selection so
        deictic references bind to explicit element ids. It is request-scoped and
        never written into the document.
        """
        confirmed_ids = list(confirmed_tool_ids or [])
        from .uicontext import UIContext
        ctx = UIContext.from_any(ui_context)
        from .context_compressor import ContextCompressor, CONTEXT_LIMIT_PRESETS

        # Session-owned memory: conversation + agent + subagent memories all live
        # on the session (S3/S9). AgentRuntime is a stateless engine, so it seeds
        # the graph from the session and writes subagent continuity back after.
        session_memory = session.memory if session is not None else None
        seeded_subagent_memories = (
            {name: mem.to_dict() for name, mem in session_memory.subagent_memories.items()}
            if session_memory is not None
            else {}
        )

        # 0. Atomic admission: validate the request CAS AND install the exclusive
        #    Agent turn lease inside ONE `document.mutation_lock` critical section.
        #    There is then no window for a GUI mutation to commit between a passing
        #    CAS and the freeze being installed. The lock protects admission only;
        #    it is released before the transcript is appended and the LLM runs.
        #    Any admission failure appends no transcript, mutates no memory, emits
        #    no `document_frozen`, and never invokes the graph.
        live_epoch = session.document.epoch if session is not None else None
        live_revision = pres.version if pres is not None else None
        turn_id = f"turn_{uuid.uuid4().hex[:10]}"
        admitted = False
        if session is not None:
            admission_error: Optional[str] = None
            async with session.document.mutation_lock:
                live_epoch = session.document.epoch
                live_revision = pres.version
                if request_document_epoch is not None and request_document_epoch != live_epoch:
                    admission_error = "request_epoch_mismatch"
                elif request_base_revision is not None and request_base_revision != live_revision:
                    admission_error = "request_stale"
                else:
                    try:
                        session.agent_execution.begin_turn(
                            turn_id,
                            document_epoch=live_epoch,
                            base_revision=live_revision,
                            kind="agent",
                        )
                        admitted = True
                    except AgentTurnInProgress:
                        admission_error = AGENT_TURN_IN_PROGRESS
            if admission_error is not None:
                return await self._reject_turn(
                    on_event,
                    code=admission_error,
                    message=_ADMISSION_MESSAGES.get(admission_error, "本次指令未执行。"),
                    version=live_revision,
                    document_epoch=live_epoch,
                )

        turn_epoch = request_document_epoch if request_document_epoch is not None else live_epoch
        turn_revision = request_base_revision if request_base_revision is not None else live_revision

        # 1. Evaluate context tokens & execute auto-compression at >= 90% threshold.
        #    AgentRuntime is the single owner of the conversation transcript: the
        #    user turn is appended exactly once here (transports must not do it),
        #    and only AFTER a successful admission.
        ctx_limit_key = getattr(settings, "context_limit", "256k").lower()
        max_tokens_budget = CONTEXT_LIMIT_PRESETS.get(ctx_limit_key, 256 * 1024)

        if session is not None and hasattr(session, "add_message"):
            session.add_message(role="user", content=user_message)
            session_messages = list(session.memory.messages)
        else:
            session_messages = [{"role": "user", "content": user_message}]

        compressed_messages, usage_report = ContextCompressor.evaluate_and_compress(
            messages=session_messages,
            max_tokens=max_tokens_budget,
            context_key=ctx_limit_key
        )

        # The compressed form is model-facing only; the raw transcript is preserved.

        # Emit real-time context usage report for frontend circular progress indicator
        if on_event:
            try:
                ev_data = {
                    "type": "context_usage",
                    "usage": usage_report.to_dict()
                }
                import inspect
                if inspect.iscoroutinefunction(on_event):
                    await on_event(ev_data)
                else:
                    res = on_event(ev_data)
                    if inspect.isawaitable(res):
                        await res
            except Exception as e:
                logger.debug(f"Failed to emit context_usage: {e}")

        # 1b. Announce the freeze. The lease was already installed atomically above
        #     (inside `document.mutation_lock`), so this is purely observational.
        if session is not None and admitted:
            await _emit(on_event, {
                "type": "document_frozen",
                "session_id": session.session_id,
                "edit_lock": session.agent_execution.edit_lock(),
            })

        initial_state: PPTAgentState = {
            "user_query": user_message,
            "messages": compressed_messages,
            "raw_messages": session_messages,
            "iteration": 0,
            "max_iterations": max_iterations,
            "active_slide_id": pres.active_slide_id,
            "presentation_version": pres.version,
            "ui_context": ctx.to_dict(),
            "ui_context_revision": ctx.ui_context_revision,
            "tool_calls": [],
            "tool_results": [],
            "confirmed_tool_ids": confirmed_ids,
            "turn_document_epoch": turn_epoch,
            "turn_base_revision": turn_revision,
            "turn_invalidated": False,
            "subagent_memories": seeded_subagent_memories,
            "agent_turn_id": turn_id,
        }

        config = {
            "configurable": {
                "pres": pres,
                "history": history,
                "session": session,
                "on_event": on_event,
                "llm_client": self.llm,
                "memory": (session.memory.agent_memory if session else None) or self.memory,
                "confirmed_tool_ids": confirmed_ids,
                "ui_context": ctx,
            }
        }

        try:
            final_state = await self.graph.ainvoke(initial_state, config=config)

            reply = final_state.get("final_summary", "处理完成。")
            executed_tools = final_state.get("tool_results", [])
            vision_critique = final_state.get("vision_critique")
            intent = final_state.get("intent", "chat")
            plan = final_state.get("plan", "")

            # Write subagent continuity back onto the session so the next turn's
            # critics can contrast their prior audit rounds.
            if session_memory is not None:
                from .subagents.memory import SubagentSessionMemory
                for name, payload in (final_state.get("subagent_memories") or {}).items():
                    if isinstance(payload, dict):
                        session_memory.set_subagent_memory(
                            name, SubagentSessionMemory.from_dict(payload)
                        )

            if session is not None and hasattr(session, "add_message"):
                session.add_message(
                    role="assistant",
                    content=reply,
                    tool_calls=executed_tools,
                    vision_critique=vision_critique
                )
            if session is not None and hasattr(session, "schedule_persist"):
                session.schedule_persist()

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
            if session is not None and hasattr(session, "add_message"):
                session.add_message(role="assistant", content=err_msg)
            if session is not None and hasattr(session, "schedule_persist"):
                session.schedule_persist()
            if on_event:
                await on_event({"type": "agent_error", "error": err_msg})
            return {
                "reply": err_msg,
                "tools_executed": [],
                "vision_critique": None,
                "version": pres.version,
                "error": str(e)
            }
        finally:
            # Release the lease on the happy path, on exception, and on
            # cancellation (a `finally` always runs for CancelledError).
            if session is not None and admitted:
                session.agent_execution.end_turn(turn_id)

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

        current_version = session.document.presentation.version
        current_epoch = getattr(session, "document_epoch", None)
        record_epoch = record.get("document_epoch")
        expected_revision = record.get("expected_revision", record["presentation_version"])

        # A pending call is only valid for the SAME document revision it was blocked
        # on. Replacing the deck (import / generation / checkpoint restore) rotates the
        # document epoch, and any mutation bumps the revision - either invalidates it.
        epoch_mismatch = record_epoch is not None and record_epoch != current_epoch
        if epoch_mismatch or expected_revision != current_version:
            session.consume_pending_confirmation(call_id)
            result = {
                "success": False,
                "error": "confirmation_invalidated",
                "call_id": call_id,
                "expected_version": expected_revision,
                "current_version": current_version,
                "message": (
                    "演示文稿在等待确认期间已发生变化，该挂起调用已失效，"
                    "请重新发起指令。"
                ),
            }
            if on_event:
                await on_event({"type": "confirmation_invalidated", **result})
            return result

        # Single claimant: consume synchronously BEFORE any await so two concurrent
        # confirmations of the same call_id cannot both reach execution. The
        # claimed record carries the frozen CAS stamps for the under-lock recheck.
        claimed = session.consume_pending_confirmation(call_id)
        if claimed is None:
            result = {
                "success": False,
                "error": "unknown_confirmation",
                "message": f"未找到待确认的挂起调用（call_id: {call_id}）。",
            }
            if on_event:
                await on_event({"type": "confirmation_failed", "call_id": call_id, **result})
            return result

        claimed_epoch = claimed.get("document_epoch")
        claimed_revision = claimed.get("expected_revision", claimed.get("presentation_version"))

        if on_event:
            await on_event({
                "type": "confirmation_approved",
                "call_id": call_id,
                "tool": claimed["tool"],
            })

        from .mutation_gateway import (
            MutationGateway,
            STALE_MUTATION,
            DOCUMENT_EPOCH_MISMATCH,
        )
        batch = await MutationGateway.execute_tool_calls(
            [{"name": claimed["tool"], "arguments": claimed["arguments"], "id": call_id}],
            session.document.presentation,
            session.history,
            session=session,
            confirmed_ids={call_id},
            source="user_confirmation",
            document_epoch=claimed_epoch,
            expected_revision=claimed_revision,
        )

        # TOCTOU: the pre-check passed but the deck advanced before the gateway
        # acquired the lock. The record is already claimed; report invalidated.
        if batch.error in (STALE_MUTATION, DOCUMENT_EPOCH_MISMATCH):
            result = {
                "success": False,
                "error": "confirmation_invalidated",
                "call_id": call_id,
                "expected_version": claimed_revision,
                "current_version": session.document.presentation.version,
                "message": (
                    "演示文稿在等待确认期间已发生变化，该挂起调用已失效，"
                    "请重新发起指令。"
                ),
            }
            if on_event:
                await on_event({"type": "confirmation_invalidated", **result})
            return result

        res = batch.first_result()
        target_el_id = claimed["arguments"].get("element_id") or (
            res.get("element_id") if isinstance(res, dict) else None
        )
        if target_el_id and hasattr(session, "last_target_id"):
            session.document.last_target_id = target_el_id

        if on_event:
            await on_event({
                "type": "tool_completed",
                "tool": claimed["tool"],
                "result": res,
                "presentation_version": session.document.presentation.version,
                "confirmed_call_id": call_id,
            })
            await on_event({
                "type": "confirmation_resolved",
                "call_id": call_id,
                "tool": claimed["tool"],
                "success": bool(res.get("success")) if isinstance(res, dict) else False,
            })

        return {
            "success": bool(res.get("success")) if isinstance(res, dict) else False,
            "call_id": call_id,
            "tool": claimed["tool"],
            "result": res,
            "version": session.document.presentation.version,
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
