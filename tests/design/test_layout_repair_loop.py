"""Art director + bounded layout repair loop tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.design.art_director import build_plan_and_direction, design_deck
from backend.design.layout_designer import design_deck_layouts


def test_design_deck_returns_plan_and_direction(
    design_client_cls, art_direction_response_builder, deck_spec_two_slides
):
    client = design_client_cls(art_direction_response_builder)
    direction, plan = asyncio.run(design_deck(client))

    assert direction is not None and direction.layout_source == "llm"
    assert plan is not None and plan.slide_count == 2
    assert plan.profile == "llm_research"
    assert client.roles == ["reasoning"]


def test_design_deck_uses_vision_when_contact_sheet_present(
    design_client_cls, art_direction_response_builder, tmp_path
):
    sheet = tmp_path / "contact_sheet.webp"
    sheet.write_bytes(b"fake-image-bytes")
    client = design_client_cls(art_direction_response_builder)
    direction, plan = asyncio.run(design_deck(client, contact_sheet_path=str(sheet)))

    assert direction is not None and plan is not None
    assert client.roles == ["vision"]


def test_design_deck_without_api_key_returns_none(design_client_cls, art_direction_response_builder):
    client = design_client_cls(art_direction_response_builder, api_key="")
    direction, plan = asyncio.run(design_deck(client))
    assert direction is None and plan is None


def test_design_deck_bad_json_returns_none(design_client_cls):
    client = design_client_cls(lambda messages, role="reasoning": "not json")
    direction, plan = asyncio.run(design_deck(client))
    assert direction is None and plan is None


def test_build_plan_and_direction_falls_back_when_disabled(
    monkeypatch, design_client_cls, art_direction_response_builder
):
    from backend.config import settings

    monkeypatch.setattr(settings, "llm_native_layout_enabled", False)
    client = design_client_cls(art_direction_response_builder)
    direction, plan, used_llm = asyncio.run(
        build_plan_and_direction(client, None, None)
    )
    assert used_llm is False
    assert direction.layout_source == "fallback_template"
    assert client.calls == []


def test_repair_loop_repairs_then_accepts(
    design_client_cls, repair_response_builder, deck_spec_two_slides,
    presentation_plan_two_slides, art_direction,
):
    client = design_client_cls(repair_response_builder)
    result = asyncio.run(
        design_deck_layouts(
            client,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            max_repair_rounds=2,
        )
    )
    assert result.all_valid
    assert result.fallback_slide_indices == []
    assert result.validation_rounds[1] == 1
    assert all(sl.metadata["layout_source"] == "llm" for sl in result.deck_layout.slides)


def test_repair_loop_falls_back_when_never_valid(
    design_client_cls, invalid_response_builder, deck_spec_two_slides,
    presentation_plan_two_slides, art_direction,
):
    client = design_client_cls(invalid_response_builder)
    result = asyncio.run(
        design_deck_layouts(
            client,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            max_repair_rounds=1,
        )
    )
    assert not result.all_valid
    assert 1 in result.fallback_slide_indices
    assert result.hard_validation[1] is False
    assert result.deck_layout.slides[0].metadata["layout_source"] == "fallback_template"


def test_design_deck_layouts_missing_plan_falls_back(
    design_client_cls, deck_spec_two_slides, presentation_plan_two_slides, art_direction,
):
    client = design_client_cls(lambda messages, role="reasoning": "not json")
    result = asyncio.run(
        design_deck_layouts(
            client,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
        )
    )
    assert set(result.fallback_slide_indices) == {1, 2}
    assert result.deck_layout.metadata["layout_source"] == "fallback_template"
