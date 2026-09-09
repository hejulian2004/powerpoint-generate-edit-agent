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


def compile_layout_element_to_ir(element: LayoutElement) -> Any:
    """Compile a single LayoutElement into the appropriate PresentationIR element model."""
    x = float(element.geometry.x)
    y = float(element.geometry.y)
    w = float(element.geometry.width)
    h = float(element.geometry.height)
    source_ref = element.source_block_id or element.element_id
    source_evidence_ids = list(getattr(element, "source_evidence_ids", []))

    # -------------------------------------------------------------
    # 1. Figure Placeholder Element
    # -------------------------------------------------------------
    if element.element_type == ElementType.FIGURE:
        payload = element.content if isinstance(element.content, dict) else {}
        label = payload.get("xref_label") or payload.get("label") or "FIGURE"
        caption = payload.get("caption") or ""
        page = payload.get("source_page")

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
            metadata={"columns": cols, "rows_count": len(rows)},
            style=ElementStyleIR(
                border=BorderStyle(color="#CBD5E1", width=1.0),
                radius=4.0,
            ),
        )

    # -------------------------------------------------------------
    # 3. Container Element (Cards / Group Backgrounds)
    # -------------------------------------------------------------
    if element.element_type == ElementType.CONTAINER:
        fill_color = element.style.background_color or "#F8FAFC"
        border_color = element.style.border_color or "#E2E8F0"
        border_w = element.style.border_width if element.style.border_width > 0 else 1.0

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
                radius=element.style.corner_radius or 8.0,
            ),
        )

    # -------------------------------------------------------------
    # 4. Badge Element
    # -------------------------------------------------------------
    if element.element_type == ElementType.BADGE:
        text_str = str(element.content) if element.content is not None else ""
        fill_color = element.style.background_color or "#EFF6FF"
        border_color = element.style.border_color or "#3B82F6"
        text_color = (element.style.text.color if element.style.text else None) or "#1D4ED8"
        font_size = (element.style.text.font_size if element.style.text else 14.0)

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
                radius=element.style.corner_radius or 6.0,
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
    text_color = (t_style.color if t_style else None) or "#1E293B"
    alignment = (t_style.alignment if t_style else "left")

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
            radius=element.style.corner_radius or 0.0,
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
) -> PresentationIR:
    """Compile a DeckLayoutSpec into PresentationIR."""
    slides_ir: List[SlideIR] = []

    for slide_layout in deck_layout.slides:
        elements_ir = []
        slide_title = None

        for el in slide_layout.elements:
            ir_el = compile_layout_element_to_ir(el)
            elements_ir.append(ir_el)
            if el.source_block_id in ("header_title", "title") and el.content:
                slide_title = str(el.content)

        slide_ir = SlideIR(
            id=slide_layout.slide_id,
            slide_num=slide_layout.slide_index,
            title=slide_title,
            width=int(slide_layout.canvas.width),
            height=int(slide_layout.canvas.height),
            background=FillStyle(type="solid", color="#FFFFFF", alpha=1.0),
            elements=elements_ir,
            notes=slide_layout.speaker_notes or "",
        )
        slides_ir.append(slide_ir)

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

    return PresentationIR(
        id=f"pres_{deck_layout.title[:12].strip().replace(' ', '_')}",
        title=deck_layout.title,
        width=int(deck_layout.canvas.width),
        height=int(deck_layout.canvas.height),
        theme=default_theme,
        slides=slides_ir,
        active_slide_id=slides_ir[0].id if slides_ir else None,
        version=1,
    )
