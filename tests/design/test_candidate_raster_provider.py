"""Candidate raster must compile like production (merge blocker 2)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.agent.graphs import generation as gen
from backend.eval.renderer_snapshot import SlideSnapshotRenderer
from backend.layout.schema import Canvas, LayoutSpec
from backend.slidespec.schema import VisualIntent


def test_candidate_provider_uses_theme_and_asset_resolver(
    monkeypatch, tmp_path, paper_ir_fixture, paper_visual_ir_fixture, art_direction
):
    captured = {}

    def fake_compile(deck, theme_override=None, asset_resolver=None):
        captured["theme"] = theme_override
        captured["resolver"] = asset_resolver
        return SimpleNamespace(slides=["rendered-slide"])

    monkeypatch.setattr(gen, "compile_layout_to_presentation_ir", fake_compile)
    monkeypatch.setattr(
        SlideSnapshotRenderer,
        "render_data_uri",
        staticmethod(lambda slide, scale=1.0: "data:image/png;base64,AAAA"),
    )

    provider = gen._make_candidate_raster_provider(
        {
            "source_type": "paper",
            "deck_art_direction": art_direction,
            "paper_ir": paper_ir_fixture,
            "paper_visual_ir": paper_visual_ir_fixture,
            "paper_cache_dir": str(tmp_path),
        }
    )
    layout = LayoutSpec(
        slide_id="slide_1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(),
        elements=[],
    )
    result = provider(layout)

    assert result == "data:image/png;base64,AAAA"
    assert captured["theme"] is not None
    assert captured["theme"]["background_color"]
    assert captured["resolver"] is not None


def test_candidate_provider_without_art_direction(monkeypatch, paper_ir_fixture):
    captured = {}

    def fake_compile(deck, theme_override=None, asset_resolver=None):
        captured["theme"] = theme_override
        return SimpleNamespace(slides=[])

    monkeypatch.setattr(gen, "compile_layout_to_presentation_ir", fake_compile)
    provider = gen._make_candidate_raster_provider({"source_type": "pptspec"})
    layout = LayoutSpec(
        slide_id="slide_1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(),
        elements=[],
    )
    assert provider(layout) is None
    assert captured["theme"] is None
