"""REST API routes for PPT-Agent-Studio."""

from __future__ import annotations
import base64
import io
import json
import logging
import urllib.parse
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, UploadFile, File, Form, Response, HTTPException, Body, Query
from fastapi.responses import StreamingResponse

from ..state.store import store, create_default_demo_presentation
from ..ir.svg_renderer import SVGRenderer
from ..config import settings, AppSettings
from ..session.session import PPTSession
from ..agent.mutation_gateway import (
    DOCUMENT_EPOCH_MISMATCH,
    DOCUMENT_FROZEN,
    STALE_MUTATION,
    MutationGateway,
)
from ..protocol.presentation import build_canonical_snapshot, build_presentation_event
from ..workspace.runtime import get_workspace_manager
from .websocket import build_preview_update
from ..server.websocket import execute_direct_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _active_workspace_session_id() -> Optional[str]:
    manager = get_workspace_manager()
    if manager is None:
        return None
    return manager.last_active_session_id


def _resolve_session(session_id: Optional[str] = None) -> PPTSession:
    """Resolve session for REST operations.

    An explicit ``session_id`` must exist (else 404). When omitted, the request is
    bound to the workspace's ``last_active_session_id`` (S4/S5). There is no hidden
    "default" session in production: ``APP_ENV=test`` retains the legacy default
    purely so the pre-workspace test suite can bootstrap without a live workspace.
    """
    if session_id:
        sess = store.session_manager.get_session(session_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND: Session not found")
        return sess
    active = _active_workspace_session_id()
    if active:
        sess = store.session_manager.get_session(active)
        if sess is not None:
            return sess
    if settings.app_env == "test":
        return store.active_session
    raise HTTPException(status_code=400, detail="SESSION_ID_REQUIRED: session_id is required")


@router.get("/workspace/bootstrap")
async def workspace_bootstrap(hint: Optional[str] = Query(None)):
    """Sole cold-start authority: returns the session the workspace should open.

    The workspace's ``last_active_session_id`` wins; a browser ``hint`` is only an
    optimization. A brand-new workspace gets exactly one empty/demo session. The
    response carries a canonical snapshot so the frontend never has to assemble
    cold-start state itself.
    """
    manager = get_workspace_manager()
    if manager is None:
        session = store.active_session
        return {
            "session_id": session.session_id,
            "is_new": False,
            "interaction_mode": session.interaction_mode,
            "snapshot": build_canonical_snapshot(session),
            "sessions": [session.to_dict()],
        }

    session = None
    # Backend authority (S5): an established server-side active session always
    # wins. A browser ``hint`` is only a fallback when the workspace has no
    # pointer yet, and it must never move an already-established server pointer.
    workspace_active = manager.last_active_session_id
    if workspace_active:
        session = (
            store.session_manager.get_session(workspace_active)
            or await manager.restore_session(workspace_active)
        )
    if session is None and hint:
        session = (
            store.session_manager.get_session(hint)
            or await manager.restore_session(hint)
        )
    is_new = session is None
    if session is None:
        session = await manager.create_session(create_default_demo_presentation())
    else:
        await manager.activate(session.session_id)

    sessions = [
        store.session_manager.get_session(sid).to_dict()
        for sid in await manager.list_session_ids()
        if store.session_manager.get_session(sid) is not None
    ]
    return {
        "session_id": session.session_id,
        "is_new": is_new,
        "interaction_mode": session.interaction_mode,
        "snapshot": build_canonical_snapshot(session),
        "sessions": sessions,
    }


@router.get("/presentation")
async def get_presentation(session_id: Optional[str] = Query(None)):
    """Legacy raw IR. Do not use to correct canonical client state."""
    session = _resolve_session(session_id)
    return session.document.presentation.model_dump()


@router.get("/presentation/snapshot")
async def get_presentation_snapshot(session_id: Optional[str] = Query(None)):
    """Canonical document snapshot: the only shape the frontend may adopt."""
    session = _resolve_session(session_id)
    return build_canonical_snapshot(session)


@router.post("/presentation/active-slide")
async def preview_active_slide(
    slide_id: str = Body(..., embed=True),
    session_id: Optional[str] = Query(None),
):
    """Returns a preview of a slide for the REQUESTER only.

    Navigation is client-local UI state: this endpoint must never write the shared
    `PresentationIR.active_slide_id`, and must never broadcast an
    `active_slide_changed` event (which would drag other clients' views). The
    response is the same `preview_update` envelope the WebSocket returns.
    """
    session = _resolve_session(session_id)
    # `build_preview_update` falls back to the session active slide when the id is
    # unknown; pre-check so an unknown slide is an explicit 404.
    if not session.document.presentation.get_slide(slide_id):
        raise HTTPException(status_code=404, detail="Slide not found")
    preview = build_preview_update(session, slide_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Slide not found")
    return preview


@router.get("/slide/{slide_id}/svg")
async def get_slide_svg(slide_id: str, session_id: Optional[str] = Query(None)):
    session = _resolve_session(session_id)
    slide = session.document.presentation.get_slide(slide_id)
    if not slide:
        raise HTTPException(status_code=404, detail="Slide not found")
    svg_code = SVGRenderer.render_slide(slide)
    return Response(content=svg_code, media_type="image/svg+xml")


async def _run_history_action(
    session: PPTSession,
    action: str,
    *,
    mutation_id: Optional[str] = None,
    document_epoch: Optional[str] = None,
    expected_revision: Optional[int] = None,
) -> Dict[str, Any]:
    """Routes REST undo/redo through the MutationGateway (single writer + CAS)."""
    resolved_mutation_id = mutation_id or f"mut_{uuid.uuid4().hex[:10]}"
    batch = await MutationGateway.execute_tool_calls(
        [{"name": action, "arguments": {}, "id": f"call_{uuid.uuid4().hex[:6]}"}],
        session.document.presentation,
        session.history,
        session=session,
        bypass_confirmation=True,
        source="rest",
        mutation_id=resolved_mutation_id,
        document_epoch=document_epoch,
        expected_revision=expected_revision,
        require_stamps=True,
    )
    res = batch.first_result()
    if batch.error or (isinstance(res, dict) and res.get("error")):
        return {"success": False, "message": batch.error or res.get("error")}
    await store.broadcast({
        "type": "presentation_updated",
        "session_id": session.session_id,
        "presentation": session.document.presentation.model_dump(),
        "can_undo": session.history.can_undo(),
        "can_redo": session.history.can_redo(),
        "active_slide_id": session.active_slide_id,
        "last_target_id": session.document.last_target_id,
        "version": session.document.presentation.version,
        "document_epoch": getattr(session, "document_epoch", None),
        "last_mutation_id": resolved_mutation_id,
    }, session_id=session.session_id)
    return {
        "success": True,
        "patch": {"action": action},
        "message": res.get("message") if isinstance(res, dict) else None,
    }


@router.post("/action/undo")
async def undo_action(
    session_id: Optional[str] = Query(None),
    payload: Optional[Dict[str, Any]] = Body(None),
):
    body = payload or {}
    session = _resolve_session(session_id or body.get("session_id"))
    return await _run_history_action(
        session,
        "undo",
        mutation_id=body.get("mutation_id"),
        document_epoch=body.get("document_epoch"),
        expected_revision=body.get("expected_revision"),
    )


@router.post("/action/redo")
async def redo_action(
    session_id: Optional[str] = Query(None),
    payload: Optional[Dict[str, Any]] = Body(None),
):
    body = payload or {}
    session = _resolve_session(session_id or body.get("session_id"))
    return await _run_history_action(
        session,
        "redo",
        mutation_id=body.get("mutation_id"),
        document_epoch=body.get("document_epoch"),
        expected_revision=body.get("expected_revision"),
    )


@router.get("/history")
async def get_history(session_id: Optional[str] = Query(None)):
    session = _resolve_session(session_id)
    return {
        "history": session.history.get_summary(),
        "can_undo": session.history.can_undo(),
        "can_redo": session.history.can_redo()
    }


@router.post("/upload")
async def upload_pptx(
    file: UploadFile = File(...),
    session_id: Optional[str] = Query(None),
    expected_epoch: Optional[str] = Query(None),
    expected_revision: Optional[int] = Query(None),
):
    from ..security.budgets import (
        PayloadTooLarge,
        read_upload_bounded,
        validate_ooxml_zip_budget,
    )
    from ..security.upload_names import sanitize_upload_name

    safe_name = sanitize_upload_name(
        getattr(file, "filename", ""), fallback="imported.pptx"
    )
    if not safe_name.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx files are supported")

    # Replacement is a concurrency transaction: the caller MUST supply the epoch
    # and revision it actually observed. Fail closed BEFORE the (potentially slow)
    # file read, and never fall back to the server's current stamp — doing so
    # would reopen a "replace whatever is currently present" escape hatch.
    if expected_epoch is None or expected_revision is None:
        raise HTTPException(status_code=409, detail="MISSING_REPLACEMENT_STAMP")

    session = _resolve_session(session_id)
    try:
        content = await read_upload_bounded(
            file, max_bytes=int(settings.max_upload_file_bytes)
        )
    except PayloadTooLarge as exc:
        raise HTTPException(status_code=413, detail=f"{exc.code}: {exc}")
    if not content:
        raise HTTPException(status_code=400, detail="EMPTY_PPTX: uploaded file is empty")
    try:
        validate_ooxml_zip_budget(content)
    except PayloadTooLarge as exc:
        code = getattr(exc, "code", "INVALID_OOXML_ZIP")
        status = 413 if "TOO_LARGE" in code or "RATIO" in code or "ENTRIES" in code else 422
        raise HTTPException(status_code=status, detail=f"{code}: {exc}")
    try:
        # Parse outside the lock; commit with the caller's stamp so an import
        # cannot overwrite edits made while the file was being read or parsed.
        pres = store.parse_pptx_bytes(content, safe_name)
        result = await session.commit_replacement(
            pres,
            expected_epoch=expected_epoch,
            expected_revision=expected_revision,
            clear_history=True,
            clear_checkpoints=True,
            checkpoint_description=f"Imported from {safe_name}",
            source="rest",
        )
        if not result.committed:
            if result.error == DOCUMENT_FROZEN:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "DOCUMENT_FROZEN: 演示文稿正被 Agent 编辑，导入已被拒绝；"
                        "请等待 Agent 完成后再试。"
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "STALE_IMPORT: the document changed while the file was being "
                    "parsed; the import was discarded. Retry to replace the "
                    "current document."
                ),
            )
        await store.broadcast(
            build_presentation_event(
                session,
                "presentation_loaded",
                extra={"checkpoints_count": len(session.checkpoints)},
            ),
            session_id=session.session_id,
        )
        importer_used = pres.metadata.get("importer_used", "unknown")
        fallback_reason = pres.metadata.get("importer_fallback_reason")
        return {
            "success": True,
            "session_id": session.session_id,
            "title": pres.title,
            "slides_count": len(pres.slides),
            # Import provenance: "fidelity" is canonical; a fallback to the legacy
            # parser is surfaced instead of being a silent success.
            "importer": importer_used,
            "degraded": bool(fallback_reason),
            "fallback_reason": fallback_reason,
            "warnings": pres.metadata.get("parser_warnings", []),
            "capabilities": dict(pres.capabilities),
            **build_canonical_snapshot(session),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse PPTX: {str(e)}")


@router.get("/export/preflight")
async def export_preflight(session_id: Optional[str] = Query(None)):
    """Structured lossy/unsupported write-back warnings before an export happens."""
    session = _resolve_session(session_id)
    return {
        "session_id": session.session_id,
        "presentation_version": session.document.presentation.version,
        **store.export_preflight(pres=session.document.presentation),
    }


@router.get("/export")
async def export_pptx(
    session_id: Optional[str] = Query(None),
    # PR #28 Phase 1: fail closed on irreversible degradation. Callers must
    # pass allow_lossy=true explicitly after seeing /export/preflight.
    allow_lossy: bool = Query(False),
):
    session = _resolve_session(session_id)
    # Render from an immutable epoch/revision-pinned copy so a concurrent edit
    # cannot produce a file that mixes revisions.
    snapshot = await session.snapshot_for_export()
    pres = snapshot.presentation
    preflight = store.export_preflight(pres=pres)

    if preflight["has_lossy"] and not allow_lossy:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "lossy_export_requires_confirmation",
                "message": "此文档包含原生 Table，当前导出会将其转为普通图形（不可逆）。",
                **preflight,
            },
        )

    try:
        data = store.export_pptx_bytes(pres=pres, allow_lossy=allow_lossy)
        safe_filename = urllib.parse.quote(f"{pres.title or 'presentation'}.pptx")
        warning_header = json.dumps(
            {"warnings": preflight["warnings"], "lossy_features": preflight["lossy_features"]},
            ensure_ascii=True,
        )
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
                "X-Fidelity-Warnings": warning_header,
                "X-Export-Lossy": "true" if preflight["has_lossy"] else "false",
                "X-Document-Epoch": snapshot.document_epoch,
                "X-Document-Revision": str(snapshot.version),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to export PPTX: {str(e)}")


@router.post("/models")
async def list_models(payload: Dict[str, Any] = Body(default={})):
    """Fetches the model list from the OpenAI-compatible endpoint.

    Accepts optional base_url / api_key overrides so the UI can probe
    unsaved settings before persisting them.

    PR #28 Phase 0 hardening:
    - A custom ``base_url`` NEVER inherits the server-saved key. The saved
      key is attached only when the caller probes the configured default
      host (or omits base_url entirely).
    - Every target passes ``OutboundURLPolicy`` (scheme + literal-IP +
      all-A/AAAA-public checks, redirects disabled). The HTTP connection
      runs inside DNS pinning so a rebinding second-lookup cannot escape
      to loopback/private space.
    """
    import httpx

    from ..security.outbound import (
        OutboundURLPolicy,
        OutboundURLRejected,
        create_pinned_async_transport,
    )

    # PR #28 Strict Key Isolation:
    # If the payload explicitly provides a base_url, NEVER inherit the server-saved key.
    # The server key is ONLY attached when base_url is omitted (probing the configured endpoint).
    caller_base = (payload.get("base_url") or "").strip()
    caller_key = (payload.get("api_key") or "").strip()
    if caller_base:
        raw_base = caller_base
        api_key = caller_key  # strictly zero inheritance
    else:
        raw_base = settings.openai_base_url
        api_key = caller_key or settings.openai_api_key

    if not raw_base:
        raise HTTPException(status_code=400, detail="Base URL is required")

    try:
        normalized, validated_host, validated_ips = OutboundURLPolicy.validate(
            raw_base,
            trusted_hosts=settings.trusted_provider_host_set or None,
        )
    except OutboundURLRejected as exc:
        code = getattr(exc, "code", "OUTBOUND_REJECTED")
        if code in ("OUTBOUND_SSRF_BLOCKED", "OUTBOUND_HOST_NOT_TRUSTED"):
            raise HTTPException(status_code=403, detail=f"{code}: {exc}")
        raise HTTPException(status_code=400, detail=f"{code}: {exc}")

    base_url = normalized
    url = f"{base_url}/models"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        transport = (
            create_pinned_async_transport(validated_host, validated_ips)
            if validated_ips
            else None
        )
        async with httpx.AsyncClient(
            transport=transport, timeout=15.0, follow_redirects=False
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        # A redirect response with follow_redirects=False surfaces here as
        # 3xx: refuse to follow it (SSRF bypass) instead of chasing it.
        status = getattr(e.response, "status_code", 502)
        if 300 <= int(status) < 400:
            raise HTTPException(
                status_code=403,
                detail="OUTBOUND_REDIRECT_BLOCKED: provider 重定向被拒绝",
            )
        try:
            body = e.response.text[:300]
        except Exception:
            body = ""
        raise HTTPException(status_code=502, detail=f"端点返回错误 ({status}): {body}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"无法连接端点: {e}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取模型列表失败: {e}")

    raw = data
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("data")
        if entries is None:
            entries = raw.get("models", [])
    else:
        entries = []

    models: list[str] = []
    for entry in entries or []:
        if isinstance(entry, dict):
            model_id = entry.get("id") or entry.get("name") or entry.get("model")
        else:
            model_id = entry
        if model_id:
            models.append(str(model_id))

    return {"models": models, "base_url": base_url}


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
        "context_limit": settings.context_limit,
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
    if "context_limit" in payload and payload["context_limit"]:
        settings.context_limit = str(payload["context_limit"]).lower()

    # Update runtime client
    store.agent_runtime.llm.base_url = settings.openai_base_url
    if settings.openai_api_key:
        store.agent_runtime.llm.api_key = settings.openai_api_key
    store.agent_runtime.llm.default_model = settings.default_model

    return {"success": True, "message": "Settings updated"}


@router.post("/chat")
async def chat_interaction(
    payload: Dict[str, Any] = Body(...),
    session_id: Optional[str] = Query(None),
):
    prompt = payload.get("message", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="Message is required")

    sid = session_id or payload.get("session_id")
    session = _resolve_session(sid)
    confirmed_tool_ids = payload.get("confirmed_tool_ids") or []

    # A chat turn is mutation-bearing: it must declare the document identity the
    # client observed, or it could be interpreted against a deck it never saw.
    request_epoch = payload.get("document_epoch")
    request_revision = payload.get("base_revision", payload.get("expected_revision"))
    if request_epoch is None or request_revision is None:
        raise HTTPException(status_code=409, detail="MISSING_REQUEST_STAMP")

    async def on_event(event):
        event["session_id"] = session.session_id
        await store.broadcast(event, session_id=session.session_id)

    # The mutation lock is not held across the LLM turn; the MutationGateway
    # serializes only the actual mutations so GUI actions stay responsive.
    result = await store.agent_runtime.run_turn(
        user_message=prompt,
        pres=session.document.presentation,
        history=session.history,
        session=session,
        on_event=on_event,
        confirmed_tool_ids=confirmed_tool_ids,
        request_document_epoch=request_epoch,
        request_base_revision=request_revision,
        ui_context=payload.get("ui_context"),
    )

    # Broadcast canonical updated presentation
    await store.broadcast(
        build_presentation_event(session, "presentation_updated"),
        session_id=session.session_id,
    )

    if isinstance(result, dict):
        result.update(build_canonical_snapshot(session))
        return result
    return {"result": result, **build_canonical_snapshot(session)}


@router.get("/confirm/pending")
async def list_pending_confirmations(session_id: Optional[str] = Query(None)):
    """Lists pending low-confidence calls awaiting explicit user confirmation."""
    session = _resolve_session(session_id)
    return {
        "session_id": session.session_id,
        "presentation_version": session.document.presentation.version,
        "pending": list(session.confirmations.pending.values()),
    }


@router.post("/confirm")
async def confirm_pending_action(
    payload: Dict[str, Any] = Body(...),
    session_id: Optional[str] = Query(None),
):
    """Executes (or cancels) the ORIGINAL pending call after explicit confirmation."""
    call_id = payload.get("call_id")
    if not call_id:
        raise HTTPException(status_code=400, detail="call_id is required")

    sid = session_id or payload.get("session_id")
    session = _resolve_session(sid)
    decision = (payload.get("decision") or "confirm").lower()

    async def on_event(event):
        event["session_id"] = session.session_id
        await store.broadcast(event, session_id=session.session_id)

    # confirm_pending commits through the MutationGateway, which owns the session
    # lock; cancel is a simple dictionary pop.
    if decision == "cancel":
        result = await store.agent_runtime.cancel_pending(
            session, call_id, on_event=on_event
        )
    elif decision in ("confirm", "approve"):
        result = await store.agent_runtime.confirm_pending(
            session, call_id, on_event=on_event
        )
    else:
        raise HTTPException(status_code=400, detail="decision must be 'confirm' or 'cancel'")

    await store.broadcast({
        "type": "presentation_updated",
        "session_id": session.session_id,
        "presentation": session.document.presentation.model_dump(),
        "can_undo": session.history.can_undo(),
        "can_redo": session.history.can_redo(),
        "last_target_id": session.document.last_target_id,
    }, session_id=session.session_id)

    return result


@router.get("/plan/pending")
async def list_pending_plans(session_id: Optional[str] = Query(None)):
    """Lists plans awaiting explicit user approval (plan interaction mode)."""
    session = _resolve_session(session_id)
    return {
        "session_id": session.session_id,
        "presentation_version": session.document.presentation.version,
        "interaction_mode": session.interaction_mode,
        "pending": list(session.plan_confirmations.pending.values()),
    }


@router.post("/plan/confirm")
async def confirm_pending_plan(
    payload: Dict[str, Any] = Body(...),
    session_id: Optional[str] = Query(None),
):
    """Retired REST plan-confirmation endpoint (PR #28 Phase 1).

    Plan confirmation is WebSocket-only: only the socket holding the current
    ``connection_generation`` may confirm/cancel a frozen plan
    (``{"type": "confirm_plan"/"cancel_plan", "plan_id"}``). A transport-less
    REST call cannot prove newest-tab-wins ownership, so it is rejected
    instead of bypassing the authority check.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "PLAN_CONFIRM_REST_RETIRED: plan confirmation is WebSocket-only; "
            "send {\"type\": \"confirm_plan\"/\"cancel_plan\", \"plan_id\"} over "
            "the owning /ws connection."
        ),
    )


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

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

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

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

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

    # Session binding: the workspace is the sole cold-start authority, so a
    # generation target must already exist. (Legacy tests without a workspace
    # manager may still auto-create under APP_ENV=test.)
    session = store.session_manager.get_session(session_id)
    if session is None:
        if settings.app_env == "test":
            session = store.session_manager.get_or_create(session_id)
        else:
            raise HTTPException(
                status_code=404,
                detail="SESSION_NOT_FOUND: Generation target session does not exist",
            )

    # PR #28 Phase 1: strict caller-observed CAS. Whole-document replacement
    # must prove the caller saw the version it replaces; a server re-read
    # fallback would let a stale caller overwrite the current document.
    request_epoch = payload.get("expected_epoch")
    request_revision = payload.get("expected_revision")
    if not request_epoch or request_revision is None:
        raise HTTPException(status_code=409, detail="MISSING_REPLACEMENT_STAMP")
    base_epoch = request_epoch
    base_revision = request_revision

    async def on_event(event: Dict[str, Any]):
        event["session_id"] = session_id
        await store.broadcast(event, session_id=session_id)

    initial_state = {
        "session_id": session_id,
        "raw_input": artifact.raw_input,
        "canonical_spec": artifact.canonical_spec,
        "mode": "generate",
        "max_repair_iterations": 3,
        "base_document_epoch": base_epoch,
        "base_revision": base_revision,
    }

    try:
        # Lock is not held across the generation pipeline; the final persist rotates
        # the document epoch atomically.
        gen_result = await generation_graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "on_event": on_event,
                    "pres": session.document.presentation,
                    "llm_client": getattr(store.agent_runtime, "llm", None),
                }
            },
        )
    except Exception as e:
        logger.exception("LangGraph generation execution error")
        raise HTTPException(status_code=500, detail=f"Generation pipeline error: {e}")

    if gen_result.get("status") == "document_frozen":
        raise HTTPException(
            status_code=409,
            detail=(
                "DOCUMENT_FROZEN: 演示文稿正被 Agent 独占编辑，生成结果已丢弃；"
                "请等待 Agent 完成后再试。"
            ),
        )
    if gen_result.get("status") == "stale_generation":
        raise HTTPException(
            status_code=409,
            detail=(
                "STALE_GENERATION: the document was edited while generation was "
                "running; the generated result was discarded instead of "
                "overwriting your changes."
            ),
        )

    if gen_result.get("error") or not gen_result.get("presentation_ir"):
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {gen_result.get('error') or 'Unknown generation error'}"
        )

    # Broadcast canonical presentation state to all connected session clients
    await store.broadcast(
        build_presentation_event(
            session,
            "presentation_loaded",
            extra={"checkpoints_count": len(session.checkpoints)},
        ),
        session_id=session_id,
    )

    return {
        "success": True,
        "session_id": session_id,
        "summary": artifact.summary,
        "asset_requirements": [r.model_dump() for r in artifact.asset_requirements],
        **build_canonical_snapshot(session),
    }


@router.post("/paper/analyze")
async def analyze_paper(
    file: UploadFile = File(...),
    session_id: Optional[str] = Query(None),
    force: bool = Query(False),
):
    """Render + visually analyze an uploaded paper PDF (PaperIR + PaperVisualIR).

    This is the Phase 0-2 observable surface: it never generates a deck and never
    writes to a session's PresentationIR. Vision is optional: when unavailable the
    response still returns the rendered pages and the textual PaperIR with
    ``vision_model=null`` and a degradation warning.

    PR #28 Phase 0: the client filename NEVER touches the filesystem. The PDF
    is always written to a server-generated ``input.pdf``; the sanitized name
    survives only as display metadata.
    """
    from ..security.budgets import (
        PayloadTooLarge,
        get_pdf_page_count,
        read_upload_bounded,
        validate_pdf_page_budget,
        VisionWorkLimiter,
    )
    from ..security.upload_names import sanitize_upload_name

    safe_name = sanitize_upload_name(
        getattr(file, "filename", ""), fallback="upload.pdf"
    )
    if not safe_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are supported")
    if session_id:
        _resolve_session(session_id)

    try:
        content = await read_upload_bounded(
            file, max_bytes=int(settings.max_upload_file_bytes)
        )
    except PayloadTooLarge as exc:
        raise HTTPException(status_code=413, detail=f"{exc.code}: {exc}")
    if not content:
        raise HTTPException(status_code=400, detail="EMPTY_PDF: uploaded file is empty")

    # Page-count budget BEFORE full parse/raster/vision (canonical PDFium read).
    try:
        page_cnt = get_pdf_page_count(content)
        validate_pdf_page_budget(page_cnt)
    except PayloadTooLarge as exc:
        raise HTTPException(status_code=413, detail=f"{exc.code}: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PDF_UNREADABLE: {exc}")

    import tempfile
    from pathlib import Path as _Path

    from ..paper import extract_paper
    from ..paper_visual import (
        analyze_paper_visual,
        compute_analysis_fingerprint,
        load_or_render,
        load_visual_ir,
        resolve_vision_model,
        save_paper_ir,
        save_visual_ir,
    )
    from ..paper_visual.cache import crops_dir

    with tempfile.TemporaryDirectory() as tmp:
        # Fixed server-generated name: client input never forms a path.
        pdf_path = _Path(tmp) / "input.pdf"
        pdf_path.write_bytes(content)
        try:
            paper_ir = extract_paper(pdf_path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"PAPER_PARSE_FAILED: {exc}")

        try:
            async with VisionWorkLimiter.semaphore():
                try:
                    render_result, cache_dir = load_or_render(pdf_path, force=force)
                except Exception as exc:
                    raise HTTPException(status_code=422, detail=f"PAPER_RENDER_FAILED: {exc}")

                llm = getattr(store.agent_runtime, "llm", None)
                vision_model = resolve_vision_model(llm)
                expected_fingerprint = compute_analysis_fingerprint(vision_model)
                analysis_cache_hit = False
                visual_ir = None
                if not force:
                    cached = load_visual_ir(cache_dir, expected_fingerprint=expected_fingerprint)
                    if cached is not None and cached.source_sha256 == render_result.pdf_sha256:
                        visual_ir = cached
                        analysis_cache_hit = True
                # The on-disk name is always input.pdf; restore the sanitized client
                # name purely as display metadata (never a path).
                try:
                    paper_ir.source_filename = safe_name
                except Exception:
                    pass
                if visual_ir is None:
                    visual_ir = await analyze_paper_visual(
                        paper_ir,
                        render_result.assets,
                        llm_client=llm,
                        crop_output_dir=str(crops_dir(cache_dir)),
                        source_sha256=render_result.pdf_sha256,
                    )
                    save_visual_ir(visual_ir, cache_dir)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"PAPER_ANALYSIS_FAILED: {exc}")
        try:
            visual_ir.source_filename = safe_name
        except Exception:
            pass
        save_paper_ir(paper_ir, cache_dir)

    return {
        "success": True,
        "source_filename": paper_ir.source_filename,
        "pdf_sha256": render_result.pdf_sha256,
        "cache_key": cache_dir.name,
        "cache_hit": render_result.cache_hit,
        "analysis_cache_hit": analysis_cache_hit,
        "page_count": render_result.page_count,
        "vision_model": visual_ir.vision_model,
        "analysis_version": visual_ir.analysis_version,
        "pages": [asset.model_dump(mode="json") for asset in render_result.assets],
        "paper_ir": paper_ir.model_dump(mode="json"),
        "paper_visual_ir": visual_ir.model_dump(mode="json"),
        "warnings": list(render_result.warnings) + list(visual_ir.warnings),
    }


@router.post("/paper/generate")
async def api_generate_from_paper(payload: Dict[str, Any] = Body(...)):
    """Generate a deck from an analyzed paper via a trusted cache capability handle.

    The request carries only ``session_id`` + ``cache_key`` (as returned by
    ``/api/paper/analyze``). The server reloads ``PaperIR`` and ``PaperVisualIR``
    from ``output/paper_cache/{cache_key}`` and re-canonicalizes every asset path
    against that root; clients can never submit a server filesystem path.

    Runs the LLM-native paper -> PPT pipeline (art direction -> free-form per-slide
    layouts -> aesthetic refinement -> PresentationIR) and persists through the
    generation graph's CAS ``commit_replacement`` (epoch rotation).
    """
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    cache_key = payload.get("cache_key")
    if not cache_key:
        raise HTTPException(
            status_code=400,
            detail="cache_key is required (analyze the PDF via /api/paper/analyze first)",
        )

    from ..paper_visual import (
        PaperCacheError,
        canonicalize_visual_ir,
        compute_analysis_fingerprint,
        load_paper_ir,
        load_visual_ir,
        resolve_cache_dir,
        resolve_vision_model,
    )

    try:
        cache_dir = resolve_cache_dir(cache_key)
    except PaperCacheError as exc:
        raise HTTPException(status_code=422, detail=f"INVALID_CACHE_KEY: {exc}")

    paper_ir = load_paper_ir(cache_dir)
    if paper_ir is None:
        raise HTTPException(
            status_code=422,
            detail="PAPER_IR_NOT_CACHED: cache_key has no paper_ir.json",
        )

    expected_fingerprint = compute_analysis_fingerprint(
        resolve_vision_model(getattr(store.agent_runtime, "llm", None))
    )
    paper_visual_ir = load_visual_ir(cache_dir, expected_fingerprint=expected_fingerprint)
    if paper_visual_ir is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "PAPER_VISUAL_IR_STALE: cache_key has no paper_visual_ir.json for the "
                "current vision model / analysis version; re-run /api/paper/analyze"
            ),
        )
    try:
        paper_visual_ir = canonicalize_visual_ir(paper_visual_ir, cache_dir)
    except PaperCacheError as exc:
        raise HTTPException(status_code=422, detail=f"INVALID_VISUAL_ASSET_PATH: {exc}")

    user_prompt = str(payload.get("user_prompt") or "")
    try:
        duration_minutes = int(payload.get("duration_minutes") or 15)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="duration_minutes must be an integer")
    duration_minutes = max(1, duration_minutes)

    session = _resolve_session(session_id)
    # PR #28 Phase 1: strict caller-observed CAS (same as /upload). A stale
    # caller must prove it saw the replaced version; no server re-read fallback.
    request_epoch = payload.get("expected_epoch")
    request_revision = payload.get("expected_revision")
    if not request_epoch or request_revision is None:
        raise HTTPException(status_code=409, detail="MISSING_REPLACEMENT_STAMP")
    base_epoch = request_epoch
    base_revision = request_revision

    async def on_event(event: Dict[str, Any]):
        event["session_id"] = session_id
        await store.broadcast(event, session_id=session_id)

    initial_state = {
        "session_id": session_id,
        "source_type": "paper",
        "mode": "generate",
        "paper_ir": paper_ir,
        "paper_visual_ir": paper_visual_ir,
        "paper_cache_dir": str(cache_dir),
        "user_prompt": user_prompt,
        "duration_minutes": duration_minutes,
        "max_repair_iterations": 2,
        "base_document_epoch": base_epoch,
        "base_revision": base_revision,
    }

    try:
        gen_result = await generation_graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "on_event": on_event,
                    "llm_client": getattr(store.agent_runtime, "llm", None),
                }
            },
        )
    except Exception as e:
        logger.exception("Paper generation pipeline error")
        raise HTTPException(status_code=500, detail=f"Paper generation error: {e}")

    if gen_result.get("status") == "document_frozen":
        raise HTTPException(
            status_code=409,
            detail=(
                "DOCUMENT_FROZEN: 演示文稿正被 Agent 独占编辑，生成结果已丢弃；"
                "请等待 Agent 完成后再试。"
            ),
        )
    if gen_result.get("status") == "stale_generation":
        raise HTTPException(
            status_code=409,
            detail=(
                "STALE_GENERATION: the document was edited while generation was "
                "running; the generated result was discarded instead of overwriting "
                "your changes."
            ),
        )

    if gen_result.get("status") == "validation_failed":
        raise HTTPException(
            status_code=422,
            detail=f"PAPER_VALIDATION_FAILED: {gen_result.get('error') or 'paper plan failed validation'}",
        )

    if gen_result.get("error") or not gen_result.get("presentation_ir"):
        raise HTTPException(
            status_code=500,
            detail=f"Paper generation failed: {gen_result.get('error') or 'Unknown error'}",
        )

    await store.broadcast(
        build_presentation_event(
            session,
            "presentation_loaded",
            extra={"checkpoints_count": len(session.checkpoints)},
        ),
        session_id=session_id,
    )

    presentation_ir = gen_result["presentation_ir"]
    return {
        "success": True,
        "session_id": session_id,
        "source_filename": paper_ir.source_filename,
        "page_count": paper_ir.metadata.page_count,
        "slide_count": len(presentation_ir.slides),
        "generation": presentation_ir.metadata.get("generation", {}),
        **build_canonical_snapshot(session),
    }


_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".heic": "image/heic",
}


def _mime_for_image(filename: str, content_type: Optional[str]) -> str:
    if content_type and content_type.startswith("image/"):
        return content_type
    import os as _os

    return _IMAGE_MIME_BY_EXT.get(_os.path.splitext(filename or "")[1].lower(), "image/png")


def _as_upload_file(name: str, content_type: Optional[str], content: bytes) -> UploadFile:
    from starlette.datastructures import UploadFile as StarletteUploadFile

    return StarletteUploadFile(file=io.BytesIO(content), filename=name)


@router.post("/chat/drive")
async def chat_with_attachments(
    message: str = Form(""),
    session_id: str = Form(""),
    expected_epoch: Optional[str] = Form(None),
    expected_revision: Optional[int] = Form(None),
    ui_context: str = Form(""),
    request_id: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
):
    """Unified entry point for chat messages that carry attachments.

    The user's natural-language message selects how each attachment is used
    (paper -> deck, pptx -> import, image -> insert, text -> source material).
    Only the dispatch happens here; every action reuses the same tested pipeline
    as its dedicated REST endpoint.

    PR #28 Phase 2: this route is the single durable turn owner. Every branch
    commits a structured UserTurn+AssistantTurn (provenance only, never binary)
    under ``conversation_lock``; failures never write fake assistant success.
    Mutating actions require 100% disposition (fail-closed, no silent drops).
    """
    import hashlib
    import asyncio
    import json
    import time

    from ..agent.attachment_router import (
        ACTION_CHAT,
        ACTION_IMAGE,
        ACTION_IMPORT,
        ACTION_PAPER,
        ACTION_TEXT,
        KIND_IMAGE,
        KIND_PDF,
        KIND_PPTX,
        KIND_TEXT,
        build_disposition_plan,
        classify_intent,
        detect_kind,
        disposition_all_consumed,
        unprocessed_attachments,
    )
    from ..security.budgets import PayloadTooLarge, read_upload_bounded
    from ..security.upload_names import sanitize_upload_name

    session = _resolve_session(session_id or None)

    # ---- Bounded ingestion (before any parse/raster/vision) ----
    max_single = int(settings.max_upload_file_bytes)
    max_total = int(settings.max_total_attachment_bytes)
    max_count = int(settings.max_attachment_count)
    incoming = [u for u in (files or []) if u is not None]
    if len(incoming) > max_count:
        raise HTTPException(
            status_code=413,
            detail=f"TOO_MANY_ATTACHMENTS: 最多 {max_count} 个附件",
        )
    attachments: List[Dict[str, Any]] = []
    total_bytes = 0
    for idx, upload in enumerate(incoming):
        safe = sanitize_upload_name(getattr(upload, "filename", ""), fallback=f"attachment_{idx}")
        try:
            content = await read_upload_bounded(upload, max_bytes=max_single)
        except PayloadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"{exc.code}: {exc}")
        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"EMPTY_ATTACHMENT: 附件《{safe}》内容为空 (0 字节)",
            )
        total_bytes += len(content)
        if total_bytes > max_total:
            raise HTTPException(
                status_code=413,
                detail=f"TOTAL_ATTACHMENTS_TOO_LARGE: 附件总和超过 {max_total} 字节上限",
            )
        attachments.append(
            {
                "attachment_id": f"att_{idx}",
                "name": safe,
                "content_type": upload.content_type,
                "content": content,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "kind": detect_kind(safe, upload.content_type),
            }
        )

    kinds = [a["kind"] for a in attachments]

    # ---- Gate B: Request-level idempotency fingerprint & admission ----
    import json
    parsed_ui_obj = None
    if ui_context:
        try:
            parsed_ui_obj = json.loads(ui_context)
        except Exception:
            parsed_ui_obj = None
    canonical_ui_str = (
        json.dumps(parsed_ui_obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if parsed_ui_obj is not None
        else ""
    )
    attachment_records = [
        {
            "index": idx,
            "name": a.get("name"),
            "kind": a.get("kind"),
            "content_type": a.get("content_type"),
            "size_bytes": a.get("size_bytes"),
            "sha256": a.get("sha256"),
        }
        for idx, a in enumerate(attachments)
    ]
    raw_fp_payload = {
        "message": (message or "").strip(),
        "attachments": attachment_records,
        "expected_epoch": (expected_epoch or "").strip(),
        "expected_revision": expected_revision,
        "ui_context": canonical_ui_str,
    }
    req_fingerprint = hashlib.sha256(
        json.dumps(raw_fp_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    from ..session.session import RequestOutcome, RequestExecution

    is_first_executor = False
    is_recovery_executor = False
    execution_fut: Optional[asyncio.Future] = None
    admitted_generation = session.conversation_generation

    if request_id:
        async with session.request_journal_lock:
            cached_record = session.get_completed_request(request_id)
            if cached_record is not None:
                if cached_record.fingerprint != req_fingerprint:
                    raise HTTPException(status_code=409, detail="REQUEST_ID_PAYLOAD_MISMATCH")
                if cached_record.durable:
                    return cached_record.response
                # Commit-uncertain recovery: record exists in memory but not yet confirmed durable
                in_flight = session.in_flight_requests.get(request_id)
                if in_flight is not None:
                    if in_flight.fingerprint != req_fingerprint:
                        raise HTTPException(status_code=409, detail="REQUEST_ID_PAYLOAD_MISMATCH")
                    execution_fut = in_flight.future
                else:
                    loop = asyncio.get_running_loop()
                    fut: asyncio.Future[RequestOutcome] = loop.create_future()
                    execution_fut = fut
                    session.in_flight_requests[request_id] = RequestExecution(
                        fingerprint=req_fingerprint,
                        future=fut,
                        admitted_generation=cached_record.admitted_generation,
                    )
                    is_recovery_executor = True

            if not is_recovery_executor and cached_record is None:
                # Check short-lived failed requests cache
                now = time.monotonic()
                failed_rec = session.failed_requests.get(request_id)
                if (
                    failed_rec is not None
                    and failed_rec.conversation_generation == session.conversation_generation
                    and failed_rec.expire_at > now
                ):
                    if failed_rec.fingerprint != req_fingerprint:
                        raise HTTPException(status_code=409, detail="REQUEST_ID_PAYLOAD_MISMATCH")
                    outcome = failed_rec.outcome
                    raise HTTPException(status_code=outcome.status_code or 500, detail=outcome.detail)

                in_flight = session.in_flight_requests.get(request_id)
                if in_flight is not None:
                    if in_flight.fingerprint != req_fingerprint:
                        raise HTTPException(status_code=409, detail="REQUEST_ID_PAYLOAD_MISMATCH")
                    execution_fut = in_flight.future
                else:
                    loop = asyncio.get_running_loop()
                    fut = loop.create_future()
                    execution_fut = fut
                    session.in_flight_requests[request_id] = RequestExecution(
                        fingerprint=req_fingerprint,
                        future=fut,
                        admitted_generation=admitted_generation,
                    )
                    is_first_executor = True

    if request_id and not is_first_executor and not is_recovery_executor and execution_fut is not None:
        # Wait for first executor or recovery executor to complete
        outcome = await execution_fut
        if not outcome.ok:
            raise HTTPException(status_code=outcome.status_code or 500, detail=outcome.detail)
        return outcome.response

    if is_recovery_executor:
        # Single-flight durability recovery for commit-uncertain completed request
        manager = get_workspace_manager()
        persist_error = False
        if manager is not None:
            try:
                await manager.persist_session_now(session.session_id)
            except Exception as exc:
                logger.warning("Durability recovery flush failed for %s: %s", request_id, exc)
                persist_error = True

        async with session.request_journal_lock:
            cached_rec = session.get_completed_request(request_id)
            if cached_rec is None or session.conversation_generation != cached_rec.admitted_generation:
                reset_outcome = RequestOutcome(
                    ok=False,
                    status_code=409,
                    detail="CONVERSATION_RESET_DURING_REQUEST",
                )
                session.record_failed_request(request_id, req_fingerprint, reset_outcome)
                session.in_flight_requests.pop(request_id, None)
                if execution_fut is not None and not execution_fut.done():
                    execution_fut.set_result(reset_outcome)
                raise HTTPException(status_code=409, detail="CONVERSATION_RESET_DURING_REQUEST")

            if persist_error:
                fail_outcome = RequestOutcome(
                    ok=False,
                    status_code=503,
                    detail="REQUEST_COMMITTED_PERSISTENCE_FAILED",
                )
                session.record_failed_request(request_id, req_fingerprint, fail_outcome)
                session.in_flight_requests.pop(request_id, None)
                if execution_fut is not None and not execution_fut.done():
                    execution_fut.set_result(fail_outcome)
                raise HTTPException(status_code=503, detail="REQUEST_COMMITTED_PERSISTENCE_FAILED")

            cached_rec.durable = True
            succ_outcome = RequestOutcome(ok=True, response=cached_rec.response)
            session.in_flight_requests.pop(request_id, None)
            if execution_fut is not None and not execution_fut.done():
                execution_fut.set_result(succ_outcome)
            return cached_rec.response

    try:
        res = await _execute_chat_drive(
            session=session,
            message=message,
            files=files,
            attachments=attachments,
            kinds=kinds,
            ui_context=ui_context,
            expected_epoch=expected_epoch,
            expected_revision=expected_revision,
            request_id=request_id,
            req_fingerprint=req_fingerprint,
            admitted_generation=admitted_generation,
        )
        if request_id and is_first_executor and execution_fut is not None:
            # Build compact canonical replay response to guarantee bounded journal size
            # Exact canonical turn is preserved without modification or truncation!
            compact_res = {
                "success": res.get("success", True),
                "action": res.get("action"),
                "session_id": session.session_id,
                "message": res.get("message"),
                "turn": res.get("turn"),
                "dispositions": res.get("dispositions"),
                "document_epoch": res.get("document_epoch") or session.document_epoch,
                "version": res.get("version") or session.document.presentation.version,
                "active_slide_id": res.get("active_slide_id") or session.active_slide_id,
                "source_filename": res.get("source_filename"),
                "page_count": res.get("page_count"),
                "summary": res.get("summary"),
            }
            # Strip None values
            compact_res = {k: v for k, v in compact_res.items() if v is not None}

            # Generation Fence 1
            reset_detected = False
            async with session.request_journal_lock:
                if session.conversation_generation != admitted_generation:
                    reset_detected = True
                    reset_outcome = RequestOutcome(
                        ok=False,
                        status_code=409,
                        detail="CONVERSATION_RESET_DURING_REQUEST",
                    )
                    session.record_failed_request(request_id, req_fingerprint, reset_outcome)
                    session.in_flight_requests.pop(request_id, None)
                    execution_fut.set_result(reset_outcome)
                else:
                    session.record_completed_request(
                        request_id=request_id,
                        fingerprint=req_fingerprint,
                        response=compact_res,
                        admitted_generation=admitted_generation,
                        durable=False,
                        schedule_persist=False,
                    )

            if reset_detected:
                raise HTTPException(status_code=409, detail="CONVERSATION_RESET_DURING_REQUEST")

            # Durable flush before success
            manager = get_workspace_manager()
            persist_failed = False
            if manager is not None:
                try:
                    await manager.persist_session_now(session.session_id)
                except Exception as exc:
                    logger.error("Durable persist_session_now failed for %s: %s", request_id, exc)
                    persist_failed = True

            # Generation Fence 2 & Terminalization
            async with session.request_journal_lock:
                if session.conversation_generation != admitted_generation:
                    reset_outcome = RequestOutcome(
                        ok=False,
                        status_code=409,
                        detail="CONVERSATION_RESET_DURING_REQUEST",
                    )
                    session.record_failed_request(request_id, req_fingerprint, reset_outcome)
                    session.in_flight_requests.pop(request_id, None)
                    execution_fut.set_result(reset_outcome)
                    raise HTTPException(status_code=409, detail="CONVERSATION_RESET_DURING_REQUEST")

                if persist_failed:
                    fail_outcome = RequestOutcome(
                        ok=False,
                        status_code=503,
                        detail="REQUEST_COMMITTED_PERSISTENCE_FAILED",
                    )
                    session.record_failed_request(request_id, req_fingerprint, fail_outcome)
                    session.in_flight_requests.pop(request_id, None)
                    execution_fut.set_result(fail_outcome)
                    raise HTTPException(status_code=503, detail="REQUEST_COMMITTED_PERSISTENCE_FAILED")

                rec = session.get_completed_request(request_id)
                if rec is not None:
                    rec.durable = True
                succ_outcome = RequestOutcome(ok=True, response=compact_res)
                session.in_flight_requests.pop(request_id, None)
                execution_fut.set_result(succ_outcome)
        return res
    except HTTPException as exc:
        if request_id and is_first_executor and execution_fut is not None:
            fail_outcome = RequestOutcome(ok=False, status_code=exc.status_code, detail=exc.detail)
            async with session.request_journal_lock:
                session.record_failed_request(request_id, req_fingerprint, fail_outcome)
                session.in_flight_requests.pop(request_id, None)
                if not execution_fut.done():
                    execution_fut.set_result(fail_outcome)
        raise
    except Exception as exc:
        if request_id and is_first_executor and execution_fut is not None:
            fail_outcome = RequestOutcome(ok=False, status_code=500, detail=str(exc))
            async with session.request_journal_lock:
                session.record_failed_request(request_id, req_fingerprint, fail_outcome)
                session.in_flight_requests.pop(request_id, None)
                if not execution_fut.done():
                    execution_fut.set_result(fail_outcome)
        raise


async def _execute_chat_drive(
    session: Any,
    message: str,
    files: Optional[List[UploadFile]],
    attachments: List[Dict[str, Any]],
    kinds: List[str],
    ui_context: Optional[str],
    expected_epoch: Optional[str],
    expected_revision: Optional[int],
    request_id: Optional[str],
    req_fingerprint: str,
    admitted_generation: int,
) -> Dict[str, Any]:
    from ..agent.attachment_router import (
        ACTION_CHAT,
        ACTION_IMAGE,
        ACTION_IMPORT,
        ACTION_PAPER,
        ACTION_TEXT,
        KIND_IMAGE,
        KIND_PDF,
        KIND_PPTX,
        KIND_TEXT,
        build_disposition_plan,
        classify_intent,
        detect_kind,
        disposition_all_consumed,
        unprocessed_attachments,
        AttachmentParseError,
    )

    action = await classify_intent(getattr(store.agent_runtime, "llm", None), message, kinds)

    # Explicit disposition: every attachment gets consume/unsupported/unused.
    # Mutating actions proceed ONLY when 100% are consumed.
    disposition_plan = build_disposition_plan(attachments, action)
    if action in (ACTION_PAPER, ACTION_IMPORT, ACTION_TEXT, ACTION_IMAGE):
        # Preserve specific missing-kind errors (clearer than generic
        # UNPROCESSED) when the required kind is entirely absent.
        _required = {
            ACTION_PAPER: (KIND_PDF, "PDF_REQUIRED_FOR_PAPER"),
            ACTION_IMPORT: (KIND_PPTX, "PPTX_REQUIRED_FOR_IMPORT"),
            ACTION_TEXT: (KIND_TEXT, "TEXT_REQUIRED_FOR_GENERATION"),
            ACTION_IMAGE: (KIND_IMAGE, "IMAGE_REQUIRED_FOR_INSERT"),
        }.get(action)
        if _required is not None and _required[0] not in kinds:
            raise HTTPException(status_code=400, detail=_required[1])
        if not disposition_all_consumed(disposition_plan):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "UNPROCESSED_ATTACHMENTS",
                    "message": "部分附件未被消费，已拒绝执行以避免静默丢文件",
                    "action": action,
                    "dispositions": disposition_plan,
                    "unprocessed": unprocessed_attachments(disposition_plan),
                },
            )

    # A single immutable request stamp is frozen BEFORE dispatch and shared by
    # every mutating action (paper/import/text/image). Preprocessing (PDF vision,
    # normalization) may take a while; the eventual commit must still CAS against
    # the revision the user actually observed, never a freshly re-read one.
    request_epoch = (expected_epoch or "").strip()
    request_revision = expected_revision

    if action in (ACTION_PAPER, ACTION_IMPORT, ACTION_TEXT, ACTION_IMAGE):
        if not request_epoch or request_revision is None:
            raise HTTPException(status_code=409, detail="MISSING_REPLACEMENT_STAMP")

    async def _commit_turn(
        turn_action: str,
        assistant_summary: str,
        provenance: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Atomically appends UserTurn+AssistantTurn (provenance only, idempotent)."""
        user_brief = (message or "").strip()[:500] or "（附件操作）"
        prov_lines = "; ".join(
            f"{p.get('name')}[{p.get('kind')},{p.get('size_bytes')}B]"
            for p in provenance
        )
        user_content = f"[{turn_action}] {user_brief}"
        if prov_lines:
            user_content += f"（附件: {prov_lines[:1000]}）"
        try:
            return await session.commit_conversation_turn(
                request_id=request_id or "",
                user_content=user_content,
                assistant_content=assistant_summary[:2000],
                provenance=provenance,
                admitted_generation=admitted_generation,
            )
        except RuntimeError as exc:
            if "CONVERSATION_RESET_DURING_REQUEST" in str(exc):
                raise HTTPException(status_code=409, detail="CONVERSATION_RESET_DURING_REQUEST")
            raise

    def _provenance_for(action_name: str, status: str = "consumed") -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for a in attachments:
            out.append({
                "name": a.get("name"),
                "kind": a.get("kind"),
                "sha256": a.get("sha256"),
                "size_bytes": a.get("size_bytes"),
                "action": action_name,
                "status": status,
            })
        return out

    # The requesting client's UI context is parsed exactly once and shared by
    # every action. It carries the client-local active slide (slide navigation
    # is client-owned), which the image path must honor instead of the possibly
    # stale server-side session cursor.
    from ..agent.uicontext import UIContext

    try:
        parsed_ui = json.loads(ui_context) if ui_context else None
    except (TypeError, ValueError):
        parsed_ui = None
    ui = UIContext.from_any(parsed_ui)

    if action == ACTION_CHAT:
        from ..agent.attachment_context import build_attachment_context

        async def _analyze_pdf(name: str, content_type: Optional[str], content: bytes):
            return await analyze_paper(
                file=_as_upload_file(name, content_type, content),
                session_id=session.session_id,
                force=False,
            )

        try:
            attachment_context = await build_attachment_context(
                attachments,
                ui_context=ui,
                analyze_pdf=_analyze_pdf,
                parse_pptx=store.parse_pptx_bytes,
            )
        except AttachmentParseError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": exc.code, "message": exc.message},
            )

        # Capability boundary: a request that carries attachments but produces NO
        # model-readable context (every kind is UNKNOWN) must fail closed instead
        # of silently answering from the user text alone. Otherwise the model can
        # fabricate an answer about a file it never actually received.
        if attachments and attachment_context.is_empty():
            raise HTTPException(
                status_code=415,
                detail="UNSUPPORTED_ATTACHMENT_TYPE: 附件格式不受支持，无法读取其中的内容",
            )

        async def _on_chat_event(ev: Dict[str, Any]):
            ev.setdefault("session_id", session.session_id)
            await store.broadcast(ev, session_id=session.session_id)

        result = await store.agent_runtime.chat_with_attachments(
            session,
            message,
            attachment_context,
            ui_context=ui,
            on_event=_on_chat_event,
        )
        # PR #28 Phase 2: inference failure is 502, never success:true.
        if isinstance(result, dict) and result.get("error") == "LLM_PROVIDER_ERROR":
            raise HTTPException(
                status_code=502,
                detail=f"LLM_PROVIDER_ERROR: 附件问答的模型推理失败：{result.get('detail') or 'unknown'}",
            )
        turn_dto = await _commit_turn(
            ACTION_CHAT,
            result.get("reply", ""),
            _provenance_for(ACTION_CHAT),
        )
        return {
            "success": True,
            "action": ACTION_CHAT,
            "session_id": session.session_id,
            "message": result.get("reply", ""),
            "turn": turn_dto,
            "dispositions": disposition_plan,
        }

    def _first(kind: str) -> Optional[Dict[str, Any]]:
        return next((a for a in attachments if a["kind"] == kind), None)

    if action == ACTION_PAPER:
        target = _first(KIND_PDF)
        if target is None:
            raise HTTPException(status_code=400, detail="PDF_REQUIRED_FOR_PAPER")
        # Long-running work runs WITHOUT holding conversation_lock (Phase 2);
        # the transcript is committed atomically only after success.
        analysis = await analyze_paper(
            file=_as_upload_file(target["name"], target["content_type"], target["content"]),
            session_id=session.session_id,
            force=False,
        )
        generated = await api_generate_from_paper(
            payload={
                "session_id": session.session_id,
                "cache_key": analysis["cache_key"],
                "user_prompt": message,
                "expected_epoch": request_epoch,
                "expected_revision": request_revision,
            }
        )
        turn_dto = await _commit_turn(
            ACTION_PAPER,
            f"已根据论文《{analysis.get('source_filename')}》"
            f"（共 {analysis.get('page_count')} 页）生成演示文稿",
            _provenance_for(ACTION_PAPER),
        )
        return {
            "success": True,
            "action": ACTION_PAPER,
            "session_id": session.session_id,
            "source_filename": analysis.get("source_filename"),
            "page_count": analysis.get("page_count"),
            "turn": turn_dto,
            "dispositions": disposition_plan,
            **generated,
        }

    if action == ACTION_IMPORT:
        target = _first(KIND_PPTX)
        if target is None:
            raise HTTPException(status_code=400, detail="PPTX_REQUIRED_FOR_IMPORT")
        # Defense-in-depth: the importer only reads OOXML .pptx. A legacy .ppt /
        # macro .pptm (or an OOXML MIME with a legacy name) must fail with a clear
        # contract error rather than a confusing capability mismatch.
        if not (target.get("name") or "").lower().endswith(".pptx"):
            raise HTTPException(
                status_code=400,
                detail="UNSUPPORTED_PPTX_FORMAT: 仅支持 .pptx 文件",
            )
        imported = await upload_pptx(
            file=_as_upload_file(target["name"], target["content_type"], target["content"]),
            session_id=session.session_id,
            expected_epoch=request_epoch,
            expected_revision=request_revision,
        )
        turn_dto = await _commit_turn(
            ACTION_IMPORT,
            f"已导入 PPTX《{target.get('name')}》并替换当前文档",
            _provenance_for(ACTION_IMPORT),
        )
        return {
            "action": ACTION_IMPORT,
            "turn": turn_dto,
            "dispositions": disposition_plan,
            **imported,
        }

    if action == ACTION_TEXT:
        target = _first(KIND_TEXT)
        if target is None:
            raise HTTPException(status_code=400, detail="TEXT_REQUIRED_FOR_GENERATION")
        try:
            raw_text = target["content"].decode("utf-8")
        except UnicodeDecodeError:
            raw_text = target["content"].decode("utf-8", errors="replace")
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="EMPTY_TEXT_ATTACHMENT")
        normalized = await api_normalize_pptspec(
            payload={"content": raw_text, "session_id": session.session_id}
        )
        normalization_id = normalized.get("normalization_id")
        if not normalized.get("valid") or not normalization_id:
            errors = "; ".join(normalized.get("errors") or []) or "normalization produced no artifact"
            raise HTTPException(
                status_code=422, detail=f"TEXT_NORMALIZATION_FAILED: {errors}"
            )
        generated = await api_generate_from_pptspec(
            payload={
                "normalization_id": normalization_id,
                "session_id": session.session_id,
                "expected_epoch": request_epoch,
                "expected_revision": request_revision,
            }
        )
        turn_dto = await _commit_turn(
            ACTION_TEXT,
            f"已根据文本附件《{target.get('name')}》生成演示文稿",
            _provenance_for(ACTION_TEXT),
        )
        return {
            "success": True,
            "action": ACTION_TEXT,
            "session_id": session.session_id,
            "summary": normalized.get("summary"),
            "warnings": normalized.get("warnings") or [],
            "turn": turn_dto,
            "dispositions": disposition_plan,
            **generated,
        }

    if action == ACTION_IMAGE:
        target = _first(KIND_IMAGE)
        if target is None:
            raise HTTPException(status_code=400, detail="IMAGE_REQUIRED_FOR_INSERT")
        mime = _mime_for_image(target["name"], target["content_type"])
        data_uri = (
            f"data:{mime};base64," + base64.b64encode(target["content"]).decode("ascii")
        )
        presentation = session.document.presentation
        # Insert into the slide the CLIENT currently has open. Slide navigation
        # is client-local, so the server-side session cursor can be stale; the
        # request ui_context is the source of truth. Fail closed (no silent
        # retarget to the session cursor or first slide) when it is missing or
        # points at a slide that no longer exists.
        active = ui.active_slide_id
        if not active or presentation.get_slide(active) is None:
            raise HTTPException(status_code=400, detail="UI_CONTEXT_TARGET_INVALID")
        result = await execute_direct_batch(
            session,
            [
                {
                    "name": "add_image",
                    "arguments": {
                        "slide_id": active,
                        "src": data_uri,
                        "alt_text": target["name"],
                        "x": 340.0,
                        "y": 160.0,
                        "width": 600.0,
                        "height": 400.0,
                    },
                }
            ],
            mutation_id=f"attach_img_{uuid.uuid4().hex[:12]}",
            atomic=True,
            document_epoch=request_epoch,
            expected_revision=request_revision,
        )
        if not result.success:
            first = result.first_result() if hasattr(result, "first_result") else None
            error = getattr(result, "error", None) or (
                first.get("error") if isinstance(first, dict) else None
            )
            if error in (STALE_MUTATION, DOCUMENT_EPOCH_MISMATCH):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "STALE_IMAGE_INSERT: 演示文稿在附件处理期间已修改，"
                        "插入已取消；请重试。"
                    ),
                )
            raise HTTPException(
                status_code=400,
                detail=f"IMAGE_INSERT_FAILED: {error or 'unknown'}",
            )
        await store.broadcast(
            build_presentation_event(
                session,
                "presentation_loaded",
                extra={"checkpoints_count": len(session.checkpoints)},
            ),
            session_id=session.session_id,
        )
        turn_dto = await _commit_turn(
            ACTION_IMAGE,
            f"已将图片《{target.get('name')}》插入当前页",
            _provenance_for(ACTION_IMAGE),
        )
        return {
            "success": True,
            "action": ACTION_IMAGE,
            "session_id": session.session_id,
            "turn": turn_dto,
            "dispositions": disposition_plan,
            **build_canonical_snapshot(session),
        }

    raise HTTPException(status_code=400, detail=f"UNSUPPORTED_ACTION: {action}")
