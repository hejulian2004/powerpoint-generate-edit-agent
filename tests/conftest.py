"""Pytest bootstrap: isolate tests from local .env / live LLM credentials.

The test suite is designed to run in deterministic mock mode. Without this,
a local `.env` (OPENAI_API_KEY / OPENAI_BASE_URL / model overrides) would
leak into tests that assume an unconfigured or mocked LLM client, causing
live network calls and configuration-dependent failures.

`load_dotenv()` never overrides variables that already exist, so pre-setting
empty values here keeps the `.env` out of every test that imports backend.
"""

import os

os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENAI_BASE_URL"] = ""
os.environ["DEFAULT_MODEL"] = "gemini-3.8-flash-high"
os.environ["REASONING_MODEL"] = "gemini-3.8-flash-high"
os.environ["VISION_MODEL"] = "gemini-3.8-flash-high"
os.environ["FAST_MODEL"] = "gemini-3.8-flash-high"
os.environ["ENABLE_VISION_LOOP"] = "true"