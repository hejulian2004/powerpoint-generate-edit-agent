"""Grounding gate for chat-originated deck generation.

Factual claims (numbers, metrics, report findings) must originate from
user-provided source material. When a user requests a data-heavy deck without
supplying sources, the agent asks for the source material first instead of
letting the model fabricate numbers. When sources are supplied, generated
numeric claims are validated against them before any mutation is committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..pptspec.validator import check_token_in_raw_text, parse_numeric_tokens

# Subject markers: the request is about facts/data rather than a generic deck.
FACTUAL_SUBJECT_KEYWORDS = (
    "数据", "指标", "财报", "营收", "利润", "增长", "同比", "环比", "统计",
    "调研", "报告", "论文", "实验", "性能", "benchmark", "市场份额", "占比",
    "用户数", "转化率", "研究", "引用", "来源", "评测", "结果",
)

# The user explicitly allows non-factual placeholder content.
PLACEHOLDER_MARKERS = (
    "示例", "占位", "虚构", "模拟", "不用真实", "不需要真实", "不必真实",
    "随意生成", "假的", "demo", "placeholder",
)

# Markers indicating the message actually carries source material.
SOURCE_CONTENT_MARKERS = (
    "以下", "如下", "素材", "资料", "原文", "报告全文", "内容如下",
    "根据这", "基于这", "摘要", "笔记", "文档", "大纲", "要点",
)

# Slide argument fields that carry factual content for numeric grounding.
_FACTUAL_SLIDE_FIELDS = ("title", "subtitle", "value", "label", "subtext", "description")

# A number followed by a real-world unit denotes an actual data claim (as
# opposed to a year/period reference such as "2025年" or "Q3").
_DATA_CLAIM_RE = re.compile(
    r"\d[\d.,]*\s*(?:%|％|万元|亿元|万|亿|元|美元|倍|个百分点|bps|人|个|家|次|台|件)"
)


@dataclass
class GroundingAssessment:
    """Result of assessing whether a generation request is grounded."""

    source_text: str = ""
    factual_subject: bool = False
    has_source: bool = False
    is_placeholder_request: bool = False
    requires_source: bool = False
    enforce_numeric_grounding: bool = False
    question: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_text": self.source_text,
            "factual_subject": self.factual_subject,
            "has_source": self.has_source,
            "is_placeholder_request": self.is_placeholder_request,
            "requires_source": self.requires_source,
            "enforce_numeric_grounding": self.enforce_numeric_grounding,
            "question": self.question,
        }


def _extract_text_blocks(content: Any) -> List[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(str(block.get("text", "")))
        return texts
    return []


def extract_source_text(user_query: str = "", messages: Optional[List[Dict[str, Any]]] = None) -> str:
    """Concatenate all user-authored text (raw transcript) as the grounding source."""
    parts: List[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        parts.extend(_extract_text_blocks(message.get("content")))
    source = "\n".join(part for part in parts if part and part.strip())
    if user_query and user_query.strip() and user_query.strip() not in source:
        source = f"{source}\n{user_query}".strip() if source else user_query.strip()
    return source


def _strip_request_phrasing(text: str) -> str:
    stripped = text
    for token in (
        "生成", "制作", "创建", "写一个", "一份", "一个", "关于", "关于",
        "ppt", "PPT", "演示文稿", "汇报", "页面", "幻灯片", "帮我", "请", "做",
    ):
        stripped = stripped.replace(token, "")
    return "".join(stripped.split())


def _has_substantive_source(source_text: str) -> bool:
    if not source_text.strip():
        return False
    data_tokens = [
        t for t in parse_numeric_tokens(source_text)
        if t.percent or t.unit or t.uncertainty
    ]
    if data_tokens or _DATA_CLAIM_RE.search(source_text):
        return True
    stripped = _strip_request_phrasing(source_text)
    if len(stripped) >= 100:
        return True
    if len(stripped) >= 50 and any(ch in source_text for ch in ("\n", "•", "；", ";", "、", "1.")):
        return True
    if len(stripped) >= 40 and any(marker in source_text for marker in SOURCE_CONTENT_MARKERS):
        return True
    return False


def assess_generation_request(
    user_query: str, messages: Optional[List[Dict[str, Any]]] = None
) -> GroundingAssessment:
    """Assess whether a deck request needs source material and numeric grounding."""
    source_text = extract_source_text(user_query, messages)
    lowered = (user_query or "").lower()
    is_placeholder = any(marker.lower() in lowered for marker in PLACEHOLDER_MARKERS)
    factual_subject = any(kw.lower() in lowered for kw in FACTUAL_SUBJECT_KEYWORDS) or bool(
        parse_numeric_tokens(user_query or "")
    )
    has_source = _has_substantive_source(source_text)
    requires_source = factual_subject and not has_source and not is_placeholder

    question = None
    if requires_source:
        question = (
            "这个主题涉及具体数据或事实。为确保内容真实可信，请先提供原始资料"
            "（例如报告、数据、要点原文，可直接粘贴），我会严格基于资料生成，绝不编造数字。"
            "如果只需要示例/占位内容，也请明确告知。"
        )

    return GroundingAssessment(
        source_text=source_text,
        factual_subject=factual_subject,
        has_source=has_source,
        is_placeholder_request=is_placeholder,
        requires_source=requires_source,
        enforce_numeric_grounding=factual_subject and not is_placeholder,
        question=question,
    )


def collect_generation_text(arguments: Dict[str, Any]) -> str:
    """Collect factual slide text from generate_presentation/generate_slide_layout args.

    Structural fields such as `badge` are excluded so ordinal labels are not
    mistaken for factual numeric claims.
    """
    parts: List[str] = []
    if arguments.get("title"):
        parts.append(str(arguments["title"]))
    if arguments.get("subtitle"):
        parts.append(str(arguments["subtitle"]))
    for slide in arguments.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        for key in ("title", "subtitle"):
            if slide.get(key):
                parts.append(str(slide[key]))
        for item in slide.get("items") or []:
            if isinstance(item, dict):
                for key in _FACTUAL_SLIDE_FIELDS:
                    if item.get(key):
                        parts.append(str(item[key]))
    for item in arguments.get("items") or []:
        if isinstance(item, dict):
            for key in _FACTUAL_SLIDE_FIELDS:
                if item.get(key):
                    parts.append(str(item[key]))
    return "\n".join(parts)


def unsupported_numbers(text: str, source_text: str) -> List[str]:
    """Return distinct numeric claims in `text` that are not grounded in `source_text`."""
    unsupported: List[str] = []
    for token in parse_numeric_tokens(text or ""):
        if check_token_in_raw_text(token, source_text or ""):
            continue
        raw = token.raw_text.strip()
        if raw and raw not in unsupported:
            unsupported.append(raw)
    return unsupported
