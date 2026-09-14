"""PPT-Agent-Studio FastAPI application entry point."""

from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .api import api_router, ws_router
from .workspace.runtime import shutdown_workspace, startup_workspace


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PR #28 Phase 0: fail fast when a non-loopback bind has no API token.
    from .security.auth import ensure_remote_auth_configured

    ensure_remote_auth_configured()
    await startup_workspace()
    try:
        yield
    finally:
        await shutdown_workspace()


app = FastAPI(
    title="PPT-Agent-Studio API",
    description="LLM Agent-driven Presentation Creation and Realtime Editing Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: explicit origin allowlist from CORS_ORIGINS (dev origins by default).
# "*" is supported but disables credential sharing per the CORS spec.
_cors_origins = settings.cors_origin_list or ["*"]
_allow_all_origins = _cors_origins == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _allow_all_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .security.auth import RemoteExposureGuardMiddleware
app.add_middleware(RemoteExposureGuardMiddleware)


@app.middleware("http")
async def _api_token_guard(request, call_next):
    """Enforces PPT_API_TOKEN on REST when explicit secure mode is on.

    When no token is configured (local loopback default) every request
    passes through. When configured, every /api/* request must carry
    ``Authorization: Bearer <token>``. Docs/health/asset paths stay public.
    """
    from .security.auth import is_auth_enabled, verify_bearer_token

    path = request.url.path or ""
    if path.startswith("/api/") and is_auth_enabled():
        if not verify_bearer_token(request.headers.get("authorization")):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=401,
                content={"detail": "UNAUTHORIZED: valid PPT_API_TOKEN required"},
            )
    return await call_next(request)

# Register API and WebSocket routes
app.include_router(api_router)
app.include_router(ws_router)

# Mount frontend dist if built
dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist_dir.exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        root = dist_dir.resolve()
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        index_file = root / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return {
            "status": "online",
            "service": "PPT-Agent-Studio Backend API",
            "docs": "/docs",
            "websocket": "/ws"
        }
else:
    @app.get("/")
    async def index_placeholder():
        return {
            "status": "online",
            "service": "PPT-Agent-Studio Backend API",
            "docs": "/docs",
            "websocket": "/ws"
        }


def run():
    import uvicorn
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    run()
