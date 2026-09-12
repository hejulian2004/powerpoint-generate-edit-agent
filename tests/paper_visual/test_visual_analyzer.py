"""Multimodal analyzer tests (batched, strict JSON, degradable)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.paper import extract_paper
from backend.paper.schema import BBox, PaperFigure, PaperIR, PaperTable
from backend.paper_visual import analyze_paper_visual, render_pdf_pages
from backend.paper_visual.analyzer import _associate_regions
from backend.paper_visual.schema import PaperPageAsset, VisualRegion


def _assets(tmp_path: Path, pdf: Path) -> list:
    return render_pdf_pages(pdf, tmp_path / "render", dpi=144).assets


def test_analyzer_batches_and_roles(multicase_pdf: Path, tmp_path: Path, fake_vision_client):
    paper = extract_paper(multicase_pdf)
    assets = _assets(tmp_path, multicase_pdf)

    visual_ir = asyncio.run(
        analyze_paper_visual(paper, assets, llm_client=fake_vision_client, batch_size=4)
    )

    assert visual_ir.page_count == 10
    assert visual_ir.vision_model == "fake-vision-model"
    assert len(fake_vision_client.calls) == 3  # ceil(10 / 4)
    assert all(call["role"] == "vision" for call in fake_vision_client.calls)
    for page in visual_ir.pages:
        assert page.regions
        assert all(r.region_id.startswith(f"page_{page.page_number:03d}_region_") for r in page.regions)


def test_analyzer_produces_crops(multicase_pdf: Path, tmp_path: Path, fake_vision_client):
    paper = extract_paper(multicase_pdf)
    assets = _assets(tmp_path, multicase_pdf)
    crop_dir = tmp_path / "crops"

    visual_ir = asyncio.run(
        analyze_paper_visual(
            paper, assets, llm_client=fake_vision_client,
            batch_size=10, crop_output_dir=str(crop_dir),
        )
    )

    crops = [r.crop_path for page in visual_ir.pages for r in page.regions if r.crop_path]
    assert crops
    assert all(Path(p).exists() for p in crops)


def test_vision_flag_disabled_short_circuits(multicase_pdf: Path, tmp_path: Path, fake_vision_client, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "paper_vision_enabled", False)
    paper = extract_paper(multicase_pdf)
    assets = _assets(tmp_path, multicase_pdf)

    visual_ir = asyncio.run(
        analyze_paper_visual(paper, assets, llm_client=fake_vision_client, batch_size=4)
    )

    assert fake_vision_client.calls == []
    assert "vision_disabled" in visual_ir.warnings
    assert visual_ir.vision_model is None


def test_analyzer_degrades_without_llm(multicase_pdf: Path, tmp_path: Path):
    paper = extract_paper(multicase_pdf)
    assets = _assets(tmp_path, multicase_pdf)

    visual_ir = asyncio.run(analyze_paper_visual(paper, assets, llm_client=None))

    assert visual_ir.page_count == 10
    assert visual_ir.vision_model is None
    assert "vision_unavailable" in visual_ir.warnings
    assert all(not page.regions for page in visual_ir.pages)


def test_malformed_response_degrades(multicase_pdf: Path, tmp_path: Path, vision_client_cls):
    paper = extract_paper(multicase_pdf)
    assets = _assets(tmp_path, multicase_pdf)

    client = vision_client_cls(response_builder=lambda _m: "not json at all")
    visual_ir = asyncio.run(
        analyze_paper_visual(paper, assets, llm_client=client, batch_size=10)
    )

    assert visual_ir.page_count == 10
    assert any("batch_1" in w for w in visual_ir.warnings)
    assert all(not page.regions for page in visual_ir.pages)


def test_batch_failure_isolated_to_batch(
    multicase_pdf: Path, tmp_path: Path, vision_client_cls, vision_response_builder
):
    paper = extract_paper(multicase_pdf)
    assets = _assets(tmp_path, multicase_pdf)

    class FlakyClient(vision_client_cls):
        def __init__(self):
            super().__init__()
            self.count = 0

        async def chat_completion(self, messages, role="default", max_tokens=4096, **kwargs):
            self.count += 1
            if self.count == 2:
                raise RuntimeError("vision backend down")
            self.calls.append({"messages": messages, "role": role})
            return {"choices": [{"message": {"content": vision_response_builder(messages)}}]}

    client = FlakyClient()
    visual_ir = asyncio.run(
        analyze_paper_visual(paper, assets, llm_client=client, batch_size=4)
    )

    assert visual_ir.page_count == 10
    assert any("batch_2" in w for w in visual_ir.warnings)
    # batches 1 and 3 produced regions; batch 2 pages are stubs
    assert any(page.regions for page in visual_ir.pages)
    assert any(not page.regions for page in visual_ir.pages)


def test_associate_regions_uses_iou():
    paper = PaperIR(
        figures=[PaperFigure(id="figure1", page=1, bbox=BBox(x0=100.0, top=100.0, x1=300.0, bottom=300.0))],
        tables=[PaperTable(id="table1", page=2)],
    )
    # page point size derived from a 612x792pt page rendered at 144 dpi
    asset = PaperPageAsset(page_number=1, image_path="x.webp", width=1224, height=1584, dpi=144)
    page_w_pt, page_h_pt = asset.width * 72.0 / asset.dpi, asset.height * 72.0 / asset.dpi
    from backend.paper_visual.geometry import normalize_bbox

    fig_norm = normalize_bbox([100.0, 100.0, 300.0, 300.0], page_w_pt, page_h_pt)
    region = VisualRegion(region_id="r1", page_number=1, region_type="figure", bbox=fig_norm)
    _associate_regions([region], paper, 1, page_w_pt, page_h_pt)
    assert region.source_figure_id == "figure1"

    table_region = VisualRegion(region_id="r2", page_number=2, region_type="table", bbox=[0.1, 0.1, 0.5, 0.5])
    page2_asset = PaperPageAsset(page_number=2, image_path="x.webp", width=1224, height=1584, dpi=144)
    _associate_regions([table_region], paper, 2, page_w_pt, page_h_pt)
    assert table_region.source_table_id == "table1"
