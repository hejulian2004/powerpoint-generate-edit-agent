"""Mutation Gateway: the single authorized write path to the PresentationIR.

Every mutation - agent-proposed tool calls, user confirmations, direct GUI
actions, and automated remediation - flows through this module. It centralizes:

1. Tool schema validation (unknown tool / missing required args fail closed).
2. Risk assessment (`RiskEnricher`) and the confirmation gate for low-confidence
   LLM-originated mutations.
3. Compare-and-swap (CAS) staleness rejection against a caller's expected
   `document_epoch` / revision, so a plan or offline edit can never overwrite a
   newer state.
4. Transactional execution: every call runs inside a PresentationIR snapshot and
   is rolled back when the handler raises or reports failure. In `atomic=True`
   mode the whole envelope shares ONE transaction, so a single failure restores
   content, version, and history and the batch still counts as one undo step.
5. Post-generation grounding validation: generated numeric claims absent from the
   bound source roll the batch back instead of being committed as fabrication.
6. Telemetry (`tool_executing`, `tool_completed`, `confirmation_required`) and
   `last_target_id` bookkeeping.

The Executor subagent no longer owns tool execution; it only proposes an
ExecutionPlan which the graph's `mutation_node` feeds to this gateway.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .risk_policy import ConfirmationGate, RiskEnricher
from .tools import tools
from ..ir.models import PresentationIR

logger = logging.getLogger(__name__)

# Tools that synthesize slide content; their committed IR text is re-validated
# against the bound source after execution.
GENERATION_TOOLS = frozenset({
    "generate_presentation",
    "generate_slide_layout",
    "batch_add_cards",
})

# CAS error codes surfaced to transports / the graph.
STALE_MUTATION = "stale_mutation"
DOCUMENT_EPOCH_MISMATCH = "document_epoch_mismatch"
STALE_EXECUTION_PLAN = "stale_execution_plan"


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
class MutationOperation:
    """A single requested mutation inside a `MutationEnvelope`."""

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:6]}")

    @classmethod
    def from_tool_call(cls, raw: Dict[str, Any]) -> "MutationOperation":
        data = dict(raw) if isinstance(raw, dict) else {}
        name = str(data.get("name") or data.get("tool") or "")
        args = dict(data.get("arguments") or data.get("args") or data.get("payload") or {})
        call_id = data.get("id") or f"call_{uuid.uuid4().hex[:6]}"
        return cls(name=name, arguments=args, call_id=call_id)

    def to_call(self) -> Dict[str, Any]:
        return {"name": self.name, "arguments": dict(self.arguments), "id": self.call_id}


@dataclass
class MutationEnvelope:
    """A versioned, optionally-atomic request to mutate the presentation.

    `document_epoch` / `expected_revision` form a compare-and-swap guard: when
    supplied, the gateway refuses to mutate if the live document has moved on.
    """

    operations: List[MutationOperation] = field(default_factory=list)
    source: str = "agent"
    subagent: Optional[str] = None
    atomic: bool = False
    document_epoch: Optional[str] = None
    expected_revision: Optional[int] = None
    mutation_id: str = field(default_factory=lambda: f"mut_{uuid.uuid4().hex[:10]}")
    grounding_source: Optional[str] = None
    enforce_grounding: bool = False

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: Sequence[Dict[str, Any]],
        *,
        source: str = "agent",
        subagent: Optional[str] = None,
        atomic: bool = False,
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
        mutation_id: Optional[str] = None,
        grounding_source: Optional[str] = None,
        enforce_grounding: bool = False,
    ) -> "MutationEnvelope":
        return cls(
            operations=[MutationOperation.from_tool_call(c) for c in (tool_calls or [])],
            source=source,
            subagent=subagent,
            atomic=atomic,
            document_epoch=document_epoch,
            expected_revision=expected_revision,
            mutation_id=mutation_id or f"mut_{uuid.uuid4().hex[:10]}",
            grounding_source=grounding_source,
            enforce_grounding=enforce_grounding,
        )

    def to_calls(self) -> List[Dict[str, Any]]:
        return [op.to_call() for op in self.operations]


@dataclass
class MutationBatchResult:
    """Aggregated outcome of a batch of tool calls."""

    attempted: int = 0
    successful: int = 0
    failed: int = 0
    blocked: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    blocked_call_ids: List[str] = field(default_factory=list)
    last_target_id: Optional[str] = None
    version: int = 1
    error: Optional[str] = None
    document_epoch: Optional[str] = None
    mutation_id: Optional[str] = None
    unsupported_numbers: List[str] = field(default_factory=list)
    rolled_back: bool = False

    @property
    def success(self) -> bool:
        return self.error is None and self.failed == 0 and self.blocked == 0

    @property
    def executed_tools(self) -> List[str]:
        """Read-only alias for the tool names that actually reached execution."""
        return [r.get("tool", "") for r in self.results if r.get("executed")]

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
        atomic: bool = False,
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
        mutation_id: Optional[str] = None,
        grounding_source: Optional[str] = None,
        enforce_grounding: bool = False,
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
                atomic=atomic,
                document_epoch=document_epoch,
                expected_revision=expected_revision,
                mutation_id=mutation_id,
                grounding_source=grounding_source,
                enforce_grounding=enforce_grounding,
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
    async def execute_envelope(
        cls,
        envelope: MutationEnvelope,
        pres: Optional[PresentationIR],
        history: Optional[Any],
        session: Optional[Any] = None,
        *,
        on_event: Optional[Callable] = None,
        memory: Optional[Any] = None,
        confirmed_ids: Optional[Iterable[str]] = None,
        bypass_confirmation: bool = False,
    ) -> MutationBatchResult:
        """Executes a pre-built `MutationEnvelope` through the gateway."""
        return await cls.execute_tool_calls(
            envelope.to_calls(),
            pres,
            history,
            session=session,
            on_event=on_event,
            memory=memory,
            confirmed_ids=confirmed_ids,
            source=envelope.source,
            subagent=envelope.subagent,
            bypass_confirmation=bypass_confirmation,
            atomic=envelope.atomic,
            document_epoch=envelope.document_epoch,
            expected_revision=envelope.expected_revision,
            mutation_id=envelope.mutation_id,
            grounding_source=envelope.grounding_source,
            enforce_grounding=envelope.enforce_grounding,
        )

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
        atomic: bool = False,
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
        mutation_id: Optional[str] = None,
        grounding_source: Optional[str] = None,
        enforce_grounding: bool = False,
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
            atomic=atomic,
            document_epoch=document_epoch,
            expected_revision=expected_revision,
            mutation_id=mutation_id,
            grounding_source=grounding_source,
            enforce_grounding=enforce_grounding,
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
    def _check_cas(
        cls,
        pres: Optional[PresentationIR],
        session: Optional[Any],
        *,
        document_epoch: Optional[str],
        expected_revision: Optional[int],
    ) -> Optional[str]:
        """Returns a CAS error code when the live document moved past the caller's view."""
        if pres is None:
            return None
        if document_epoch is not None and session is not None:
            live_epoch = getattr(session, "document_epoch", None)
            if live_epoch is not None and live_epoch != document_epoch:
                return DOCUMENT_EPOCH_MISMATCH
        if expected_revision is not None and pres.version != expected_revision:
            return STALE_MUTATION
        return None

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
        atomic: bool = False,
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
        mutation_id: Optional[str] = None,
        grounding_source: Optional[str] = None,
        enforce_grounding: bool = False,
    ) -> MutationBatchResult:
        calls = list(tool_calls or [])
        live_epoch = getattr(session, "document_epoch", None) if session is not None else None
        batch = MutationBatchResult(
            attempted=len(calls),
            last_target_id=getattr(session, "last_target_id", None) if session else None,
            version=pres.version if pres else 1,
            document_epoch=live_epoch,
            mutation_id=mutation_id or f"mut_{uuid.uuid4().hex[:10]}",
        )

        # 0. Compare-and-swap: reject a stale plan / offline mutation before writing.
        cas_error = cls._check_cas(
            pres,
            session,
            document_epoch=document_epoch,
            expected_revision=expected_revision,
        )
        if cas_error:
            batch.error = cas_error
            batch.failed = len(calls)
            emit({
                "type": "mutation_rejected",
                "error": cas_error,
                "mutation_id": batch.mutation_id,
                "version": batch.version,
                "document_epoch": batch.document_epoch,
            })
            return batch

        confirmed = set(confirmed_ids or [])

        if pres is None:
            for raw_call in calls:
                call = dict(raw_call) if isinstance(raw_call, dict) else {}
                fn_name = str(call.get("name") or call.get("tool") or "")
                args = dict(call.get("arguments") or call.get("args") or {})
                res = {"success": False, "error": "No presentation state available"}
                batch.results.append({"tool": fn_name, "arguments": args, "result": res})
                batch.failed += 1
            return batch

        if atomic:
            before_texts = cls._capture_texts(pres) if enforce_grounding else {}
            use_batch = history is not None and hasattr(history, "batch")
            batch_ctx = (
                history.batch(
                    description="批量编辑 (单步撤销)",
                    source="mutation_gateway",
                )
                if use_batch
                else nullcontext(None)
            )
            with pres.transaction(f"mutation_batch:{batch.mutation_id}", history=history) as tx:
                with batch_ctx as hb:
                    cls._run_calls(
                        calls, pres, history,
                        emit=emit, session=session, memory=memory, confirmed=confirmed,
                        source=source, subagent=subagent, bypass_confirmation=bypass_confirmation,
                        batch=batch, tx=tx, atomic=True,
                        grounding_source=grounding_source, enforce_grounding=enforce_grounding,
                        before_texts=before_texts,
                    )
                    if batch.error:
                        tx.rollback(reason=batch.error)
                        if hb is not None:
                            hb.rollback()
            if tx.is_aborted:
                batch.rolled_back = True
        else:
            cls._run_calls(
                calls, pres, history,
                emit=emit, session=session, memory=memory, confirmed=confirmed,
                source=source, subagent=subagent, bypass_confirmation=bypass_confirmation,
                batch=batch, tx=None, atomic=False,
                grounding_source=grounding_source, enforce_grounding=enforce_grounding,
                before_texts={},
            )

        batch.version = pres.version if pres else batch.version
        batch.last_target_id = (
            getattr(session, "last_target_id", None) if session is not None else batch.last_target_id
        )
        return batch

    @classmethod
    def _run_calls(
        cls,
        calls: List[Dict[str, Any]],
        pres: PresentationIR,
        history: Optional[Any],
        *,
        emit: Callable[[Dict[str, Any]], None],
        session: Optional[Any],
        memory: Optional[Any],
        confirmed: set,
        source: str,
        subagent: Optional[str],
        bypass_confirmation: bool,
        batch: MutationBatchResult,
        tx: Optional[Any],
        atomic: bool,
        grounding_source: Optional[str],
        enforce_grounding: bool,
        before_texts: Dict[str, str],
    ) -> None:
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
                batch.failed += 1
                emit({
                    "type": "tool_failed",
                    "tool": fn_name,
                    "arguments": args,
                    "error": validation_error,
                    **subagent_meta,
                })
                if atomic:
                    batch.error = batch.error or "atomic_batch_failed"
                    return
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
                            presentation_version=pres.version,
                            target_element_id=args.get("element_id"),
                            document_epoch=getattr(session, "document_epoch", None),
                            expected_revision=pres.version,
                        )
                    batch.results.append({
                        "tool": fn_name,
                        "arguments": args,
                        "result": blocked,
                        "requires_confirmation": True,
                    })
                    batch.blocked += 1
                    batch.blocked_call_ids.append(call_id)
                    emit({
                        "type": "confirmation_required",
                        "tool": fn_name,
                        "arguments": args,
                        "resolution_confidence": call.get("_resolution_confidence"),
                        "call_id": call_id,
                        "presentation_version": (
                            pending_record["presentation_version"]
                            if pending_record else pres.version
                        ),
                        "message": blocked["message"],
                    })
                    if memory:
                        memory.log_action(
                            f"RiskPolicy 拦截低置信度操作 '{fn_name}'，等待用户确认"
                        )
                    if atomic:
                        batch.error = batch.error or "atomic_batch_blocked"
                        return
                    continue

            emit({
                "type": "tool_executing",
                "tool": fn_name,
                "arguments": args,
                **subagent_meta,
            })

            # 3. Transactional execution (shared tx when atomic).
            res = cls._execute_single(fn_name, args, pres, history, session=session, tx=tx)

            # 4. Post-generation grounding: re-validate committed IR text, not just args.
            if (
                enforce_grounding
                and grounding_source is not None
                and fn_name in GENERATION_TOOLS
                and isinstance(res, dict)
                and res.get("success") is not False
            ):
                changed_text = cls._changed_text(pres, before_texts)
                unsupported = cls._unsupported_data_claims(changed_text, grounding_source)
                if unsupported:
                    res = {
                        "success": False,
                        "error": "unsupported_facts",
                        "unsupported_numbers": unsupported,
                        "message": "生成内容包含资料中不存在的数字，已阻止写入以避免编造事实。",
                    }
                    batch.unsupported_numbers = list(unsupported)
                    batch.error = "unsupported_facts"

            batch.results.append({
                "tool": fn_name,
                "arguments": args,
                "result": res,
                "executed": True,
            })
            call_failed = isinstance(res, dict) and res.get("success") is False
            if call_failed:
                batch.failed += 1
                if atomic and batch.error is None:
                    batch.error = "atomic_batch_failed"
            else:
                batch.successful += 1

            target_el_id = args.get("element_id") or (
                res.get("element_id") if isinstance(res, dict) else None
            )
            if target_el_id:
                batch.last_target_id = target_el_id
                if session is not None and hasattr(session, "last_target_id"):
                    session.last_target_id = target_el_id

            if batch.error:
                emit({
                    "type": "tool_failed",
                    "tool": fn_name,
                    "arguments": args,
                    "error": batch.error,
                    "result": res,
                    **subagent_meta,
                })
                if atomic:
                    return
                continue

            emit({
                "type": "tool_completed",
                "tool": fn_name,
                "result": res,
                "presentation_version": pres.version,
                **subagent_meta,
            })

            if memory:
                message = res.get("message", "ok") if isinstance(res, dict) else "ok"
                memory.log_action(f"执行工具 '{fn_name}': {message}")

    # ------------------------------------------------------------------
    # Grounding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _capture_texts(pres: PresentationIR) -> Dict[str, str]:
        from .grounding import collect_ir_text

        return {slide.id: collect_ir_text([slide]) for slide in pres.slides}

    @staticmethod
    def _changed_text(pres: PresentationIR, before_texts: Dict[str, str]) -> str:
        from .grounding import collect_ir_text

        parts: List[str] = []
        for slide in pres.slides:
            current = collect_ir_text([slide])
            if before_texts.get(slide.id) != current:
                parts.append(current)
        return "\n".join(parts)

    @staticmethod
    def _unsupported_data_claims(text: str, source_text: str) -> List[str]:
        from .grounding import data_claim_numbers

        return data_claim_numbers(text, source_text)

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
        tx: Optional[Any] = None,
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

        # Shared transaction (atomic batch): never roll back a single call in isolation.
        if tx is not None:
            try:
                return tools.execute(fn_name, args, pres, history)
            except Exception as e:
                logger.error(f"Mutation gateway error running {fn_name}: {e}", exc_info=True)
                return {"success": False, "error": f"Execution error in {fn_name}: {str(e)}"}

        try:
            with pres.transaction(f"tool:{fn_name}", history=history) as local_tx:
                res = tools.execute(fn_name, args, pres, history)
                if isinstance(res, dict) and res.get("success") is False:
                    local_tx.rollback(reason=res.get("error", f"{fn_name} reported failure"))
            return res
        except Exception as e:
            logger.error(f"Mutation gateway error running {fn_name}: {e}", exc_info=True)
            return {"success": False, "error": f"Execution error in {fn_name}: {str(e)}"}
