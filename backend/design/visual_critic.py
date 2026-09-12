"""Layout-aware visual critic for the LLM-native pipeline (S3 / Phase 6).

Strictly read-only. Combines:

1. Deterministic rule critique of the compiled ``LayoutSpec`` (reuses the canonical
   ``backend.evaluation.RuleBasedEvaluator`` — no duplicated geometry rules).
2. Optional semantic color/contrast findings from ``color_validator``.
3. Optional multimodal aesthetic critique via ``role="vision"`` when a raster
   snapshot (data URI) is supplied; otherwise the text manifest is critiqued with
   ``role="reasoning"``.

The critic NEVER edits layout or text. It returns diagnostics + a refinement
directive consumed by ``aesthetic_refiner``.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..layout.schema import ElementType, LayoutSpec
from .json_utils import clamp_unit, extract_json
from .layout_compiler import hard_validate_layout

logger = logging.getLogger(__name__)

VISUAL_CRITIC_SYSTEM_PROMPT = """You are an independent visual art director auditing ONE presentation slide.
You receive the rendered slide (if available) plus an objective element coordinate manifest.
You are strictly read-only: you NEVER rewrite text or facts, and you never change semantics.

Focus ONLY on: geometry, alignment, whitespace/breathing room, visual hierarchy,
color harmony, contrast, and composition balance.

Hard rules:
1. Return STRICT JSON only (no prose, no markdown fences).
2. Do NOT suggest changing wording or numbers; only layout/style/composition.
3. Be concrete and actionable.

Return JSON matching:
{
  "aesthetic_score": <0-100 integer>,
  "defects": [
    {"element_id": "id or null", "severity": "error|warning", "description": "..."}
  ],
  "recommendations": ["concise layout/style action", "..."]
}
"""

_REFINE_SCORE_THRESHOLD = 80.0


@dataclass
class SlideCritique:
    slide_id: str
    score: float = 100.0
    geometry: float = 100.0
    readability: float = 100.0
    contrast: float = 100.0
    balance: float = 100.0
    aesthetics: float = 100.0
    hard_valid: bool = True
    defects: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    vision_feedback: Optional[str] = None
    vision_status: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_error(self) -> bool:
        return any(d.get("severity") in ("error", "critical") for d in self.defects)

    @property
    def needs_refinement(self) -> bool:
        return (not self.hard_valid) or self.has_error or self.score < _REFINE_SCORE_THRESHOLD

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "score": round(self.score, 1),
            "geometry": round(self.geometry, 1),
            "readability": round(self.readability, 1),
            "contrast": round(self.contrast, 1),
            "balance": round(self.balance, 1),
            "aesthetics": round(self.aesthetics, 1),
            "hard_valid": self.hard_valid,
            "defects": self.defects,
            "recommendations": self.recommendations,
            "vision_feedback": self.vision_feedback,
            "vision_status": self.vision_status,
            "needs_refinement": self.needs_refinement,
        }


async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
    if not on_event:
        return
    try:
        result = on_event(data)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover
        logger.debug("Visual critic event ignored: %s", exc)


def format_layout_manifest(layout: LayoutSpec) -> str:
    """Objective element coordinate manifest (no author intent, no facts)."""
    lines = [
        f"Slide '{layout.slide_id}' (Canvas: {layout.canvas.width:.0f}x{layout.canvas.height:.0f}, "
        f"Elements: {len(layout.elements)}):"
    ]
    for el in layout.elements:
        geo = el.geometry
        desc = (
            f"- [ID: '{el.element_id}'] Type: {el.element_type.value}, "
            f"Rect: ({geo.x:.0f}, {geo.y:.0f}, {geo.width:.0f}x{geo.height:.0f})"
        )
        if el.element_type in (ElementType.TEXT, ElementType.BADGE) and el.content:
            text = str(el.content).replace("\n", " ")[:40]
            desc += f", Text: '{text}'"
        if el.style and el.style.text and el.style.text.font_size:
            desc += f", FontSize: {el.style.text.font_size:.0f}"
        lines.append(desc)
    return "\n".join(lines)


def _rule_issues(layout: LayoutSpec) -> List[Any]:
    """Deterministic rule critique on LayoutSpec (lazy import keeps PIL out of hot path)."""
    from ..evaluation.evaluator import RuleBasedEvaluator

    return RuleBasedEvaluator().evaluate(None, layout)


_DIMENSION_BY_ISSUE = {
    "OVERFLOW": "geometry",
    "OVERLAP": "geometry",
    "TEXT_OVERFLOW": "readability",
    "TEXT_DENSITY_HIGH": "readability",
    "TOO_SMALL": "readability",
    "WRONG_SCALE": "readability",
    "LOW_CONTRAST": "contrast",
    "BAD_ALIGNMENT": "balance",
    "EXCESSIVE_EMPTY_SPACE": "balance",
    "UNDER_UTILIZED_SPACE": "balance",
}

_PENALTY = {"ERROR": 18.0, "CRITICAL": 25.0, "WARNING": 6.0, "INFO": 1.0}


def _score_from_issues(issues: List[Any]) -> Dict[str, float]:
    scores = {k: 100.0 for k in ("geometry", "readability", "contrast", "balance")}
    defects: List[Dict[str, Any]] = []
    for issue in issues:
        severity = getattr(issue.severity, "value", str(issue.severity))
        issue_type = getattr(issue.issue_type, "value", str(issue.issue_type))
        dim = _DIMENSION_BY_ISSUE.get(issue_type, "balance")
        scores[dim] = max(0.0, scores[dim] - _PENALTY.get(severity, 5.0))
        defects.append(
            {
                "element_id": getattr(issue, "element_id", None),
                "severity": severity.lower(),
                "description": getattr(issue, "description", ""),
                "issue_type": issue_type,
            }
        )
    scores["aesthetics"] = round(0.5 * scores["balance"] + 0.5 * scores["readability"], 1)
    scores["_defects"] = defects  # type: ignore[assignment]
    return scores


def _color_findings(color_report: Any, slide_id: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if color_report is None:
        return findings
    for issue in getattr(color_report, "issues", []):
        if issue.slide_id not in (None, slide_id):
            continue
        findings.append(
            {
                "element_id": issue.element_id,
                "severity": issue.severity,
                "description": issue.description,
                "issue_type": issue.kind.upper(),
            }
        )
    return findings


def _vision_messages(
    layout: LayoutSpec,
    raster_data_uri: Optional[str],
    source_image_data_uris: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    user_prompt = (
        "Audit this single slide's visual layout. "
        f"Deterministic rule score will be fused with your aesthetic rating.\n\n"
        f"【Element Coordinate Manifest】:\n{format_layout_manifest(layout)}"
    )
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    if raster_data_uri:
        content.append(
            {"type": "image_url", "image_url": {"url": raster_data_uri, "detail": "low"}}
        )
    if source_image_data_uris:
        content.append(
            {
                "type": "text",
                "text": (
                    "【Source paper pages/crops relevant to this slide】: compare the "
                    "slide against the original paper visuals for coverage."
                ),
            }
        )
        for data_uri in source_image_data_uris[:4]:
            content.append(
                {"type": "image_url", "image_url": {"url": data_uri, "detail": "low"}}
            )
    return [
        {"role": "system", "content": VISUAL_CRITIC_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


async def critique_slide(
    layout: LayoutSpec,
    llm_client: Any = None,
    include_multimodal: bool = True,
    raster_data_uri: Optional[str] = None,
    source_image_data_uris: Optional[Sequence[str]] = None,
    color_report: Any = None,
    on_event: Optional[Callable] = None,
) -> SlideCritique:
    """Critique one compiled slide (deterministic + optional multimodal)."""
    issues = _rule_issues(layout)
    scores = _score_from_issues(issues)
    hard_report = hard_validate_layout(
        layout,
        None,
    )
    hard_valid = hard_report.is_valid
    defects: List[Dict[str, Any]] = list(scores.pop("_defects"))  # type: ignore[arg-type]
    if not hard_valid:
        for err in hard_report.errors:
            defects.append(
                {"element_id": None, "severity": "error", "description": err, "issue_type": "HARD"}
            )

    color_defects = _color_findings(color_report, layout.slide_id)
    defects.extend(color_defects)
    for finding in color_defects:
        if finding["severity"] == "error":
            scores["contrast"] = max(0.0, scores["contrast"] - 18.0)
        else:
            scores["contrast"] = max(0.0, scores["contrast"] - 6.0)

    recommendations: List[str] = []
    vision_feedback: Optional[str] = None
    vision_status: Dict[str, Any] = {"vision_available": False, "mode": "rules_only"}

    has_vision_api = bool(llm_client and getattr(llm_client, "api_key", None))
    if include_multimodal and has_vision_api:
        try:
            messages = _vision_messages(layout, raster_data_uri, source_image_data_uris)
            # Any request that actually carries an ``image_url`` MUST go out on the
            # vision role, even when only source paper images are attached and the
            # slide raster is missing.
            has_images = bool(raster_data_uri) or bool(source_image_data_uris)
            role = "vision" if has_images else "reasoning"
            response = await llm_client.chat_completion(messages, role=role, max_tokens=800)
            vision_feedback = response["choices"][0]["message"].get("content", "")
            payload = extract_json(vision_feedback)
            if isinstance(payload, dict):
                vm_score = payload.get("aesthetic_score")
                if vm_score is not None:
                    rule_aesthetic = float(scores["aesthetics"])
                    fused = 0.5 * rule_aesthetic + 0.5 * (clamp_unit(float(vm_score) / 100.0) * 100.0)
                    scores["aesthetics"] = round(fused, 1)
                for raw in payload.get("defects", []) or []:
                    if isinstance(raw, dict):
                        defects.append(
                            {
                                "element_id": raw.get("element_id"),
                                "severity": str(raw.get("severity", "warning")).lower(),
                                "description": str(raw.get("description", "")),
                                "issue_type": "VISION",
                            }
                        )
                for rec in payload.get("recommendations", []) or []:
                    text = str(rec).strip()
                    if text:
                        recommendations.append(text)
            vision_status = {
                "vision_available": True,
                "mode": (
                    "multimodal"
                    if raster_data_uri
                    else ("source_only" if source_image_data_uris else "manifest_only")
                ),
            }
        except Exception as exc:
            logger.warning("Visual critique model call failed for %s: %s", layout.slide_id, exc)
            vision_status = {
                "vision_available": False,
                "mode": "rules_only",
                "fallback": "rules_only",
                "message": str(exc),
            }

    score = round(
        0.30 * scores["geometry"]
        + 0.20 * scores["readability"]
        + 0.15 * scores["contrast"]
        + 0.15 * scores["balance"]
        + 0.20 * scores["aesthetics"],
        1,
    )
    return SlideCritique(
        slide_id=layout.slide_id,
        score=score,
        geometry=scores["geometry"],
        readability=scores["readability"],
        contrast=scores["contrast"],
        balance=scores["balance"],
        aesthetics=scores["aesthetics"],
        hard_valid=hard_valid,
        defects=defects,
        recommendations=recommendations,
        vision_feedback=vision_feedback,
        vision_status=vision_status,
    )


async def critique_deck(
    layouts: Sequence[LayoutSpec],
    llm_client: Any = None,
    include_multimodal: bool = True,
    raster_data_uris: Optional[Dict[str, str]] = None,
    source_images_by_slide: Optional[Dict[str, Sequence[str]]] = None,
    color_report: Any = None,
    on_event: Optional[Callable] = None,
) -> List[SlideCritique]:
    """Critique every slide in a deck (read-only)."""
    rasters = raster_data_uris or {}
    source_images = source_images_by_slide or {}
    results: List[SlideCritique] = []
    total = len(layouts)
    for idx, layout in enumerate(layouts, start=1):
        await _safe_emit(
            on_event,
            {
                "type": "generation_stage",
                "phase": "visual_critique",
                "current": idx,
                "total": total,
                "slide_id": layout.slide_id,
            },
        )
        results.append(
            await critique_slide(
                layout,
                llm_client=llm_client,
                include_multimodal=include_multimodal,
                raster_data_uri=rasters.get(layout.slide_id),
                source_image_data_uris=source_images.get(layout.slide_id),
                color_report=color_report,
                on_event=on_event,
            )
        )
    return results


def format_critique_feedback(critique: SlideCritique) -> str:
    """Turn a critique into a concise refinement directive (layout/style only)."""
    lines = [f"Visual critique score: {critique.score:.0f}/100."]
    errors = [d for d in critique.defects if d.get("severity") in ("error", "critical")]
    warnings = [d for d in critique.defects if d.get("severity") == "warning"]
    if errors:
        lines.append("HARD DEFECTS (must fix):")
        lines.extend(f"- {d['description']}" for d in errors[:8])
    if warnings:
        lines.append("VISUAL WARNINGS (improve if possible):")
        lines.extend(f"- {d['description']}" for d in warnings[:6])
    if critique.recommendations:
        lines.append("ART DIRECTOR RECOMMENDATIONS (geometry/style only):")
        lines.extend(f"- {r}" for r in critique.recommendations[:6])
    lines.append(
        "Return the COMPLETE replacement layout as strict JSON. Preserve all text content exactly; "
        "only change geometry, spacing, typography scale, color, and composition."
    )
    return "\n".join(lines)


__all__ = [
    "SlideCritique",
    "VISUAL_CRITIC_SYSTEM_PROMPT",
    "format_layout_manifest",
    "format_critique_feedback",
    "critique_slide",
    "critique_deck",
]
