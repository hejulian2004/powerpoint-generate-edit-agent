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

    await store.connect_ws(websocket)
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

                session.add_message(role="user", content=user_message)

                # Event streaming callback
                async def on_event(ev: dict):
                    await store.broadcast(ev)

                try:
                    result = await store.agent_runtime.run_turn(
                        user_message=user_message,
                        pres=session.pres,
                        history=session.history,
                        session=session,
                        on_event=on_event
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
                    })

                    new_preview = build_preview_update(session)
                    if new_preview:
                        await store.broadcast(new_preview)

                except Exception as e:
                    logger.error(f"Error in agent turn: {e}", exc_info=True)
                    await websocket.send_json({
                        "type": "agent_error",
                        "error": str(e)
                    })

            # User selected a slide thumbnail
            elif msg_type == "select_slide":
                slide_id = data.get("slide_id")
                if slide_id and session.set_active_slide(slide_id):
                    await store.broadcast({
                        "type": "active_slide_changed",
                        "session_id": session.session_id,
                        "active_slide_id": slide_id
                    })
                    new_preview = build_preview_update(session, slide_id)
                    if new_preview:
                        await store.broadcast(new_preview)

            # User triggered Undo
            elif msg_type == "undo":
                cmd = session.undo()
                if cmd:
                    await store.broadcast({
                        "type": "presentation_updated",
                        "session_id": session.session_id,
                        "presentation": session.pres.model_dump(),
                        "can_undo": session.history.can_undo(),
                        "can_redo": session.history.can_redo(),
                        "active_slide_id": session.active_slide_id
                    })
                    new_preview = build_preview_update(session)
                    if new_preview:
                        await store.broadcast(new_preview)

            # User triggered Redo
            elif msg_type == "redo":
                cmd = session.redo()
                if cmd:
                    await store.broadcast({
                        "type": "presentation_updated",
                        "session_id": session.session_id,
                        "presentation": session.pres.model_dump(),
                        "can_undo": session.history.can_undo(),
                        "can_redo": session.history.can_redo(),
                        "active_slide_id": session.active_slide_id
                    })
                    new_preview = build_preview_update(session)
                    if new_preview:
                        await store.broadcast(new_preview)

            # User edited element on canvas directly
            elif msg_type == "direct_update_element":
                args = data.get("payload", {})
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
                })
                new_preview = build_preview_update(session)
                if new_preview:
                    await store.broadcast(new_preview)

            # Client requested immediate preview
            elif msg_type == "preview_request":
                target_slide_id = data.get("slide_id")
                new_preview = build_preview_update(session, target_slide_id)
                if new_preview:
                    await websocket.send_json(new_preview)

            # Checkpoint operations
            elif msg_type == "create_checkpoint":
                desc = data.get("description", "手动快照")
                health = LayoutDiffEngine.evaluate_slide(session.get_active_slide()) if session.get_active_slide() else None
                score = health.score if health else None
                cp = session.create_checkpoint(description=desc, score=score)
                await websocket.send_json({
                    "type": "checkpoint_created",
                    "checkpoint": cp.to_dict()
                })

            elif msg_type == "restore_checkpoint":
                cp_id = data.get("checkpoint_id")
                if cp_id and session.restore_checkpoint(cp_id):
                    await store.broadcast({
                        "type": "presentation_updated",
                        "session_id": session.session_id,
                        "presentation": session.pres.model_dump(),
                        "can_undo": session.history.can_undo(),
                        "can_redo": session.history.can_redo(),
                        "active_slide_id": session.active_slide_id
                    })
                    new_preview = build_preview_update(session)
                    if new_preview:
                        await store.broadcast(new_preview)

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected from session '{session.session_id}'")
        store.disconnect_ws(websocket)
    except Exception as e:
        logger.warning(f"WebSocket session error: {e}")
        store.disconnect_ws(websocket)
