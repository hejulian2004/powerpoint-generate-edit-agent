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

from ...compiler.presentation_ir import compile_layout_to_presentation_ir
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
    pres_ir = compile_layout_to_presentation_ir(deck_layout)

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
    if pres_ir:
        for slide in pres_ir.slides:
            # Pre-render SVG to ensure fidelity and catch exceptions
            SVGRenderer.render_slide(slide)

    return {"status": "preview_rendered"}


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


def visual_repair_route(state: PPTGenerationState) -> Literal["visual_repair_node", "persist_session_node"]:
    """Route based on visual issues and max iteration bound."""
    issues = state.get("visual_issues", [])
    iteration = state.get("repair_iteration", 0)
    max_iterations = state.get("max_repair_iterations", 3)

    has_fixable_issues = any(i.severity in (IssueSeverity.ERROR, IssueSeverity.WARNING) for i in issues)

    if has_fixable_issues and iteration < max_iterations:
        return "visual_repair_node"

    return "persist_session_node"


def entry_route(state: PPTGenerationState) -> Literal["paper_plan_node", "ingest_node"]:
    """Choose the paper branch or the canonical PPTSpec branch."""
    return "paper_plan_node" if state.get("source_type") == "paper" else "ingest_node"


def paper_plan_route(state: PPTGenerationState) -> Literal["paper_design_node", "__end__"]:
    """Terminate early when the paper branch has no PaperIR."""
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
    workflow.add_node("paper_design_node", paper_design_node)
    workflow.add_node("layout_node", layout_node)
    workflow.add_node("compile_presentation_ir_node", compile_presentation_ir_node)
    workflow.add_node("preview_node", preview_node)
    workflow.add_node("visual_review_node", visual_review_node)
    workflow.add_node("visual_repair_node", visual_repair_node)
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
            "persist_session_node": "persist_session_node",
        },
    )
    # Loop back from visual repair to re-compile PresentationIR and re-review
    workflow.add_edge("visual_repair_node", "compile_presentation_ir_node")

    # 6. Finalization
    workflow.add_edge("persist_session_node", END)

    return workflow.compile()


generation_graph = build_generation_graph()
