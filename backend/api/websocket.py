"""WebSocket endpoint for ultra-low latency real-time streaming and synchronization."""

from __future__ import annotations
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..state.store import store
from ..agent.tools import tools

logger = logging.getLogger(__name__)
ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await store.connect_ws(websocket)
    logger.info("WebSocket client connected")

    try:
        # 1. Send initial presentation state immediately
        await websocket.send_json({
            "type": "presentation_loaded",
            "presentation": store.get_presentation().model_dump(),
            "active_slide_id": store.get_presentation().active_slide_id,
            "can_undo": store.history.can_undo(),
            "can_redo": store.history.can_redo()
        })

        # 2. Main incoming message loop
        while True:
            raw_msg = await websocket.receive_text()
            try:
                data = json.loads(raw_msg)
            except Exception:
                continue

            msg_type = data.get("type", "")

            # User sends chat prompt to agent
            if msg_type == "chat":
                user_message = data.get("message", "")
                if not user_message.strip():
                    continue

                # Event callback for live streaming events to all clients
                async def on_event(ev: dict):
                    await store.broadcast(ev)

                try:
                    result = await store.agent_runtime.run_turn(
                        user_message=user_message,
                        pres=store.get_presentation(),
                        history=store.history,
                        on_event=on_event
                    )
                    # Broadcast refreshed state
                    await store.broadcast({
                        "type": "presentation_updated",
                        "presentation": store.get_presentation().model_dump(),
                        "can_undo": store.history.can_undo(),
                        "can_redo": store.history.can_redo()
                    })
                except Exception as e:
                    logger.error(f"Error in agent turn: {e}")
                    await websocket.send_json({
                        "type": "agent_error",
                        "error": str(e)
                    })

            # User clicked slide thumbnail
            elif msg_type == "select_slide":
                slide_id = data.get("slide_id")
                if slide_id and store.set_active_slide(slide_id):
                    await store.broadcast({
                        "type": "active_slide_changed",
                        "active_slide_id": slide_id
                    })

            # User triggered Undo
            elif msg_type == "undo":
                patch = store.undo()
                if patch:
                    await store.broadcast({
                        "type": "presentation_updated",
                        "presentation": store.get_presentation().model_dump(),
                        "patch": patch,
                        "can_undo": store.history.can_undo(),
                        "can_redo": store.history.can_redo()
                    })

            # User triggered Redo
            elif msg_type == "redo":
                patch = store.redo()
                if patch:
                    await store.broadcast({
                        "type": "presentation_updated",
                        "presentation": store.get_presentation().model_dump(),
                        "patch": patch,
                        "can_undo": store.history.can_undo(),
                        "can_redo": store.history.can_redo()
                    })

            # User directly edited an element on canvas (e.g. moved / resized)
            elif msg_type == "direct_update_element":
                args = data.get("payload", {})
                res = tools.execute("update_element", args, store.get_presentation(), store.history)
                await store.broadcast({
                    "type": "presentation_updated",
                    "presentation": store.get_presentation().model_dump(),
                    "can_undo": store.history.can_undo(),
                    "can_redo": store.history.can_redo()
                })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        store.disconnect_ws(websocket)
    except Exception as e:
        logger.warning(f"WebSocket session error: {e}")
        store.disconnect_ws(websocket)
