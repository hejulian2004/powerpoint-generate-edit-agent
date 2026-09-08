"""Tool API for PPT-Agent.

Provides OpenAI tool definitions and execution handlers that mutate the PPT-IR
and log reversible patch records for undo/redo and live WebSocket broadcasting.
"""

from __future__ import annotations
import json
import uuid
import copy
from typing import Dict, Any, List, Optional, Callable
from ..ir.models import (
    PresentationIR, SlideIR, ElementIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, ImageElementIR, TableElementIR, ElementStyleIR,
    FillStyle, BorderStyle, ShadowStyle, TextContentIR, ParagraphIR, RunIR, FontIR
)
from ..ir.patch import HistoryManager


# =====================================================================
# Tool Execution Registry
# =====================================================================

class ToolRegistry:
    def __init__(self):
        self.schemas: List[Dict[str, Any]] = []
        self.handlers: Dict[str, Callable] = {}

    def register(self, schema: Dict[str, Any]):
        def decorator(func: Callable):
            name = schema["function"]["name"]
            self.schemas.append(schema)
            self.handlers[name] = func
            return func
        return decorator

    def execute(
        self,
        name: str,
        args: Dict[str, Any],
        pres: PresentationIR,
        history: HistoryManager
    ) -> Dict[str, Any]:
        if name not in self.handlers:
            return {"success": False, "error": f"Unknown tool: {name}"}
        try:
            return self.handlers[name](pres, history, **args)
        except Exception as e:
            return {"success": False, "error": f"Execution error in {name}: {str(e)}"}


tools = ToolRegistry()


# =====================================================================
# 1. Slide & Presentation Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "create_slide",
        "description": "Create a new slide in the presentation with optional background and layout.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Slide title or topic"},
                "background_color": {"type": "string", "description": "Hex color like #FFFFFF or #0F172A", "default": "#FFFFFF"},
                "position": {"type": "integer", "description": "1-based index to insert slide. Defaults to append at end."}
            },
            "required": []
        }
    }
})
def create_slide(
    pres: PresentationIR,
    history: HistoryManager,
    title: str = "New Slide",
    background_color: str = "#FFFFFF",
    position: Optional[int] = None
) -> Dict[str, Any]:
    slide_num = len(pres.slides) + 1 if position is None else position
    new_slide = SlideIR(
        id=f"slide_{uuid.uuid4().hex[:6]}",
        slide_num=slide_num,
        title=title,
        background=FillStyle(type="solid", color=background_color, alpha=1.0)
    )

    if position is not None and 1 <= position <= len(pres.slides):
        pres.slides.insert(position - 1, new_slide)
        # renumber
        for idx, s in enumerate(pres.slides):
            s.slide_num = idx + 1
    else:
        pres.slides.append(new_slide)

    pres.active_slide_id = new_slide.id
    pres.version += 1

    history.record(
        action="create_slide",
        description=f"创建幻灯片: {title}",
        slide_id=new_slide.id,
        after=new_slide.model_dump()
    )

    return {
        "success": True,
        "slide_id": new_slide.id,
        "slide_num": new_slide.slide_num,
        "message": f"成功创建幻灯片 #{new_slide.slide_num}: {title}"
    }


@tools.register({
    "type": "function",
    "function": {
        "name": "delete_slide",
        "description": "Delete a slide by its slide_id or 1-based slide_num.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id_or_num": {"type": "string", "description": "Slide ID (e.g. 'slide_01') or number (e.g. '2')"}
            },
            "required": ["slide_id_or_num"]
        }
    }
})
def delete_slide(pres: PresentationIR, history: HistoryManager, slide_id_or_num: str) -> Dict[str, Any]:
    target_slide = None
    target_idx = -1

    for idx, s in enumerate(pres.slides):
        if s.id == slide_id_or_num or str(s.slide_num) == str(slide_id_or_num):
            target_slide = s
            target_idx = idx
            break

    if not target_slide or target_idx < 0:
        return {"success": False, "error": f"找不到幻灯片: {slide_id_or_num}"}

    if len(pres.slides) <= 1:
        return {"success": False, "error": "不能删除演示文稿中的最后一页"}

    pres.slides.pop(target_idx)
    # Renumber
    for idx, s in enumerate(pres.slides):
        s.slide_num = idx + 1

    pres.active_slide_id = pres.slides[min(target_idx, len(pres.slides) - 1)].id
    pres.version += 1

    history.record(
        action="delete_slide",
        description=f"删除幻灯片 #{target_slide.slide_num}",
        slide_id=target_slide.id,
        before=target_slide.model_dump()
    )

    return {"success": True, "message": f"已删除幻灯片 #{target_slide.slide_num}"}


# =====================================================================
# 2. Add Elements Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "add_text",
        "description": "Add a standalone text box to a slide. Standard slide is 1280x720 px.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "text": {"type": "string", "description": "Text content to display (supports newline)"},
                "x": {"type": "number", "description": "X position in px (0-1280)", "default": 100},
                "y": {"type": "number", "description": "Y position in px (0-720)", "default": 100},
                "width": {"type": "number", "description": "Width in px", "default": 400},
                "height": {"type": "number", "description": "Height in px", "default": 60},
                "font_size": {"type": "number", "description": "Font size in px (e.g. 18, 24, 32, 44)", "default": 20},
                "font_color": {"type": "string", "description": "Hex color like #1E293B", "default": "#1E293B"},
                "bold": {"type": "boolean", "default": False},
                "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"}
            },
            "required": ["text"]
        }
    }
})
def add_text(
    pres: PresentationIR,
    history: HistoryManager,
    text: str,
    slide_id: Optional[str] = None,
    x: float = 100.0,
    y: float = 100.0,
    width: float = 400.0,
    height: float = 60.0,
    font_size: float = 20.0,
    font_color: str = "#1E293B",
    bold: bool = False,
    align: str = "left"
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    elem = TextElementIR(
        id=f"txt_{uuid.uuid4().hex[:6]}",
        name="Text Box",
        x=x,
        y=y,
        width=width,
        height=height,
        text_content=TextContentIR.from_plain_text(
            text,
            font=FontIR(size=font_size, color=font_color, bold=bold),
            align=align if align in ["left", "center", "right"] else "left"
        )
    )
    slide.add_element(elem)
    pres.version += 1

    history.record(
        action="add_element",
        description=f"添加文本框: {text[:20]}",
        slide_id=slide.id,
        element_id=elem.id,
        after=elem.model_dump()
    )

    return {"success": True, "element_id": elem.id, "message": f"已添加文本框到第 {slide.slide_num} 页"}


@tools.register({
    "type": "function",
    "function": {
        "name": "add_shape",
        "description": "Add a styled geometric shape or card (roundRect, rectangle, ellipse, diamond, triangle, rightArrow).",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "shape_type": {"type": "string", "enum": ["roundRect", "rectangle", "ellipse", "diamond", "triangle", "rightArrow"], "default": "roundRect"},
                "x": {"type": "number", "description": "X coordinate in px (0-1280)", "default": 100},
                "y": {"type": "number", "description": "Y coordinate in px (0-720)", "default": 150},
                "width": {"type": "number", "description": "Width in px", "default": 280},
                "height": {"type": "number", "description": "Height in px", "default": 160},
                "fill_color": {"type": "string", "description": "Hex fill color like #2563EB or #F8FAFC", "default": "#2563EB"},
                "border_color": {"type": "string", "description": "Hex border color", "default": ""},
                "border_width": {"type": "number", "description": "Border width in px", "default": 1.0},
                "radius": {"type": "number", "description": "Corner radius for roundRect (e.g. 8.0, 16.0)", "default": 12.0},
                "shadow": {"type": "boolean", "description": "Enable subtle drop shadow", "default": True},
                "text": {"type": "string", "description": "Text inside the shape (supports multi-line)", "default": ""},
                "text_color": {"type": "string", "description": "Text hex color", "default": "#FFFFFF"},
                "font_size": {"type": "number", "default": 16.0}
            },
            "required": []
        }
    }
})
def add_shape(
    pres: PresentationIR,
    history: HistoryManager,
    slide_id: Optional[str] = None,
    shape_type: str = "roundRect",
    x: float = 100.0,
    y: float = 150.0,
    width: float = 280.0,
    height: float = 160.0,
    fill_color: str = "#2563EB",
    border_color: str = "",
    border_width: float = 1.0,
    radius: float = 12.0,
    shadow: bool = True,
    text: str = "",
    text_color: str = "#FFFFFF",
    font_size: float = 16.0
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    fill_style = FillStyle(type="solid", color=fill_color, alpha=1.0) if fill_color else FillStyle(type="none")
    border_style = BorderStyle(color=border_color, width=border_width) if border_color else None
    shadow_style = ShadowStyle(enabled=shadow) if shadow else None

    tc = None
    if text:
        tc = TextContentIR.from_plain_text(
            text,
            font=FontIR(size=font_size, color=text_color),
            align="center"
        )

    elem = ShapeElementIR(
        id=f"shape_{uuid.uuid4().hex[:6]}",
        name=f"{shape_type.capitalize()} Shape",
        shape_type=shape_type,
        x=x,
        y=y,
        width=width,
        height=height,
        text_content=tc,
        style=ElementStyleIR(
            fill=fill_style,
            border=border_style,
            shadow=shadow_style,
            radius=radius
        )
    )
    slide.add_element(elem)
    pres.version += 1

    history.record(
        action="add_element",
        description=f"添加形状: {shape_type}",
        slide_id=slide.id,
        element_id=elem.id,
        after=elem.model_dump()
    )

    return {"success": True, "element_id": elem.id, "message": f"已成功添加 {shape_type} 元素"}


@tools.register({
    "type": "function",
    "function": {
        "name": "add_connector",
        "description": "Add an arrow or connector line connecting points or elements.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "start_x": {"type": "number", "description": "Start X coordinate in px"},
                "start_y": {"type": "number", "description": "Start Y coordinate in px"},
                "end_x": {"type": "number", "description": "End X coordinate in px"},
                "end_y": {"type": "number", "description": "End Y coordinate in px"},
                "color": {"type": "string", "description": "Line color hex", "default": "#3B82F6"},
                "width": {"type": "number", "description": "Stroke width in px", "default": 2.0},
                "arrow_end": {"type": "string", "enum": ["triangle", "none"], "default": "triangle"},
                "arrow_start": {"type": "string", "enum": ["none", "triangle"], "default": "none"},
                "line_type": {"type": "string", "enum": ["straight", "elbow"], "default": "straight"}
            },
            "required": ["start_x", "start_y", "end_x", "end_y"]
        }
    }
})
def add_connector(
    pres: PresentationIR,
    history: HistoryManager,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    slide_id: Optional[str] = None,
    color: str = "#3B82F6",
    width: float = 2.0,
    arrow_end: str = "triangle",
    arrow_start: str = "none",
    line_type: str = "straight"
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    elem = ConnectorElementIR(
        id=f"conn_{uuid.uuid4().hex[:6]}",
        name="Connector Line",
        x=min(start_x, end_x),
        y=min(start_y, end_y),
        width=max(abs(end_x - start_x), 1.0),
        height=max(abs(end_y - start_y), 1.0),
        start_x=start_x,
        start_y=start_y,
        end_x=end_x,
        end_y=end_y,
        arrow_end=arrow_end if arrow_end in ["triangle", "none"] else "triangle",
        arrow_start=arrow_start if arrow_start in ["triangle", "none"] else "none",
        line_type=line_type if line_type in ["straight", "elbow"] else "straight",
        style=ElementStyleIR(border=BorderStyle(color=color, width=width))
    )
    slide.add_element(elem)
    pres.version += 1

    history.record(
        action="add_element",
        description="添加连接线与箭头",
        slide_id=slide.id,
        element_id=elem.id,
        after=elem.model_dump()
    )

    return {"success": True, "element_id": elem.id, "message": "已添加连接线与箭头"}


# =====================================================================
# 3. Modify & Delete Elements Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "update_element",
        "description": "Update element position, size, text content, fill, border or styles by element_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "ID of element to update"},
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "x": {"type": "number"},
                "y": {"type": "number"},
                "width": {"type": "number"},
                "height": {"type": "number"},
                "text": {"type": "string", "description": "Updated text content"},
                "fill_color": {"type": "string", "description": "New fill color hex"},
                "border_color": {"type": "string"},
                "border_width": {"type": "number"},
                "font_size": {"type": "number"},
                "font_color": {"type": "string"},
                "bold": {"type": "boolean"},
                "align": {"type": "string", "enum": ["left", "center", "right"]}
            },
            "required": ["element_id"]
        }
    }
})
def update_element(
    pres: PresentationIR,
    history: HistoryManager,
    element_id: str,
    slide_id: Optional[str] = None,
    x: Optional[float] = None,
    y: Optional[float] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    text: Optional[str] = None,
    fill_color: Optional[str] = None,
    border_color: Optional[str] = None,
    border_width: Optional[float] = None,
    font_size: Optional[float] = None,
    font_color: Optional[str] = None,
    bold: Optional[bool] = None,
    align: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    elem = slide.get_element(element_id)
    if not elem:
        return {"success": False, "error": f"Element {element_id} not found on slide"}

    before_state = elem.model_dump()

    if x is not None:
        elem.x = x
    if y is not None:
        elem.y = y
    if width is not None:
        elem.width = width
    if height is not None:
        elem.height = height

    if fill_color is not None:
        elem.style.fill = FillStyle(type="solid", color=fill_color) if fill_color else FillStyle(type="none")
    if border_color is not None:
        elem.style.border = BorderStyle(color=border_color, width=border_width or 1.0)

    # Text update
    if text is not None:
        if isinstance(elem, TextElementIR) or isinstance(elem, ShapeElementIR):
            f_color = font_color or "#1E293B"
            f_size = font_size or 18.0
            b = bold if bold is not None else False
            a = align or "left"
            elem.text_content = TextContentIR.from_plain_text(
                text,
                font=FontIR(size=f_size, color=f_color, bold=b),
                align=a if a in ["left", "center", "right"] else "left"
            )

    pres.version += 1
    after_state = elem.model_dump()

    history.record(
        action="update_element",
        description=f"更新元素: {element_id}",
        slide_id=slide.id,
        element_id=element_id,
        before=before_state,
        after=after_state
    )

    return {"success": True, "element_id": element_id, "message": f"元素 {element_id} 更新完成"}


@tools.register({
    "type": "function",
    "function": {
        "name": "delete_element",
        "description": "Delete an element from a slide.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "ID of element to delete"},
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"}
            },
            "required": ["element_id"]
        }
    }
})
def delete_element(
    pres: PresentationIR,
    history: HistoryManager,
    element_id: str,
    slide_id: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    elem = slide.get_element(element_id)
    if not elem:
        return {"success": False, "error": f"Element {element_id} not found"}

    before_dump = elem.model_dump()
    slide.remove_element(element_id)
    pres.version += 1

    history.record(
        action="delete_element",
        description=f"删除元素: {element_id}",
        slide_id=slide.id,
        element_id=element_id,
        before=before_dump
    )

    return {"success": True, "message": f"已成功删除元素 {element_id}"}


# =====================================================================
# 4. Layout & Theme Optimization Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "optimize_layout",
        "description": "Automatically align and arrange cards/boxes on a slide into a neat horizontal or grid layout.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "layout_mode": {"type": "string", "enum": ["horizontal_cards", "two_columns", "grid_2x2"], "default": "horizontal_cards"},
                "start_y": {"type": "number", "description": "Top margin for cards in px", "default": 200},
                "gap": {"type": "number", "description": "Spacing between cards in px", "default": 30}
            },
            "required": []
        }
    }
})
def optimize_layout(
    pres: PresentationIR,
    history: HistoryManager,
    slide_id: Optional[str] = None,
    layout_mode: str = "horizontal_cards",
    start_y: float = 200.0,
    gap: float = 30.0
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    # Find shape elements that act like cards
    cards = [e for e in slide.elements if isinstance(e, ShapeElementIR) and e.width >= 100]
    if not cards:
        return {"success": False, "error": "No cards/shapes found on slide to optimize"}

    n = len(cards)
    canvas_w = slide.width  # 1280
    margin = 80.0

    if layout_mode == "horizontal_cards" or (layout_mode == "two_columns" and n <= 2):
        total_gaps = (n - 1) * gap
        avail_w = canvas_w - (margin * 2) - total_gaps
        card_w = max(avail_w / n, 120.0)
        card_h = 320.0

        for idx, c in enumerate(cards):
            c.x = margin + idx * (card_w + gap)
            c.y = start_y
            c.width = card_w
            c.height = card_h

    elif layout_mode == "grid_2x2" or n >= 4:
        cols = 2
        card_w = (canvas_w - (margin * 2) - gap) / 2.0
        card_h = 180.0
        for idx, c in enumerate(cards[:4]):
            col = idx % cols
            row = idx // cols
            c.x = margin + col * (card_w + gap)
            c.y = start_y + row * (card_h + gap)
            c.width = card_w
            c.height = card_h

    pres.version += 1
    history.record(
        action="optimize_layout",
        description=f"自适应规整排版: {layout_mode}",
        slide_id=slide.id
    )

    return {"success": True, "message": f"已按 {layout_mode} 规整排列 {len(cards)} 个模块"}


@tools.register({
    "type": "function",
    "function": {
        "name": "apply_theme",
        "description": "Apply a unified design color palette and style theme to the presentation.",
        "parameters": {
            "type": "object",
            "properties": {
                "theme_preset": {
                    "type": "string",
                    "enum": ["tech_blue", "dark_minimal", "emerald_nature", "warm_corporate"],
                    "default": "tech_blue"
                }
            },
            "required": ["theme_preset"]
        }
    }
})
def apply_theme(pres: PresentationIR, history: HistoryManager, theme_preset: str = "tech_blue") -> Dict[str, Any]:
    presets = {
        "tech_blue": {
            "bg": "#F8FAFC",
            "card_fill": "#FFFFFF",
            "primary": "#2563EB",
            "text": "#0F172A",
            "border": "#E2E8F0"
        },
        "dark_minimal": {
            "bg": "#0B0F19",
            "card_fill": "#1E293B",
            "primary": "#38BDF8",
            "text": "#F8FAFC",
            "border": "#334155"
        },
        "emerald_nature": {
            "bg": "#F0FDF4",
            "card_fill": "#FFFFFF",
            "primary": "#059669",
            "text": "#064E3B",
            "border": "#A7F3D0"
        },
        "warm_corporate": {
            "bg": "#FFFBEB",
            "card_fill": "#FFFFFF",
            "primary": "#D97706",
            "text": "#78350F",
            "border": "#FDE68A"
        }
    }

    t = presets.get(theme_preset, presets["tech_blue"])
    pres.theme["name"] = theme_preset
    pres.theme["primary_color"] = t["primary"]
    pres.theme["background_color"] = t["bg"]

    # Apply background to all slides
    for s in pres.slides:
        s.background.color = t["bg"]
        for el in s.elements:
            if isinstance(el, ShapeElementIR):
                if el.style.fill and el.style.fill.type == "solid":
                    el.style.fill.color = t["card_fill"]
                if el.style.border:
                    el.style.border.color = t["border"]
            elif isinstance(el, TextElementIR):
                for p in el.text_content.paragraphs:
                    for r in p.runs:
                        if r.font:
                            r.font.color = t["text"]

    pres.version += 1
    history.record(
        action="apply_theme",
        description=f"应用主题风格: {theme_preset}"
    )

    return {"success": True, "message": f"已应用 {theme_preset} 全局主题规范"}
