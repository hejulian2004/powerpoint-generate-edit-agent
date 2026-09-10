"""Mutation Gateway: the single authorized write path to the PresentationIR.

Every mutation - agent-proposed tool calls, user confirmations, direct GUI
actions, and automated remediation - flows through this module. It centralizes:

1. Tool schema validation (unknown tool / missing required args fail closed).
2. Risk assessment (`RiskEnricher`) and the confirmation gate for low-confidence
   LLM-originated mutations.
3. Transactional execution: each call runs inside a PresentationIR snapshot and
   is rolled back when the handler raises or reports failure.
4. Telemetry (`tool_executing`, `tool_completed`, `confirmation_required`) and
   `last_target_id` bookkeeping.

The Executor subagent no longer owns tool execution; it only proposes an
ExecutionPlan which the graph's `mutation_node` feeds to this gateway.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .risk_policy import ConfirmationGate, RiskEnricher
from .tools import tools
from ..ir.models import PresentationIR

logger = logging.getLogger(__name__)


def _fire_event(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
    """Best-effort sync emitter for callers that are not async (remediation)."""
    if not on_event:
        return
    try:
        if inspect.iscoroutinefunction(on_event):
            try:
                asyncio.get_running_loop().create_task(on_event(data))
            except RuntimeError:
                asyncio.run(on_event(data))
        else:
            res = on_event(data)
            if inspect.isawaitable(res):
                try:
                    asyncio.get_running_loop().create_task(res)
                except RuntimeError:
                    asyncio.run(res)
    except Exception as e:
        logger.debug(f"Mutation gateway event ignored: {e}")


async def _await_event(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
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
        logger.debug(f"Mutation gateway event ignored: {e}")


@dataclass
class MutationBatchResult:
    """Aggregated outcome of a batch of tool calls."""

    results: List[Dict[str, Any]] = field(default_factory=list)
    executed_tools: List[str] = field(default_factory=list)
    blocked_call_ids: List[str] = field(default_factory=list)
    last_target_id: Optional[str] = None
    version: int = 1
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None

    def first_result(self) -> Dict[str, Any]:
        if not self.results:
            return {"success": False, "error": "Empty tool batch"}
        return self.results[0].get("result", {"success": False, "error": "Missing tool result"})


class MutationGateway:
    """Centralized execution pipeline for all PresentationIR mutations."""

    # Pseudo-tools handled internally by the gateway rather than by ToolRegistry.
    INTERNAL_TOOLS = {"undo", "redo"}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    async def execute_tool_calls(
        cls,
        tool_calls: Sequence[Dict[str, Any]],
        pres: Optional[PresentationIR],
        history: Optional[Any],
        session: Optional[Any] = None,
        *,
        on_event: Optional[Callable] = None,
        memory: Optional[Any] = None,
        confirmed_ids: Optional[Iterable[str]] = None,
        source: str = "agent",
        subagent: Optional[str] = None,
        bypass_confirmation: bool = False,
    ) -> MutationBatchResult:
        """Executes a batch of tool calls, awaiting every telemetry event."""
        events: List[Dict[str, Any]] = []

        def _run() -> MutationBatchResult:
            return cls._execute(
                tool_calls,
                pres,
                history,
                session=session,
                emit=events.append,
                memory=memory,
                confirmed_ids=confirmed_ids,
                source=source,
                subagent=subagent,
                bypass_confirmation=bypass_confirmation,
            )

        # Serialize only the actual mutations. The lock is NOT held while the graph
        # plans or calls LLMs; transports delegate locking entirely to the gateway.
        lock = getattr(session, "mutation_lock", None)
        if lock is not None:
            async with lock:
                batch = _run()
        else:
            batch = _run()

        for event in events:
            await _await_event(on_event, event)
        return batch

    @classmethod
    def execute_tool_calls_sync(
        cls,
        tool_calls: Sequence[Dict[str, Any]],
        pres: Optional[PresentationIR],
        history: Optional[Any],
        session: Optional[Any] = None,
        *,
        on_event: Optional[Callable] = None,
        memory: Optional[Any] = None,
        confirmed_ids: Optional[Iterable[str]] = None,
        source: str = "agent",
        subagent: Optional[str] = None,
        bypass_confirmation: bool = False,
    ) -> MutationBatchResult:
        """Sync entry point used by deterministic remediation pipelines."""

        def emit(event: Dict[str, Any]) -> None:
            _fire_event(on_event, event)

        return cls._execute(
            tool_calls,
            pres,
            history,
            session=session,
            emit=emit,
            memory=memory,
            confirmed_ids=confirmed_ids,
            source=source,
            subagent=subagent,
            bypass_confirmation=bypass_confirmation,
        )

    @classmethod
    def execute_one_sync(
        cls,
        name: str,
        arguments: Dict[str, Any],
        pres: Optional[PresentationIR],
        history: Optional[Any],
        session: Optional[Any] = None,
        *,
        on_event: Optional[Callable] = None,
        source: str = "remediation",
        bypass_confirmation: bool = True,
    ) -> Dict[str, Any]:
        """Convenience wrapper for internal single-call mutation pipelines."""
        call = {
            "name": name,
            "arguments": dict(arguments or {}),
            "id": f"call_{uuid.uuid4().hex[:6]}",
        }
        batch = cls.execute_tool_calls_sync(
            [call],
            pres,
            history,
            session=session,
            on_event=on_event,
            source=source,
            bypass_confirmation=bypass_confirmation,
        )
        return batch.first_result()

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    @classmethod
    def _execute(
        cls,
        tool_calls: Sequence[Dict[str, Any]],
        pres: Optional[PresentationIR],
        history: Optional[Any],
        *,
        emit: Callable[[Dict[str, Any]], None],
        session: Optional[Any] = None,
        memory: Optional[Any] = None,
        confirmed_ids: Optional[Iterable[str]] = None,
        source: str = "agent",
        subagent: Optional[str] = None,
        bypass_confirmation: bool = False,
    ) -> MutationBatchResult:
        calls = list(tool_calls or [])
        batch = MutationBatchResult(
            last_target_id=getattr(session, "last_target_id", None) if session else None,
            version=pres.version if pres else 1,
        )
        confirmed = set(confirmed_ids or [])
        current_target = batch.last_target_id
        subagent_meta = {"subagent": subagent} if subagent else {}

        for raw_call in calls:
            call = dict(raw_call) if isinstance(raw_call, dict) else {}
            fn_name = str(call.get("name") or call.get("tool") or "")
            args = dict(call.get("arguments") or call.get("args") or {})
            call_id = call.get("id") or f"call_{uuid.uuid4().hex[:6]}"
            call["arguments"] = args
            call["id"] = call_id

            # 1. Schema validation: unknown tools and missing required args fail closed.
            validation_error = None
            if fn_name not in cls.INTERNAL_TOOLS:
                validation_error = tools.validate_arguments(fn_name, args)
            if validation_error:
                batch.results.append({
                    "tool": fn_name,
                    "arguments": args,
                    "result": {"success": False, "error": validation_error},
                })
                emit({
                    "type": "tool_failed",
                    "tool": fn_name,
                    "arguments": args,
                    "error": validation_error,
                    **subagent_meta,
                })
                continue

            # 2. Risk enrichment + confirmation gate (LLM-originated mutations only).
            if not bypass_confirmation:
                RiskEnricher.enrich_tool_call(call, pres)
                if ConfirmationGate.is_blocked(call, confirmed):
                    blocked = ConfirmationGate.blocked_result(call)
                    pending_record = None
                    if session is not None and call_id and hasattr(session, "register_pending_confirmation"):
                        pending_record = session.register_pending_confirmation(
                            call_id=call_id,
                            tool=fn_name,
                            arguments=args,
                            confidence=call.get("_resolution_confidence"),
                            presentation_version=pres.version if pres else 1,
                            target_element_id=args.get("element_id"),
                            document_epoch=getattr(session, "document_epoch", None),
                            expected_revision=pres.version if pres else 1,
                        )
                    batch.results.append({
                        "tool": fn_name,
                        "arguments": args,
                        "result": blocked,
                        "requires_confirmation": True,
                    })
                    batch.blocked_call_ids.append(call_id)
                    emit({
                        "type": "confirmation_required",
                        "tool": fn_name,
                        "arguments": args,
                        "resolution_confidence": call.get("_resolution_confidence"),
                        "call_id": call_id,
                        "presentation_version": (
                            pending_record["presentation_version"]
                            if pending_record
                            else (pres.version if pres else 1)
                        ),
                        "message": blocked["message"],
                    })
                    if memory:
                        memory.log_action(
                            f"RiskPolicy 拦截低置信度操作 '{fn_name}'，等待用户确认"
                        )
                    continue

            emit({
                "type": "tool_executing",
                "tool": fn_name,
                "arguments": args,
                **subagent_meta,
            })

            # 3. Transactional execution with rollback on failure.
            res = cls._execute_single(fn_name, args, pres, history, session=session)
            batch.results.append({
                "tool": fn_name,
                "arguments": args,
                "result": res,
            })
            batch.executed_tools.append(fn_name)

            target_el_id = args.get("element_id") or (
                res.get("element_id") if isinstance(res, dict) else None
            )
            if target_el_id:
                current_target = target_el_id
                if session is not None and hasattr(session, "last_target_id"):
                    session.last_target_id = target_el_id

            emit({
                "type": "tool_completed",
                "tool": fn_name,
                "result": res,
                "presentation_version": pres.version if pres else 1,
                **subagent_meta,
            })

            if memory:
                message = res.get("message", "ok") if isinstance(res, dict) else "ok"
                memory.log_action(f"执行工具 '{fn_name}': {message}")

        batch.last_target_id = current_target
        batch.version = pres.version if pres else 1
        return batch

    # ------------------------------------------------------------------
    # Single-call execution
    # ------------------------------------------------------------------

    @classmethod
    def _execute_single(
        cls,
        fn_name: str,
        args: Dict[str, Any],
        pres: Optional[PresentationIR],
        history: Optional[Any],
        *,
        session: Optional[Any] = None,
    ) -> Dict[str, Any]:
        # Undo / redo are already atomic history operations.
        if fn_name == "undo":
            if session and hasattr(session, "undo"):
                patch = session.undo()
            elif history and hasattr(history, "undo"):
                patch = history.undo(pres)
            else:
                patch = None
            return {
                "success": bool(patch),
                "message": "已成功撤销上一步操作" if patch else "当前无历史操作可撤销",
            }
        if fn_name == "redo":
            if session and hasattr(session, "redo"):
                patch = session.redo()
            elif history and hasattr(history, "redo"):
                patch = history.redo(pres)
            else:
                patch = None
            return {
                "success": bool(patch),
                "message": "已成功重做操作" if patch else "当前无历史操作可重做",
            }

        if pres is None:
            return {"success": False, "error": "No presentation state available"}

        try:
            with pres.transaction(f"tool:{fn_name}", history=history) as tx:
                res = tools.execute(fn_name, args, pres, history)
                if isinstance(res, dict) and res.get("success") is False:
                    tx.rollback(reason=res.get("error", f"{fn_name} reported failure"))
            return res
        except Exception as e:
            logger.error(f"Mutation gateway error running {fn_name}: {e}", exc_info=True)
            return {"success": False, "error": f"Execution error in {fn_name}: {str(e)}"}
