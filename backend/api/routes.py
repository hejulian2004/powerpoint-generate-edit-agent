"""REST API routes for PPT-Agent-Studio."""

from __future__ import annotations
import urllib.parse
from typing import Dict, Any, Optional
from fastapi import APIRouter, UploadFile, File, Response, HTTPException, Body
from fastapi.responses import StreamingResponse, Response
import io

from ..state.store import store
from ..ir.svg_renderer import SVGRenderer
from ..config import settings, AppSettings

router = APIRouter(prefix="/api")


@router.get("/presentation")
async def get_presentation():
    return store.get_presentation().model_dump()


@router.post("/presentation/active-slide")
async def set_active_slide(slide_id: str = Body(..., embed=True)):
    ok = store.set_active_slide(slide_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Slide not found")
    await store.broadcast({
        "type": "active_slide_changed",
        "active_slide_id": slide_id
    })
    return {"success": True, "active_slide_id": slide_id}


@router.get("/slide/{slide_id}/svg")
async def get_slide_svg(slide_id: str):
    pres = store.get_presentation()
    slide = pres.get_slide(slide_id)
    if not slide:
        raise HTTPException(status_code=404, detail="Slide not found")
    svg_code = SVGRenderer.render_slide(slide)
    return Response(content=svg_code, media_type="image/svg+xml")


@router.post("/action/undo")
async def undo_action():
    patch = store.undo()
    if patch:
        await store.broadcast({
            "type": "presentation_updated",
            "presentation": store.get_presentation().model_dump(),
            "patch": patch
        })
        return {"success": True, "patch": patch}
    return {"success": False, "message": "Nothing to undo"}


@router.post("/action/redo")
async def redo_action():
    patch = store.redo()
    if patch:
        await store.broadcast({
            "type": "presentation_updated",
            "presentation": store.get_presentation().model_dump(),
            "patch": patch
        })
        return {"success": True, "patch": patch}
    return {"success": False, "message": "Nothing to redo"}


@router.get("/history")
async def get_history():
    return {
        "history": store.history.get_summary(),
        "can_undo": store.history.can_undo(),
        "can_redo": store.history.can_redo()
    }


@router.post("/upload")
async def upload_pptx(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")

    content = await file.read()
    try:
        pres = store.import_pptx_bytes(content, file.filename)
        await store.broadcast({
            "type": "presentation_loaded",
            "presentation": pres.model_dump()
        })
        return {
            "success": True,
            "title": pres.title,
            "slides_count": len(pres.slides),
            "presentation": pres.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse PPTX: {str(e)}")


@router.get("/export")
async def export_pptx():
    try:
        data = store.export_pptx_bytes()
        pres = store.get_presentation()
        safe_filename = urllib.parse.quote(f"{pres.title or 'presentation'}.pptx")
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export PPTX: {str(e)}")


@router.get("/settings")
async def get_settings():
    return {
        "openai_base_url": settings.openai_base_url,
        "openai_api_key_set": bool(settings.openai_api_key),
        "default_model": settings.default_model,
        "reasoning_model": settings.reasoning_model,
        "vision_model": settings.vision_model,
        "fast_model": settings.fast_model,
        "enable_vision_loop": settings.enable_vision_loop,
    }


@router.post("/settings")
async def update_settings(payload: Dict[str, Any] = Body(...)):
    if "openai_base_url" in payload:
        settings.openai_base_url = payload["openai_base_url"]
    if "openai_api_key" in payload and payload["openai_api_key"]:
        settings.openai_api_key = payload["openai_api_key"]
    if "default_model" in payload:
        settings.default_model = payload["default_model"]
    if "reasoning_model" in payload:
        settings.reasoning_model = payload["reasoning_model"]
    if "vision_model" in payload:
        settings.vision_model = payload["vision_model"]
    if "fast_model" in payload:
        settings.fast_model = payload["fast_model"]
    if "enable_vision_loop" in payload:
        settings.enable_vision_loop = bool(payload["enable_vision_loop"])

    # Update runtime client
    store.agent_runtime.llm.base_url = settings.openai_base_url
    if settings.openai_api_key:
        store.agent_runtime.llm.api_key = settings.openai_api_key
    store.agent_runtime.llm.default_model = settings.default_model

    return {"success": True, "message": "Settings updated"}


@router.post("/chat")
async def chat_interaction(payload: Dict[str, Any] = Body(...)):
    prompt = payload.get("message", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Message is required")

    async def on_event(event):
        await store.broadcast(event)

    result = await store.agent_runtime.run_turn(
        user_message=prompt,
        pres=store.get_presentation(),
        history=store.history,
        on_event=on_event
    )

    # Broadcast updated presentation
    await store.broadcast({
        "type": "presentation_updated",
        "presentation": store.get_presentation().model_dump()
    })

    return result


# =====================================================================
# PPTSpec & LangGraph Generation API Endpoints (PR13)
# =====================================================================

from ..pptspec.prompt_template import get_general_prompt, get_strict_prompt
from ..pptspec.schema import CanonicalPPTSpec
from ..pptspec.normalizer import normalize_presentation_input
from ..pptspec.validator import validate_truthfulness
from ..pptspec.artifact import artifact_store
from ..agent.graphs.generation import generation_graph


@router.get("/pptspec/prompts/general")
async def api_get_general_prompt():
    """Return recommended general external-AI analysis prompt."""
    return {"prompt": get_general_prompt()}


@router.get("/pptspec/prompts/strict")
async def api_get_strict_prompt():
    """Return strict JSON prompt with dynamic CanonicalPPTSpec JSON schema attached."""
    return {"prompt": get_strict_prompt()}


@router.get("/pptspec/schema")
async def api_get_pptspec_schema():
    """Return internal CanonicalPPTSpec JSON Schema."""
    return CanonicalPPTSpec.model_json_schema()


@router.post("/pptspec/normalize")
async def api_normalize_pptspec(payload: Dict[str, Any] = Body(...)):
    """Flexible ingestion and normalization of external AI output.

    Caches valid artifacts server-side bound to session_id and returns
    a normalization_id to prevent client-side specification tampering.
    """
    raw_content = payload.get("content", "").strip()
    if not raw_content:
        raise HTTPException(status_code=400, detail="Input content cannot be empty")

    session_id = payload.get("session_id") or store.active_session_id
    llm_client = getattr(store.agent_runtime, "llm", None)

    norm_res = await normalize_presentation_input(
        raw_text=raw_content,
        llm_client=llm_client,
        strict_truthfulness=False,
    )

    norm_id = None
    if norm_res.valid and norm_res.spec is not None:
        artifact = artifact_store.save(
            session_id=session_id,
            raw_input=raw_content,
            spec=norm_res.spec,
            summary=norm_res.summary,
            asset_requirements=norm_res.asset_requirements,
            warnings=norm_res.warnings,
        )
        norm_id = artifact.id

    return {
        "valid": norm_res.valid,
        "normalization_id": norm_id,
        "spec": norm_res.spec.model_dump() if norm_res.spec else None,
        "warnings": norm_res.warnings,
        "errors": norm_res.errors,
        "summary": norm_res.summary,
        "asset_requirements": [r.model_dump() for r in norm_res.asset_requirements],
    }


@router.post("/pptspec/generate")
async def api_generate_from_pptspec(payload: Dict[str, Any] = Body(...)):
    """Orchestrates LangGraph PPT generation from a verified NormalizationArtifact."""
    norm_id = payload.get("normalization_id")
    if not norm_id:
        raise HTTPException(status_code=400, detail="normalization_id is required")

    session_id = payload.get("session_id") or store.active_session_id
    artifact = artifact_store.get(norm_id, include_expired=True)
    if not artifact:
        raise HTTPException(status_code=404, detail="ARTIFACT_NOT_FOUND: Normalization artifact not found.")

    if artifact.is_expired:
        artifact_store.delete(norm_id)
        raise HTTPException(status_code=410, detail="ARTIFACT_EXPIRED: Normalization artifact has expired.")

    if artifact.session_id != session_id:
        raise HTTPException(status_code=403, detail="ARTIFACT_SESSION_MISMATCH: Artifact does not belong to the requested session.")

    # Re-enforce Truthfulness Guard on server side before generation
    val_res = validate_truthfulness(artifact.raw_input, artifact.canonical_spec, strict=False)
    if not val_res.valid:
        raise HTTPException(
            status_code=422,
            detail=f"Truthfulness validation failed: {'; '.join(val_res.errors)}"
        )

    # Session binding
    session = store.session_manager.get_or_create(session_id)

    async def on_event(event: Dict[str, Any]):
        event["session_id"] = session_id
        await store.broadcast(event, session_id=session_id)

    initial_state = {
        "session_id": session_id,
        "raw_input": artifact.raw_input,
        "canonical_spec": artifact.canonical_spec,
        "mode": "generate",
        "max_repair_iterations": 3,
    }

    try:
        gen_result = await generation_graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "on_event": on_event,
                    "pres": session.pres,
                    "llm_client": getattr(store.agent_runtime, "llm", None),
                }
            },
        )
    except Exception as e:
        logger.exception("LangGraph generation execution error")
        raise HTTPException(status_code=500, detail=f"Generation pipeline error: {e}")

    if gen_result.get("error") or not gen_result.get("presentation_ir"):
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {gen_result.get('error') or 'Unknown generation error'}"
        )

    # Broadcast presentation state to all connected session clients
    await store.broadcast({
        "type": "presentation_loaded",
        "session_id": session_id,
        "presentation": session.pres.model_dump(),
        "active_slide_id": session.active_slide_id,
        "can_undo": session.history.can_undo(),
        "can_redo": session.history.can_redo(),
    }, session_id=session_id)

    return {
        "success": True,
        "session_id": session_id,
        "presentation": session.pres.model_dump(),
        "summary": artifact.summary,
        "asset_requirements": [r.model_dump() for r in artifact.asset_requirements],
    }
