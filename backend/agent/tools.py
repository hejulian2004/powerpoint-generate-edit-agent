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
    ConnectorElementIR, ImageElementIR, TableElementIR, GroupElementIR, ElementStyleIR,
    FillStyle, BorderStyle, ShadowStyle, TextContentIR, ParagraphIR, RunIR, FontIR,
    GradientFill, GradientStop
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

    def validate_arguments(self, name: str, args: Dict[str, Any]) -> Optional[str]:
        """Fail-closed validation of a tool call before any mutation is attempted.

        Returns an error string when the call must not execute, otherwise None.
        """
        if name not in self.handlers:
            return f"Unknown tool: {name}"
        if not isinstance(args, dict):
            return f"Invalid arguments for {name}: expected an object"
        schema = next((s for s in self.schemas if s["function"]["name"] == name), None)
        if schema is not None:
            required = schema["function"].get("parameters", {}).get("required", [])
            missing = [key for key in required if key not in args]
            if missing:
                return f"Missing required arguments for {name}: {', '.join(missing)}"
        return None

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
    prev_active_slide_id = pres.active_slide_id
    new_slide = SlideIR(
        id=f"slide_{uuid.uuid4().hex[:6]}",
        slide_num=slide_num,
        title=title,
        background=FillStyle(type="solid", color=background_color, alpha=1.0)
    )

    if position is not None and 1 <= position <= len(pres.slides):
        insert_idx = position - 1
        pres.slides.insert(insert_idx, new_slide)
        # renumber
        for idx, s in enumerate(pres.slides):
            s.slide_num = idx + 1
    else:
        insert_idx = len(pres.slides)
        pres.slides.append(new_slide)
        new_slide.slide_num = insert_idx + 1

    pres.active_slide_id = new_slide.id
    pres.version += 1

    history.record(
        action="create_slide",
        description=f"创建幻灯片: {title}",
        slide_id=new_slide.id,
        before={"active_slide_id": prev_active_slide_id},
        after=new_slide.model_dump(),
        position=insert_idx,
        prev_active_slide_id=prev_active_slide_id
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
    active_after_delete = pres.active_slide_id
    pres.version += 1

    history.record(
        action="delete_slide",
        description=f"删除幻灯片 #{target_slide.slide_num}",
        slide_id=target_slide.id,
        before=target_slide.model_dump(),
        position=target_idx,
        active_after_delete=active_after_delete
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
                "radius": {"type": "number", "description": "Corner radius in px for roundRect (0 = square; use small values like 0-3 for sharp editorial cards)", "default": 2.0},
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
    radius: float = 2.0,
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
        "description": "Update element position, size, text content, font family, font size, fill, border, radius or styles by element_id.",
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
                "radius": {"type": "number", "description": "Corner radius in px"},
                "opacity": {"type": "number", "description": "Opacity 0.0 to 1.0"},
                "font_family": {"type": "string", "description": "Font family name e.g. 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Inter', 'SimSun'"},
                "font_size": {"type": "number"},
                "font_color": {"type": "string"},
                "bold": {"type": "boolean"},
                "italic": {"type": "boolean"},
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
    radius: Optional[float] = None,
    opacity: Optional[float] = None,
    font_family: Optional[str] = None,
    font_size: Optional[float] = None,
    font_color: Optional[str] = None,
    bold: Optional[bool] = None,
    italic: Optional[bool] = None,
    align: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    elem = slide.get_element(element_id)
    if not elem:
        return {"success": False, "error": f"Element {element_id} not found on slide"}

    before_state = elem.model_dump()

    if isinstance(elem, GroupElementIR):
        dx = (x - elem.x) if x is not None else 0.0
        dy = (y - elem.y) if y is not None else 0.0
        sx = (width / elem.width) if (width is not None and elem.width > 0) else 1.0
        sy = (height / elem.height) if (height is not None and elem.height > 0) else 1.0

        if sx != 1.0 or sy != 1.0:
            elem.scale(sx, sy)
        if dx != 0.0 or dy != 0.0:
            elem.translate(dx, dy)
    else:
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
    if border_width is not None and elem.style.border:
        elem.style.border.width = border_width
    if radius is not None:
        elem.style.radius = radius
    if opacity is not None:
        elem.style.opacity = max(0.0, min(1.0, opacity))

    # Text update
    if text is not None:
        if isinstance(elem, TextElementIR) or isinstance(elem, ShapeElementIR):
            existing_font = None
            existing_align = "left"
            if elem.text_content and elem.text_content.paragraphs:
                p0 = elem.text_content.paragraphs[0]
                existing_align = p0.align
                if p0.runs and p0.runs[0].font:
                    existing_font = p0.runs[0].font

            f_color = font_color or (existing_font.color if existing_font else "#1E293B")
            f_size = font_size or (existing_font.size if existing_font else (28.0 if isinstance(elem, TextElementIR) else 18.0))
            f_family = font_family or (existing_font.name if existing_font else "Segoe UI")
            b = bold if bold is not None else (existing_font.bold if existing_font else False)
            it = italic if italic is not None else (existing_font.italic if existing_font else False)
            a = align or existing_align

            elem.text_content = TextContentIR.from_plain_text(
                text,
                font=FontIR(name=f_family, size=f_size, color=f_color, bold=b, italic=it),
                align=a if a in ["left", "center", "right"] else "left"
            )
    else:
        # In-place typography update on existing text_content.
        # If text_content is empty but typography (color/size/bold/italic) was
        # requested, lazily seed a single placeholder run so that font styling
        # can be applied to a freshly created text/card element.
        if hasattr(elem, "text_content"):
            if not elem.text_content:
                any_typography = any(
                    v is not None
                    for v in (font_family, font_size, font_color, bold, italic, align)
                )
                if any_typography:
                    placeholder = "点击输入文本"
                    elem.text_content = TextContentIR.from_plain_text(
                        placeholder,
                        font=FontIR(
                            name=font_family or "Segoe UI",
                            size=font_size or 18.0,
                            color=font_color or "#1E293B",
                            bold=bold if bold is not None else False,
                            italic=italic if italic is not None else False,
                        ),
                        align=align if align in ["left", "center", "right"] else "left",
                    )
            if elem.text_content:
                for p in elem.text_content.paragraphs:
                    if align and align in ["left", "center", "right"]:
                        p.align = align
                    for r in p.runs:
                        if not r.font:
                            r.font = FontIR()
                        if font_family is not None:
                            r.font.name = font_family
                        if font_size is not None:
                            r.font.size = font_size
                        if font_color is not None:
                            r.font.color = font_color
                        if bold is not None:
                            r.font.bold = bold
                        if italic is not None:
                            r.font.italic = italic

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


@tools.register({
    "type": "function",
    "function": {
        "name": "duplicate_element",
        "description": "Duplicate an existing element with a slight offset.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Element ID to duplicate"},
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"}
            },
            "required": ["element_id"]
        }
    }
})
def duplicate_element(
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
        return {"success": False, "error": "Element not found"}

    new_dump = elem.model_dump()
    new_dump["id"] = f"{elem.type}_{uuid.uuid4().hex[:6]}"
    new_dump["x"] = elem.x + 20.0
    new_dump["y"] = elem.y + 20.0

    from ..ir.models import ShapeElementIR, TextElementIR, ConnectorElementIR, ImageElementIR, TableElementIR
    type_map = {
        "shape": ShapeElementIR,
        "text": TextElementIR,
        "connector": ConnectorElementIR,
        "image": ImageElementIR,
        "table": TableElementIR
    }
    cls = type_map.get(elem.type, ShapeElementIR)
    new_elem = cls(**new_dump)
    slide.add_element(new_elem)
    pres.version += 1

    history.record(
        action="add_element",
        description=f"复制图元: {element_id}",
        slide_id=slide.id,
        element_id=new_elem.id,
        after=new_elem.model_dump()
    )
    return {"success": True, "new_element_id": new_elem.id}


@tools.register({
    "type": "function",
    "function": {
        "name": "set_slide_background",
        "description": "Set background color of a slide.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Target slide ID or empty for active slide"},
                "color": {"type": "string", "description": "Hex color like #FFFFFF or #0F172A"}
            },
            "required": ["color"]
        }
    }
})
def set_slide_background(
    pres: PresentationIR,
    history: HistoryManager,
    color: str,
    slide_id: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    old_color = getattr(slide.background, "color", "#FFFFFF")
    slide.background.color = color
    slide.background.type = "solid"
    pres.version += 1

    history.record(
        action="set_slide_background",
        description=f"修改背景色: {color}",
        slide_id=slide.id,
        before={"color": old_color},
        after={"color": color}
    )
    return {"success": True, "color": color, "slide_id": slide.id}


@tools.register({
    "type": "function",
    "function": {
        "name": "group_elements",
        "description": "Group multiple elements on a slide into a single group container.",
        "parameters": {
            "type": "object",
            "properties": {
                "element_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of element IDs to group together"
                },
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "group_name": {"type": "string", "description": "Display name for the new group", "default": "Group"}
            },
            "required": ["element_ids"]
        }
    }
})
def group_elements(
    pres: PresentationIR,
    history: HistoryManager,
    element_ids: List[str],
    slide_id: Optional[str] = None,
    group_name: str = "Group"
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    grp = slide.group_elements(element_ids, group_name=group_name)
    if not grp:
        return {"success": False, "error": "Could not group specified elements (need at least 2 valid top-level elements)"}

    pres.version += 1
    history.record(
        action="group_elements",
        description=f"组合 {len(element_ids)} 个图元为组: {group_name}",
        slide_id=slide.id,
        element_id=grp.id,
        after=grp.model_dump()
    )
    return {
        "success": True,
        "group_id": grp.id,
        "x": grp.x,
        "y": grp.y,
        "width": grp.width,
        "height": grp.height,
        "children_count": len(grp.children),
        "message": f"成功将 {len(grp.children)} 个图元组合为组 '{group_name}'"
    }


@tools.register({
    "type": "function",
    "function": {
        "name": "ungroup_elements",
        "description": "Dissolve a group element on a slide, restoring its children to top-level elements.",
        "parameters": {
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "description": "ID of group element to ungroup"},
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"}
            },
            "required": ["group_id"]
        }
    }
})
def ungroup_elements(
    pres: PresentationIR,
    history: HistoryManager,
    group_id: str,
    slide_id: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    children = slide.ungroup_elements(group_id)
    if not children:
        return {"success": False, "error": f"Group '{group_id}' not found or has no children"}

    pres.version += 1
    history.record(
        action="ungroup_elements",
        description=f"解散组: {group_id}",
        slide_id=slide.id,
        element_id=group_id,
        after={"restored_elements": [c.model_dump() for c in children]}
    )
    return {
        "success": True,
        "restored_count": len(children),
        "child_ids": [c.id for c in children],
        "message": f"成功解散组，已恢复 {len(children)} 个独立图元"
    }


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


DESIGN_TOKENS: Dict[str, Dict[str, str]] = {
    # Light, technical-editorial: precision instrument / inspection-sheet aesthetic.
    "monochrome_studio": {
        "bg": "#F6F7F8", "surface": "#FFFFFF", "ink": "#16181D",
        "muted": "#5A6472", "hairline": "#DFE3E8", "accent": "#C2410C",
        "accent_soft": "#F6E7E0", "dark": "0",
    },
    "editorial_technical": {
        "bg": "#F4F5F7", "surface": "#FFFFFF", "ink": "#101418",
        "muted": "#5B6470", "hairline": "#D9DEE3", "accent": "#C2410C",
        "accent_soft": "#F7E8E4", "dark": "0",
    },
    "tech_blue": {
        "bg": "#F6F8FB", "surface": "#FFFFFF", "ink": "#0F172A",
        "muted": "#5B6470", "hairline": "#DCE3EC", "accent": "#0E7490",
        "accent_soft": "#E1F1F5", "dark": "0",
    },
    "emerald_nature": {
        "bg": "#F2F7F3", "surface": "#FFFFFF", "ink": "#0E2A1E",
        "muted": "#4E6B5A", "hairline": "#D6E4DA", "accent": "#047857",
        "accent_soft": "#E0F2E8", "dark": "0",
    },
    "warm_corporate": {
        "bg": "#FAF6EF", "surface": "#FFFFFF", "ink": "#3B2A14",
        "muted": "#7A6A4E", "hairline": "#E7DECD", "accent": "#B45309",
        "accent_soft": "#F7E8D5", "dark": "0",
    },
    "stark_white": {
        "bg": "#FFFFFF", "surface": "#FFFFFF", "ink": "#14161A",
        "muted": "#62666B", "hairline": "#E3E4E6", "accent": "#111318",
        "accent_soft": "#ECECEE", "dark": "0",
    },
    # Dark, engineering-console: measurement readout / inspection terminal.
    "dark_minimal": {
        "bg": "#101318", "surface": "#1A1E25", "ink": "#ECEFF2",
        "muted": "#8B93A0", "hairline": "#2A2F38", "accent": "#38BDF8",
        "accent_soft": "#12283A", "dark": "1",
    },
    "engineering_dark": {
        "bg": "#111418", "surface": "#191D22", "ink": "#E8ECEF",
        "muted": "#8A929C", "hairline": "#262C33", "accent": "#E8A33D",
        "accent_soft": "#2B2415", "dark": "1",
    },
    "slate_silver": {
        "bg": "#0E1014", "surface": "#181B21", "ink": "#F1F2F6",
        "muted": "#949AA4", "hairline": "#2B2F37", "accent": "#E2E8F0",
        "accent_soft": "#1E2128", "dark": "1",
    },
    "matte_graphite": {
        "bg": "#1E2733", "surface": "#2B3542", "ink": "#F6F8FA",
        "muted": "#A6B0BC", "hairline": "#3A4656", "accent": "#F8FAFC",
        "accent_soft": "#29313D", "dark": "1",
    },
}


def _theme_tokens(pres: PresentationIR) -> Dict[str, str]:
    """Resolves the active semantic design tokens for a presentation."""
    name = (pres.theme or {}).get("name", "editorial_technical")
    return dict(DESIGN_TOKENS.get(name, DESIGN_TOKENS["editorial_technical"]))


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
                    "enum": ["editorial_technical", "monochrome_studio", "tech_blue", "engineering_dark", "dark_minimal", "emerald_nature", "warm_corporate", "stark_white", "slate_silver", "matte_graphite"],
                    "default": "editorial_technical"
                }
            },
            "required": ["theme_preset"]
        }
    }
})


def apply_theme(pres: PresentationIR, history: HistoryManager, theme_preset: str = "tech_blue") -> Dict[str, Any]:
    """Applies a semantic design palette. Recolors the existing deck so that
    surface/in̶k/muted/hairline/accent roles are remapped — not flattened to one color.
    """
    if theme_preset not in DESIGN_TOKENS:
        theme_preset = "editorial_technical"
    t = DESIGN_TOKENS[theme_preset]

    pres.theme["name"] = theme_preset
    pres.theme["primary_color"] = t["accent"]
    pres.theme["background_color"] = t["bg"]

    # Map from the tokens the deck was built with (stored on first apply) so that
    # semantic roles (surface/ink/muted/hairline/accent) are remapped, not flattened.
    old = pres.theme.get("_prev_tokens") or dict(DESIGN_TOKENS["editorial_technical"])

    def remap(color: str) -> str:
        if not color:
            return color
        lc = color.lower()
        for key in ("bg", "surface", "ink", "muted", "hairline", "accent", "accent_soft"):
            if lc == old.get(key, "").lower():
                return t[key]
        return color

    for s in pres.slides:
        s.background.color = t["bg"]
        for el in s.elements:
            if isinstance(el, ShapeElementIR):
                if el.style.fill and el.style.fill.type == "solid":
                    el.style.fill.color = remap(el.style.fill.color)
                if el.style.fill and el.style.fill.type == "gradient" and el.style.fill.gradient:
                    for st in el.style.fill.gradient.stops:
                        st.color = remap(st.color)
                if el.style.border:
                    el.style.border.color = remap(el.style.border.color)
            elif isinstance(el, TextElementIR):
                for p in el.text_content.paragraphs:
                    for r in p.runs:
                        if r.font:
                            r.font.color = remap(r.font.color)

    pres.theme["_prev_tokens"] = dict(t)
    pres.version += 1
    history.record(
        action="apply_theme",
        description=f"应用主题风格: {theme_preset}"
    )

    return {"success": True, "message": f"已应用 {theme_preset} 全局主题规范"}


# =====================================================================
# 5. Advanced PPT Generation & Archetype Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "generate_presentation",
        "description": "Generate a full multi-slide presentation deck from topic, outline, and layout specifications.",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Presentation topic or title"},
                "slides": {
                    "type": "array",
                    "description": "List of slide specifications to generate",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Slide title"},
                            "layout": {
                                "type": "string",
                                "enum": ["title_slide", "card_grid", "timeline", "kpi_metrics", "comparison"],
                                "description": "Slide layout archetype"
                            },
                            "subtitle": {"type": "string", "description": "Subtitle or description"},
                            "items": {
                                "type": "array",
                                "description": "Items/cards/steps/metrics content for the slide",
                                "items": {"type": "object"}
                            }
                        },
                        "required": ["title", "layout"]
                    }
                },
                "theme": {
                    "type": "string",
                    "enum": ["editorial_technical", "monochrome_studio", "tech_blue", "engineering_dark", "dark_minimal", "emerald_nature", "warm_corporate", "stark_white", "slate_silver", "matte_graphite"],
                    "default": "editorial_technical"
                },
                "replace": {
                    "type": "boolean",
                    "description": "If true, replaces all current slides; if false, appends to existing presentation",
                    "default": True
                }
            },
            "required": ["topic", "slides"]
        }
    }
})
def generate_presentation(
    pres: PresentationIR,
    history: HistoryManager,
    topic: str,
    slides: List[Dict[str, Any]],
    theme: str = "editorial_technical",
    replace: bool = True
) -> Dict[str, Any]:
    pres.title = topic

    if replace:
        pres.slides.clear()

    start_num = len(pres.slides) + 1
    new_slides: List[SlideIR] = []

    for i, s_spec in enumerate(slides):
        s_title = s_spec.get("title", f"Slide {i + 1}")
        s_layout = s_spec.get("layout", "card_grid")
        s_subtitle = s_spec.get("subtitle", "")
        s_items = s_spec.get("items", [])

        slide_id = f"slide_{uuid.uuid4().hex[:6]}"
        slide = SlideIR(
            id=slide_id,
            slide_num=start_num + i,
            title=s_title,
            background=FillStyle(type="solid", color="#FFFFFF")
        )

        _build_slide_elements_by_layout(slide, s_title, s_layout, s_subtitle, s_items)
        new_slides.append(slide)
        pres.slides.append(slide)

    if pres.slides:
        pres.active_slide_id = pres.slides[0].id

    # Apply chosen theme
    apply_theme(pres, history, theme_preset=theme)

    pres.version += 1
    history.record(
        action="generate_presentation",
        description=f"生成完整演示文稿: {topic} (共 {len(new_slides)} 页)"
    )

    return {
        "success": True,
        "topic": topic,
        "slides_count": len(pres.slides),
        "generated_count": len(new_slides),
        "message": f"成功生成《{topic}》演示文稿，包含 {len(new_slides)} 页精美幻灯片。"
    }


def _build_slide_elements_by_layout(
    slide: SlideIR,
    title: str,
    layout: str,
    subtitle: str = "",
    items: Optional[List[Dict[str, Any]]] = None
):
    """Populates slide elements based on design archetypes.

    Design language — technical editorial / inspection sheet:
    - Sharp corners (radius <= 2) instead of large rounded cards.
    - Hairline rules instead of heavy drop shadows on every card.
    - A single accent used as a structural device (edge bars, rules, numerals),
      with quiet neutral surfaces.
    - Numbered markers only where the content is a real sequence (timeline).
    """
    items = items or []

    dark = slide.background.color.lower() in ["#0a0a0a", "#0b0f19", "#000000", "#121212", "#111418", "#0e1014", "#101318", "#1e2733"]
    ink = "#E8ECEF" if dark else "#16181D"
    muted = "#8A929C" if dark else "#5A6472"
    surface = "#191D22" if dark else "#FFFFFF"
    hairline = "#262C33" if dark else "#DFE3E8"
    accent = "#E8A33D" if dark else "#C2410C"
    accent_soft = "#2B2415" if dark else "#F7E8E4"

    def add_text(eid, name, x, y, w, h, text, size, color, bold=False, align="left"):
        slide.elements.append(TextElementIR(
            id=eid,
            name=name,
            x=x, y=y, width=w, height=h,
            text_content=TextContentIR.from_plain_text(
                text, font=FontIR(size=size, color=color, bold=bold), align=align
            )
        ))

    def add_rule(eid, x, y, w, h, color, width=1.5, alpha=1.0):
        slide.elements.append(ShapeElementIR(
            id=eid, name="Rule",
            shape_type="rect", x=x, y=y, width=w, height=h,
            style=ElementStyleIR(fill=FillStyle(type="solid", color=color, alpha=alpha))
        ))

    def add_grad_bar(eid, name, x, y, w, h, c1, c2, angle=90.0, alpha=1.0):
        """Decorative two-color gradient accent bar/rule (accent -> accent_soft)."""
        slide.elements.append(ShapeElementIR(
            id=eid, name=name,
            shape_type="rect", x=x, y=y, width=w, height=h,
            style=ElementStyleIR(fill=FillStyle(
                type="gradient",
                gradient=GradientFill(
                    type="linear",
                    angle=angle,
                    stops=[
                        GradientStop(position=0.0, color=c1, alpha=alpha),
                        GradientStop(position=1.0, color=c2, alpha=alpha),
                    ]
                )
            ))
        ))

    def add_panel(eid, name, x, y, w, h, fill=None, border=None, radius=1.5):
        slide.elements.append(ShapeElementIR(
            id=eid, name=name,
            shape_type="roundRect", x=x, y=y, width=w, height=h,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color=fill or surface),
                border=BorderStyle(color=border or hairline, width=1.0),
                radius=radius
            )
        ))

    def header(kicker: str = "01"):
        """Shared editorial header: kicker + title + hairline rule."""
        add_text(f"kick_{uuid.uuid4().hex[:6]}", "Kicker", 100, 64, 400, 22,
                 kicker, 13.0, accent, bold=True)
        add_text(f"title_{uuid.uuid4().hex[:6]}", "Slide Title", 100, 92, 1080, 52,
                 title, 34.0, ink, bold=True)
        if subtitle:
            add_text(f"sub_{uuid.uuid4().hex[:6]}", "Slide Subtitle", 100, 148, 1080, 30,
                     subtitle, 15.0, muted)
        # Gradient underline sweep from accent -> transparent for a refined accent.
        add_grad_bar(f"gbar_{uuid.uuid4().hex[:6]}", "Gradient Rule", 100, 194, 1080, 3,
                     accent, accent_soft, angle=90.0, alpha=0.9)

    if layout == "title_slide":
        # Editorial hero: left-aligned kicker, oversized title, hairline, subtitle.
        add_text(f"kick_{uuid.uuid4().hex[:6]}", "Kicker", 100, 190, 700, 24,
                 "RESEARCH · CV · AGENTIC AI", 13.0, accent, bold=True)
        add_text(f"title_{uuid.uuid4().hex[:6]}", "Hero Title", 100, 226, 1080, 130,
                 title, 48.0, ink, bold=True)
        add_rule(f"rule_{uuid.uuid4().hex[:6]}", 100, 384, 1080, 2, hairline)
        if subtitle:
            add_text(f"sub_{uuid.uuid4().hex[:6]}", "Hero Subtitle", 100, 410, 920, 64,
                     subtitle, 19.0, muted)
        # Left accent edge bar (gradient sweep for a polished look)
        add_grad_bar(f"edge_{uuid.uuid4().hex[:6]}", "Accent Edge", 0, 0, 8, 720,
                     accent, accent_soft, angle=180.0, alpha=1.0)
        # Section index block (bottom-left)
        add_text(f"idx_{uuid.uuid4().hex[:6]}", "Index", 100, 620, 300, 30,
                 "01 / OVERVIEW", 12.0, accent, bold=True)

    elif layout == "card_grid":
        header("02 / CONTENT")
        n = len(items) if items else 3
        margin = 100.0
        gap = 28.0
        start_y = 230.0
        avail_w = 1280.0 - (margin * 2) - (n - 1) * gap
        card_w = max(avail_w / n, 150.0)
        card_h = 400.0

        for idx, item in enumerate(items or [{"title": f"核心特性 {idx+1}", "description": "详细描述与架构说明"} for idx in range(3)]):
            cx = margin + idx * (card_w + gap)
            item_title = item.get("title", f"Feature {idx+1}")
            item_desc = item.get("description", "")

            # Quiet surface panel, sharp corner, hairline border, gradient accent top edge
            add_panel(f"card_{idx}_{uuid.uuid4().hex[:6]}", f"Card {idx+1}",
                      cx, start_y, card_w, card_h)
            add_grad_bar(f"top_{idx}_{uuid.uuid4().hex[:6]}", "Card Accent", cx, start_y, card_w, 3,
                         accent, accent_soft, angle=90.0, alpha=0.9)
            add_text(f"ct_{idx}_{uuid.uuid4().hex[:6]}", f"Card Title {idx+1}",
                     cx + 20, start_y + 22, card_w - 40, 28,
                     item_title, 17.0, ink, bold=True)
            add_text(f"cd_{idx}_{uuid.uuid4().hex[:6]}", f"Card Desc {idx+1}",
                     cx + 20, start_y + 60, card_w - 40, card_h - 90,
                     item_desc, 13.5, muted)

    elif layout == "timeline":
        header("03 / TIMELINE")
        steps = items or [
            {"title": "阶段一: 需求分析", "description": "定义核心流程与目标"},
            {"title": "阶段二: 架构研发", "description": "设计中间件与工具链"},
            {"title": "阶段三: 质检上线", "description": "自动化验证与全面交付"}
        ]
        n = len(steps)
        margin = 100.0
        gap = 40.0
        step_w = (1280.0 - (margin * 2) - (n - 1) * gap) / n
        cy = 320.0

        # Connecting hairline spine
        add_rule(f"spine_{uuid.uuid4().hex[:6]}", margin, cy + 20, 1280.0 - margin * 2, 2, hairline)

        for idx, st in enumerate(steps):
            cx = margin + idx * (step_w + gap)
            st_title = st.get("title", f"Step {idx+1}")
            st_desc = st.get("description", "")

            # Node numeral (real sequence -> numbered marker is meaningful)
            add_text(f"num_{idx}_{uuid.uuid4().hex[:6]}", f"Step Num {idx+1}",
                     cx, cy - 46, step_w, 40, f"{idx+1:02d}", 30.0, accent, bold=True)
            # Step panel below spine
            add_panel(f"step_{idx}_{uuid.uuid4().hex[:6]}", f"Timeline Step {idx+1}",
                      cx, cy + 56, step_w, 210)
            add_text(f"st_{idx}_{uuid.uuid4().hex[:6]}", f"Step Title {idx+1}",
                     cx + 20, cy + 76, step_w - 40, 30, st_title, 16.0, ink, bold=True)
            add_text(f"sd_{idx}_{uuid.uuid4().hex[:6]}", f"Step Desc {idx+1}",
                     cx + 20, cy + 114, step_w - 40, 120, st_desc, 13.0, muted)

            # Accent node dot on the spine
            slide.elements.append(ShapeElementIR(
                id=f"dot_{idx}_{uuid.uuid4().hex[:6]}", name=f"Node {idx+1}",
                shape_type="ellipse", x=cx + step_w / 2 - 6, y=cy + 14, width=12, height=12,
                style=ElementStyleIR(fill=FillStyle(type="solid", color=accent))
            ))

    elif layout == "kpi_metrics":
        header("04 / METRICS")
        stats = items or [
            {"value": "99.9%", "label": "系统高可用性", "subtext": "SLA 严格达标保证"},
            {"value": "10x", "label": "PPT 制作效率提升", "subtext": "自动化秒级编排"},
            {"value": "< 500ms", "label": "双向渲染延迟", "subtext": "实时高保真同步"}
        ]
        n = len(stats)
        margin = 100.0
        gap = 40.0
        col_w = (1280.0 - (margin * 2) - (n - 1) * gap) / n
        cy = 250.0

        for idx, st in enumerate(stats):
            cx = margin + idx * (col_w + gap)
            val = st.get("value", "100%")
            lbl = st.get("label", "Metric")
            sub = st.get("subtext", "")

            # Oversized numeral is the hero; hairline separator beneath.
            add_rule(f"sep_{idx}_{uuid.uuid4().hex[:6]}", cx, cy, col_w, 2, hairline)
            # First metric gets a gradient underline accent bar to draw the eye.
            if idx == 0:
                add_grad_bar(f"gv_{idx}_{uuid.uuid4().hex[:6]}", "Metric Gradient", cx, cy + 2, 64, 3,
                             accent, accent_soft, angle=90.0, alpha=0.9)
            add_text(f"val_{idx}_{uuid.uuid4().hex[:6]}", f"Metric Value {idx+1}",
                     cx, cy + 20, col_w, 70, val, 48.0, accent if idx == 0 else ink, bold=True)
            add_text(f"lbl_{idx}_{uuid.uuid4().hex[:6]}", f"Metric Label {idx+1}",
                     cx, cy + 104, col_w, 28, lbl, 15.0, ink, bold=True)
            add_text(f"sub_{idx}_{uuid.uuid4().hex[:6]}", f"Metric Sub {idx+1}",
                     cx, cy + 138, col_w, 40, sub, 12.5, muted)

    elif layout == "comparison":
        header("05 / COMPARISON")
        cols = items or [
            {"title": "传统设计模式", "description": "• 手动反复排版与校对\n• 耗时耗力且样式易冲突\n• 跨平台协同效率低"},
            {"title": "Agentic AI 架构", "description": "• PPT-IR 核心结构解耦\n• 自然语言驱动自动化生成\n• 实时渲染与无损 OOXML 导出"}
        ]
        col_w = 510.0
        col_h = 400.0
        cy = 230.0

        for idx, col in enumerate(cols[:2]):
            cx = 100.0 if idx == 0 else 670.0
            c_title = col.get("title", f"Column {idx+1}")
            c_desc = col.get("description", "")
            is_highlight = idx == 1

            add_panel(f"col_{idx}_{uuid.uuid4().hex[:6]}", f"Column {idx+1}",
                      cx, cy, col_w, col_h,
                      border=accent if is_highlight else hairline)
            if is_highlight:
                add_rule(f"cacc_{idx}_{uuid.uuid4().hex[:6]}", cx, cy, 4, col_h, accent)
            add_text(f"ct_{idx}_{uuid.uuid4().hex[:6]}", f"Column Title {idx+1}",
                     cx + 24, cy + 24, col_w - 48, 30,
                     c_title, 18.0, accent if is_highlight else ink, bold=True)
            add_text(f"cd_{idx}_{uuid.uuid4().hex[:6]}", f"Column Desc {idx+1}",
                     cx + 24, cy + 68, col_w - 48, col_h - 96,
                     c_desc, 14.0, muted)


@tools.register({
    "type": "function",
    "function": {
        "name": "generate_slide_layout",
        "description": "Generate a full structured slide layout (card_grid, timeline, kpi_metrics, comparison, title_slide) on the current or targeted slide.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Target slide ID or empty for active slide"},
                "layout_type": {
                    "type": "string",
                    "enum": ["card_grid", "timeline", "kpi_metrics", "comparison", "title_slide"],
                    "default": "card_grid"
                },
                "title": {"type": "string", "description": "Slide title"},
                "subtitle": {"type": "string", "description": "Optional subtitle", "default": ""},
                "items": {
                    "type": "array",
                    "description": "Items data list for the layout",
                    "items": {"type": "object"}
                },
                "clear_existing": {"type": "boolean", "description": "Whether to clear existing elements before populating", "default": True}
            },
            "required": ["title", "layout_type"]
        }
    }
})
def generate_slide_layout(
    pres: PresentationIR,
    history: HistoryManager,
    title: str,
    layout_type: str = "card_grid",
    slide_id: Optional[str] = None,
    subtitle: str = "",
    items: Optional[List[Dict[str, Any]]] = None,
    clear_existing: bool = True
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    if clear_existing:
        slide.elements.clear()

    slide.title = title
    _build_slide_elements_by_layout(slide, title, layout_type, subtitle, items)

    pres.version += 1
    history.record(
        action="generate_slide_layout",
        description=f"排版生成页面: {layout_type} - {title}",
        slide_id=slide.id
    )

    return {
        "success": True,
        "slide_id": slide.id,
        "elements_count": len(slide.elements),
        "message": f"已在第 {slide.slide_num} 页成功生成 {layout_type} 布局架构"
    }


@tools.register({
    "type": "function",
    "function": {
        "name": "batch_add_cards",
        "description": "Add multiple neatly arranged cards across the canvas with calculated spacing.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Target slide ID or empty for active slide"},
                "cards": {
                    "type": "array",
                    "description": "List of cards with title, description, badge, and optional color",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "badge": {"type": "string"}
                        },
                        "required": ["title"]
                    }
                },
                "start_y": {"type": "number", "description": "Top margin for cards", "default": 200},
                "card_height": {"type": "number", "default": 360}
            },
            "required": ["cards"]
        }
    }
})
def batch_add_cards(
    pres: PresentationIR,
    history: HistoryManager,
    cards: List[Dict[str, Any]],
    slide_id: Optional[str] = None,
    start_y: float = 200.0,
    card_height: float = 360.0
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    n = len(cards)
    if n == 0:
        return {"success": False, "error": "Cards list cannot be empty"}

    margin = 100.0
    gap = 24.0
    avail_w = 1280.0 - (margin * 2) - (n - 1) * gap
    card_w = max(avail_w / n, 140.0)

    is_dark = slide.background.color.lower() in ["#0a0a0a", "#0b0f19", "#000000", "#121212", "#111418", "#0e1014", "#101318", "#1e2733"]
    text_c = "#E8ECEF" if is_dark else "#16181D"
    muted_c = "#8A929C" if is_dark else "#5A6472"
    card_bg = "#191D22" if is_dark else "#FFFFFF"
    border_c = "#262C33" if is_dark else "#DFE3E8"
    accent_c = "#E8A33D" if is_dark else "#C2410C"

    added_ids = []
    for idx, card in enumerate(cards):
        cx = margin + idx * (card_w + gap)
        c_title = card.get("title", f"Card {idx+1}")
        c_desc = card.get("description", "")

        elem = ShapeElementIR(
            id=f"card_{uuid.uuid4().hex[:6]}",
            name=c_title,
            shape_type="roundRect",
            x=cx,
            y=start_y,
            width=card_w,
            height=card_height,
            style=ElementStyleIR(
                fill=FillStyle(type="solid", color=card_bg),
                border=BorderStyle(color=border_c, width=1.0),
                radius=1.5
            ),
            text_content=TextContentIR.from_plain_text(
                f"{c_title}\n\n{c_desc}",
                font=FontIR(size=15.0, color=text_c),
                align="left"
            )
        )
        slide.add_element(elem)
        added_ids.append(elem.id)

        # Accent top edge as a structural device instead of a badge in the text
        slide.add_element(ShapeElementIR(
            id=f"edge_{uuid.uuid4().hex[:6]}",
            name=f"Card Edge {idx+1}",
            shape_type="rect",
            x=cx,
            y=start_y,
            width=card_w,
            height=3,
            style=ElementStyleIR(fill=FillStyle(type="solid", color=accent_c))
        ))

    pres.version += 1
    history.record(
        action="batch_add_cards",
        description=f"批量添加 {n} 张卡片",
        slide_id=slide.id
    )

    return {"success": True, "added_count": n, "element_ids": added_ids, "message": f"成功批量添加 {n} 个卡片"}


# =====================================================================
# 6. Advanced Modification & Formatting Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "format_text",
        "description": "Fine-grained text typography formatting for an element (font size, color, bold, alignment).",
        "parameters": {
            "type": "object",
            "properties": {
                "element_id": {"type": "string", "description": "Target element ID"},
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "font_family": {"type": "string", "description": "Font family name"},
                "font_size": {"type": "number", "description": "Font size in px"},
                "font_color": {"type": "string", "description": "Hex color like #FFFFFF"},
                "bold": {"type": "boolean"},
                "align": {"type": "string", "enum": ["left", "center", "right"]}
            },
            "required": ["element_id"]
        }
    }
})
def format_text(
    pres: PresentationIR,
    history: HistoryManager,
    element_id: str,
    slide_id: Optional[str] = None,
    font_family: Optional[str] = None,
    font_size: Optional[float] = None,
    font_color: Optional[str] = None,
    bold: Optional[bool] = None,
    align: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    elem = slide.get_element(element_id)
    if not elem or not hasattr(elem, "text_content") or not elem.text_content:
        return {"success": False, "error": f"Element {element_id} has no text content to format"}

    for p in elem.text_content.paragraphs:
        if align and align in ["left", "center", "right"]:
            p.align = align
        for r in p.runs:
            if not r.font:
                r.font = FontIR()
            if font_family is not None:
                r.font.name = font_family
            if font_size is not None:
                r.font.size = font_size
            if font_color is not None:
                r.font.color = font_color
            if bold is not None:
                r.font.bold = bold

    pres.version += 1
    history.record(
        action="format_text",
        description=f"格式化文本: {element_id}",
        slide_id=slide.id,
        element_id=element_id
    )

    return {"success": True, "element_id": element_id, "message": "文本排版格式已更新"}


@tools.register({
    "type": "function",
    "function": {
        "name": "align_elements",
        "description": "Align or distribute elements on the slide (left, center, right, top, middle, bottom, distribute_h, distribute_v).",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "element_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of element IDs to align. If empty, aligns all shape/card elements."
                },
                "alignment": {
                    "type": "string",
                    "enum": ["left", "center", "right", "top", "middle", "bottom", "distribute_h", "distribute_v"],
                    "default": "center"
                }
            },
            "required": ["alignment"]
        }
    }
})
def align_elements(
    pres: PresentationIR,
    history: HistoryManager,
    alignment: str = "center",
    slide_id: Optional[str] = None,
    element_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    targets = []
    if element_ids:
        targets = [e for e in slide.elements if e.id in element_ids]
    else:
        targets = [e for e in slide.elements if isinstance(e, ShapeElementIR)]

    if len(targets) < 2 and alignment.startswith("distribute"):
        return {"success": False, "error": "Need at least 2 elements to distribute"}
    if not targets:
        return {"success": False, "error": "No elements found to align"}

    if alignment == "left":
        min_x = min(e.x for e in targets)
        for e in targets:
            e.x = min_x
    elif alignment == "right":
        max_r = max(e.x + e.width for e in targets)
        for e in targets:
            e.x = max_r - e.width
    elif alignment == "top":
        min_y = min(e.y for e in targets)
        for e in targets:
            e.y = min_y
    elif alignment == "bottom":
        max_b = max(e.y + e.height for e in targets)
        for e in targets:
            e.y = max_b - e.height
    elif alignment == "center":
        avg_cx = sum(e.x + e.width / 2.0 for e in targets) / len(targets)
        for e in targets:
            e.x = avg_cx - e.width / 2.0
    elif alignment == "middle":
        avg_cy = sum(e.y + e.height / 2.0 for e in targets) / len(targets)
        for e in targets:
            e.y = avg_cy - e.height / 2.0
    elif alignment == "distribute_h":
        targets.sort(key=lambda e: e.x)
        min_x = targets[0].x
        max_x = targets[-1].x + targets[-1].width
        total_elems_w = sum(e.width for e in targets)
        if len(targets) > 1 and max_x - min_x > total_elems_w:
            gap = (max_x - min_x - total_elems_w) / (len(targets) - 1)
            curr_x = min_x
            for e in targets:
                e.x = curr_x
                curr_x += e.width + gap

    pres.version += 1
    history.record(
        action="align_elements",
        description=f"对齐图元: {alignment}",
        slide_id=slide.id
    )

    return {"success": True, "alignment": alignment, "count": len(targets), "message": f"已对 {len(targets)} 个图元执行 {alignment} 对齐"}


@tools.register({
    "type": "function",
    "function": {
        "name": "clear_slide_elements",
        "description": "Clear all elements or non-title elements on a slide to start fresh.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "keep_title": {"type": "boolean", "default": True}
            },
            "required": []
        }
    }
})
def clear_slide_elements(
    pres: PresentationIR,
    history: HistoryManager,
    slide_id: Optional[str] = None,
    keep_title: bool = True
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    if keep_title:
        # Keep title elements (y < 150 and is TextElementIR)
        slide.elements = [e for e in slide.elements if isinstance(e, TextElementIR) and e.y < 150]
    else:
        slide.elements.clear()

    pres.version += 1
    history.record(
        action="clear_slide_elements",
        description=f"清理页面元素 (keep_title={keep_title})",
        slide_id=slide.id
    )

    return {"success": True, "remaining": len(slide.elements), "message": f"已清空第 {slide.slide_num} 页内容"}


@tools.register({
    "type": "function",
    "function": {
        "name": "duplicate_slide",
        "description": "Duplicate an existing slide by slide_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID to duplicate"}
            },
            "required": ["slide_id"]
        }
    }
})
def duplicate_slide(pres: PresentationIR, history: HistoryManager, slide_id: str) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id)
    if not slide:
        return {"success": False, "error": "Slide not found"}

    idx = pres.slides.index(slide)
    prev_active_slide_id = pres.active_slide_id
    new_slide_dict = copy.deepcopy(slide.model_dump())
    new_slide_dict["id"] = f"slide_{uuid.uuid4().hex[:6]}"
    new_slide_dict["slide_num"] = idx + 2
    new_slide_dict["title"] = f"{slide.title or 'Slide'} (副本)"

    for el in new_slide_dict.get("elements", []):
        el["id"] = f"{el.get('type', 'el')}_{uuid.uuid4().hex[:6]}"

    new_slide = SlideIR(**new_slide_dict)
    pres.slides.insert(idx + 1, new_slide)

    for i, s in enumerate(pres.slides):
        s.slide_num = i + 1

    pres.active_slide_id = new_slide.id
    pres.version += 1

    history.record(
        action="duplicate_slide",
        description=f"复制幻灯片 #{slide.slide_num}",
        slide_id=new_slide.id,
        before={"active_slide_id": prev_active_slide_id},
        after=new_slide.model_dump(),
        position=idx + 1,
        prev_active_slide_id=prev_active_slide_id
    )

    return {"success": True, "new_slide_id": new_slide.id, "slide_num": new_slide.slide_num, "message": f"已成功复制幻灯片为第 {new_slide.slide_num} 页"}


# =====================================================================
# 7. Visual Evaluation & Self-Healing Tools
# =====================================================================

@tools.register({
    "type": "function",
    "function": {
        "name": "evaluate_layout",
        "description": "Perform comprehensive visual geometry and WCAG contrast inspection on a slide, returning quality health score and defects.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"}
            },
            "required": []
        }
    }
})
def evaluate_layout(
    pres: PresentationIR,
    history: HistoryManager,
    slide_id: Optional[str] = None
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    from ..quality import QualityService
    report = QualityService.evaluate_slide(slide)
    return {
        "success": True,
        "slide_id": slide.id,
        "score": report.score,
        "summary": report.summary(),
        "report": report.to_dict()
    }


@tools.register({
    "type": "function",
    "function": {
        "name": "auto_fix_layout",
        "description": "Automatically detect and safely remediate layout defects with transaction rollback protection.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_id": {"type": "string", "description": "Slide ID or empty for active slide"},
                "only_critical": {"type": "boolean", "default": False, "description": "If False, also addresses structural spacing/alignments"}
            },
            "required": []
        }
    }
})
def auto_fix_layout(
    pres: PresentationIR,
    history: HistoryManager,
    slide_id: Optional[str] = None,
    only_critical: bool = False
) -> Dict[str, Any]:
    slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
    if not slide:
        return {"success": False, "error": "Slide not found"}

    from ..quality import QualityService
    from .remediation_runner import RemediationRunner

    # Generate decoupled plan
    health_report = QualityService.evaluate_slide(slide)
    plan = QualityService.plan_remediation(slide, health_report)

    # Execute plan safely with rollback protection
    res = RemediationRunner.apply_plan(
        pres=pres,
        history=history,
        plan=plan,
        slide_id=slide.id,
        only_critical=only_critical
    )

    if res.get("applied_count", 0) > 0 and not res.get("rolled_back"):
        history.record(
            action="auto_fix_layout",
            description=f"视觉自动修复: 修复 {res['applied_count']} 项排版缺陷 (得分: {res.get('score_before', 0):.1f} -> {res.get('score_after', 0):.1f})",
            slide_id=slide.id
        )

    return res

