"""WebSocket service for realtime PPT-Agent-Studio streaming, session state, and preview updates."""

from __future__ import annotations
import json
import logging
import uuid
from typing import Dict, Any, Optional
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


async def run_direct_tool(
    session: PPTSession,
    name: str,
    args: Dict[str, Any],
    on_event: Optional[Any] = None,
) -> Dict[str, Any]:
    """Executes an explicit user action through the MutationGateway.

    Direct GUI actions are unambiguous user intent, so the confirmation gate is
    bypassed; schema validation, transactions, and history tracking still apply.
    """
    batch = await MutationGateway.execute_tool_calls(
        [{"name": name, "arguments": args, "id": f"call_{uuid.uuid4().hex[:6]}"}],
        session.pres,
        session.history,
        session=session,
        on_event=on_event,
        bypass_confirmation=True,
        source="user_direct",
    )
    return batch.first_result()


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
            "checkpoints_count": len(session.checkpoints)
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
                    await store.broadcast({
                        "type": "presentation_updated",
                        "session_id": session.session_id,
                        "presentation": session.pres.model_dump(),
                        "can_undo": session.history.can_undo(),
                        "can_redo": session.history.can_redo(),
                        "active_slide_id": session.active_slide_id,
                        "last_target_id": session.last_target_id
                    }, session_id=session.session_id)

                    new_preview = build_preview_update(session)
                    if new_preview:
                        await store.broadcast(new_preview, session_id=session.session_id)

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

                await store.broadcast({
                    "type": "presentation_updated",
                    "session_id": session.session_id,
                    "presentation": session.pres.model_dump(),
                    "can_undo": session.history.can_undo(),
                    "can_redo": session.history.can_redo(),
                    "active_slide_id": session.active_slide_id,
                    "last_target_id": session.last_target_id,
                    "pending_confirmations_count": len(session.pending_confirmations),
                }, session_id=session.session_id)

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
                        await store.broadcast({
                            "type": "presentation_updated",
                            "session_id": session.session_id,
                            "presentation": session.pres.model_dump(),
                            "can_undo": session.history.can_undo(),
                            "can_redo": session.history.can_redo(),
                            "active_slide_id": session.active_slide_id
                        }, session_id=session.session_id)
                        new_preview = build_preview_update(session)
                        if new_preview:
                            await store.broadcast(new_preview, session_id=session.session_id)

            # User triggered Redo
            elif msg_type == "redo":
                async with session.mutation_lock:
                    cmd = session.redo()
                    if cmd:
                        await store.broadcast({
                            "type": "presentation_updated",
                            "session_id": session.session_id,
                            "presentation": session.pres.model_dump(),
                            "can_undo": session.history.can_undo(),
                            "can_redo": session.history.can_redo(),
                            "active_slide_id": session.active_slide_id
                        }, session_id=session.session_id)
                        new_preview = build_preview_update(session)
                        if new_preview:
                            await store.broadcast(new_preview, session_id=session.session_id)

            # User edited element on canvas directly
            elif msg_type == "direct_update_element":
                args = data.get("payload", {})
                # run_direct_tool commits through the gateway, which owns the lock.
                res = await run_direct_tool(session, "update_element", args)
                if args.get("element_id"):
                    session.last_target_id = args.get("element_id")

                await store.broadcast({
                    "type": "presentation_updated",
                    "session_id": session.session_id,
                    "presentation": session.pres.model_dump(),
                    "can_undo": session.history.can_undo(),
                    "can_redo": session.history.can_redo(),
                    "active_slide_id": session.active_slide_id,
                    "last_target_id": session.last_target_id
                }, session_id=session.session_id)
                new_preview = build_preview_update(session)
                if new_preview:
                    await store.broadcast(new_preview, session_id=session.session_id)

            # Direct GUI manipulation (create slide, delete slide, add shape/text, delete element, etc.)
            # Decoupled from agent dialogue - does not append to chat messages
            elif msg_type == "direct_action":
                action = data.get("action", "")
                args = data.get("payload", {})
                if "slide_id" not in args and session.active_slide_id:
                    args["slide_id"] = session.active_slide_id

                # Each run_direct_tool acquires the session lock via the gateway.
                if action == "create_slide":
                    bg = args.get("background_color", "#FFFFFF")
                    res = await run_direct_tool(session, "create_slide", {
                        "title": args.get("title", "新建幻灯片"),
                        "background_color": bg
                    })
                    if res.get("success"):
                        new_sid = res.get("slide_id") or (session.pres.slides[-1].id if session.pres.slides else None)
                        if new_sid:
                            session.set_active_slide(new_sid)
                elif action == "delete_slide":
                    res = await run_direct_tool(session, "delete_slide", {
                        "slide_id_or_num": args.get("slide_id_or_num", args.get("slide_id", ""))
                    })
                    if res.get("success"):
                        if not session.get_active_slide() and session.pres.slides:
                            session.set_active_slide(session.pres.slides[0].id)
                elif action == "duplicate_slide":
                    res = await run_direct_tool(session, "duplicate_slide", {
                        "slide_id": args.get("slide_id")
                    })
                elif action == "delete_element":
                    elem_id = args.get("element_id")
                    if elem_id:
                        await run_direct_tool(session, "delete_element", {
                            "element_id": elem_id,
                            "slide_id": args.get("slide_id")
                        })
                        session.last_target_id = None
                elif action == "duplicate_element":
                    elem_id = args.get("element_id")
                    if elem_id:
                        await run_direct_tool(session, "duplicate_element", {
                            "element_id": elem_id,
                            "slide_id": args.get("slide_id")
                        })
                elif action == "set_slide_background":
                    color = args.get("color", "#FFFFFF")
                    await run_direct_tool(session, "set_slide_background", {
                        "color": color,
                        "slide_id": args.get("slide_id")
                    })
                elif action == "group_elements":
                    res = await run_direct_tool(session, action, args)
                    if res.get("group_id"):
                        session.last_target_id = res.get("group_id")
                elif action == "ungroup_elements":
                    await run_direct_tool(session, action, args)
                    session.last_target_id = None
                elif action == "align_elements":
                    await run_direct_tool(session, action, args)
                    session.last_target_id = None
                elif action in (
                    "add_shape", "add_text", "add_connector", "optimize_layout", "apply_theme",
                    "clear_slide_elements", "generate_slide_layout",
                    "batch_add_cards", "auto_fix_layout",
                ):
                    res = await run_direct_tool(session, action, args)
                    if res.get("element_id"):
                        session.last_target_id = res.get("element_id")

                await store.broadcast({
                    "type": "presentation_updated",
                    "session_id": session.session_id,
                    "presentation": session.pres.model_dump(),
                    "can_undo": session.history.can_undo(),
                    "can_redo": session.history.can_redo(),
                    "active_slide_id": session.active_slide_id,
                    "last_target_id": session.last_target_id
                }, session_id=session.session_id)
                new_preview = build_preview_update(session)
                if new_preview:
                    await store.broadcast(new_preview, session_id=session.session_id)

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
                        await store.broadcast({
                            "type": "presentation_updated",
                            "session_id": session.session_id,
                            "presentation": session.pres.model_dump(),
                            "can_undo": session.history.can_undo(),
                            "can_redo": session.history.can_redo(),
                            "active_slide_id": session.active_slide_id
                        }, session_id=session.session_id)
                        new_preview = build_preview_update(session)
                        if new_preview:
                            await store.broadcast(new_preview, session_id=session.session_id)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from session '{session.session_id}'")
        store.disconnect_ws(websocket)
    except Exception as e:
        logger.warning(f"WebSocket session error: {e}")
        store.disconnect_ws(websocket)
