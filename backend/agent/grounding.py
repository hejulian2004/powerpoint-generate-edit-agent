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

# Markers indicating the current turn explicitly refers back to material supplied
# in an earlier turn. Without one of these, prior user turns MUST NOT ground a
# new generation request (a source from Turn A cannot launder Turn B's numbers).
CONTINUATION_MARKERS = (
    "以上", "上述", "如下", "以下", "根据这", "基于这", "之前", "刚才",
    "前面的", "上面", "该资料", "这些资料", "这份资料", "我提供的", "我给的",
    "已提供", "资料中", "素材中", "原文中", "如下所示", "如下内容", "上述资料",
)

# Slide argument fields that carry factual content for numeric grounding.
_FACTUAL_SLIDE_FIELDS = ("title", "subtitle", "value", "label", "subtext", "description")

# A number followed by a real-world unit denotes an actual data claim (as
# opposed to a year/period reference such as "2025年" or "Q3").
_DATA_CLAIM_RE = re.compile(
    r"\d[\d.,]*\s*(?:%|％|万元|亿元|万|亿|元|美元|倍|个百分点|bps|人|个|家|次|台|件)"
)


# --- Structured grounding policy (ALLOW / PLACEHOLDER / BLOCK) --------------
#
# Policy decisions are data, not control flow: tuning false positives means
# editing this table only, never the Generation / Mutation main path.
DECISION_ALLOW = "ALLOW"
DECISION_PLACEHOLDER = "PLACEHOLDER"
DECISION_BLOCK = "BLOCK"

CATEGORY_NUMERIC = "numeric"
CATEGORY_PERFORMANCE = "performance"
CATEGORY_COMPATIBILITY = "compatibility"
CATEGORY_ATTRIBUTION = "attribution"
CATEGORY_QUALITATIVE = "qualitative"


@dataclass(frozen=True)
class GroundingRule:
    """One data-driven classification rule.

    Rules are evaluated in order; the first match for a span wins, so a specific
    commitment (BLOCK) must precede a fuzzy bare term (PLACEHOLDER).
    """

    pattern: "re.Pattern[str]"
    decision: str
    category: str
    reason: str
    replacement: Optional[str] = None


# Evidence-free specific commitments that may not be written.
_BLOCK_SOURCE_ATTRIBUTION = re.compile(
    r"(?:据|来自|引用)\s*(?:Gartner|IDC|Forrester|McKinsey|Nielsen|Nature|Science|IEEE|"
    r"艾瑞|易观|QuestMobile)",
    re.IGNORECASE,
)
_BLOCK_ENTERPRISE_COMMITMENT = re.compile(
    r"企业级\s*(?:SLA|高并发|并发|可用性|承载|吞吐|QPS)|"
    r"(?:SLA|QPS)\s*\d",
)
_BLOCK_SOTA = re.compile(r"SOTA|state[\s-]of[\s-]the[\s-]art", re.IGNORECASE)
_BLOCK_COMPAT_RANGE = re.compile(r"(?:全|所有|全部)\s*平台\s*(?:兼容|支持|覆盖)")

GROUNDING_POLICY: tuple[GroundingRule, ...] = (
    GroundingRule(
        _BLOCK_ENTERPRISE_COMMITMENT, DECISION_BLOCK, CATEGORY_COMPATIBILITY,
        "涉及企业级可用性/并发等可验证承诺，缺乏依据时不得写为事实。",
    ),
    GroundingRule(
        _BLOCK_SOTA, DECISION_BLOCK, CATEGORY_PERFORMANCE,
        "SOTA/最先进属于可证伪的性能主张，缺乏依据时不得写为事实。",
    ),
    GroundingRule(
        _BLOCK_SOURCE_ATTRIBUTION, DECISION_BLOCK, CATEGORY_ATTRIBUTION,
        "指名道姓的外部来源引用必须可溯源，否则不得写入。",
    ),
    GroundingRule(
        _BLOCK_COMPAT_RANGE, DECISION_BLOCK, CATEGORY_COMPATIBILITY,
        "全平台兼容范围属于可验证承诺，缺乏依据时不得写为事实。",
    ),
    GroundingRule(
        re.compile(r"毫秒级|微秒级|毫秒内|秒级", re.IGNORECASE),
        DECISION_PLACEHOLDER, CATEGORY_PERFORMANCE,
        "模糊性能表述缺少量化依据。", "[待验证性能描述]",
    ),
    GroundingRule(
        re.compile(r"无损"),
        DECISION_PLACEHOLDER, CATEGORY_PERFORMANCE,
        "“无损”属于性能承诺而非风格描述。", "[待验证性能描述]",
    ),
    GroundingRule(
        re.compile(r"业界领先|行业领先|领先水平|业界顶尖|行业顶尖"),
        DECISION_PLACEHOLDER, CATEGORY_PERFORMANCE,
        "模糊领先性表述缺少可验证依据。", "[待验证性能描述]",
    ),
    GroundingRule(
        re.compile(r"企业级可靠性"),
        DECISION_PLACEHOLDER, CATEGORY_PERFORMANCE,
        "模糊可靠性表述缺少可验证依据。", "[待验证性能描述]",
    ),
    GroundingRule(
        re.compile(r"企业级"),
        DECISION_PLACEHOLDER, CATEGORY_PERFORMANCE,
        "“企业级”单独出现属于模糊定位，非具体承诺。", "[待验证性能描述]",
    ),
    GroundingRule(
        re.compile(r"全平台|跨平台|所有平台"),
        DECISION_PLACEHOLDER, CATEGORY_COMPATIBILITY,
        "模糊兼容性表述缺少验证依据。", "[待补充兼容性依据]",
    ),
)


@dataclass
class GroundingVerdict:
    """Structured grounding decision for a single claim."""

    decision: str
    claim: str
    category: str
    reason: str
    evidence: Optional[str] = None
    replacement: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "claim": self.claim,
            "category": self.category,
            "reason": self.reason,
            "evidence": self.evidence,
            "replacement": self.replacement,
        }


def scan_text_verdicts(
    text: str, source_text: str = "", *, placeholder_ok: bool = False
) -> List[GroundingVerdict]:
    """Classify factual claims in `text` against `source_text`.

    Numeric data claims absent from the source are BLOCK. Policy-table phrase
    matches absent from the source are BLOCK or PLACEHOLDER per the table.
    Deterministic and side-effect free so it can be reused by the gateway.
    """
    if not text or not text.strip():
        return []

    verdicts: List[GroundingVerdict] = []
    seen: set = set()

    for raw in data_claim_numbers(text, source_text):
        key = (DECISION_BLOCK, raw)
        if key in seen:
            continue
        seen.add(key)
        verdicts.append(GroundingVerdict(
            decision=DECISION_BLOCK,
            claim=raw,
            category=CATEGORY_NUMERIC,
            reason="数值型数据主张在提供的资料中找不到依据。",
        ))

    for rule in GROUNDING_POLICY:
        if placeholder_ok and rule.decision == DECISION_PLACEHOLDER:
            continue
        for match in rule.pattern.finditer(text):
            claim = match.group(0).strip()
            if not claim or claim in (source_text or ""):
                continue
            key = (rule.decision, claim)
            if key in seen:
                continue
            seen.add(key)
            verdicts.append(GroundingVerdict(
                decision=rule.decision,
                claim=claim,
                category=rule.category,
                reason=rule.reason,
                replacement=rule.replacement,
            ))

    return verdicts


def blocking_verdicts(
    text: str, source_text: str = "", *, placeholder_ok: bool = False
) -> List[GroundingVerdict]:
    """Verdicts that must stop a write (BLOCK, plus PLACEHOLDER unless allowed)."""
    return [
        v for v in scan_text_verdicts(text, source_text, placeholder_ok=placeholder_ok)
        if v.decision in (DECISION_BLOCK, DECISION_PLACEHOLDER)
    ]



@dataclass
class SourceBundle:
    """Explicitly bound grounding source for one generation request.

    `origin` records where the text came from so a prior turn's source cannot be
    silently reused: "current_turn", "conversation" (current turn explicitly
    referred back to earlier material), or "none".
    """

    text: str = ""
    origin: str = "none"
    turn_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "origin": self.origin, "turn_count": self.turn_count}


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
    source_origin: str = "none"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_text": self.source_text,
            "factual_subject": self.factual_subject,
            "has_source": self.has_source,
            "is_placeholder_request": self.is_placeholder_request,
            "requires_source": self.requires_source,
            "enforce_numeric_grounding": self.enforce_numeric_grounding,
            "question": self.question,
            "source_origin": self.source_origin,
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
    bundle = build_source_bundle(user_query, messages)
    source_text = bundle.text
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
        source_origin=bundle.origin,
    )


def build_source_bundle(
    user_query: str = "", messages: Optional[List[Dict[str, Any]]] = None
) -> SourceBundle:
    """Binds the grounding source for the CURRENT turn only.

    Prior user turns are only consulted when the current turn explicitly refers
    back to earlier material (continuation markers). This prevents a source
    supplied for an earlier deck from grounding fabricated numbers in a later,
    unrelated generation request.
    """
    query = (user_query or "").strip()
    user_turns = [
        m for m in (messages or [])
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    uses_prior = any(marker in query for marker in CONTINUATION_MARKERS)

    if uses_prior:
        text = extract_source_text(user_query, messages)
    else:
        text = query

    origin = "none"
    if _has_substantive_source(text):
        origin = "conversation" if uses_prior else "current_turn"

    return SourceBundle(text=text, origin=origin, turn_count=len(user_turns))


def _element_text(el: Any) -> List[str]:
    parts: List[str] = []
    text_content = getattr(el, "text_content", None)
    if text_content is not None:
        plain = getattr(text_content, "plain_text", None)
        if plain:
            parts.append(str(plain))
    for child in getattr(el, "children", None) or []:
        parts.extend(_element_text(child))
    return parts


def collect_ir_text(slides: Optional[List[Any]]) -> str:
    """Collect the visible text of a list of slides from their committed IR."""
    parts: List[str] = []
    for slide in slides or []:
        for el in getattr(slide, "elements", None) or []:
            parts.extend(_element_text(el))
    return "\n".join(part for part in parts if part and part.strip())


def data_claim_numbers(text: str, source_text: str) -> List[str]:
    """Unsupported numeric DATA claims (units/percent/uncertainty/comparator).

    Structural numerals (slide kickers like "02 / CONTENT", ordinal step markers,
    years) carry no unit and are intentionally ignored so IR-wide post-validation
    does not raise false positives.
    """
    unsupported: List[str] = []
    for token in parse_numeric_tokens(text or ""):
        if not (token.percent or token.unit or token.uncertainty or token.comparator):
            continue
        if check_token_in_raw_text(token, source_text or ""):
            continue
        raw = token.raw_text.strip()
        if raw and raw not in unsupported:
            unsupported.append(raw)
    return unsupported


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
