"""Global application configuration with dynamic settings override."""

from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "backend" / "static"
ASSETS_DIR = BASE_DIR / "output" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


class AppSettings(BaseModel):
    # Server — loopback by default (PR #28 Phase 0). Remote exposure requires
    # PPT_API_TOKEN (see backend/security/auth.py startup guard).
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8000"))

    # Remote-mode API token. Empty = local/trusted mode (no auth enforced).
    # Non-empty = explicit secure mode (REST + WebSocket both enforce auth).
    ppt_api_token: str = os.getenv("PPT_API_TOKEN", "")

    # Explicit allowlist for custom provider hosts probed via /api/models.
    # Comma-separated hostnames, e.g. "api.openai.com,my-proxy.example.com".
    # Empty = any publicly-routable host (still SSRF-checked + DNS-pinned).
    trusted_provider_hosts: str = os.getenv("TRUSTED_PROVIDER_HOSTS", "")

    # ---- Upload / parse / vision resource budgets (PR #28 Phase 0) ----
    max_upload_file_bytes: int = int(os.getenv("MAX_UPLOAD_FILE_BYTES", str(50 * 1024 * 1024)))
    max_total_attachment_bytes: int = int(
        os.getenv("MAX_TOTAL_ATTACHMENT_BYTES", str(100 * 1024 * 1024))
    )
    max_attachment_count: int = int(os.getenv("MAX_ATTACHMENT_COUNT", "10"))
    max_pdf_pages: int = int(os.getenv("MAX_PDF_PAGES", "80"))
    pptx_max_uncompressed_bytes: int = int(
        os.getenv("PPTX_MAX_UNCOMPRESSED_BYTES", str(200 * 1024 * 1024))
    )
    pptx_max_entries: int = int(os.getenv("PPTX_MAX_ENTRIES", "1000"))
    vision_concurrency: int = int(os.getenv("VISION_CONCURRENCY", "4"))

    # Runtime environment: "production" | "test" | "dev".
    # Mock LLM completions are only permitted outside production when explicitly enabled.
    app_env: str = os.getenv("APP_ENV", "production").strip().lower()
    mock_llm: bool = os.getenv("MOCK_LLM", "false").strip().lower() in ("1", "true", "yes")

    # LLM Settings
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    
    # Model Roles
    default_model: str = os.getenv("DEFAULT_MODEL", "gpt-4o")
    reasoning_model: str = os.getenv("REASONING_MODEL", "gpt-4o")
    vision_model: str = os.getenv("VISION_MODEL", "gpt-4o")
    fast_model: str = os.getenv("FAST_MODEL", "gpt-4o-mini")

    # Vision Loop toggle
    enable_vision_loop: bool = os.getenv("ENABLE_VISION_LOOP", "true").lower() == "true"

    # Visual Self-Healing Auto-Fix Loop
    max_visual_iterations: int = int(os.getenv("MAX_VISUAL_ITERATIONS", "3"))

    # ------------------------------------------------------------------
    # LLM-native multimodal presentation design (paper -> PPT)
    # ------------------------------------------------------------------
    # Master switch for the LLM-native free-form layout path. When disabled the
    # pipeline falls back to the legacy deterministic/template layout engine.
    llm_native_layout_enabled: bool = os.getenv(
        "LLM_NATIVE_LAYOUT_ENABLED", "true"
    ).strip().lower() == "true"

    # Paper page rasterization + multimodal (vision) paper understanding.
    paper_vision_enabled: bool = os.getenv(
        "PAPER_VISION_ENABLED", "true"
    ).strip().lower() == "true"

    # Bounded repair / refinement loops (guards against infinite churn).
    max_layout_repair_rounds: int = int(os.getenv("MAX_LAYOUT_REPAIR_ROUNDS", "2"))
    max_aesthetic_refinement_rounds: int = int(
        os.getenv("MAX_AESTHETIC_REFINEMENT_ROUNDS", "2")
    )
    max_deck_revisit_rounds: int = int(os.getenv("MAX_DECK_REVISIT_ROUNDS", "1"))

    # Paper vision analysis batching and canonical page render resolution.
    paper_vision_batch_size: int = int(os.getenv("PAPER_VISION_BATCH_SIZE", "4"))
    paper_page_render_dpi: int = int(os.getenv("PAPER_PAGE_RENDER_DPI", "144"))

    # Context Window Limit & Auto-Compression Setting
    context_limit: str = os.getenv("CONTEXT_LIMIT", "256k")  # "128k" | "256k" | "512k" | "1m" | "2m"

    # CORS allowlist (comma-separated origins). "*" explicitly allows all origins,
    # but then credentialed requests are disabled per the CORS spec.
    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000,tauri://localhost",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_provider_host_set(self) -> set[str]:
        return {
            h.strip().lower()
            for h in (self.trusted_provider_hosts or "").split(",")
            if h.strip()
        }


settings = AppSettings()
