"""PresentationIR Compiler (PR13 Step 4).

Compiles DeckLayoutSpec into PresentationIR, establishing the canonical editable
state for PPT-Agent-Studio.

Identity Chain & Provenance:
CanonicalPPTSpec -> SlideSpec (block_id) -> LayoutElement (source_block_id) -> BaseElementIR (source_ref)

Guarantees:
1. Figure placeholders are editable ShapeElementIR with clear user replacement instructions.
2. Incomplete tables are compiled into explicit ShapeElementIR placeholders with amber warning borders.
3. Complete tables are compiled into structured TableElementIR with editable cells.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from ..ir.models import (
    BorderStyle,
    ElementStyleIR,
    FillStyle,
    FontIR,
    ImageElementIR,
    ParagraphIR,
    PresentationIR,
    RunIR,
    ShapeElementIR,
    SlideIR,
    TableCellIR,
    TableElementIR,
    TextContentIR,
    TextElementIR,
)
from ..layout.schema import DeckLayoutSpec, ElementType, LayoutElement, LayoutSpec

logger = logging.getLogger(__name__)


def theme_from_art_direction(art_direction: Any) -> Dict[str, Any]:
    """Derive the OOXML theme from the deck's LLM art direction (theme ownership).

    The compiler owns deck-level colors; the LLM only decides the palette. Any
    accidental per-element color is therefore only a fallback, never the source of
    truth for the deck background/surface.
    """
    color_direction = getattr(art_direction, "color_direction", None)
    if color_direction is None:
        return {}

    primary = getattr(color_direction, "primary_accent", None) or "#2563EB"
    secondary = getattr(color_direction, "primary_text", None) or "#0F172A"
    background = getattr(color_direction, "background_color", None) or "#FFFFFF"
    surface = getattr(color_direction, "surface_color", None) or "#F8FAFC"
    secondary_accent = getattr(color_direction, "secondary_accent", None) or primary

    return {
        "name": "LLM Art Direction",
        "primary_color": primary,
        "secondary_color": secondary,
        "background_color": background,
        "card_background": surface,
        "color_scheme": {
            "accent1": primary,
            "accent2": secondary_accent,
            "accent3": getattr(color_direction, "semantic_positive", None) or "#10B981",
            "accent4": getattr(color_direction, "semantic_warning", None) or "#F59E0B",
            "accent5": getattr(color_direction, "semantic_negative", None) or "#EF4444",
            "accent6": secondary_accent,
            "dk1": secondary,
            "lt1": background,
            "dk2": getattr(color_direction, "secondary_text", None) or "#334155",
            "lt2": surface,
            "hlink": primary,
            "folHlink": secondary_accent,
        },
    }


def compile_layout_element_to_ir(
    element: LayoutElement,
    asset_resolver: Optional[Any] = None,
    asset_sink: Optional[Dict[str, str]] = None,
    theme: Optional[Dict[str, Any]] = None,
) -> Any:
    """Compile a single LayoutElement into the appropriate PresentationIR element model."""
    x = float(element.geometry.x)
    y = float(element.geometry.y)
    w = float(element.geometry.width)
    h = float(element.geometry.height)
    source_ref = element.source_block_id or element.element_id
    source_evidence_ids = list(getattr(element, "source_evidence_ids", []))
    theme = theme or {}
    surface_color = theme.get("card_background") or "#F8FAFC"
    accent_color = theme.get("primary_color") or "#3B82F6"
    text_default = theme.get("secondary_color") or "#1E293B"

    # -------------------------------------------------------------
    # 1. Figure Element (real trusted crop) or Placeholder fallback
    # -------------------------------------------------------------
    if element.element_type == ElementType.FIGURE:
        payload = element.content if isinstance(element.content, dict) else {}
        label = payload.get("xref_label") or payload.get("label") or "FIGURE"
        caption = payload.get("caption") or ""
        page = payload.get("source_page")

        resolved = asset_resolver(element) if asset_resolver is not None else None
        if resolved and resolved.get("src"):
            asset_id = resolved.get("asset_id") or element.element_id
            if asset_sink is not None:
                asset_sink[asset_id] = resolved["src"]
            figure_style = ElementStyleIR(
                fill=FillStyle(type="none"),
                border=BorderStyle(color="#E2E8F0", width=0.0, style="none"),
                radius=0.0,
                padding=0.0,
            )
            return ImageElementIR(
                id=element.element_id,
                name=f"Figure_{label}",
                x=x,
                y=y,
                width=w,
                height=h,
                z_index=element.z_index,
                source_ref=source_ref,
                source_evidence_ids=source_evidence_ids,
                src=resolved["src"],
                asset_id=asset_id,
                alt_text=resolved.get("alt_text") or caption or label,
                style=figure_style,
                metadata={
                    "asset_status": "resolved",
                    "source_figure_id": payload.get("source_figure_id") or "",
                },
            )

        paras: List[ParagraphIR] = [
            ParagraphIR(
                align="center",
                space_after=4.0,
                runs=[RunIR(text=f"[{label.upper()}]", font=FontIR(size=20.0, bold=True, color="#1E293B"))],
            ),
            ParagraphIR(
                align="center",
                space_after=8.0,
                runs=[RunIR(text=f"请粘贴论文原始 {label}", font=FontIR(size=15.0, bold=True, color="#2563EB"))],
            ),
        ]
        if caption:
            paras.append(
                ParagraphIR(
                    align="center",
                    space_after=4.0,
                    runs=[RunIR(text=caption, font=FontIR(size=13.0, italic=True, color="#64748B"))],
                )
            )
        if page:
            paras.append(
                ParagraphIR(
                    align="center",
                    runs=[RunIR(text=f"论文出处：第 {page} 页", font=FontIR(size=12.0, color="#94A3B8"))],
                )
            )

        return ShapeElementIR(
            id=element.element_id,
            name=f"Placeholder_{label}",
            shape_type="roundRect",
            x=x,
            y=y,
            width=w,
            height=h,
            z_index=element.z_index,
            source_ref=source_ref,
            source_evidence_ids=source_evidence_ids,
            metadata={
                "is_figure_placeholder": True,
                "asset_status": "placeholder",
                "source_figure_id": payload.get("source_figure_id") or "",
                "label": label,
                "caption": caption,
                "page": page,
            },
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color="#F8FAFC", alpha=1.0),
                border=BorderStyle(color="#94A3B8", width=1.5, style="dashed"),
                radius=8.0,
                padding=16.0,
            ),
            text_content=TextContentIR(paragraphs=paras),
        )

    # -------------------------------------------------------------
    # 2. Table Element (Complete vs Placeholder)
    # -------------------------------------------------------------
    if element.element_type == ElementType.TABLE:
        payload = element.content if isinstance(element.content, dict) else {}
        is_placeholder = bool(payload.get("placeholder", False))
        cols = payload.get("columns") or []
        rows = payload.get("rows") or []

        # If incomplete or missing columns/rows, render as Table Placeholder
        if is_placeholder or not cols or not rows:
            label = payload.get("xref_label") or "TABLE"
            caption = payload.get("caption") or ""
            page = payload.get("source_page")

            paras = [
                ParagraphIR(
                    align="center",
                    space_after=4.0,
                    runs=[RunIR(text=f"[{label.upper()}]", font=FontIR(size=20.0, bold=True, color="#92400E"))],
                ),
                ParagraphIR(
                    align="center",
                    space_after=8.0,
                    runs=[RunIR(text=f"请粘贴论文原始 {label}", font=FontIR(size=15.0, bold=True, color="#D97706"))],
                ),
            ]
            if caption:
                paras.append(
                    ParagraphIR(
                        align="center",
                        space_after=4.0,
                        runs=[RunIR(text=caption, font=FontIR(size=13.0, italic=True, color="#78350F"))],
                    )
                )
            if page:
                paras.append(
                    ParagraphIR(
                        align="center",
                        runs=[RunIR(text=f"论文出处：第 {page} 页", font=FontIR(size=12.0, color="#B45309"))],
                    )
                )

            return ShapeElementIR(
                id=element.element_id,
                name=f"Placeholder_{label}",
                shape_type="roundRect",
                x=x,
                y=y,
                width=w,
                height=h,
                z_index=element.z_index,
                source_ref=source_ref,
                source_evidence_ids=source_evidence_ids,
                metadata={
                    "is_table_placeholder": True,
                    "asset_status": "placeholder",
                    "source_table_id": payload.get("source_table_id") or "",
                    "label": label,
                    "caption": caption,
                    "page": page,
                },
                style=ElementStyleIR(
                    fill=FillStyle(type="solid", color="#FFFBEB", alpha=1.0),
                    border=BorderStyle(color="#F59E0B", width=1.5, style="dashed"),
                    radius=8.0,
                    padding=16.0,
                ),
                text_content=TextContentIR(paragraphs=paras),
            )

        # Complete, structured Table -> TableElementIR
        highlight_cells = set(payload.get("highlight_cells") or [])
        num_cols = len(cols)
        num_rows = len(rows) + 1  # 1 header + data rows
        grid_cells: List[List[TableCellIR]] = []

        # Row 0: Header
        header_row_cells: List[TableCellIR] = []
        for c_idx, col_name in enumerate(cols):
            header_row_cells.append(
                TableCellIR(
                    row=0,
                    col=c_idx,
                    style=ElementStyleIR(
                        fill=FillStyle(type="solid", color="#1E293B", alpha=1.0),
                        border=BorderStyle(color="#CBD5E1", width=1.0),
                        padding=6.0,
                    ),
                    text_content=TextContentIR.from_plain_text(
                        str(col_name),
                        font=FontIR(size=14.0, bold=True, color="#FFFFFF"),
                        align="center",
                    ),
                )
            )
        grid_cells.append(header_row_cells)

        # Rows 1..N: Data rows
        for r_idx, row_data in enumerate(rows, start=1):
            curr_row_cells: List[TableCellIR] = []
            is_alt = (r_idx % 2 == 0)
            row_bg = "#F8FAFC" if is_alt else "#FFFFFF"

            for c_idx in range(num_cols):
                val = str(row_data[c_idx]) if c_idx < len(row_data) else ""
                cell_key1 = f"{r_idx - 1},{c_idx}"
                cell_key2 = f"r{r_idx - 1}c{c_idx}"
                is_highlight = cell_key1 in highlight_cells or cell_key2 in highlight_cells

                cell_fill = "#FEF3C7" if is_highlight else row_bg
                cell_text_color = "#92400E" if is_highlight else "#1E293B"

                curr_row_cells.append(
                    TableCellIR(
                        row=r_idx,
                        col=c_idx,
                        style=ElementStyleIR(
                            fill=FillStyle(type="solid", color=cell_fill, alpha=1.0),
                            border=BorderStyle(color="#CBD5E1", width=1.0),
                            padding=6.0,
                        ),
                        text_content=TextContentIR.from_plain_text(
                            val,
                            font=FontIR(
                                size=13.0,
                                bold=is_highlight,
                                color=cell_text_color,
                            ),
                            align="center" if any(char.isdigit() for char in val) else "left",
                        ),
                    )
                )
            grid_cells.append(curr_row_cells)

        return TableElementIR(
            id=element.element_id,
            name=f"Table_{element.element_id}",
            x=x,
            y=y,
            width=w,
            height=h,
            rows=num_rows,
            cols=num_cols,
            cells=grid_cells,
            z_index=element.z_index,
            source_ref=source_ref,
            source_evidence_ids=source_evidence_ids,
            metadata={
                "asset_status": "resolved",
                "source_table_id": payload.get("source_table_id") or "",
                "columns": cols,
                "rows_count": len(rows),
            },
            style=ElementStyleIR(
                border=BorderStyle(color="#CBD5E1", width=1.0),
                radius=4.0,
            ),
        )

    # -------------------------------------------------------------
    # 3. Container Element (Cards / Group Backgrounds)
    # -------------------------------------------------------------
    if element.element_type == ElementType.CONTAINER:
        fill_color = element.style.background_color or surface_color
        border_color = element.style.border_color or "#E2E8F0"
        border_w = element.style.border_width if element.style.border_width > 0 else 1.0
        radius = element.style.corner_radius if element.style.corner_radius is not None else 0.0

        return ShapeElementIR(
            id=element.element_id,
            name="Container",
            shape_type="roundRect",
            x=x,
            y=y,
            width=w,
            height=h,
            z_index=element.z_index,
            source_ref=source_ref,
            source_evidence_ids=source_evidence_ids,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color=fill_color, alpha=1.0),
                border=BorderStyle(color=border_color, width=border_w),
                radius=radius,
            ),
        )

    # -------------------------------------------------------------
    # 4. Badge Element
    # -------------------------------------------------------------
    if element.element_type == ElementType.BADGE:
        text_str = str(element.content) if element.content is not None else ""
        fill_color = element.style.background_color or surface_color
        border_color = element.style.border_color or accent_color
        text_color = (element.style.text.color if element.style.text else None) or accent_color
        font_size = (element.style.text.font_size if element.style.text else 14.0)
        radius = element.style.corner_radius if element.style.corner_radius is not None else 0.0

        return ShapeElementIR(
            id=element.element_id,
            name="Badge",
            shape_type="roundRect",
            x=x,
            y=y,
            width=w,
            height=h,
            z_index=element.z_index,
            source_ref=source_ref,
            source_evidence_ids=source_evidence_ids,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color=fill_color, alpha=1.0),
                border=BorderStyle(color=border_color, width=1.0),
                radius=radius,
                padding=element.style.padding or 4.0,
            ),
            text_content=TextContentIR.from_plain_text(
                text_str,
                font=FontIR(size=font_size, bold=True, color=text_color),
                align="center",
            ),
        )

    # -------------------------------------------------------------
    # 5. Text Element (Default)
    # -------------------------------------------------------------
    text_val = str(element.content) if element.content is not None else ""
    t_style = element.style.text
    font_name = t_style.font_family if t_style else "Segoe UI"
    font_sz = t_style.font_size if t_style else 16.0
    is_bold = (t_style.font_weight == "bold") if t_style else False
    is_italic = t_style.italic if t_style else False
    text_color = (t_style.color if t_style else None) or text_default
    alignment = (t_style.alignment if t_style else "left")
    text_radius = element.style.corner_radius if element.style.corner_radius is not None else 0.0

    fill = FillStyle(type="solid", color=element.style.background_color) if element.style.background_color else FillStyle(type="none")
    border = BorderStyle(color=element.style.border_color, width=element.style.border_width) if element.style.border_color else BorderStyle(style="none", width=0.0)

    return TextElementIR(
        id=element.element_id,
        name="Text",
        x=x,
        y=y,
        width=w,
        height=h,
        z_index=element.z_index,
        source_ref=source_ref,
        source_evidence_ids=source_evidence_ids,
        style=ElementStyleIR(
            fill=fill,
            border=border,
            padding=element.style.padding or 4.0,
            radius=text_radius,
        ),
        text_content=TextContentIR.from_plain_text(
            text_val,
            font=FontIR(name=font_name, size=font_sz, bold=is_bold, italic=is_italic, color=text_color),
            align=alignment,
        ),
    )


def compile_layout_to_presentation_ir(
    deck_layout: DeckLayoutSpec,
    theme_override: Optional[Dict[str, Any]] = None,
    asset_resolver: Optional[Any] = None,
) -> PresentationIR:
    """Compile a DeckLayoutSpec into PresentationIR.

    ``theme_override`` carries the deck-level palette derived from the LLM art
    direction (see :func:`theme_from_art_direction`); the compiler then owns the
    slide background and container/surface defaults.
    """
    default_theme = {
        "name": "Academic Clean",
        "primary_color": "#2563EB",
        "secondary_color": "#0F172A",
        "background_color": "#FFFFFF",
        "card_background": "#F8FAFC",
        "font_heading": "Segoe UI",
        "font_body": "Segoe UI",
        "color_scheme": {
            "accent1": "#2563EB",
            "accent2": "#0EA5E9",
            "accent3": "#10B981",
            "accent4": "#F59E0B",
            "accent5": "#EF4444",
            "accent6": "#8B5CF6",
            "dk1": "#0F172A",
            "lt1": "#FFFFFF",
            "dk2": "#334155",
            "lt2": "#F8FAFC",
            "hlink": "#2563EB",
            "folHlink": "#7C3AED",
        },
        "font_scheme": {
            "major_font": "Segoe UI",
            "minor_font": "Segoe UI",
        },
    }
    if theme_override:
        default_theme.update(theme_override)

    slide_background = default_theme.get("background_color") or "#FFFFFF"

    slides_ir: List[SlideIR] = []
    assets: Dict[str, str] = {}

    for slide_layout in deck_layout.slides:
        elements_ir = []
        slide_title = None

        for el in slide_layout.elements:
            ir_el = compile_layout_element_to_ir(
                el,
                asset_resolver=asset_resolver,
                asset_sink=assets,
                theme=default_theme,
            )
            elements_ir.append(ir_el)
            if el.source_block_id in ("header_title", "title") and el.content:
                slide_title = str(el.content)

        slide_ir = SlideIR(
            id=slide_layout.slide_id,
            slide_num=slide_layout.slide_index,
            title=slide_title,
            width=int(slide_layout.canvas.width),
            height=int(slide_layout.canvas.height),
            background=FillStyle(type="solid", color=slide_background, alpha=1.0),
            elements=elements_ir,
            notes=slide_layout.speaker_notes or "",
        )
        slides_ir.append(slide_ir)

    return PresentationIR(
        id=f"pres_{deck_layout.title[:12].strip().replace(' ', '_')}",
        title=deck_layout.title,
        width=int(deck_layout.canvas.width),
        height=int(deck_layout.canvas.height),
        theme=default_theme,
        slides=slides_ir,
        assets=assets,
        active_slide_id=slides_ir[0].id if slides_ir else None,
        version=1,
    )
