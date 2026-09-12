"""LangGraph PPT Generation Pipeline (PR13 Step 5).

Unified generation workflow driven strictly by StateGraph and conditional edges:
START
  ↓
ingest_node
  ↓
normalize_node
  ↓
validate_spec_node
  ↓ (validation_route)
  ├── Invalid (Fatal) ──> END (with error)
  ├── Invalid (Format) ──> repair_spec_node ──> validate_spec_node
  └── Valid
        ↓
compile_slidespec_node
        ↓
layout_node  (Transient DeckLayoutSpec)
        ↓
compile_presentation_ir_node  (PresentationIR)
        ↓
preview_node
        ↓
visual_review_node
        ↓ (visual_repair_route)
        ├── Needs Repair ──> visual_repair_node ──> compile_presentation_ir_node
        └── Accepted / Max Iterations
              ↓
      persist_session_node  (PresentationIR becomes canonical editable state)
              ↓
             END
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Literal, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from ...compiler.presentation_ir import compile_layout_to_presentation_ir, theme_from_art_direction
from ...evaluation.schema import IssueSeverity, VisualIssue
from ...ir.svg_renderer import SVGRenderer
from ...layout.engine import generate_deck_layout
from ...pptspec.compiler import compile_pptspec_to_deckspec
from ...pptspec.normalizer import (
    normalize_dict_to_canonical_spec,
    normalize_presentation_input,
)
from ...pptspec.parser import detect_format, parse_presentation_input
from ...pptspec.schema import CanonicalPPTSpec
from ...pptspec.validator import validate_truthfulness
from ...quality import QualityService
from ...session.manager import session_manager
from ..grounding import blocking_verdicts
from .generation_state import PPTGenerationState

logger = logging.getLogger(__name__)


async def _safe_emit(on_event: Optional[Callable], event_data: Dict[str, Any]):
    if not on_event:
        return
    import inspect
    try:
        if inspect.iscoroutinefunction(on_event):
            await on_event(event_data)
        else:
            res = on_event(event_data)
            if inspect.isawaitable(res):
                await res
    except Exception as e:
        logger.debug(f"Failed to emit event: {e}")


# =====================================================================
# Paper truthfulness (fact boundary) helpers
# =====================================================================

def _paper_source_text(paper_ir: Any) -> str:
    """Concatenated PaperIR text that exclusively may ground deck claims."""
    parts: List[str] = []
    if getattr(paper_ir, "title", None):
        parts.append(str(paper_ir.title))
    if getattr(paper_ir, "abstract", None):
        parts.append(str(paper_ir.abstract))
    for section in getattr(paper_ir, "sections", []) or []:
        if getattr(section, "title", None):
            parts.append(str(section.title))
        parts.extend(str(p) for p in getattr(section, "paragraphs", []) or [] if p)
    for figure in getattr(paper_ir, "figures", []) or []:
        if getattr(figure, "caption", None):
            parts.append(str(figure.caption))
    for table in getattr(paper_ir, "tables", []) or []:
        if getattr(table, "caption", None):
            parts.append(str(table.caption))
    return "\n".join(p for p in parts if p and p.strip())


def _paper_plan_claim_text(plan: Any) -> str:
    parts: List[str] = []
    for slide in getattr(plan, "slides", []) or []:
        for value in (getattr(slide, "title", None), getattr(slide, "objective", None)):
            if value:
                parts.append(str(value))
        parts.extend(str(m) for m in getattr(slide, "key_messages", []) or [] if m)
    return "\n".join(parts)


def _evidence_ref_exists(ref: Any, paper_ir: Any) -> bool:
    text = str(ref or "").strip()
    if not text:
        return False
    prefix, sep, value = text.partition(":")
    prefix = prefix.strip().lower() if sep else ""
    target = (value if sep else text).strip().lower()
    if not target:
        return False
    if prefix in ("", "section"):
        for section in getattr(paper_ir, "sections", []) or []:
            number = str(getattr(section, "number", "") or "").strip().lower()
            title = str(getattr(section, "title", "") or "").strip().lower()
            if target in (number, title):
                return True
        if prefix == "section":
            return False
    if prefix in ("", "figure"):
        for figure in getattr(paper_ir, "figures", []) or []:
            fid = str(getattr(figure, "id", "") or "").strip().lower()
            xref = str(getattr(figure, "xref_label", "") or "").strip().lower()
            if target in (fid, xref):
                return True
        if prefix == "figure":
            return False
    if prefix in ("", "table"):
        for table in getattr(paper_ir, "tables", []) or []:
            tid = str(getattr(table, "id", "") or "").strip().lower()
            xref = str(getattr(table, "xref_label", "") or "").strip().lower()
            if target in (tid, xref):
                return True
        if prefix == "table":
            return False
    return False


def _validate_paper_plan_grounding(
    plan: Any,
    paper_ir: Any,
    *,
    paper_visual_ir: Any = None,
    strict_policy: bool = True,
) -> List[str]:
    """Return truthfulness violations for a plan (empty == grounded).

    Numeric data claims are ALWAYS enforced. Policy phrases (SOTA, 企业级, ...)
    are enforced only for LLM-authored plans (``strict_policy``); the deterministic
    legacy planner is curated template text and is exempt from the phrase policy.

    Every evidence handle the plan can carry must resolve to a real PaperIR /
    PaperVisualIR object: ``factual_evidence_ids`` (section/figure/table handles),
    ``source_sections``, ``source_figures``, ``source_tables``, ``source_pages`` and
    ``visual_evidence_ids``. A plan that references a non-existent object is
    ungrounded and must never reach design.
    """
    source_text = _paper_source_text(paper_ir)
    claim_text = _paper_plan_claim_text(plan)
    errors: List[str] = []
    seen: set = set()

    def _add(message: str) -> None:
        if message not in seen:
            seen.add(message)
            errors.append(message)

    for verdict in blocking_verdicts(claim_text, source_text, placeholder_ok=False):
        is_numeric = verdict.category == "numeric"
        if not is_numeric and not strict_policy:
            continue
        if verdict.decision == "PLACEHOLDER":
            _add(f"UNGROUNDED_CLAIM: '{verdict.claim}' is not supported by PaperIR")
        else:
            _add(f"UNSUPPORTED_TEXTUAL_FACT: '{verdict.claim}' is not grounded in PaperIR")

    page_count = int(getattr(getattr(paper_ir, "metadata", None), "page_count", 0) or 0)
    if page_count <= 0 and paper_visual_ir is not None:
        page_count = int(getattr(paper_visual_ir, "page_count", 0) or 0)
    visual_evidence_pool = set()
    if paper_visual_ir is not None:
        try:
            visual_evidence_pool = set(paper_visual_ir.visual_evidence_ids())
        except Exception:  # pragma: no cover - defensive
            visual_evidence_pool = set()

    for slide in getattr(plan, "slides", []) or []:
        index = getattr(slide, "index", "?")

        for ref in getattr(slide, "factual_evidence_ids", []) or []:
            if not _evidence_ref_exists(ref, paper_ir):
                _add(
                    f"INVALID_EVIDENCE_REFERENCE: '{ref}' on slide "
                    f"{index} does not exist in PaperIR"
                )

        for ref in getattr(slide, "source_sections", []) or []:
            if not _evidence_ref_exists(f"section:{ref}", paper_ir):
                _add(
                    f"INVALID_SECTION_REFERENCE: '{ref}' on slide "
                    f"{index} does not exist in PaperIR"
                )

        for ref in getattr(slide, "source_figures", []) or []:
            if not _evidence_ref_exists(f"figure:{ref}", paper_ir):
                _add(
                    f"INVALID_FIGURE_REFERENCE: '{ref}' on slide "
                    f"{index} does not exist in PaperIR"
                )

        for ref in getattr(slide, "source_tables", []) or []:
            if not _evidence_ref_exists(f"table:{ref}", paper_ir):
                _add(
                    f"INVALID_TABLE_REFERENCE: '{ref}' on slide "
                    f"{index} does not exist in PaperIR"
                )

        if page_count > 0:
            for page in getattr(slide, "source_pages", []) or []:
                try:
                    page_number = int(page)
                except (TypeError, ValueError):
                    page_number = -1
                if page_number < 1 or page_number > page_count:
                    _add(
                        f"INVALID_SOURCE_PAGE: '{page}' on slide {index} is outside "
                        f"1..{page_count}"
                    )

        for ref in getattr(slide, "visual_evidence_ids", []) or []:
            if str(ref) not in visual_evidence_pool:
                _add(
                    f"INVALID_VISUAL_EVIDENCE_ID: '{ref}' on slide {index} does not "
                    f"exist in PaperVisualIR"
                )

    return errors


def _format_truthfulness_feedback(errors: List[str]) -> str:
    lines = [
        "TRUTHFULNESS VIOLATIONS: the previous plan contained claims that are NOT",
        "grounded in the provided paper facts. Remove or rewrite them and return the",
        "complete JSON again. Numbers and factual claims may ONLY come from the paper.",
    ]
    lines.extend(f"- {e}" for e in errors[:8])
    return "\n".join(lines)


def _paper_source_images_by_slide(state: PPTGenerationState) -> Dict[str, List[str]]:
    """Trusted page/crop data URIs per slide for the source-aware critic."""
    if state.get("source_type") != "paper":
        return {}
    plan = state.get("presentation_plan")
    if plan is None:
        return {}
    from ...design.paper_assets import paper_source_images_by_slide

    return paper_source_images_by_slide(
        state.get("paper_ir"),
        state.get("paper_visual_ir"),
        state.get("paper_cache_dir"),
        getattr(plan, "slides", []) or [],
    )


def _make_candidate_raster_provider(
    state: PPTGenerationState,
) -> Callable[[Any], Optional[str]]:
    """Build a raster provider that compiles candidates EXACTLY like production.

    The candidate screenshot shown to the Vision critic must use the same deck
    theme and paper asset resolution as the final ``PresentationIR``; otherwise the
    critic reviews a different artifact than the one that gets persisted.
    """
    art_direction = state.get("deck_art_direction")
    theme_override = (
        theme_from_art_direction(art_direction) if art_direction is not None else None
    )
    asset_resolver = None
    if state.get("source_type") == "paper":
        from ...design.paper_assets import make_paper_asset_resolver

        asset_resolver = make_paper_asset_resolver(
            state.get("paper_ir"),
            state.get("paper_visual_ir"),
            state.get("paper_cache_dir"),
        )

    def _provider(layout: Any) -> Optional[str]:
        try:
            from ...eval.renderer_snapshot import SlideSnapshotRenderer
            from ...layout.schema import Canvas, DeckLayoutSpec

            deck = DeckLayoutSpec(
                title="_candidate",
                canvas=layout.canvas or Canvas(),
                slides=[layout],
            )
            pres = compile_layout_to_presentation_ir(
                deck,
                theme_override=theme_override,
                asset_resolver=asset_resolver,
            )
            if not pres.slides:
                return None
            return SlideSnapshotRenderer.render_data_uri(pres.slides[0], scale=1.0)
        except Exception as exc:  # pragma: no cover - renderer dependent
            logger.debug("Candidate raster provider failed: %s", exc)
            return None

    return _provider


# =====================================================================
# Node Implementations
# =====================================================================

async def ingest_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Inspect and classify raw input format."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    raw_input = state.get("raw_input", "")
    fmt = detect_format(raw_input)

    await _safe_emit(on_event, {"type": "generation_progress", "status": "ingested", "format": fmt.value})

    return {
        "input_format": fmt.value,
        "status": "ingested",
        "repair_iteration": state.get("repair_iteration", 0),
        "max_repair_iterations": state.get("max_repair_iterations", 3),
        "normalization_warnings": list(state.get("normalization_warnings", [])),
        "validation_errors": list(state.get("validation_errors", [])),
    }


async def normalize_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Perform flexible ingestion and deterministic normalization to CanonicalPPTSpec."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    llm_client = configurable.get("llm_client")

    raw_input = state.get("raw_input", "")
    await _safe_emit(on_event, {"type": "generation_progress", "status": "normalizing", "text": "归一化内容为规范 CanonicalPPTSpec..."})

    # If canonical_spec is already set (e.g. pre-validated artifact passed from API), skip
    if state.get("canonical_spec") is not None:
        return {"status": "normalized"}

    norm_res = await normalize_presentation_input(
        raw_text=raw_input,
        llm_client=llm_client,
        strict_truthfulness=False,  # Truthfulness will be checked in validate_spec_node
    )

    warnings = list(state.get("normalization_warnings", [])) + norm_res.warnings
    errors = list(state.get("validation_errors", [])) + norm_res.errors

    return {
        "canonical_spec": norm_res.spec,
        "input_format": norm_res.input_format,
        "normalization_warnings": warnings,
        "validation_errors": errors,
        "asset_requirements": norm_res.asset_requirements,
        "status": "normalized",
    }


async def validate_spec_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Execute rigorous Truthfulness Guard and schema validation."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "validating", "text": "执行真实性校验与数值回溯..."})

    spec = state.get("canonical_spec")
    raw_input = state.get("raw_input", "")

    if spec is None:
        return {
            "validation_errors": state.get("validation_errors", []) + ["Spec is None; normalization failed."],
            "status": "validation_failed",
            "error": "CANONICAL_SPEC_MISSING",
        }

    val_res = validate_truthfulness(raw_input, spec, strict=False)

    errors = list(state.get("validation_errors", [])) + val_res.errors
    warnings = list(state.get("normalization_warnings", [])) + val_res.warnings

    status = "spec_validated" if len(errors) == 0 else "validation_failed"
    error_msg = None if len(errors) == 0 else "; ".join(errors)

    return {
        "validation_errors": errors,
        "normalization_warnings": warnings,
        "status": status,
        "error": error_msg,
    }


async def repair_spec_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Deterministic structural/formatting repair (never invents facts or numbers)."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    attempts = state.get("spec_repair_attempts", 0) + 1
    await _safe_emit(on_event, {"type": "generation_progress", "status": "repairing_spec", "text": f"修复格式与证据映射 (第 {attempts} 次)..."})

    raw_input = state.get("raw_input", "")
    warnings: List[str] = []

    try:
        _, candidate = parse_presentation_input(raw_input)
        repaired_spec = normalize_dict_to_canonical_spec(candidate, warnings=warnings)
        return {
            "canonical_spec": repaired_spec,
            "spec_repair_attempts": attempts,
            "normalization_warnings": list(state.get("normalization_warnings", [])) + warnings,
            "validation_errors": [],  # Cleared for re-validation in next node
            "status": "spec_repaired",
        }
    except Exception as e:
        return {
            "spec_repair_attempts": attempts,
            "error": f"Failed to repair spec: {e}",
            "status": "repair_spec_failed",
        }


async def compile_slidespec_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Compile CanonicalPPTSpec to DeckSpec with deterministic block IDs."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "planning", "text": "规划幻灯片结构与生成 Block ID..."})

    spec = state["canonical_spec"]
    assert spec is not None, "CanonicalPPTSpec cannot be None"
    deck_spec = compile_pptspec_to_deckspec(spec)

    return {
        "deck_spec": deck_spec,
        "status": "slidespec_compiled",
    }


async def paper_plan_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Plan a paper deck: art direction + presentation plan + DeckSpec.

    Uses the LLM-native art director when available; otherwise falls back to the
    deterministic planner + default art direction. Never fabricates facts.
    """
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    llm_client = configurable.get("llm_client")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "planning", "text": "论文艺术总监规划叙事结构与视觉语言..."})

    paper_ir = state.get("paper_ir")
    if paper_ir is None:
        return {
            "status": "validation_failed",
            "error": "PAPER_IR_MISSING",
            "validation_errors": list(state.get("validation_errors", [])) + ["PAPER_IR_MISSING"],
        }

    from ...design import build_plan_and_direction
    from ...slidespec.mapper import map_presentation_plan_to_deck_spec

    art_direction, plan, used_llm = await build_plan_and_direction(
        llm_client,
        paper_ir,
        state.get("paper_visual_ir"),
        user_prompt=state.get("user_prompt", ""),
        duration_minutes=int(state.get("duration_minutes", 15) or 15),
        contact_sheet_dir=state.get("paper_cache_dir"),
        on_event=on_event,
    )
    deck_spec = map_presentation_plan_to_deck_spec(plan, paper_ir)

    return {
        "deck_art_direction": art_direction,
        "presentation_plan": plan,
        "deck_spec": deck_spec,
        "generation_mode": "llm_native" if used_llm else "legacy_template",
        "layout_source": "llm" if used_llm else "fallback_template",
        "fallback_reason": None if used_llm else "art_direction_unavailable",
        "status": "paper_planned",
    }


async def paper_truthfulness_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Validate the Art Director plan against PaperIR; one repair then hard fail.

    This is the paper branch's equivalent of ``validate_truthfulness``: numbers and
    factual claims produced by the LLM must be grounded in the paper text, and every
    ``factual_evidence_ids`` handle must reference a real PaperIR section/figure/table.
    A single targeted repair round is attempted; persistent violations terminate the
    graph without persisting a deck (never a silent fallback).
    """
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    llm_client = configurable.get("llm_client")

    plan = state.get("presentation_plan")
    paper_ir = state.get("paper_ir")
    if plan is None or paper_ir is None:
        return {"status": state.get("status", "paper_planned")}

    await _safe_emit(
        on_event,
        {"type": "generation_progress", "status": "grounding", "text": "校验论文事实边界与证据引用..."},
    )

    attempts = int(state.get("paper_truthfulness_attempts", 0) or 0)
    strict_policy = state.get("generation_mode") == "llm_native"
    errors = _validate_paper_plan_grounding(
        plan,
        paper_ir,
        paper_visual_ir=state.get("paper_visual_ir"),
        strict_policy=strict_policy,
    )

    if errors and attempts < 1:
        await _safe_emit(
            on_event,
            {
                "type": "generation_progress",
                "status": "repairing_grounding",
                "text": "发现未grounded主张，进行 1 次定向修复...",
            },
        )
        from ...design import build_plan_and_direction
        from ...slidespec.mapper import map_presentation_plan_to_deck_spec

        rework_prompt = (
            (state.get("user_prompt") or "") + "\n\n" + _format_truthfulness_feedback(errors)
        ).strip()
        art_direction, repaired_plan, used_llm = await build_plan_and_direction(
            llm_client,
            paper_ir,
            state.get("paper_visual_ir"),
            user_prompt=rework_prompt,
            duration_minutes=int(state.get("duration_minutes", 15) or 15),
            contact_sheet_dir=state.get("paper_cache_dir"),
            on_event=on_event,
        )
        attempts += 1
        if repaired_plan is not None:
            remaining = _validate_paper_plan_grounding(
                repaired_plan,
                paper_ir,
                paper_visual_ir=state.get("paper_visual_ir"),
                strict_policy=strict_policy,
            )
            if not remaining:
                deck_spec = map_presentation_plan_to_deck_spec(repaired_plan, paper_ir)
                return {
                    "deck_art_direction": art_direction,
                    "presentation_plan": repaired_plan,
                    "deck_spec": deck_spec,
                    "generation_mode": "llm_native" if used_llm else "legacy_template",
                    "layout_source": "llm" if used_llm else "fallback_template",
                    "fallback_reason": None if used_llm else "art_direction_unavailable",
                    "paper_truthfulness_attempts": attempts,
                    "paper_truthfulness_errors": [],
                    "status": "paper_truthfulness_passed",
                    "error": None,
                }
            errors = remaining

    if errors:
        message = "PAPER_TRUTHFULNESS_FAILED: " + "; ".join(errors[:8])
        await _safe_emit(
            on_event,
            {
                "type": "generation_progress",
                "status": "grounding_failed",
                "error": message,
                "text": "论文事实边界校验失败，已阻止生成。",
            },
        )
        return {
            "paper_truthfulness_attempts": attempts,
            "paper_truthfulness_errors": errors,
            "status": "validation_failed",
            "error": message,
            "validation_errors": list(state.get("validation_errors", [])) + errors,
        }

    return {
        "paper_truthfulness_attempts": attempts,
        "paper_truthfulness_errors": [],
        "status": "paper_truthfulness_passed",
        "error": None,
    }


async def paper_design_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Design the deck from the paper plan: free-form layouts + bounded refinement."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    llm_client = configurable.get("llm_client")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "layout", "text": "逐页自由式布局设计 + 视觉精炼..."})

    deck_spec = state["deck_spec"]
    plan = state["presentation_plan"]
    art_direction = state["deck_art_direction"]
    paper_ir = state.get("paper_ir")
    paper_visual_ir = state.get("paper_visual_ir")
    assert deck_spec is not None, "DeckSpec cannot be None"

    from ...config import settings
    from ...layout.schema import Canvas

    canvas = Canvas()
    if settings.llm_native_layout_enabled and state.get("generation_mode") == "llm_native":
        from ...design import design_deck_layouts, refine_deck_aesthetics

        result = await design_deck_layouts(
            llm_client,
            deck_spec,
            plan,
            art_direction,
            paper_ir=paper_ir,
            paper_visual_ir=paper_visual_ir,
            canvas=canvas,
            on_event=on_event,
        )
        result = await refine_deck_aesthetics(
            llm_client,
            result,
            deck_spec,
            plan,
            art_direction,
            paper_ir=paper_ir,
            paper_visual_ir=paper_visual_ir,
            canvas=canvas,
            on_event=on_event,
            include_multimodal=False,
        )
        deck_layout = result.deck_layout
        fallbacks = deck_layout.metadata.get("fallback_slide_indices") or []
        return {
            "deck_layout": deck_layout,
            "generation_mode": "llm_native",
            "layout_source": deck_layout.metadata.get("layout_source", "llm"),
            "fallback_reason": (
                f"template_fallback_slide_indices={fallbacks}" if fallbacks else None
            ),
            "status": "layout_generated",
        }

    deck_layout = generate_deck_layout(deck_spec, validate=True, strict=False)
    return {
        "deck_layout": deck_layout,
        "generation_mode": "legacy_template",
        "layout_source": "fallback_template",
        "fallback_reason": state.get("fallback_reason") or "llm_native_disabled",
        "status": "layout_generated",
    }


async def layout_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Calculate 1280x720 canvas geometry and generate transient DeckLayoutSpec.

    Prefers free-form LLM layout plans (``state["llm_layout_plans"]``) when the
    native layout flag is enabled; otherwise falls back to the deterministic
    template engine. Per-slide template fallback is recorded as provenance.
    """
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "layout", "text": "计算 1280x720 坐标与几何布局..."})

    deck_spec = state["deck_spec"]
    assert deck_spec is not None, "DeckSpec cannot be None"

    from ...config import settings

    plans = state.get("llm_layout_plans") or []
    if plans and settings.llm_native_layout_enabled:
        from ...design.layout_compiler import compile_llm_deck_layout

        deck_layout = compile_llm_deck_layout(plans, deck_spec)
        fallbacks = deck_layout.metadata.get("fallback_slide_indices") or []
        generation_mode = "llm_native"
        layout_source = deck_layout.metadata.get("layout_source", "llm")
        fallback_reason = (
            f"template_fallback_slide_indices={fallbacks}" if fallbacks else None
        )
    else:
        deck_layout = generate_deck_layout(deck_spec, validate=True, strict=False)
        generation_mode = "legacy_template"
        layout_source = "fallback_template"
        fallback_reason = None if plans else "no_llm_layout_plans"

    return {
        "deck_layout": deck_layout,
        "status": "layout_generated",
        "generation_mode": generation_mode,
        "layout_source": layout_source,
        "fallback_reason": fallback_reason,
    }


async def compile_presentation_ir_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Compile transient DeckLayoutSpec into PresentationIR."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "rendering", "text": "编译 PresentationIR 图元与占位符..."})

    deck_layout = state["deck_layout"]
    assert deck_layout is not None, "DeckLayoutSpec cannot be None"

    asset_resolver = None
    if state.get("source_type") == "paper":
        from ...design.paper_assets import make_paper_asset_resolver

        asset_resolver = make_paper_asset_resolver(
            state.get("paper_ir"),
            state.get("paper_visual_ir"),
            state.get("paper_cache_dir"),
        )

    art_direction = state.get("deck_art_direction")
    theme_override = None
    if art_direction is not None:
        theme_override = theme_from_art_direction(art_direction)

    pres_ir = compile_layout_to_presentation_ir(
        deck_layout, theme_override=theme_override, asset_resolver=asset_resolver
    )

    generation = {
        "mode": state.get("generation_mode", "legacy_template"),
        "source_type": state.get("source_type", "pptspec"),
        "layout_source": state.get("layout_source", "fallback_template"),
    }
    fallback_reason = state.get("fallback_reason")
    if fallback_reason:
        generation["fallback_reason"] = fallback_reason

    if generation["source_type"] == "paper":
        paper_ir = state.get("paper_ir")
        if paper_ir is not None:
            generation["paper"] = {
                "title": paper_ir.title,
                "page_count": paper_ir.metadata.page_count,
                "figure_count": len(paper_ir.figures),
                "table_count": len(paper_ir.tables),
            }
        paper_visual_ir = state.get("paper_visual_ir")
        if paper_visual_ir is not None:
            generation["paper_visual"] = {
                "page_count": paper_visual_ir.page_count,
                "vision_model": paper_visual_ir.vision_model,
            }
        art_direction = state.get("deck_art_direction")
        if art_direction is not None:
            generation["art_direction"] = {
                "design_concept": art_direction.design_concept,
                "visual_language": art_direction.visual_language,
                "primary_accent": art_direction.color_direction.primary_accent,
            }
        generation["duration_minutes"] = int(state.get("duration_minutes", 15) or 15)

    pres_ir.metadata["generation"] = generation

    return {
        "presentation_ir": pres_ir,
        "status": "ir_compiled",
    }


async def preview_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Render SVGs for slides to enable visual critique and studio preview."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "preview", "text": "生成 SVG 预览渲染..."})

    pres_ir = state["presentation_ir"]
    rasters: Dict[str, str] = {}
    if pres_ir:
        from ...eval.renderer_snapshot import SlideSnapshotRenderer

        for slide in pres_ir.slides:
            # Pre-render SVG to ensure fidelity and catch exceptions
            SVGRenderer.render_slide(slide)
            try:
                rasters[slide.id] = SlideSnapshotRenderer.render_data_uri(slide, scale=1.0)
            except Exception as exc:  # pragma: no cover - renderer dependent
                logger.debug("Slide raster for %s failed: %s", slide.id, exc)

    return {"status": "preview_rendered", "slide_rasters": rasters}


async def visual_review_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Critique layout geometry using RuleBasedEvaluator on DeckLayoutSpec."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    await _safe_emit(on_event, {"type": "generation_progress", "status": "reviewing", "text": "视觉与几何冲突自检..."})

    deck_layout = state["deck_layout"]
    assert deck_layout is not None, "DeckLayoutSpec cannot be None"

    issues: List[VisualIssue] = QualityService.evaluate_layout(deck_layout)

    return {
        "visual_issues": issues,
        "status": "visual_reviewed",
    }


async def visual_repair_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Apply spatial/typographic patches to transient DeckLayoutSpec only (never touches facts)."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    iteration = state.get("repair_iteration", 0) + 1
    await _safe_emit(on_event, {"type": "generation_progress", "status": "repairing", "text": f"执行自愈布局微调 (第 {iteration} 轮)..."})

    deck_layout = state["deck_layout"]
    issues = state.get("visual_issues", [])
    assert deck_layout is not None, "DeckLayoutSpec cannot be None"

    # Collect patches across all slides
    all_patches = []
    for slide in deck_layout.slides:
        slide_issues = [i for i in issues if i.slide_id == slide.slide_id]
        all_patches.extend(QualityService.patches_for_issues(slide_issues, slide))

    if all_patches:
        patched_deck_layout, _ = QualityService.apply_layout_patches(
            deck_layout,
            all_patches,
            enforce_transaction=True,
        )
    else:
        patched_deck_layout = deck_layout

    return {
        "deck_layout": patched_deck_layout,
        "repair_iteration": iteration,
        "status": "visual_repaired",
    }


async def deck_visual_review_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Source-aware deck-level multimodal review (S4 / Phase 9).

    Runs only for the paper branch and only when a vision-capable client exists.
    Read-only: aggregates a ``DeckCritique`` and lists ``slides_to_revisit``. The
    critic receives each rendered slide screenshot alongside the paper page/crop it
    claims to represent.
    """
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    llm_client = configurable.get("llm_client")

    if state.get("source_type") != "paper":
        return {"status": "deck_review_skipped", "slides_to_revisit": []}
    llm_available = bool(llm_client and getattr(llm_client, "api_key", None))
    if not llm_available:
        return {"status": "deck_review_skipped", "slides_to_revisit": []}

    deck_layout = state.get("deck_layout")
    art_direction = state.get("deck_art_direction")
    if deck_layout is None or art_direction is None:
        return {"status": "deck_review_skipped", "slides_to_revisit": []}

    await _safe_emit(
        on_event,
        {"type": "generation_progress", "status": "deck_review", "text": "Deck 级论文对照视觉复审..."},
    )

    from ...design.deck_critic import review_deck
    from ...design.color_validator import validate_deck_colors

    color_report = validate_deck_colors(art_direction, deck_layout.slides)
    critique = await review_deck(
        deck_layout.slides,
        llm_client,
        raster_data_uris=state.get("slide_rasters") or {},
        source_images_by_slide=_paper_source_images_by_slide(state),
        color_report=color_report,
        on_event=on_event,
    )
    return {
        "deck_review": critique.to_dict(),
        "slides_to_revisit": list(critique.slides_to_revisit),
        "status": "deck_reviewed",
    }


async def deck_revisit_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Re-design ONLY the slides flagged by the deck critic (bounded)."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    llm_client = configurable.get("llm_client")

    deck_layout = state.get("deck_layout")
    deck_spec = state.get("deck_spec")
    plan = state.get("presentation_plan")
    art_direction = state.get("deck_art_direction")
    revisit = state.get("slides_to_revisit") or []
    assert deck_layout is not None and deck_spec is not None and plan is not None

    await _safe_emit(
        on_event,
        {
            "type": "generation_progress",
            "status": "deck_revisit",
            "text": f"针对 {len(revisit)} 页进行视觉复审返工...",
        },
    )

    from ...design.aesthetic_refiner import refine_deck_aesthetics
    from ...design.layout_designer import DeckDesignResult

    result = DeckDesignResult(deck_layout=deck_layout, plans=[])
    refined = await refine_deck_aesthetics(
        llm_client,
        result,
        deck_spec,
        plan,
        art_direction,
        paper_ir=state.get("paper_ir"),
        paper_visual_ir=state.get("paper_visual_ir"),
        canvas=deck_layout.canvas,
        raster_data_uris=state.get("slide_rasters") or {},
        source_images_by_slide=_paper_source_images_by_slide(state),
        raster_provider=_make_candidate_raster_provider(state),
        only_slide_indices=revisit,
        include_multimodal=True,
        on_event=on_event,
    )
    return {
        "deck_layout": refined.deck_layout,
        "deck_revisit_round": int(state.get("deck_revisit_round", 0) or 0) + 1,
        "status": "deck_revisited",
    }


async def final_generation_validation_node(
    state: PPTGenerationState, config: RunnableConfig
) -> Dict[str, Any]:
    """Unified hard correctness gate validating the exact IR that will be persisted.

    Runs after every layout-changing stage (visual repair, deck revisit). It NEVER
    recompiles: it validates the already-compiled ``presentation_ir`` together with
    the ``deck_layout`` it was derived from and the ``deck_spec`` plan. Figures and
    tables are recognized via explicit ``metadata['asset_status']`` ('resolved' |
    'placeholder') so no text sniffing is required. Any failure is fail-closed: the
    graph ends without ever reaching ``commit_replacement``.
    """
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")

    deck_layout = state.get("deck_layout")
    deck_spec = state.get("deck_spec")
    pres_ir = state.get("presentation_ir")
    art_direction = state.get("deck_art_direction")

    errors: List[str] = []
    if deck_layout is None:
        errors.append("FINAL_VALIDATION: deck_layout is missing")
    if deck_spec is None:
        errors.append("FINAL_VALIDATION: deck_spec is missing")
    if pres_ir is None:
        errors.append("FINAL_VALIDATION: presentation_ir is missing")

    if not errors:
        from ...design.color_validator import validate_deck_colors
        from ...design.layout_compiler import hard_validate_layout
        from ...ir.models import ImageElementIR, TableElementIR

        slide_specs = {s.index: s for s in deck_spec.slides}

        if len(pres_ir.slides) != len(deck_layout.slides):
            errors.append(
                "FINAL_VALIDATION: presentation_ir slide count "
                f"{len(pres_ir.slides)} != deck_layout slide count {len(deck_layout.slides)}"
            )

        # 1. Hard layout validation (geometry, collisions, readable type).
        # Canonical block coverage is an LLM-native contract: the free-form layout
        # model must bind every required content block. The deterministic template
        # engine never promised 1:1 block binding, so it is validated structurally
        # only (otherwise a legitimate legacy deck would be blocked). Visual source
        # assets are the exception and are covered unconditionally in step 3.
        for layout in deck_layout.slides:
            is_llm = (getattr(layout, "metadata", {}) or {}).get("layout_source") == "llm"
            slide_spec = slide_specs.get(layout.slide_index) if is_llm else None
            report = hard_validate_layout(layout, slide_spec)
            for message in report.errors:
                errors.append(f"FINAL_LAYOUT[{layout.slide_index}]: {message}")

        # 2. Fresh deck color validation.
        if art_direction is not None:
            color_report = validate_deck_colors(art_direction, deck_layout.slides)
            for issue in color_report.errors:
                errors.append(f"FINAL_COLOR[{issue.slide_id}]: {issue.description}")

        # 3. Unconditional visual source-asset coverage (figures + tables) on the
        # actual IR, via explicit asset_status. Applies to every layout: a fallback
        # template must still map each FigureBlock/TableBlock to a resolved asset or
        # an explicit placeholder so visual source content is never silently dropped.
        for slide_ir in pres_ir.slides:
            if not slide_ir.elements:
                errors.append(f"FINAL_IR[{slide_ir.id}]: slide has no elements")
                continue
            elements_by_ref = {
                getattr(el, "source_ref", None): el for el in slide_ir.elements
            }
            spec = slide_specs.get(slide_ir.slide_num)
            if spec is None:
                continue
            for block in spec.blocks:
                block_id = getattr(block, "block_id", "")
                if not block_id:
                    continue
                kind = getattr(block, "kind", "")

                if kind == "figure":
                    element = elements_by_ref.get(block_id)
                    if element is None:
                        errors.append(
                            f"FINAL_IR[{slide_ir.id}]: figure block '{block_id}' is not compiled"
                        )
                        continue
                    meta = getattr(element, "metadata", {}) or {}
                    expected = getattr(block, "source_figure_id", "") or ""
                    if isinstance(element, ImageElementIR):
                        if meta.get("asset_status") != "resolved" or not getattr(element, "src", None):
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: figure '{block_id}' is not resolved"
                            )
                        elif (meta.get("source_figure_id") or "") != expected:
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: figure '{block_id}' "
                                "source_figure_id mismatch"
                            )
                    elif meta.get("asset_status") == "placeholder":
                        if (meta.get("source_figure_id") or "") != expected:
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: figure placeholder '{block_id}' "
                                "source_figure_id mismatch"
                            )
                    else:
                        errors.append(
                            f"FINAL_IR[{slide_ir.id}]: figure '{block_id}' has no explicit "
                            "asset_status"
                        )

                elif kind == "table":
                    element = elements_by_ref.get(block_id)
                    if element is None:
                        errors.append(
                            f"FINAL_IR[{slide_ir.id}]: table block '{block_id}' is not compiled"
                        )
                        continue
                    meta = getattr(element, "metadata", {}) or {}
                    expected = getattr(block, "source_table_id", "") or ""
                    if isinstance(element, TableElementIR):
                        if meta.get("asset_status") != "resolved":
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: table '{block_id}' is not resolved"
                            )
                        elif (meta.get("source_table_id") or "") != expected:
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: table '{block_id}' "
                                "source_table_id mismatch"
                            )
                    elif meta.get("asset_status") == "placeholder":
                        if not meta.get("is_table_placeholder"):
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: table placeholder '{block_id}' "
                                "lacks is_table_placeholder"
                            )
                        if (meta.get("source_table_id") or "") != expected:
                            errors.append(
                                f"FINAL_IR[{slide_ir.id}]: table placeholder '{block_id}' "
                                "source_table_id mismatch"
                            )
                    else:
                        errors.append(
                            f"FINAL_IR[{slide_ir.id}]: table '{block_id}' has no explicit "
                            "asset_status"
                        )

    if errors:
        message = "FINAL_GENERATION_VALIDATION_FAILED: " + "; ".join(errors[:8])
        await _safe_emit(
            on_event,
            {
                "type": "generation_progress",
                "status": "final_validation_failed",
                "error": message,
                "text": "最终一致性校验失败，已阻止写入。",
            },
        )
        return {
            "status": "validation_failed",
            "error": message,
            "validation_errors": list(state.get("validation_errors", [])) + errors,
        }

    return {"status": "final_validation_passed"}


async def persist_session_node(state: PPTGenerationState, config: RunnableConfig) -> Dict[str, Any]:
    """Persist final PresentationIR into target PPTSession as the single canonical editable state."""
    configurable = config.get("configurable", {})
    on_event = configurable.get("on_event")
    session_id = state.get("session_id")

    pres_ir = state.get("presentation_ir")
    base_epoch = state.get("base_document_epoch")
    base_revision = state.get("base_revision")
    committed = False
    commit_error: Optional[str] = None

    if session_id and pres_ir:
        session = session_manager.get_session(session_id)
        if session is not None:
            # CAS commit: rejects when the user (or another writer) advanced the
            # document while generation was running. Owns the mutation lock.
            # This is a REST-initiated replacement (the PPTSpec generate endpoint
            # is not an Agent turn), so it is source="rest": if an Agent turn
            # holds the session freeze it is rejected DOCUMENT_FROZEN.
            result = await session.commit_replacement(
                pres_ir,
                expected_epoch=base_epoch,
                expected_revision=base_revision,
                clear_history=True,
                clear_checkpoints=True,
                checkpoint_description=(
                    "Generated from PaperIR (LLM-native, S4)"
                    if state.get("source_type") == "paper"
                    else "Generated from CanonicalPPTSpec (PR13)"
                ),
                source="rest",
            )
            committed = result.committed
            commit_error = result.error
            if not committed:
                logger.info(
                    f"Generation for session '{session_id}' discarded as stale "
                    f"({result.error}); document revision advanced during generation."
                )

    if not committed:
        await _safe_emit(on_event, {
            "type": "generation_progress",
            "status": "stale_generation",
            "error": commit_error or "generation_not_committed",
            "text": "生成期间文档已被修改，结果已丢弃，未覆盖用户的最新编辑。",
        })
        return {
            "status": "stale_generation",
            "error": None,
        }

    await _safe_emit(on_event, {
        "type": "generation_progress",
        "status": "completed",
        "presentation_id": pres_ir.id if pres_ir else None,
        "slides_count": len(pres_ir.slides) if pres_ir else 0,
    })

    return {
        "status": "completed",
    }


# =====================================================================
# Conditional Routers
# =====================================================================

def validation_route(state: PPTGenerationState) -> Literal["compile_slidespec_node", "repair_spec_node", "__end__"]:
    """Route based on spec validation status.

    Truthfulness violations (UNSUPPORTED_NUMERIC_VALUE, UNSUPPORTED_TEXTUAL_FACT,
    UNSUPPORTED_SOURCE_LOCATOR, INVALID_EVIDENCE_REFERENCE) are fatal non-repairable errors
    and terminate directly to __end__.
    """
    errors = state.get("validation_errors", [])
    if not errors:
        return "compile_slidespec_node"

    fatal_error_signatures = (
        "UNSUPPORTED_NUMERIC_VALUE",
        "UNSUPPORTED_TEXTUAL_FACT",
        "UNSUPPORTED_SOURCE_LOCATOR",
        "UNSUPPORTED_FACT_RELATION",
        "INVALID_EVIDENCE_REFERENCE",
    )

    if any(any(sig in e for sig in fatal_error_signatures) for e in errors):
        return "__end__"

    attempts = state.get("spec_repair_attempts", 0)
    max_attempts = state.get("max_spec_repair_attempts", 1)

    # If error is a recoverable format error and attempts haven't reached max
    if attempts < max_attempts:
        return "repair_spec_node"

    # Max repair attempts reached or unrecoverable error -> terminate
    return "__end__"


def visual_repair_route(state: PPTGenerationState) -> Literal["visual_repair_node", "deck_visual_review_node"]:
    """Route geometry self-heal, then hand off to the deck-level review."""
    issues = state.get("visual_issues", [])
    iteration = state.get("repair_iteration", 0)
    max_iterations = state.get("max_repair_iterations", 3)

    has_fixable_issues = any(i.severity in (IssueSeverity.ERROR, IssueSeverity.WARNING) for i in issues)

    if has_fixable_issues and iteration < max_iterations:
        return "visual_repair_node"

    return "deck_visual_review_node"


def deck_visual_review_route(
    state: PPTGenerationState,
) -> Literal["deck_revisit_node", "final_generation_validation_node"]:
    """Revisit flagged slides for a bounded number of rounds, else final-validate."""
    if state.get("source_type") != "paper":
        return "final_generation_validation_node"
    revisit = state.get("slides_to_revisit") or []
    round_index = int(state.get("deck_revisit_round", 0) or 0)
    from ...config import settings

    if revisit and round_index < settings.max_deck_revisit_rounds:
        return "deck_revisit_node"
    return "final_generation_validation_node"


def final_validation_route(state: PPTGenerationState) -> Literal["persist_session_node", "__end__"]:
    """Fail closed: a deck that fails the final gate is never persisted."""
    return "__end__" if state.get("status") == "validation_failed" else "persist_session_node"


def entry_route(state: PPTGenerationState) -> Literal["paper_plan_node", "ingest_node"]:
    """Choose the paper branch or the canonical PPTSpec branch."""
    return "paper_plan_node" if state.get("source_type") == "paper" else "ingest_node"


def paper_plan_route(state: PPTGenerationState) -> Literal["paper_truthfulness_node", "__end__"]:
    """Terminate early when the paper branch has no PaperIR."""
    return "__end__" if state.get("status") == "validation_failed" else "paper_truthfulness_node"


def paper_truthfulness_route(state: PPTGenerationState) -> Literal["paper_design_node", "__end__"]:
    """Terminate when the paper plan cannot be grounded in PaperIR."""
    return "__end__" if state.get("status") == "validation_failed" else "paper_design_node"


# =====================================================================
# StateGraph Construction
# =====================================================================

def build_generation_graph() -> Any:
    """Build and compile the unified LangGraph PPT Generation StateGraph."""
    workflow = StateGraph(PPTGenerationState)

    # 1. Add all nodes
    workflow.add_node("ingest_node", ingest_node)
    workflow.add_node("normalize_node", normalize_node)
    workflow.add_node("validate_spec_node", validate_spec_node)
    workflow.add_node("repair_spec_node", repair_spec_node)
    workflow.add_node("compile_slidespec_node", compile_slidespec_node)
    workflow.add_node("paper_plan_node", paper_plan_node)
    workflow.add_node("paper_truthfulness_node", paper_truthfulness_node)
    workflow.add_node("paper_design_node", paper_design_node)
    workflow.add_node("layout_node", layout_node)
    workflow.add_node("compile_presentation_ir_node", compile_presentation_ir_node)
    workflow.add_node("preview_node", preview_node)
    workflow.add_node("visual_review_node", visual_review_node)
    workflow.add_node("visual_repair_node", visual_repair_node)
    workflow.add_node("deck_visual_review_node", deck_visual_review_node)
    workflow.add_node("deck_revisit_node", deck_revisit_node)
    workflow.add_node("final_generation_validation_node", final_generation_validation_node)
    workflow.add_node("persist_session_node", persist_session_node)

    # 2. Entry: paper branch (PaperIR + PaperVisualIR) vs PPTSpec branch
    workflow.add_conditional_edges(
        START,
        entry_route,
        {
            "paper_plan_node": "paper_plan_node",
            "ingest_node": "ingest_node",
        },
    )
    workflow.add_conditional_edges(
        "paper_plan_node",
        paper_plan_route,
        {
            "paper_truthfulness_node": "paper_truthfulness_node",
            "__end__": END,
        },
    )
    workflow.add_conditional_edges(
        "paper_truthfulness_node",
        paper_truthfulness_route,
        {
            "paper_design_node": "paper_design_node",
            "__end__": END,
        },
    )
    workflow.add_edge("paper_design_node", "compile_presentation_ir_node")

    # 3. PPTSpec linear ingestion
    workflow.add_edge("ingest_node", "normalize_node")
    workflow.add_edge("normalize_node", "validate_spec_node")

    # 3. Conditional validation routing
    workflow.add_conditional_edges(
        "validate_spec_node",
        validation_route,
        {
            "compile_slidespec_node": "compile_slidespec_node",
            "repair_spec_node": "repair_spec_node",
            "__end__": END,
        },
    )
    workflow.add_edge("repair_spec_node", "validate_spec_node")

    # 4. Compilation & layout pipeline
    workflow.add_edge("compile_slidespec_node", "layout_node")
    workflow.add_edge("layout_node", "compile_presentation_ir_node")
    workflow.add_edge("compile_presentation_ir_node", "preview_node")
    workflow.add_edge("preview_node", "visual_review_node")

    # 5. Conditional visual self-healing loop routing
    workflow.add_conditional_edges(
        "visual_review_node",
        visual_repair_route,
        {
            "visual_repair_node": "visual_repair_node",
            "deck_visual_review_node": "deck_visual_review_node",
        },
    )
    # Loop back from visual repair to re-compile PresentationIR and re-review
    workflow.add_edge("visual_repair_node", "compile_presentation_ir_node")

    # 5b. Deck-level source-aware review (paper branch) and bounded revisit loop
    workflow.add_conditional_edges(
        "deck_visual_review_node",
        deck_visual_review_route,
        {
            "deck_revisit_node": "deck_revisit_node",
            "final_generation_validation_node": "final_generation_validation_node",
        },
    )
    workflow.add_edge("deck_revisit_node", "compile_presentation_ir_node")

    # 5c. Unified hard correctness gate on the exact IR that will be persisted.
    workflow.add_conditional_edges(
        "final_generation_validation_node",
        final_validation_route,
        {
            "persist_session_node": "persist_session_node",
            "__end__": END,
        },
    )

    # 6. Finalization
    workflow.add_edge("persist_session_node", END)

    return workflow.compile()


generation_graph = build_generation_graph()
