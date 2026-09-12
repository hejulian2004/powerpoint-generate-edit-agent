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

# Register API and WebSocket routes
app.include_router(api_router)
app.include_router(ws_router)

# Mount frontend dist if built
dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        index_file = dist_dir / "index.html"
        file_path = dist_dir / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(index_file)
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
