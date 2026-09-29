"""Turn chat tool slide dicts into a DeckSpec and compile them with the layout engine.

This is the chat entry to ``layout.engine`` and ``compile_layout_to_presentation_ir``.
It does not invent coordinates. Text-only timelines use the takeaway list so items
are not dropped into an empty figure column.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..compiler.presentation_ir import compile_layout_to_presentation_ir
from ..ir.models import PresentationIR
from ..layout.engine import generate_deck_layout
from ..presentation.schema import SlideType
from ..slidespec.schema import (
    BadgeBlock,
    BlockRole,
    DeckSpec,
    SlideSpec,
    TextBlock,
    VisualIntent,
)

_LAYOUT_MAP: Dict[str, Tuple[VisualIntent, SlideType]] = {
    "title_slide": (VisualIntent.TITLE_HERO, SlideType.TITLE),
    "card_grid": (VisualIntent.METRIC_CARD_GRID, SlideType.RESULT),
    "timeline": (VisualIntent.KEY_TAKEAWAY_LIST, SlideType.METHOD_OVERVIEW),
    "kpi_metrics": (VisualIntent.METRIC_CARD_GRID, SlideType.RESULT),
    "comparison": (VisualIntent.TWO_COLUMN_CONTRAST, SlideType.RESULT),
}


def _item_text(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item or "").strip()
    title = str(item.get("title") or item.get("label") or item.get("value") or "").strip()
    description = str(item.get("description") or item.get("subtext") or "").strip()
    if title and description:
        return f"{title}\n{description}"
    return title or description or str(item.get("text") or "").strip()


def _slide_dict_to_spec(index: int, raw: Dict[str, Any]) -> SlideSpec:
    layout = str(raw.get("layout") or raw.get("layout_type") or "card_grid")
    intent, slide_type = _LAYOUT_MAP.get(layout, (VisualIntent.KEY_TAKEAWAY_LIST, SlideType.RESULT))
    title = str(raw.get("title") or f"第 {index} 页").strip() or f"第 {index} 页"
    subtitle = str(raw.get("subtitle") or "").strip()
    items = list(raw.get("items") or [])
    blocks: List[Any] = []
    if subtitle:
        blocks.append(TextBlock(
            role=BlockRole.SUBHEADING,
            content=subtitle,
            block_id=f"s{index}_sub",
        ))

    has_figure = any(
        isinstance(item, dict) and (item.get("figure") or item.get("source_figure_id"))
        for item in items
    )
    if layout == "timeline" and has_figure:
        intent = VisualIntent.PIPELINE_ARCHITECTURE
        slide_type = SlideType.METHOD_OVERVIEW

    if layout == "kpi_metrics":
        for j, item in enumerate(items):
            if isinstance(item, dict):
                value = str(item.get("value") or "").strip()
                label = str(item.get("label") or item.get("title") or "").strip()
                text = " ".join(part for part in (value, label) if part) or _item_text(item)
            else:
                text = _item_text(item)
            if text:
                blocks.append(BadgeBlock(text=text, block_id=f"s{index}_b{j + 1}"))
    elif layout == "comparison":
        for j, item in enumerate(items):
            column = "left" if j % 2 == 0 else "right"
            if isinstance(item, dict) and item.get("column") in ("left", "right"):
                column = item["column"]
            text = _item_text(item)
            if text:
                blocks.append(TextBlock(
                    role=BlockRole.BULLET_ITEM,
                    content=text,
                    column=column,  # type: ignore[arg-type]
                    block_id=f"s{index}_t{j + 1}",
                ))
    elif layout == "title_slide":
        for j, item in enumerate(items):
            text = _item_text(item)
            if text:
                blocks.append(BadgeBlock(text=text[:48], block_id=f"s{index}_b{j + 1}"))
    else:
        text_items = [text for text in (_item_text(item) for item in items) if text]
        if layout == "card_grid" and not (2 <= len(text_items) <= 4):
            intent = VisualIntent.KEY_TAKEAWAY_LIST
        for j, text in enumerate(text_items):
            blocks.append(TextBlock(
                role=BlockRole.BULLET_ITEM,
                content=text,
                block_id=f"s{index}_t{j + 1}",
            ))

    return SlideSpec(
        index=index,
        slide_type=slide_type,
        visual_intent=intent,
        title=title,
        subtitle=subtitle or None,
        blocks=blocks,
    )


def tool_slides_to_deck_spec(topic: str, slides: Optional[List[Dict[str, Any]]]) -> DeckSpec:
    specs = [
        _slide_dict_to_spec(index, raw if isinstance(raw, dict) else {"title": str(raw)})
        for index, raw in enumerate(slides or [], start=1)
    ]
    return DeckSpec(title=(topic or "演示文稿").strip() or "演示文稿", slides=specs)


def compile_tool_slides(topic: str, slides: Optional[List[Dict[str, Any]]]) -> PresentationIR:
    """Offline geometry path: DeckSpec → generate_deck_layout → PresentationIR.

    Online art-direction still lives in ``design_deck_layouts`` on the paper graph.
    Chat already received titles and bullets as tool arguments, so this call only
    places those blocks with the same template engine the designer falls back to.
    """
    deck = tool_slides_to_deck_spec(topic, slides)
    layout = generate_deck_layout(deck, validate=False)
    return compile_layout_to_presentation_ir(layout)
