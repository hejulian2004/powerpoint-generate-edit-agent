"""Unit tests for Prompt Templates (PR13 Step 1)."""

import json
from backend.pptspec.prompt_template import get_general_prompt, get_strict_prompt


def test_general_prompt_content():
    prompt = get_general_prompt()
    assert "严禁捏造任何事实" in prompt
    assert "图表占位机制" in prompt
    assert "Figure" in prompt
    assert "Table" in prompt
    assert "占位" in prompt


def test_strict_prompt_contains_valid_schema():
    prompt = get_strict_prompt()
    assert "CanonicalPPTSpec" in prompt
    assert "model_json_schema" not in prompt  # should be expanded JSON
    # Extract the JSON block
    assert "```json" in prompt
    parts = prompt.split("```json")
    json_part = parts[1].split("```")[0].strip()
    parsed_schema = json.loads(json_part)
    assert "properties" in parsed_schema
    assert "spec_version" in parsed_schema["properties"]
    assert "slides" in parsed_schema["properties"]
