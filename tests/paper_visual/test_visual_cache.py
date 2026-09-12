"""Content-addressed paper cache tests."""

from __future__ import annotations

import time
from pathlib import Path

from backend.paper_visual import (
    compute_cache_key,
    load_or_render,
    load_visual_ir,
    paper_cache_dir,
    save_visual_ir,
)
from backend.paper_visual.schema import PaperVisualIR


def test_cache_hit_reuses_rendered_pages(multicase_pdf: Path, cache_root: Path):
    first, first_dir = load_or_render(multicase_pdf, dpi=144, root=cache_root)
    assert first.cache_hit is False
    assert len(first.assets) == 10

    mtimes = {a.page_number: Path(a.image_path).stat().st_mtime_ns for a in first.assets}
    time.sleep(0.01)

    second, second_dir = load_or_render(multicase_pdf, dpi=144, root=cache_root)
    assert second.cache_hit is True
    assert second_dir == first_dir
    assert [a.sha256 for a in second.assets] == [a.sha256 for a in first.assets]
    for asset in second.assets:
        assert Path(asset.image_path).stat().st_mtime_ns == mtimes[asset.page_number]


def test_force_rerenders(multicase_pdf: Path, cache_root: Path):
    load_or_render(multicase_pdf, dpi=144, root=cache_root)
    forced, _ = load_or_render(multicase_pdf, dpi=144, root=cache_root, force=True)
    assert forced.cache_hit is False


def test_cache_key_is_deterministic_and_dpi_sensitive():
    key_a = compute_cache_key("deadbeef", dpi=144)
    key_b = compute_cache_key("deadbeef", dpi=144)
    key_c = compute_cache_key("deadbeef", dpi=72)
    assert key_a == key_b
    assert key_a != key_c
    assert len(key_a) == 64


def test_cache_dir_is_content_addressed(cache_root: Path):
    key = compute_cache_key("abc", dpi=144)
    assert paper_cache_dir(key, root=cache_root) == cache_root / key


def test_visual_ir_cache_roundtrip(tmp_path: Path):
    ir = PaperVisualIR(source_filename="p.pdf", vision_model="vision-x")
    save_visual_ir(ir, tmp_path)
    restored = load_visual_ir(tmp_path)
    assert restored == ir


def test_load_visual_ir_missing_returns_none(tmp_path: Path):
    assert load_visual_ir(tmp_path) is None
