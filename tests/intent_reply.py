"""Test helper: a model answer to the intent router, not a keyword classifier."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

ROUTER_MARK = "意图路由分类器"


def system_text(messages: Optional[List[Dict[str, Any]]]) -> str:
    for message in messages or []:
        if isinstance(message, dict) and message.get("role") == "system":
            content = message.get("content") or ""
            return content if isinstance(content, str) else ""
    return ""


def intent_choice(intent: str) -> Dict[str, Any]:
    payload = json.dumps({"intent": intent, "reason": "model"}, ensure_ascii=False)
    return {"choices": [{"message": {"content": payload}}]}


def maybe_route(messages: Optional[List[Dict[str, Any]]], intent: str) -> Optional[Dict[str, Any]]:
    if ROUTER_MARK in system_text(messages):
        return intent_choice(intent)
    return None


def tool_call_choice(name: str, arguments: Dict[str, Any], call_id: str = "call_model") -> Dict[str, Any]:
    """OpenAI-style tool call, as if the model chose the operation."""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }],
            }
        }]
    }


# A five-page deck the model can hand to generate_presentation. Copy stays short
# so content and visual critics can approve a real compiled deck.
SAMPLE_DECK_SLIDES: List[Dict[str, Any]] = [
    {
        "title": "主题封面",
        "layout": "title_slide",
        "subtitle": "结构与路线",
    },
    {
        "title": "三层体系",
        "layout": "card_grid",
        "subtitle": "状态 · 编排 · 导出",
        "items": [
            {"title": "状态层", "description": "标准坐标", "badge": "01"},
            {"title": "编排层", "description": "状态闭环", "badge": "02"},
            {"title": "导出层", "description": "双向导出", "badge": "03"},
        ],
    },
    {
        "title": "演进时间线",
        "layout": "timeline",
        "items": [
            {"title": "原型验证", "description": "数据模型"},
            {"title": "状态编排", "description": "闭环自省"},
            {"title": "商业发布", "description": "企业交付"},
        ],
    },
    {
        "title": "效能指标",
        "layout": "kpi_metrics",
        "items": [
            {"value": "10x", "label": "出稿效率", "subtext": "秒级排版"},
            {"value": "99%", "label": "排版保真", "subtext": "规范对齐"},
            {"value": "200ms", "label": "重绘延迟", "subtext": "流畅重绘"},
        ],
    },
    {
        "title": "方案对比",
        "layout": "comparison",
        "items": [
            {"title": "传统方案", "description": "耦合严重"},
            {"title": "中间表示", "description": "解耦编排"},
        ],
    },
]


def generation_tool_choice(topic: str) -> Dict[str, Any]:
    return tool_call_choice(
        "generate_presentation",
        {
            "topic": topic,
            "theme": "monochrome_studio",
            "replace": True,
            "slides": SAMPLE_DECK_SLIDES,
        },
        call_id="call_gen_deck",
    )
