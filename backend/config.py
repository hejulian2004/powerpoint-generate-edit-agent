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


settings = AppSettings()
