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
    # Server
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

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


settings = AppSettings()
