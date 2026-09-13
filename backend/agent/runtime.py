"""PPT Agent Runtime: LangGraph-powered Multi-step Observe-Plan-Execute-Critique Loop."""

from __future__ import annotations
import json
import uuid
import logging
from contextlib import nullcontext
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
from ..session.services.connection import ConnectionTakenOver, STALE_CONNECTION
from .uicontext import UI_CONTEXT_TARGET_INVALID

logger = logging.getLogger(__name__)

# Terminal rejection messages for a turn that fails admission.
_ADMISSION_MESSAGES = {
    "request_epoch_mismatch": "演示文稿已被替换，本次指令未执行，已同步到最新版本，请重试。",
    "request_stale": "演示文稿已在您发送后更新，本次指令未执行，已同步到最新版本，请重试。",
    AGENT_TURN_IN_PROGRESS: "演示文稿正被另一个 Agent 任务编辑，请稍后重试。",
    STALE_CONNECTION: "会话已在其他窗口接管，本次指令未执行。",
    UI_CONTEXT_TARGET_INVALID: "所选元素在当前版本中已不存在，本次指令未执行，请重新选择后重试。",
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
                    "message": message,
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
        transport: Optional[Any] = None,
        mode: Optional[str] = None,
        approved_plan: Optional[str] = None,
        record_user_message: bool = True,
    ) -> Dict[str, Any]:
        """Runs an interactive turn executed through the LangGraph state machine.

        `mode` selects the session interaction mode ("auto" | "plan"). When
        `approved_plan` is supplied the plan critic stage is bypassed and the frozen
        plan executes directly (used by the plan-confirmation lifecycle). In that
        path `record_user_message=False` avoids duplicating the original user turn.

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

        # Every path that reads the transcript to build model context, or writes
        # the transcript / compression anchor, is serialized by the session's
        # conversation lock. Admission installs the exclusive agent edit lease, so
        # it MUST happen INSIDE this lock: otherwise a read-only attachment chat
        # holding the conversation would make a queued agent turn freeze the
        # document (rejecting GUI edits) before that turn can actually start.
        # Lock order is always conversation_lock -> document.mutation_lock; no
        # path ever takes them in the reverse order. This lock is independent of
        # document.mutation_lock / the agent edit lease, so it never blocks GUI
        # PPT editing by itself.
        conversation_lock = (
            session.memory.conversation_lock
            if session is not None and hasattr(session, "memory")
            else None
        )
        if conversation_lock is not None:
            await conversation_lock.acquire()
        turn_id = f"turn_{uuid.uuid4().hex[:10]}"
        admitted = False
        try:
            # 0. Atomic admission: validate the request CAS AND install the
            #    exclusive Agent turn lease inside ONE `document.mutation_lock`
            #    critical section, under the conversation lock. There is then no
            #    window for a GUI mutation to commit between a passing CAS and the
            #    freeze being installed. The document lock protects admission only;
            #    it is released before the transcript is appended and the LLM runs.
            #    Any admission failure appends no transcript, mutates no memory,
            #    emits no `document_frozen`, and never invokes the graph.
            live_epoch = session.document.epoch if session is not None else None
            live_revision = pres.version if pres is not None else None
            if session is not None:
                admission_error: Optional[str] = None
                async with session.document.mutation_lock:
                    live_epoch = session.document.epoch
                    live_revision = pres.version
                    if transport is not None:
                        try:
                            session.connection.assert_current(
                                transport.websocket, transport.connection_generation
                            )
                        except ConnectionTakenOver:
                            admission_error = STALE_CONNECTION
                    if admission_error is not None:
                        pass
                    elif request_document_epoch is not None and request_document_epoch != live_epoch:
                        admission_error = "request_epoch_mismatch"
                    elif request_base_revision is not None and request_base_revision != live_revision:
                        admission_error = "request_stale"
                    elif ctx.invalid_targets(pres):
                        # The requesting client targeted a slide/element that no
                        # longer exists. Fail closed before the lease is installed
                        # so no tool ever executes against a silently retargeted
                        # element.
                        admission_error = UI_CONTEXT_TARGET_INVALID
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
            elif ctx.invalid_targets(pres):
                # Session-less callers (tests, direct runtime use) still fail
                # closed on stale UI targets: no graph invocation, no tool
                # execution.
                return await self._reject_turn(
                    on_event,
                    code=UI_CONTEXT_TARGET_INVALID,
                    message=_ADMISSION_MESSAGES[UI_CONTEXT_TARGET_INVALID],
                    version=live_revision,
                    document_epoch=live_epoch,
                )

            turn_epoch = request_document_epoch if request_document_epoch is not None else live_epoch
            turn_revision = request_base_revision if request_base_revision is not None else live_revision

            # Conversation memory is read under the lock too, so a concurrent
            # rework/compression writer can never mutate subagent continuity
            # mid-turn.
            seeded_subagent_memories = (
                {name: mem.to_dict() for name, mem in session_memory.subagent_memories.items()}
                if session_memory is not None
                else {}
            )
            # 1. Evaluate context tokens & execute auto-compression at >= 90% threshold.
            #    AgentRuntime is the single owner of the conversation transcript: the
            #    user turn is appended exactly once here (transports must not do it),
            #    and only AFTER a successful admission.
            ctx_limit_key = getattr(settings, "context_limit", "256k").lower()
            max_tokens_budget = CONTEXT_LIMIT_PRESETS.get(ctx_limit_key, 256 * 1024)

            if session is not None and hasattr(session, "add_message"):
                if record_user_message:
                    session.add_message(role="user", content=user_message)
                session_messages = list(session.memory.messages)
            else:
                session_messages = (
                    [{"role": "user", "content": user_message}]
                    if record_user_message
                    else []
                )

            # A user-triggered manual compression anchor persists across turns: the
            # model-facing window is rebuilt from the anchor plus the live tail, while
            # the raw transcript (state["raw_messages"]) is never rewritten.
            manual_anchor = getattr(session_memory, "compressed_anchor", None) if session_memory else None
            manual_through = getattr(session_memory, "compression_through_index", 0) if session_memory else 0
            model_base_messages = ContextCompressor.assemble_model_messages(
                session_messages, manual_anchor, manual_through
            )
            compressed_messages, usage_report = ContextCompressor.evaluate_and_compress(
                messages=model_base_messages,
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
                "interaction_mode": (
                    mode
                    or (getattr(session, "interaction_mode", "auto") if session is not None else "auto")
                ),
                "plan_preapproved": bool(approved_plan),
            }
            if approved_plan:
                initial_state["plan"] = approved_plan

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
            # cancellation (a `finally` always runs for CancelledError). This
            # outer finally spans admission AND the graph, so a cancellation
            # while queued on the conversation lock can never leak a lease.
            if session is not None and admitted:
                session.agent_execution.end_turn(turn_id)
            # Release the conversation lock LAST so no next turn can observe a
            # half-written transcript.
            if conversation_lock is not None:
                conversation_lock.release()

    # ------------------------------------------------------------------
    # Manual context compression (user-triggered slash command)
    # ------------------------------------------------------------------

    async def compress_context(
        self,
        session: Any,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Force-condenses the transcript and persists the anchor for later turns.

        The raw transcript is preserved; only the model-facing window shrinks. The
        resulting usage report is emitted so the frontend gauge updates.
        """
        from .context_compressor import ContextCompressor, CONTEXT_LIMIT_PRESETS

        ctx_limit_key = getattr(settings, "context_limit", "256k").lower()
        max_tokens_budget = CONTEXT_LIMIT_PRESETS.get(ctx_limit_key, 256 * 1024)

        memory = getattr(session, "memory", None) if session is not None else None
        # Compression reads the transcript and rewrites the anchor, so it shares
        # the conversation lock with run_turn / attachment chat.
        lock = memory.conversation_lock if memory is not None else nullcontext()
        async with lock:
            messages = list(getattr(memory, "messages", []) or [])
            anchor, through_index, report = ContextCompressor.build_anchor(
                messages, max_tokens=max_tokens_budget, context_key=ctx_limit_key
            )
            applied = anchor is not None
            if applied and memory is not None:
                memory.compressed_anchor = anchor
                memory.compression_through_index = through_index
                memory.compression_report = report.to_dict()
            if session is not None and hasattr(session, "schedule_persist"):
                session.schedule_persist()

        if on_event:
            await _emit(on_event, {"type": "context_usage", "usage": report.to_dict()})
            await _emit(
                on_event,
                {
                    "type": "context_compressed",
                    "applied": applied,
                    "covered_messages": through_index if applied else 0,
                    "usage": report.to_dict(),
                },
            )
        return {"applied": applied, "covered_messages": through_index if applied else 0, "usage": report.to_dict()}

    # ------------------------------------------------------------------
    # Read-only attachment chat (user asks a question about a file)
    # ------------------------------------------------------------------

    async def chat_with_attachments(
        self,
        session: Any,
        user_message: str,
        context: Any,
        ui_context: Optional[Any] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Answers a question about attached material without mutating the deck.

        This path deliberately does NOT acquire the agent edit lease and never
        emits ``document_frozen``: it is read-only reasoning, so the user keeps
        editing the presentation while the answer is produced. It does hold the
        conversation-state lock (never ``document.mutation_lock``) so concurrent
        chat turns cannot answer a stale transcript.

        The bounded digest / image parts are injected only into this one model
        call; the durable transcript stores plain user/assistant text only.
        """
        from .context_compressor import ContextCompressor, CONTEXT_LIMIT_PRESETS
        from .uicontext import UIContext

        if session is None:
            raise ValueError("chat_with_attachments requires a session")

        ctx = UIContext.from_any(ui_context)
        memory = session.memory
        ctx_limit_key = getattr(settings, "context_limit", "256k").lower()
        max_tokens_budget = CONTEXT_LIMIT_PRESETS.get(ctx_limit_key, 256 * 1024)

        async with memory.conversation_lock:
            history = ContextCompressor.assemble_model_messages(
                list(memory.messages),
                getattr(memory, "compressed_anchor", None),
                getattr(memory, "compression_through_index", 0),
            )
            content_parts: List[Dict[str, Any]] = [
                {"type": "text", "text": user_message or "请根据附件内容回答问题。"}
            ]
            digest = getattr(context, "text_digest", "") or ""
            if digest:
                content_parts.append({"type": "text", "text": "【附件内容（只读）】\n" + digest})
            content_parts.extend(getattr(context, "image_parts", []) or [])
            model_messages = list(history) + [{"role": "user", "content": content_parts}]
            model_messages, usage_report = ContextCompressor.evaluate_and_compress(
                messages=model_messages,
                max_tokens=max_tokens_budget,
                context_key=ctx_limit_key,
            )

            # The model role is decided by the FINAL payload: any real image part
            # makes this a vision request, otherwise it is plain reasoning.
            has_images = any(
                isinstance(m.get("content"), list)
                and any(
                    isinstance(p, dict) and p.get("type") == "image_url"
                    for p in m["content"]
                )
                for m in model_messages
            )
            role = "vision" if has_images else "reasoning"

            try:
                response = await self.llm.chat_completion(
                    model_messages, role=role, max_tokens=2000
                )
                reply = response["choices"][0]["message"].get("content", "") or ""
            except Exception as exc:
                logger.error("Attachment chat LLM call failed: %s", exc)
                reply = f"附件内容读取失败：{exc}"

            # Use the session-level writer so the workspace `updated_at`
            # timestamp advances exactly like a normal turn (the transcript
            # itself lives on `session.memory`).
            session.add_message(role="user", content=user_message or "（已附加文件）")
            session.add_message(role="assistant", content=reply)
            if hasattr(session, "schedule_persist"):
                session.schedule_persist()

        if on_event:
            await _emit(
                on_event,
                {"type": "context_usage", "usage": usage_report.to_dict()},
            )
        return {
            "reply": reply,
            "role": role,
            "has_images": has_images,
            "usage": usage_report.to_dict(),
        }

    # ------------------------------------------------------------------
    # Pending confirmation lifecycle (PR6-hardening round 2)
    # ------------------------------------------------------------------

    async def confirm_pending(
        self,
        session: Any,
        call_id: str,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        transport: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Executes the ORIGINAL pending call after explicit user confirmation.

        Confirmation is invalidated when the presentation changed since the call was
        blocked: executing it against a newer version could hit a different element.
        """
        if transport is not None and session is not None:
            try:
                session.connection.assert_current(
                    transport.websocket, transport.connection_generation
                )
            except ConnectionTakenOver:
                result = {
                    "success": False,
                    "error": STALE_CONNECTION,
                    "call_id": call_id,
                    "message": "会话已在其他窗口接管，确认未执行。",
                }
                if on_event:
                    await on_event({"type": "confirmation_failed", **result})
                return result
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
            transport=transport,
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

    # ------------------------------------------------------------------
    # Plan-confirmation lifecycle (plan interaction mode)
    # ------------------------------------------------------------------

    async def confirm_plan(
        self,
        session: Any,
        plan_id: str,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        transport: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Executes a frozen plan after explicit user approval.

        Mirrors :meth:`confirm_pending`: the connection ownership is re-checked,
        the plan must still match the document identity it was drafted against,
        and only one claimant may consume it.
        """
        if transport is not None and session is not None:
            try:
                session.connection.assert_current(
                    transport.websocket, transport.connection_generation
                )
            except ConnectionTakenOver:
                result = {
                    "success": False,
                    "error": STALE_CONNECTION,
                    "plan_id": plan_id,
                    "message": "会话已在其他窗口接管，计划确认未执行。",
                }
                if on_event:
                    await _emit(on_event, {"type": "plan_failed", **result})
                return result

        record = session.get_pending_plan(plan_id) if session else None
        if record is None:
            result = {
                "success": False,
                "error": "unknown_plan",
                "plan_id": plan_id,
                "message": f"未找到待确认的计划（plan_id: {plan_id}）。",
            }
            if on_event:
                await _emit(on_event, {"type": "plan_failed", **result})
            return result

        current_epoch = getattr(session, "document_epoch", None)
        current_revision = session.document.presentation.version
        record_epoch = record.get("document_epoch")
        record_revision = record.get("expected_revision")

        if record_epoch != current_epoch or (
            record_revision is not None and record_revision != current_revision
        ):
            session.consume_pending_plan(plan_id)
            result = {
                "success": False,
                "error": "plan_invalidated",
                "plan_id": plan_id,
                "document_epoch": current_epoch,
                "version": current_revision,
                "message": (
                    "计划生成后演示文稿已被修改，原计划已失效，请重新下达指令以生成新计划。"
                ),
            }
            if on_event:
                await _emit(on_event, {"type": "plan_invalidated", **result})
            return result

        # Single-claimant: consume before any await so only one confirmation runs.
        session.consume_pending_plan(plan_id)
        if on_event:
            await _emit(on_event, {"type": "plan_approved", "plan_id": plan_id})

        result = await self.run_turn(
            user_message=record.get("user_query", ""),
            pres=session.document.presentation,
            history=session.history,
            session=session,
            on_event=on_event,
            request_document_epoch=record_epoch,
            request_base_revision=record_revision,
            # Restore the UI context captured when the user asked for the plan,
            # not whatever the client has selected at confirmation time.
            ui_context=record.get("ui_context"),
            transport=transport,
            mode="plan",
            approved_plan=record.get("plan", ""),
            record_user_message=False,
        )
        if result.get("turn_rejected"):
            # The resumed turn was terminally invalidated (stale request stamp or
            # the captured UI target vanished). Surface the rejection instead of
            # reporting a false success.
            if on_event:
                await _emit(
                    on_event,
                    {
                        "type": "plan_resolved",
                        "plan_id": plan_id,
                        "success": False,
                        "error": result.get("error"),
                    },
                )
            return {"success": False, "plan_id": plan_id, **result}
        if on_event:
            await _emit(
                on_event,
                {"type": "plan_resolved", "plan_id": plan_id, "success": True},
            )
        return {"success": True, "plan_id": plan_id, **result}

    async def cancel_plan(
        self,
        session: Any,
        plan_id: str,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Discards a pending plan without executing it."""
        record = session.consume_pending_plan(plan_id) if session else None
        result = {
            "success": record is not None,
            "plan_id": plan_id,
            "cancelled": record is not None,
            "message": "已取消该计划。" if record else f"未找到待确认的计划（plan_id: {plan_id}）。",
        }
        if on_event:
            await _emit(on_event, {"type": "plan_cancelled", **result})
        return result

    # ------------------------------------------------------------------
    # On-demand visual review (user-triggered slash command, read-only)
    # ------------------------------------------------------------------

    async def review_visuals(
        self,
        session: Any,
        target: Optional[str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
        transport: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Runs the blind visual critic on selected slides. Never mutates the deck."""
        if transport is not None and session is not None:
            try:
                session.connection.assert_current(
                    transport.websocket, transport.connection_generation
                )
            except ConnectionTakenOver:
                result = {
                    "success": False,
                    "error": STALE_CONNECTION,
                    "message": "会话已在其他窗口接管，视觉审查未执行。",
                }
                if on_event:
                    await _emit(on_event, {"type": "vision_review_result", **result})
                return result

        from .review_targeting import build_slide_manifest, resolve_review_targets
        from ..quality.service import QualityService

        manifest = build_slide_manifest(session)
        index_by_id = {m["slide_id"]: m["index"] for m in manifest}
        slide_ids = await resolve_review_targets(self.llm, target, manifest)

        presentation = session.document.presentation if session is not None else None
        reviews: List[Dict[str, Any]] = []
        for slide_id in slide_ids:
            slide = presentation.get_slide(slide_id) if presentation is not None else None
            if slide is None:
                continue
            if on_event:
                await _emit(
                    on_event,
                    {
                        "type": "agent_thinking",
                        "status": "vision_review",
                        "text": f"正在审查第 {index_by_id.get(slide_id)} 页视觉排版...",
                    },
                )
            review = await QualityService.review_slide(
                slide, llm_client=self.llm, on_event=on_event
            )
            payload = review.to_dict()
            reviews.append(
                {
                    "slide_id": slide_id,
                    "page": index_by_id.get(slide_id),
                    "score": payload.get("score"),
                    "defects_count": payload.get("defects_count"),
                    "needs_auto_correction": payload.get("needs_auto_correction"),
                    "critique_summary": payload.get("critique_summary"),
                    "multimodal_feedback": payload.get("multimodal_feedback"),
                }
            )

        scores = [
            r["score"] for r in reviews if isinstance(r.get("score"), (int, float))
        ]
        overall = {
            "score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "defects_count": sum(int(r.get("defects_count") or 0) for r in reviews),
            "needs_auto_correction": any(r.get("needs_auto_correction") for r in reviews),
            "critique_summary": "\n".join(
                f"第{r.get('page')}页: {r.get('critique_summary') or ''}".strip()
                for r in reviews
            ),
        }

        result = {
            "success": True,
            "type": "vision_review_result",
            "session_id": getattr(session, "session_id", None),
            "target": target or "all",
            "targets": [r["slide_id"] for r in reviews],
            "slide_reviews": reviews,
            "overall": overall,
        }
        if on_event:
            await _emit(on_event, result)
        return result
