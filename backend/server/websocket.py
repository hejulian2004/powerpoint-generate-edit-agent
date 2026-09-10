"""WebSocket service for realtime PPT-Agent-Studio streaming, session state, and preview updates."""

from __future__ import annotations
import json
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..state.store import store, create_default_demo_presentation
from ..session.manager import session_manager
from ..session.session import PPTSession
from ..ir.svg_renderer import SVGRenderer
from ..eval.layout_diff import LayoutDiffEngine
from ..agent.tools import tools

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
        health_report = LayoutDiffEngine.evaluate_slide(slide)
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


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Session-aware WebSocket endpoint for streaming editing, chat, and instant previews."""
    session_id = websocket.query_params.get("session_id") or store.active_session_id
    session: PPTSession = session_manager.get_or_create(
        session_id=session_id,
        pres_factory=create_default_demo_presentation
    )

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

                async with session.mutation_lock:
                    session.add_message(role="user", content=user_message)

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

                        reply_text = result.get("reply", "处理完成。")
                        session.add_message(
                            role="assistant",
                            content=reply_text,
                            tool_calls=result.get("tools_executed"),
                            vision_critique=result.get("vision_critique")
                        )

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

                async with session.mutation_lock:
                    async def on_event(ev: dict):
                        if "session_id" not in ev:
                            ev["session_id"] = session.session_id
                        await store.broadcast(ev, session_id=session.session_id)

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
                async with session.mutation_lock:
                    res = tools.execute("update_element", args, session.pres, session.history)
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

                async with session.mutation_lock:
                    if action == "create_slide":
                        bg = args.get("background_color", "#FFFFFF")
                        res = tools.execute("create_slide", {
                            "title": args.get("title", "新建幻灯片"),
                            "background_color": bg
                        }, session.pres, session.history)
                        if res.get("success"):
                            new_sid = res.get("slide_id") or (session.pres.slides[-1].id if session.pres.slides else None)
                            if new_sid:
                                session.set_active_slide(new_sid)
                    elif action == "delete_slide":
                        res = tools.execute("delete_slide", {
                            "slide_id_or_num": args.get("slide_id_or_num", args.get("slide_id", ""))
                        }, session.pres, session.history)
                        if res.get("success"):
                            if not session.get_active_slide() and session.pres.slides:
                                session.set_active_slide(session.pres.slides[0].id)
                    elif action == "duplicate_slide":
                        res = tools.execute("duplicate_slide", {
                            "slide_id": args.get("slide_id")
                        }, session.pres, session.history)
                    elif action == "delete_element":
                        elem_id = args.get("element_id")
                        if elem_id:
                            tools.execute("delete_element", {
                                "element_id": elem_id,
                                "slide_id": args.get("slide_id")
                            }, session.pres, session.history)
                            session.last_target_id = None
                    elif action == "duplicate_element":
                        elem_id = args.get("element_id")
                        if elem_id:
                            tools.execute("duplicate_element", {
                                "element_id": elem_id,
                                "slide_id": args.get("slide_id")
                            }, session.pres, session.history)
                    elif action == "set_slide_background":
                        color = args.get("color", "#FFFFFF")
                        tools.execute("set_slide_background", {
                            "color": color,
                            "slide_id": args.get("slide_id")
                        }, session.pres, session.history)
                    elif action in ("add_shape", "add_text", "add_connector", "optimize_layout", "apply_theme"):
                        tools.execute(action, args, session.pres, session.history)

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
                    health = LayoutDiffEngine.evaluate_slide(session.get_active_slide()) if session.get_active_slide() else None
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
