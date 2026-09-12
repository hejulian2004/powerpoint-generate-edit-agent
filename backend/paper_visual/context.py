"""Third-level context selection: choose paper visuals for a single slide.

The pipeline uses a three-tier context budget so the whole paper is never re-sent
to vision for every slide:

1. Paper indexing  -> all pages, batched (builds PaperVisualIR)
2. Deck planning   -> PaperVisualIR summary + contact sheet + a few key pages
3. Slide designing -> 1..3 relevant high-res pages + region crops

This module implements tier 3 (and the page/region ranking reusable by tier 2).
Facts are NOT selected here; only visual evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Set

from .schema import PaperPageAsset, PaperVisualIR, VisualRegion


@dataclass
class SlideVisualContext:
    """Selected visual material for one slide's design pass."""

    source_pages: List[int] = field(default_factory=list)
    page_assets: List[PaperPageAsset] = field(default_factory=list)
    regions: List[VisualRegion] = field(default_factory=list)

    @property
    def crop_paths(self) -> List[str]:
        return [r.crop_path for r in self.regions if r.crop_path]

    @property
    def page_image_paths(self) -> List[str]:
        return [a.image_path for a in self.page_assets]

    def is_empty(self) -> bool:
        return not self.page_assets and not self.regions


def _pages_for_asset_ids(
    paper_visual_ir: PaperVisualIR,
    figure_ids: Set[str],
    table_ids: Set[str],
) -> Set[int]:
    pages: Set[int] = set()
    for page in paper_visual_ir.pages:
        for region in page.regions:
            if region.source_figure_id and region.source_figure_id in figure_ids:
                pages.add(page.page_number)
            if region.source_table_id and region.source_table_id in table_ids:
                pages.add(page.page_number)
    return pages


def select_visual_context_for_slide(
    paper_visual_ir: Optional[PaperVisualIR],
    source_pages: Optional[Sequence[int]] = None,
    figure_ids: Optional[Iterable[str]] = None,
    table_ids: Optional[Iterable[str]] = None,
    max_pages: int = 3,
    max_regions: int = 8,
) -> SlideVisualContext:
    """Select high-res pages + region crops relevant to one slide.

    Page priority: explicit ``source_pages`` -> pages of referenced figures/tables
    -> remaining pages by visual importance. Regions are ranked by
    ``ppt_usefulness * importance``.
    """
    if paper_visual_ir is None or not paper_visual_ir.pages:
        return SlideVisualContext()

    figure_set = {f for f in (figure_ids or []) if f}
    table_set = {t for t in (table_ids or []) if t}

    ordered_pages: List[int] = []
    seen: Set[int] = set()

    def _push(page_number: int) -> None:
        if page_number not in seen and paper_visual_ir.page_by_number(page_number):
            seen.add(page_number)
            ordered_pages.append(page_number)

    for page_number in source_pages or []:
        _push(int(page_number))

    for page_number in sorted(_pages_for_asset_ids(paper_visual_ir, figure_set, table_set)):
        _push(page_number)

    remaining = sorted(
        paper_visual_ir.pages,
        key=lambda p: p.visual_importance,
        reverse=True,
    )
    for page in remaining:
        _push(page.page_number)

    selected_page_numbers = ordered_pages[: max(1, max_pages)]
    selected_pages = [
        paper_visual_ir.page_by_number(pn) for pn in selected_page_numbers
    ]

    regions: List[VisualRegion] = []
    for page in selected_pages:
        if page is None:
            continue
        for region in page.regions:
            regions.append(region)
    regions.sort(key=lambda r: (r.ppt_usefulness * r.importance), reverse=True)
    regions = regions[: max(0, max_regions)]

    return SlideVisualContext(
        source_pages=selected_page_numbers,
        page_assets=[p.page_asset for p in selected_pages if p is not None],
        regions=regions,
    )


__all__ = ["SlideVisualContext", "select_visual_context_for_slide"]
