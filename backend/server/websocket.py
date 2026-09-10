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
from ..ir.svg_renderer import SVGRenderer
from ..quality import QualityService
from ..agent.mutation_gateway import MutationGateway

logger = logging.getLogger(__name__)
ws_router = APIRouter()


def build_preview_update(session: PPTSession, slide_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Generates real-time SVG rendering and quantitative layout health scores for the active slide."""
    slide = None
    if slide_id:
        slide = session.pres.get_slide(slide_id)
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
            "version": session.pres.version
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
    payload: Dict[str, Any] = {
        "type": "presentation_updated",
        "session_id": session.session_id,
        "presentation": session.pres.model_dump(),
        "can_undo": session.history.can_undo(),
        "can_redo": session.history.can_redo(),
        "active_slide_id": session.active_slide_id,
        "last_target_id": session.last_target_id,
        "version": session.pres.version,
        "document_epoch": getattr(session, "document_epoch", None),
        "last_mutation_id": last_mutation_id,
    }
    payload.update(extra)
    return payload


async def execute_direct_batch(
    session: PPTSession,
    tool_calls: List[Dict[str, Any]],
    *,
    mutation_id: str,
    atomic: bool = False,
    document_epoch: Optional[str] = None,
    expected_revision: Optional[int] = None,
    on_event: Optional[Any] = None,
):
    """Executes a direct (unambiguous user) mutation envelope through the gateway."""
    return await MutationGateway.execute_tool_calls(
        tool_calls,
        session.pres,
        session.history,
        session=session,
        on_event=on_event,
        bypass_confirmation=True,
        source="user_direct",
        atomic=atomic,
        mutation_id=mutation_id,
        document_epoch=document_epoch,
        expected_revision=expected_revision,
    )


def _rejection_payload(session: PPTSession, mutation_id: str, batch: Any) -> Dict[str, Any]:
    if batch.error:
        error = batch.error
    elif batch.results:
        error = batch.first_result().get("error") or "mutation_failed"
    else:
        error = "mutation_failed"
    return {
        "type": "mutation_rejected",
        "session_id": session.session_id,
        "mutation_id": mutation_id,
        "error": error,
        "version": session.pres.version,
        "document_epoch": getattr(session, "document_epoch", None),
    }


async def _broadcast_state(session: PPTSession, *, last_mutation_id: Optional[str] = None) -> None:
    await store.broadcast(
        build_presentation_updated(session, last_mutation_id=last_mutation_id),
        session_id=session.session_id,
    )
    new_preview = build_preview_update(session)
    if new_preview:
        await store.broadcast(new_preview, session_id=session.session_id)


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Session-aware WebSocket endpoint for streaming editing, chat, and instant previews."""
    session_id = websocket.query_params.get("session_id") or store.active_session_id
    session: PPTSession = session_manager.get_or_create(session_id=session_id)

    await store.connect_ws(websocket, session_id=session.session_id)
    logger.info(f"WebSocket client connected to session '{session.session_id}'")

    try:
        # 1. Send initial presentation state immediately
        await websocket.send_json({
            "type": "presentation_loaded",
            "session_id": session.session_id,
            "presentation": session.pres.model_dump(),
            "active_slide_id": session.active_slide_id,
            "can_undo": session.history.can_undo(),
            "can_redo": session.history.can_redo(),
            "last_target_id": session.last_target_id,
            "checkpoints_count": len(session.checkpoints),
            "version": session.pres.version,
            "document_epoch": getattr(session, "document_epoch", None),
            "last_mutation_id": None,
        })

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

            # User sends conversational design instruction
            if msg_type == "chat":
                user_message = data.get("message", "").strip()
                if not user_message:
                    continue

                # The mutation lock is NOT held across the LLM turn: the gateway
                # serializes only the actual mutations, so GUI edits stay responsive.
                # Event streaming callback
                async def on_event(ev: dict):
                    if "session_id" not in ev:
                        ev["session_id"] = session.session_id
                    await store.broadcast(ev, session_id=session.session_id)

                try:
                    result = await store.agent_runtime.run_turn(
                        user_message=user_message,
                        pres=session.pres,
                        history=session.history,
                        session=session,
                        on_event=on_event,
                        confirmed_tool_ids=data.get("confirmed_tool_ids") or []
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
                        session, call_id, on_event=on_event
                    )
                else:
                    result = await store.agent_runtime.cancel_pending(
                        session, call_id, on_event=on_event
                    )

                await store.broadcast(
                    build_presentation_updated(
                        session,
                        pending_confirmations_count=len(session.pending_confirmations),
                    ),
                    session_id=session.session_id,
                )

                new_preview = build_preview_update(session)
                if new_preview:
                    await store.broadcast(new_preview, session_id=session.session_id)

            # User selected a slide thumbnail
            elif msg_type == "select_slide":
                slide_id = data.get("slide_id")
                async with session.mutation_lock:
                    if slide_id and session.set_active_slide(slide_id):
                        await store.broadcast({
                            "type": "active_slide_changed",
                            "session_id": session.session_id,
                            "active_slide_id": slide_id
                        }, session_id=session.session_id)
                        new_preview = build_preview_update(session, slide_id)
                        if new_preview:
                            await store.broadcast(new_preview, session_id=session.session_id)

            # User triggered Undo
            elif msg_type == "undo":
                async with session.mutation_lock:
                    cmd = session.undo()
                    if cmd:
                        await _broadcast_state(session)

            # User triggered Redo
            elif msg_type == "redo":
                async with session.mutation_lock:
                    cmd = session.redo()
                    if cmd:
                        await _broadcast_state(session)

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
                )
                if batch.error or not batch.success:
                    await websocket.send_json(_rejection_payload(session, mutation_id, batch))
                else:
                    if args.get("element_id"):
                        session.last_target_id = args.get("element_id")
                    await _broadcast_state(session, last_mutation_id=mutation_id)

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
                )

                if batch.error or not batch.success:
                    await websocket.send_json(_rejection_payload(session, mutation_id, batch))
                else:
                    res = batch.first_result()
                    if action == "create_slide":
                        new_sid = res.get("slide_id") or (
                            session.pres.slides[-1].id if session.pres.slides else None
                        )
                        if new_sid:
                            session.set_active_slide(new_sid)
                    elif action == "delete_slide":
                        if not session.get_active_slide() and session.pres.slides:
                            session.set_active_slide(session.pres.slides[0].id)
                    elif action == "delete_element":
                        session.last_target_id = None
                    elif action in ("ungroup_elements", "align_elements"):
                        session.last_target_id = None
                    elif action == "group_elements":
                        if res.get("group_id"):
                            session.last_target_id = res.get("group_id")
                    elif action in (
                        "duplicate_element", "add_shape", "add_text", "add_connector",
                        "optimize_layout", "apply_theme", "clear_slide_elements",
                        "generate_slide_layout", "batch_add_cards", "auto_fix_layout",
                    ):
                        if res.get("element_id"):
                            session.last_target_id = res.get("element_id")

                    await _broadcast_state(session, last_mutation_id=mutation_id)

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
                )
                if batch.error or not batch.success:
                    await websocket.send_json(_rejection_payload(session, mutation_id, batch))
                else:
                    await _broadcast_state(session, last_mutation_id=mutation_id)

            # Client requested immediate preview
            elif msg_type == "preview_request":
                target_slide_id = data.get("slide_id")
                new_preview = build_preview_update(session, target_slide_id)
                if new_preview:
                    await websocket.send_json(new_preview)

            # Checkpoint operations
            elif msg_type == "create_checkpoint":
                desc = data.get("description", "手动快照")
                async with session.mutation_lock:
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
                async with session.mutation_lock:
                    if cp_id and session.restore_checkpoint(cp_id):
                        await _broadcast_state(session)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from session '{session.session_id}'")
        store.disconnect_ws(websocket)
    except Exception as e:
        logger.warning(f"WebSocket session error: {e}")
        store.disconnect_ws(websocket)
