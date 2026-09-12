"""WebSocket service for realtime PPT-Agent-Studio streaming, session state, and preview updates.

Mutation protocol (single-writer envelope):
- Every direct/batch mutation may carry a client `mutation_id` plus optional CAS
  hints (`document_epoch`, `expected_revision`).
- Successful mutations broadcast `presentation_updated` carrying
  `last_mutation_id`, `version`, and `document_epoch` so the client can retire
  optimistic patches and discard stale outbox entries.
- Failed / stale mutations emit `mutation_rejected` instead of a success broadcast.
"""

from __future__ import annotations
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..state.store import store
from ..session.manager import session_manager
from ..session.session import PPTSession
from ..workspace.runtime import get_workspace_manager
from ..session.services.connection import (
    SESSION_TAKEN_OVER,
    WS_TAKEN_OVER_CODE,
    TransportOwnership,
)
from ..ir.svg_renderer import SVGRenderer
from ..quality import QualityService
from ..agent.mutation_gateway import (
    MutationGateway,
    STALE_MUTATION,
    DOCUMENT_EPOCH_MISMATCH,
)
from ..protocol.presentation import build_presentation_event

logger = logging.getLogger(__name__)
ws_router = APIRouter()


def build_preview_update(session: PPTSession, slide_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Generates real-time SVG rendering and quantitative layout health scores for the active slide."""
    slide = None
    if slide_id:
        slide = session.document.presentation.get_slide(slide_id)
    if not slide:
        slide = session.get_active_slide()
    if not slide:
        return None

    try:
        svg = SVGRenderer.render_slide(slide)
        health_report = QualityService.evaluate_slide(slide)
        return {
            "type": "preview_update",
            "session_id": session.session_id,
            "slide_id": slide.id,
            "svg": svg,
            "score": round(health_report.score, 1),
            "quality_score": health_report.quality_score.to_dict(),
            "version": session.document.presentation.version
        }
    except Exception as e:
        logger.warning(f"Failed to generate preview update: {e}")
        return None


def _mutation_id(data: Dict[str, Any]) -> str:
    return data.get("mutation_id") or f"mut_{uuid.uuid4().hex[:10]}"


def build_presentation_updated(
    session: PPTSession,
    *,
    last_mutation_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Canonical `presentation_updated` envelope with ACK + CAS version fields."""
    return build_presentation_event(
        session,
        "presentation_updated",
        last_mutation_id=last_mutation_id,
        extra=extra or None,
    )


async def execute_direct_batch(
    session: PPTSession,
    tool_calls: List[Dict[str, Any]],
    *,
    mutation_id: str,
    atomic: bool = False,
    document_epoch: Optional[str] = None,
    expected_revision: Optional[int] = None,
    client_id: Optional[str] = None,
    client_sequence: Optional[int] = None,
    on_event: Optional[Any] = None,
    transport: Optional[Any] = None,
):
    """Executes a direct (unambiguous user) mutation envelope through the gateway."""
    return await MutationGateway.execute_tool_calls(
        tool_calls,
        session.document.presentation,
        session.history,
        session=session,
        on_event=on_event,
        bypass_confirmation=True,
        source="user_direct",
        atomic=atomic,
        mutation_id=mutation_id,
        document_epoch=document_epoch,
        expected_revision=expected_revision,
        client_id=client_id,
        client_sequence=client_sequence,
        # Session-backed user writes MUST carry CAS stamps; an unstamped direct
        # mutation is rejected rather than silently applied to "current".
        require_stamps=True,
        transport=transport,
    )


def _rejection_payload(session: PPTSession, mutation_id: str, batch: Any) -> Dict[str, Any]:
    if batch.error:
        error = batch.error
    elif batch.results:
        error = batch.first_result().get("error") or "mutation_failed"
    else:
        error = "mutation_failed"
    payload: Dict[str, Any] = {
        "type": "mutation_rejected",
        "session_id": session.session_id,
        "mutation_id": mutation_id,
        "error": error,
        "version": session.document.presentation.version,
        "document_epoch": getattr(session, "document_epoch", None),
    }
    # CAS-class rejections mean the client's baseline is stale. Ship the
    # authoritative snapshot in the same message so the client can resync
    # atomically (no extra round-trip that could itself race). Ordinary schema /
    # business failures stay lightweight.
    if error in (STALE_MUTATION, DOCUMENT_EPOCH_MISMATCH):
        payload["presentation"] = session.document.presentation.model_dump()
        payload["active_slide_id"] = session.active_slide_id
        payload["can_undo"] = session.history.can_undo()
        payload["can_redo"] = session.history.can_redo()
    return payload


async def _broadcast_state(
    session: PPTSession,
    *,
    last_mutation_id: Optional[str] = None,
    preview_slide_id: Optional[str] = None,
    local_view_hint_slide_id: Optional[str] = None,
) -> None:
    extra: Dict[str, Any] = {}
    # Navigation is client-local, so `active_slide_id` carries no document
    # authority. When a mutation creates a slide for THIS request, ship a
    # mutation-scoped hint so the initiating client may follow it while other
    # clients keep their own view.
    if local_view_hint_slide_id:
        extra["local_view_hint"] = {"active_slide_id": local_view_hint_slide_id}
    await store.broadcast(
        build_presentation_updated(
            session, last_mutation_id=last_mutation_id, **extra
        ),
        session_id=session.session_id,
    )
    # Preview the slide the mutation actually touched; the session no longer owns
    # a single "active" slide now that navigation is client-local.
    new_preview = build_preview_update(session, preview_slide_id)
    if new_preview:
        await store.broadcast(new_preview, session_id=session.session_id)


async def _chat_event_router(websocket: WebSocket, session: PPTSession, ev: dict) -> None:
    """Routes a chat-turn event to the right transport scope.

    Ordinary admitted-turn events describe a mutation/conversation that every
    window attached to the session should see, so they broadcast. A
    ``turn_rejected`` event is terminal for ONE request: only the originating
    socket may surface it, otherwise another window (which may be the legitimate
    writer) would render a spurious error/thinking state for a request it never
    issued.
    """
    if "session_id" not in ev:
        ev["session_id"] = session.session_id
    if ev.get("type") == "turn_rejected":
        await websocket.send_json(ev)
        return
    await store.broadcast(ev, session_id=session.session_id)


async def _handle_history_action(
    websocket: WebSocket,
    session: PPTSession,
    action: str,
    data: Dict[str, Any],
    transport: Optional[Any] = None,
) -> None:
    """Routes undo/redo through the MutationGateway so CAS + single-writer hold.

    An empty history is a valid no-op: it is acknowledged (not rejected) so the
    client can retire its pending mutation without rolling back.
    """
    mutation_id = _mutation_id(data)
    batch = await execute_direct_batch(
        session,
        [{"name": action, "arguments": {}, "id": f"call_{uuid.uuid4().hex[:6]}"}],
        mutation_id=mutation_id,
        document_epoch=data.get("document_epoch"),
        expected_revision=data.get("expected_revision"),
        client_id=data.get("client_id"),
        client_sequence=data.get("client_sequence"),
        transport=transport,
    )
    res = batch.first_result()
    if batch.error or (isinstance(res, dict) and res.get("error")):
        await websocket.send_json(_rejection_payload(session, mutation_id, batch))
    else:
        await _broadcast_state(session, last_mutation_id=mutation_id)


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Session-aware WebSocket endpoint for streaming editing, chat, and instant previews."""
    # The socket must name an EXISTING session. The workspace is the sole creator
    # of sessions; the websocket never implicitly creates one (S4).
    session_id = websocket.query_params.get("session_id")
    if not session_id:
        await websocket.accept()
        await websocket.send_json({
            "type": "session_error",
            "error": "MISSING_SESSION_ID",
            "message": "session_id is required",
        })
        await websocket.close(code=4400)
        return

    session: PPTSession = session_manager.get_session(session_id)
    if session is None:
        manager = get_workspace_manager()
        if manager is not None:
            session = await manager.restore_session(session_id)
    if session is None:
        await websocket.accept()
        await websocket.send_json({
            "type": "session_error",
            "error": "SESSION_NOT_FOUND",
            "session_id": session_id,
            "message": "Session not found",
        })
        await websocket.close(code=4404)
        return

    await store.connect_ws(websocket, session_id=session.session_id)
    logger.info(f"WebSocket client connected to session '{session.session_id}'")

    # S1: newest tab wins. Notify + evict any previous owner of this session so
    # exactly one writable frontend remains.
    previous, generation = session.connection.attach(
        websocket, frontend_instance_id=websocket.query_params.get("frontend_instance_id")
    )
    # Server-bound proof of ownership for THIS socket. Every mutation/chat this
    # socket dispatches carries it so the gateway can re-verify at commit time.
    transport = TransportOwnership(websocket, generation)
    if previous is not None and previous is not websocket:
        try:
            await previous.send_json({
                "type": SESSION_TAKEN_OVER,
                "session_id": session.session_id,
                "reason": "another_tab_opened",
            })
        except Exception:
            pass
        try:
            await previous.close(code=WS_TAKEN_OVER_CODE)
        except Exception:
            pass
        store.disconnect_ws(previous)

    try:
        # 1. Send initial presentation state immediately
        await websocket.send_json(
            build_presentation_event(
                session,
                "presentation_loaded",
                extra={
                    "checkpoints_count": len(session.checkpoints),
                    "connection_generation": generation,
                },
            )
        )

        # 2. Push initial preview update
        preview = build_preview_update(session)
        if preview:
            await websocket.send_json(preview)

        # 3. Main event loop
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue

            msg_type = data.get("type", "")

            # A superseded socket loses write access the moment another tab
            # attaches (S1). Read-only preview requests still terminate here:
            # the socket is closed and the client suppresses reconnect.
            if not session.connection.is_current(websocket):
                break

            # User sends conversational design instruction
            if msg_type == "chat":
                user_message = data.get("message", "").strip()
                if not user_message:
                    continue

                # A chat turn is a mutation-bearing request: it MUST declare the
                # document identity the client observed. A missing stamp is
                # rejected so an offline/unsynced client cannot have its request
                # interpreted against a deck it never saw.
                request_epoch = data.get("document_epoch")
                request_revision = data.get("base_revision", data.get("expected_revision"))
                if request_epoch is None or request_revision is None:
                    await websocket.send_json({
                        "type": "turn_rejected",
                        "session_id": session.session_id,
                        "error": "missing_request_stamp",
                        "message": "本次指令缺少文档版本信息，未执行，请同步当前版本后重试。",
                        "document_epoch": getattr(session, "document_epoch", None),
                        "version": session.document.presentation.version,
                    })
                    # This pre-admission rejection never enters `run_turn()`, so it
                    # must push the canonical document state itself. Otherwise the
                    # client stays in `agent_lock_pending` forever (the rejection
                    # is request-specific and deliberately never unlocks), with no
                    # subsequent snapshot to restore it.
                    await _broadcast_state(session)
                    continue

                # The mutation lock is NOT held across the LLM turn: the gateway
                # serializes only the actual mutations, so GUI edits stay responsive.
                # Event streaming callback
                async def on_event(ev: dict):
                    await _chat_event_router(websocket, session, ev)

                try:
                    result = await store.agent_runtime.run_turn(
                        user_message=user_message,
                        pres=session.document.presentation,
                        history=session.history,
                        session=session,
                        on_event=on_event,
                        confirmed_tool_ids=data.get("confirmed_tool_ids") or [],
                        request_document_epoch=request_epoch,
                        request_base_revision=request_revision,
                        ui_context=data.get("ui_context"),
                        transport=transport,
                        mode=data.get("mode"),
                    )

                    # Transcript is owned by AgentRuntime.run_turn.

                    # Broadcast refreshed state & preview
                    await _broadcast_state(session)

                except Exception as e:
                    logger.error(f"Error in agent turn: {e}", exc_info=True)
                    await websocket.send_json({
                        "type": "agent_error",
                        "session_id": session.session_id,
                        "error": str(e)
                    })

            # User's natural-language message is empty but the turn carries a plan
            # execution directive (confirmed plan) or other control command below.
            elif msg_type == "new_conversation":
                await session.reset_conversation()
                await store.broadcast(
                    {"type": "conversation_reset", "session_id": session.session_id},
                    session_id=session.session_id,
                )
                await _broadcast_state(session)

            elif msg_type == "compress_context":
                async def on_event(ev: dict):
                    if "session_id" not in ev:
                        ev["session_id"] = session.session_id
                    await store.broadcast(ev, session_id=session.session_id)

                await store.agent_runtime.compress_context(session, on_event=on_event)

            elif msg_type == "set_plan_mode":
                mode = session.set_interaction_mode(data.get("mode", "auto"))
                await store.broadcast(
                    {
                        "type": "plan_mode_changed",
                        "session_id": session.session_id,
                        "mode": mode,
                    },
                    session_id=session.session_id,
                )

            elif msg_type in ("confirm_plan", "cancel_plan"):
                plan_id = data.get("plan_id")
                if not plan_id:
                    await websocket.send_json({
                        "type": "plan_failed",
                        "session_id": session.session_id,
                        "error": "plan_id is required",
                    })
                    continue

                async def on_event(ev: dict):
                    if "session_id" not in ev:
                        ev["session_id"] = session.session_id
                    await store.broadcast(ev, session_id=session.session_id)

                if msg_type == "confirm_plan":
                    await store.agent_runtime.confirm_plan(
                        session, plan_id, on_event=on_event, transport=transport
                    )
                else:
                    await store.agent_runtime.cancel_plan(
                        session, plan_id, on_event=on_event
                    )
                await _broadcast_state(session)

            elif msg_type == "vision_review":
                async def on_event(ev: dict):
                    if "session_id" not in ev:
                        ev["session_id"] = session.session_id
                    await store.broadcast(ev, session_id=session.session_id)

                await store.agent_runtime.review_visuals(
                    session,
                    target=data.get("target"),
                    on_event=on_event,
                    transport=transport,
                )

            # User explicitly confirms (or cancels) a pending low-confidence call
            elif msg_type in ("confirm_tool_call", "cancel_tool_call"):
                call_id = data.get("call_id")
                if not call_id:
                    await websocket.send_json({
                        "type": "confirmation_failed",
                        "session_id": session.session_id,
                        "error": "call_id is required",
                    })
                    continue

                async def on_event(ev: dict):
                    if "session_id" not in ev:
                        ev["session_id"] = session.session_id
                    await store.broadcast(ev, session_id=session.session_id)

                # The gateway serializes the confirmed mutation internally.
                if msg_type == "confirm_tool_call":
                    result = await store.agent_runtime.confirm_pending(
                        session, call_id, on_event=on_event, transport=transport
                    )
                else:
                    result = await store.agent_runtime.cancel_pending(
                        session, call_id, on_event=on_event
                    )

                await store.broadcast(
                    build_presentation_updated(
                        session,
                        pending_confirmations_count=len(session.confirmations.pending),
                    ),
                    session_id=session.session_id,
                )

                new_preview = build_preview_update(session)
                if new_preview:
                    await store.broadcast(new_preview, session_id=session.session_id)

            # User selected a slide thumbnail.
            #
            # Navigation is CLIENT-LOCAL UI state: it must not mutate the shared
            # document's `active_slide_id`, and it must not be broadcast to other
            # clients (which would drag their view to someone else's slide). We
            # only return a preview of the requested slide to the requester.
            elif msg_type == "select_slide":
                slide_id = data.get("slide_id")
                if slide_id and session.document.presentation.get_slide(slide_id):
                    new_preview = build_preview_update(session, slide_id)
                    if new_preview:
                        await websocket.send_json(new_preview)

            # User triggered Undo
            elif msg_type == "undo":
                await _handle_history_action(websocket, session, "undo", data, transport)

            # User triggered Redo
            elif msg_type == "redo":
                await _handle_history_action(websocket, session, "redo", data, transport)

            # User edited element on canvas directly
            elif msg_type == "direct_update_element":
                args = data.get("payload", {})
                mutation_id = _mutation_id(data)
                batch = await execute_direct_batch(
                    session,
                    [{"name": "update_element", "arguments": args, "id": f"call_{uuid.uuid4().hex[:6]}"}],
                    mutation_id=mutation_id,
                    document_epoch=data.get("document_epoch"),
                    expected_revision=data.get("expected_revision"),
                    client_id=data.get("client_id"),
                    client_sequence=data.get("client_sequence"),
                    transport=transport,
                )
                if batch.error or not batch.success:
                    await websocket.send_json(_rejection_payload(session, mutation_id, batch))
                else:
                    if args.get("element_id"):
                        session.document.last_target_id = args.get("element_id")
                    await _broadcast_state(
                        session,
                        last_mutation_id=mutation_id,
                        preview_slide_id=args.get("slide_id"),
                    )

            # Direct GUI manipulation (create slide, delete slide, add shape/text, delete element, etc.)
            # Decoupled from agent dialogue - does not append to chat messages
            elif msg_type == "direct_action":
                action = data.get("action", "")
                args = dict(data.get("payload", {}))
                if "slide_id" not in args and session.active_slide_id:
                    args["slide_id"] = session.active_slide_id
                mutation_id = _mutation_id(data)

                tool_name = action
                tool_args = args
                if action == "create_slide":
                    tool_args = {
                        "title": args.get("title", "新建幻灯片"),
                        "background_color": args.get("background_color", "#FFFFFF"),
                    }
                elif action == "delete_slide":
                    tool_args = {
                        "slide_id_or_num": args.get("slide_id_or_num", args.get("slide_id", ""))
                    }
                elif action == "duplicate_slide":
                    tool_args = {"slide_id": args.get("slide_id")}
                elif action == "delete_element":
                    tool_args = {
                        "element_id": args.get("element_id"),
                        "slide_id": args.get("slide_id"),
                    }
                elif action == "duplicate_element":
                    tool_args = {
                        "element_id": args.get("element_id"),
                        "slide_id": args.get("slide_id"),
                    }
                elif action == "set_slide_background":
                    tool_args = {
                        "color": args.get("color", "#FFFFFF"),
                        "slide_id": args.get("slide_id"),
                    }

                batch = await execute_direct_batch(
                    session,
                    [{"name": tool_name, "arguments": tool_args, "id": f"call_{uuid.uuid4().hex[:6]}"}],
                    mutation_id=mutation_id,
                    document_epoch=data.get("document_epoch"),
                    expected_revision=data.get("expected_revision"),
                    client_id=data.get("client_id"),
                    client_sequence=data.get("client_sequence"),
                    transport=transport,
                )

                if batch.error or not batch.success:
                    await websocket.send_json(_rejection_payload(session, mutation_id, batch))
                else:
                    res = batch.first_result()
                    hint_sid: Optional[str] = None
                    if action == "create_slide":
                        new_sid = res.get("slide_id") or (
                            session.document.presentation.slides[-1].id if session.document.presentation.slides else None
                        )
                        if new_sid:
                            session.set_active_slide(new_sid)
                            hint_sid = new_sid
                    elif action == "duplicate_slide":
                        # The tool mirrors the new slide into `pres.active_slide_id`;
                        # echo it back only as this request's own navigation hint.
                        dup_sid = res.get("new_slide_id")
                        if dup_sid:
                            hint_sid = dup_sid
                    elif action == "delete_slide":
                        if not session.get_active_slide() and session.document.presentation.slides:
                            session.set_active_slide(session.document.presentation.slides[0].id)
                    elif action == "delete_element":
                        session.document.last_target_id = None
                    elif action in ("ungroup_elements", "align_elements"):
                        session.document.last_target_id = None
                    elif action == "group_elements":
                        if res.get("group_id"):
                            session.document.last_target_id = res.get("group_id")
                    elif action in (
                        "duplicate_element", "add_shape", "add_text", "add_connector",
                        "optimize_layout", "apply_theme", "clear_slide_elements",
                        "generate_slide_layout", "batch_add_cards", "auto_fix_layout",
                    ):
                        new_id = res.get("element_id") or res.get("new_element_id")
                        if new_id:
                            session.document.last_target_id = new_id

                    await _broadcast_state(
                        session,
                        last_mutation_id=mutation_id,
                        preview_slide_id=args.get("slide_id") or session.active_slide_id,
                        local_view_hint_slide_id=hint_sid,
                    )

            # Atomic batch mutation (e.g. multi-select drag as ONE undo step)
            elif msg_type == "batch_mutation":
                mutation_id = _mutation_id(data)
                raw_ops = data.get("mutations") or data.get("operations") or []
                calls: List[Dict[str, Any]] = []
                for op in raw_ops:
                    if not isinstance(op, dict):
                        continue
                    name = op.get("name") or op.get("tool") or ""
                    op_args = dict(op.get("payload") or op.get("arguments") or {})
                    if "slide_id" not in op_args and session.active_slide_id:
                        op_args["slide_id"] = session.active_slide_id
                    calls.append({
                        "name": name,
                        "arguments": op_args,
                        "id": op.get("id") or f"call_{uuid.uuid4().hex[:6]}",
                    })

                batch = await execute_direct_batch(
                    session,
                    calls,
                    mutation_id=mutation_id,
                    atomic=True,
                    document_epoch=data.get("document_epoch"),
                    expected_revision=data.get("expected_revision"),
                    client_id=data.get("client_id"),
                    client_sequence=data.get("client_sequence"),
                    transport=transport,
                )
                if batch.error or not batch.success:
                    await websocket.send_json(_rejection_payload(session, mutation_id, batch))
                else:
                    preview_sid = calls[0]["arguments"].get("slide_id") if calls else None
                    await _broadcast_state(
                        session,
                        last_mutation_id=mutation_id,
                        preview_slide_id=preview_sid or session.active_slide_id,
                    )

            # Client requested immediate preview
            elif msg_type == "preview_request":
                target_slide_id = data.get("slide_id")
                new_preview = build_preview_update(session, target_slide_id)
                if new_preview:
                    await websocket.send_json(new_preview)

            # Checkpoint operations
            elif msg_type == "create_checkpoint":
                desc = data.get("description", "手动快照")
                async with session.document.mutation_lock:
                    health = QualityService.evaluate_slide(session.get_active_slide()) if session.get_active_slide() else None
                    score = health.score if health else None
                    cp = session.create_checkpoint(description=desc, score=score)
                    await websocket.send_json({
                        "type": "checkpoint_created",
                        "session_id": session.session_id,
                        "checkpoint": cp.to_dict()
                    })

            elif msg_type == "restore_checkpoint":
                cp_id = data.get("checkpoint_id")
                if cp_id:
                    result = await session.commit_checkpoint_restore(
                        cp_id,
                        expected_epoch=data.get("document_epoch"),
                        expected_revision=data.get("expected_revision"),
                        source="rest",
                    )
                    if result.committed:
                        await _broadcast_state(session)
                    else:
                        await websocket.send_json({
                            "type": "replacement_rejected",
                            "session_id": session.session_id,
                            "error": result.error,
                        })

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from session '{session.session_id}'")
        session.connection.detach(websocket)
        store.disconnect_ws(websocket)
    except Exception as e:
        logger.warning(f"WebSocket session error: {e}")
        session.connection.detach(websocket)
        store.disconnect_ws(websocket)
