"""Design schema + default art direction tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.design.art_director import default_art_direction, default_color_direction
from backend.design.prompts import (
    ART_DIRECTOR_SYSTEM_PROMPT,
    LAYOUT_DESIGNER_SYSTEM_PROMPT,
    LAYOUT_REPAIR_INSTRUCTION,
)
from backend.design.schema import ColorDirection, DeckArtDirection, SemanticColorBinding


def test_default_art_direction_is_fallback_marked():
    direction = default_art_direction()
    assert direction.layout_source == "fallback_template"
    assert direction.color_direction.primary_accent
    assert direction.consistency_rules


def test_color_direction_rejects_empty_color():
    with pytest.raises(ValidationError):
        SemanticColorBinding(semantic_key="ours", color="   ")


def test_deck_art_direction_json_roundtrip(tmp_path):
    direction = default_art_direction()
    path = tmp_path / "direction.json"
    direction.to_json_file(path)
    assert DeckArtDirection.from_json_file(path) == direction


def test_prompts_forbid_facts_and_prose():
    assert "STRICT JSON" in ART_DIRECTOR_SYSTEM_PROMPT
    assert "NEVER infer a number" in ART_DIRECTOR_SYSTEM_PROMPT
    assert "no layout_type field" in LAYOUT_DESIGNER_SYSTEM_PROMPT
    assert "COMPLETE replacement" in LAYOUT_REPAIR_INSTRUCTION


def test_default_color_direction_binding():
    color = default_color_direction()
    assert color.primary_text.startswith("#")
    assert color.bindings
