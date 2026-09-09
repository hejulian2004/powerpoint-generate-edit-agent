"""Flexible Normalization Pipeline (PR13 Step 2).

Converts candidate parsed dictionaries into strict CanonicalPPTSpec instances:
1. Field alias resolution (pages -> slides, facts -> evidence, etc.)
2. SlideType and VisualIntent taxonomic mapping
3. Evidence classification and table completeness checking
4. Enforcing safe SourcePolicy defaults
5. Fallback to LLM semantic normalization if deterministic normalization fails
6. Truthfulness validation
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..presentation.schema import SlideType
from ..slidespec.schema import VisualIntent
from .errors import NormalizationError, ValidationError
from .parser import InputFormat, detect_format, parse_presentation_input
from .schema import (
    AssetRequirement,
    CanonicalPPTSpec,
    ClaimEvidence,
    EquationEvidence,
    EvidenceItem,
    EvidenceKind,
    FigureReferenceEvidence,
    MetricEntry,
    MetricEvidence,
    MetricGroupEvidence,
    PresentationConfig,
    QuoteEvidence,
    SlideRequest,
    SourceDocument,
    SourcePolicy,
    TableEvidence,
)
from .validator import TruthfulnessValidator, validate_truthfulness, normalize_for_textual_match

logger = logging.getLogger(__name__)


# Mapping table for Chinese and variant slide categories to standard SlideType
SLIDE_TYPE_KEYWORDS: List[Tuple[re.Pattern, SlideType]] = [
    (re.compile(r"封面|标题|title|heading", re.I), SlideType.TITLE),
    (re.compile(r"背景|background|context|现状", re.I), SlideType.BACKGROUND),
    (re.compile(r"问题|挑战|痛点|problem|challenge", re.I), SlideType.PROBLEM),
    (re.compile(r"动机|motivation|启发", re.I), SlideType.MOTIVATION),
    (re.compile(r"相关工作|related\s*work|prior\s*work", re.I), SlideType.RELATED_WORK),
    (re.compile(r"方法概览|架构|模型概览|framework|method\s*overview|system\s*overview", re.I), SlideType.METHOD_OVERVIEW),
    (re.compile(r"方法|算法|细节|实现|method|detail|algorithm|architecture", re.I), SlideType.METHOD_DETAIL),
    (re.compile(r"实验设置|数据集|实验环境|setup|dataset|setting", re.I), SlideType.EXPERIMENT_SETUP),
    (re.compile(r"实验结果|对比|性能|benchmark|result|evaluation|performance|compare|comparison", re.I), SlideType.RESULT),
    (re.compile(r"消融|ablation", re.I), SlideType.ABLATION),
    (re.compile(r"局限|limitation|不足", re.I), SlideType.LIMITATION),
    (re.compile(r"总结|结论|未来|conclusion|summary|future", re.I), SlideType.CONCLUSION),
]


def map_slide_type(raw_type: Optional[str], title: str = "", index: int = 1) -> SlideType:
    """Map raw string or title to canonical SlideType enum."""
    candidate = (raw_type or "").strip()
    if candidate:
        try:
            return SlideType(candidate.upper())
        except ValueError:
            pass

    # Match by keywords in raw_type or title
    full_text = f"{candidate} {title}".strip()
    for pattern, s_type in SLIDE_TYPE_KEYWORDS:
        if pattern.search(full_text):
            return s_type

    return SlideType.TITLE if index == 1 else SlideType.BACKGROUND


def map_visual_intent(raw_intent: Optional[str], slide_type: SlideType) -> Optional[VisualIntent]:
    """Map raw intent or infer appropriate VisualIntent from slide type."""
    if raw_intent:
        try:
            return VisualIntent(raw_intent.upper())
        except ValueError:
            pass

    if slide_type == SlideType.TITLE:
        return VisualIntent.TITLE_HERO
    elif slide_type == SlideType.METHOD_OVERVIEW:
        return VisualIntent.PIPELINE_ARCHITECTURE
    elif slide_type in (SlideType.RESULT, SlideType.ABLATION):
        return VisualIntent.BENCHMARK_COMPARISON

    return VisualIntent.KEY_TAKEAWAY_LIST


@dataclass
class NormalizationResult:
    """Outcome of normalizing raw presentation input."""

    valid: bool
    spec: Optional[CanonicalPPTSpec]
    input_format: str
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    asset_requirements: List[AssetRequirement] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "input_format": self.input_format,
            "spec": self.spec.model_dump() if self.spec else None,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "summary": dict(self.summary),
            "asset_requirements": [r.model_dump() for r in self.asset_requirements],
        }


def normalize_dict_to_canonical_spec(
    candidate: Dict[str, Any],
    warnings: List[str],
) -> CanonicalPPTSpec:
    """Deterministically map candidate dictionary into a strictly typed CanonicalPPTSpec."""
    # 1. Alias Resolution
    cand = dict(candidate)

    # Resolve presentation config
    pres_raw = cand.get("presentation") or cand.get("metadata") or cand.get("config") or {}
    if not isinstance(pres_raw, dict):
        pres_raw = {}

    title = (
        pres_raw.get("title")
        or cand.get("title")
        or (cand.get("source_document") or {}).get("title")
        or "学术论文汇报演示"
    )
    pres_config = PresentationConfig(
        title=str(title),
        language=str(pres_raw.get("language") or "zh-CN"),
        audience=str(pres_raw.get("audience") or "计算机专业研究生组会"),
        duration_minutes=int(pres_raw.get("duration_minutes") or 15),
        style=str(pres_raw.get("style") or "academic_clean"),
        aspect_ratio="16:9",
    )

    # Resolve source policy - ALWAYS FORCE SAFE DEFAULTS
    source_policy = SourcePolicy(
        allow_external_knowledge=False,
        allow_inferred_facts=False,
        allow_invented_numbers=False,
        allow_synthetic_figures=False,
        missing_information_policy="omit",
    )

    # Resolve source document
    doc_raw = cand.get("source_document") or {}
    if not isinstance(doc_raw, dict):
        doc_raw = {}
    source_doc = SourceDocument(
        title=doc_raw.get("title") or pres_config.title,
        venue=doc_raw.get("venue"),
        year=int(doc_raw["year"]) if doc_raw.get("year") is not None else None,
        authors=list(doc_raw.get("authors") or []),
    )

    # 2. Resolve Evidence items
    raw_evidences = (
        cand.get("evidence")
        or cand.get("evidences")
        or cand.get("facts")
        or cand.get("claims")
        or cand.get("data")
        or []
    )
    if not isinstance(raw_evidences, list):
        raw_evidences = []

    normalized_evidences: List[EvidenceItem] = []
    seen_ev_ids = set()

    for idx, raw_ev in enumerate(raw_evidences):
        if not isinstance(raw_ev, dict):
            continue
        ev_id = str(raw_ev.get("id") or f"ev_{idx + 1}")
        if ev_id in seen_ev_ids:
            ev_id = f"{ev_id}_{idx}"
        seen_ev_ids.add(ev_id)

        kind_str = str(raw_ev.get("kind") or "").lower()

        # Deduce kind if missing
        if not kind_str:
            if "columns" in raw_ev or "rows" in raw_ev:
                kind_str = "table"
            elif "label" in raw_ev and any(k in str(raw_ev["label"]).lower() for k in ("fig", "figure", "图")):
                kind_str = "figure_reference"
            elif "value" in raw_ev and "name" in raw_ev:
                kind_str = "metric"
            elif "metrics" in raw_ev:
                kind_str = "metric_group"
            elif "latex" in raw_ev:
                kind_str = "equation"
            else:
                kind_str = "claim"

        page_num = raw_ev.get("source_page") or raw_ev.get("page")
        page_val = int(page_num) if page_num is not None else None

        if kind_str in ("figure", "figure_reference", "fig"):
            label = str(raw_ev.get("label") or raw_ev.get("xref_label") or f"Figure {idx + 1}")
            normalized_evidences.append(
                FigureReferenceEvidence(
                    id=ev_id,
                    label=label,
                    caption=raw_ev.get("caption"),
                    source_page=page_val,
                )
            )

        elif kind_str in ("table", "tbl"):
            cols = [str(c) for c in (raw_ev.get("columns") or raw_ev.get("header") or [])]
            rows_raw = raw_ev.get("rows") or []
            rows = [[str(cell) for cell in r] for r in rows_raw if isinstance(r, list)]

            # Validate completeness
            is_complete = bool(cols) and bool(rows) and all(len(r) == len(cols) for r in rows)
            if not is_complete and (cols or rows):
                warnings.append(f"Table '{ev_id}' data is incomplete or has mismatched rows; demoted to placeholder.")

            caption_val = raw_ev.get("caption")
            source_ref = raw_ev.get("source_reference") or raw_ev.get("xref_label") or raw_ev.get("label")
            if not source_ref and caption_val:
                tbl_match = re.search(r"((?:Table|表)\s*\d+)", str(caption_val), re.IGNORECASE)
                if tbl_match:
                    source_ref = tbl_match.group(1).strip()

            normalized_evidences.append(
                TableEvidence(
                    id=ev_id,
                    source_reference=source_ref,
                    columns=cols,
                    rows=rows,
                    caption=caption_val,
                    source_page=page_val,
                    complete_table=is_complete,
                )
            )

        elif kind_str in ("metric", "metric_result"):
            val_raw = raw_ev.get("value")
            if val_raw is None or str(val_raw).strip() == "":
                warnings.append(f"MISSING_METRIC_VALUE: Metric '{ev_id}' has no value provided; omitted to prevent fabricating data.")
                continue
            normalized_evidences.append(
                MetricEvidence(
                    id=ev_id,
                    name=str(raw_ev.get("name") or "Metric"),
                    value=str(val_raw).strip(),
                    unit=raw_ev.get("unit"),
                    method=raw_ev.get("method"),
                )
            )

        elif kind_str == "metric_group":
            m_entries: List[MetricEntry] = []
            for m in raw_ev.get("metrics") or []:
                if isinstance(m, dict) and "name" in m:
                    m_val = m.get("value")
                    if m_val is not None and str(m_val).strip() != "":
                        m_entries.append(
                            MetricEntry(
                                name=str(m["name"]),
                                value=str(m_val).strip(),
                                unit=m.get("unit"),
                            )
                        )
                    else:
                        warnings.append(f"MISSING_METRIC_VALUE: MetricGroup '{ev_id}' entry '{m.get('name')}' has no value; omitted.")
            if m_entries:
                normalized_evidences.append(
                    MetricGroupEvidence(
                        id=ev_id,
                        group_name=str(raw_ev.get("group_name") or "Metrics"),
                        metrics=m_entries,
                    )
                )
            else:
                warnings.append(f"MISSING_METRIC_VALUE: MetricGroup '{ev_id}' has no valid metric entries; omitted.")

        elif kind_str == "equation":
            normalized_evidences.append(
                EquationEvidence(
                    id=ev_id,
                    latex=str(raw_ev.get("latex") or ""),
                    description=raw_ev.get("description"),
                )
            )

        elif kind_str == "quote":
            normalized_evidences.append(
                QuoteEvidence(
                    id=ev_id,
                    content=str(raw_ev.get("content") or ""),
                    speaker_or_section=raw_ev.get("speaker_or_section"),
                )
            )

        else:
            # Default to ClaimEvidence
            content = str(raw_ev.get("content") or raw_ev.get("text") or raw_ev.get("claim") or "")
            normalized_evidences.append(
                ClaimEvidence(
                    id=ev_id,
                    content=content,
                    source_reference=raw_ev.get("source_reference"),
                    source_page=page_val,
                )
            )

    # 3. Resolve Slides
    raw_slides = (
        cand.get("slides")
        or cand.get("pages")
        or cand.get("outline")
        or cand.get("slide_list")
        or []
    )
    if not isinstance(raw_slides, list) or not raw_slides:
        # Generate default slide
        raw_slides = [{"title": pres_config.title, "type": "TITLE"}]

    valid_ev_ids = {ev.id for ev in normalized_evidences}
    normalized_slides: List[SlideRequest] = []

    for s_idx, raw_slide in enumerate(raw_slides, start=1):
        if not isinstance(raw_slide, dict):
            continue
        slide_id = str(raw_slide.get("id") or f"slide_{s_idx:02d}")
        title_str = str(raw_slide.get("title") or raw_slide.get("heading") or f"Slide {s_idx}")
        slide_type = map_slide_type(raw_slide.get("type"), title=title_str, index=s_idx)
        visual_intent = map_visual_intent(raw_slide.get("visual_intent"), slide_type)

        # Preserve all evidence_refs without silently dropping unknown ones!
        # TruthfulnessValidator will validate references and record INVALID_EVIDENCE_REFERENCE.
        raw_refs = raw_slide.get("evidence_refs") or raw_slide.get("evidences") or []
        cleaned_refs: List[str] = [str(r).strip() for r in raw_refs if str(r).strip()]

        # Resolve bullet items from key_messages or bullets (synthesize ClaimEvidence if needed)
        # Avoid duplicate synthesis if an evidence with equivalent normalized content is already referenced
        referenced_contents = {
            normalize_for_textual_match(getattr(ev, "content", ""))
            for ev in normalized_evidences
            if ev.id in cleaned_refs and getattr(ev, "content", "")
        }
        for ev in normalized_evidences:
            if ev.id in cleaned_refs and isinstance(ev, MetricEvidence):
                referenced_contents.add(normalize_for_textual_match(ev.name))
                referenced_contents.add(normalize_for_textual_match(f"{ev.name} {ev.value}"))

        bullets_raw = (
            raw_slide.get("key_messages")
            or raw_slide.get("bullets")
            or []
        )
        bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
        synthesized_count = 0
        for b_idx, bullet in enumerate(bullets, start=1):
            norm_b = normalize_for_textual_match(bullet)
            if not norm_b or norm_b in referenced_contents:
                continue
            synthesized_count += 1
            new_ev_id = f"ev_bullet_{slide_id}_{synthesized_count}"
            if new_ev_id not in valid_ev_ids:
                claim = ClaimEvidence(id=new_ev_id, content=bullet)
                normalized_evidences.append(claim)
                valid_ev_ids.add(new_ev_id)
            if new_ev_id not in cleaned_refs:
                cleaned_refs.append(new_ev_id)
            referenced_contents.add(norm_b)

        # Presentation/layout directives only in instructions (never slide text content)
        instructions_raw = raw_slide.get("instructions") or []
        if isinstance(instructions_raw, str):
            instructions = [instructions_raw.strip()] if instructions_raw.strip() else []
        else:
            instructions = [str(item).strip() for item in instructions_raw if str(item).strip()]

        normalized_slides.append(
            SlideRequest(
                id=slide_id,
                type=slide_type,
                title=title_str,
                objective=raw_slide.get("objective") or raw_slide.get("purpose"),
                visual_intent=visual_intent,
                evidence_refs=cleaned_refs,
                instructions=instructions,
                speaker_notes=raw_slide.get("speaker_notes") or raw_slide.get("notes"),
            )
        )

    return CanonicalPPTSpec(
        spec_version="1.0",
        presentation=pres_config,
        source_policy=source_policy,
        source_document=source_doc,
        evidence=normalized_evidences,
        slides=normalized_slides,
    )


def compute_spec_summary(spec: CanonicalPPTSpec) -> Dict[str, int]:
    """Compute summary statistics for user normalization preview."""
    claims = sum(1 for ev in spec.evidence if isinstance(ev, ClaimEvidence))
    metrics = sum(1 for ev in spec.evidence if isinstance(ev, MetricEvidence))
    metric_groups = sum(len(ev.metrics) for ev in spec.evidence if isinstance(ev, MetricGroupEvidence))
    figures = sum(1 for ev in spec.evidence if isinstance(ev, FigureReferenceEvidence))
    complete_tables = sum(1 for ev in spec.evidence if isinstance(ev, TableEvidence) and ev.complete_table)
    table_placeholders = sum(1 for ev in spec.evidence if isinstance(ev, TableEvidence) and not ev.complete_table)

    return {
        "slides": len(spec.slides),
        "claims": claims,
        "metrics": metrics + metric_groups,
        "figures": figures,
        "complete_tables": complete_tables,
        "table_placeholders": table_placeholders,
    }


async def normalize_presentation_input(
    raw_text: str,
    llm_client: Optional[Any] = None,
    strict_truthfulness: bool = True,
) -> NormalizationResult:
    """End-to-end async normalization pipeline with truthfulness verification."""
    warnings: List[str] = []
    errors: List[str] = []

    # 1. Detect format & parse candidate dictionary
    fmt = detect_format(raw_text)
    spec: Optional[CanonicalPPTSpec] = None

    try:
        _, candidate = parse_presentation_input(raw_text)
        spec = normalize_dict_to_canonical_spec(candidate, warnings=warnings)
    except Exception as e:
        logger.warning(f"Deterministic normalization failed: {e}")
        # 2. LLM fallback if deterministic normalization raised error and llm_client is provided
        if llm_client is not None and hasattr(llm_client, "chat_completion"):
            try:
                system_prompt = (
                    "你是一位严格的学术 PPT 结构化编译器。将用户的非结构化大纲整理为符合 CanonicalPPTSpec 的 JSON。\n"
                    "【绝密原则】: 严禁添加任何新事实，严禁添加用户未提供的数字，严禁生成假图假表。"
                )
                resp = await llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": raw_text},
                    ],
                )
                if isinstance(resp, dict):
                    if "choices" in resp and resp["choices"]:
                        content_str = resp["choices"][0]["message"].get("content", "")
                    else:
                        content_str = resp.get("content") or json.dumps(resp)
                else:
                    content_str = str(resp)

                _, llm_dict = parse_presentation_input(content_str)
                spec = normalize_dict_to_canonical_spec(llm_dict, warnings=warnings)
            except Exception as llm_err:
                errors.append(f"LLM normalization fallback also failed: {llm_err}")
        else:
            errors.append(f"Normalization failed: {e}")

    if spec is None:
        return NormalizationResult(
            valid=False,
            spec=None,
            input_format=fmt.value,
            warnings=warnings,
            errors=errors,
            summary={},
            asset_requirements=[],
        )

    # 3. Truthfulness Guard
    try:
        val_result = validate_truthfulness(raw_text, spec, strict=strict_truthfulness)
        warnings.extend(val_result.warnings)
        if not val_result.valid:
            errors.extend(val_result.errors)
    except ValidationError as val_err:
        errors.append(str(val_err))

    valid = len(errors) == 0
    summary = compute_spec_summary(spec)
    asset_requirements = spec.get_asset_requirements()

    return NormalizationResult(
        valid=valid,
        spec=spec if valid else None,
        input_format=fmt.value,
        warnings=warnings,
        errors=errors,
        summary=summary,
        asset_requirements=asset_requirements,
    )
