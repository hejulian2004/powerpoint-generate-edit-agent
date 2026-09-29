"""LangGraph StateGraph Workflow for PPT-Agent-Studio.

Orchestrates multi-phase Agent loop:
Router -> Planner -> Executor (Tool Calling) -> Tools Execution -> Vision Review -> Designer Summary.
"""

from __future__ import annotations
import hashlib
import json
import logging
import re
import uuid
from typing import Dict, Any, List, Optional, Callable, TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from .memory import AgentMemory
from .vision import VisionEngine
from .llm import LLMClient
from .intent import classify_intent_with_llm
from .iteration import AgentIteration
from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..config import settings

logger = logging.getLogger(__name__)


async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]):
    if not on_event:
        return
    import inspect
    try:
        if inspect.iscoroutinefunction(on_event):
            await on_event(data)
        else:
            res = on_event(data)
            if inspect.isawaitable(res):
                await res
    except Exception as e:
        logger.debug(f"Event emission ignored: {e}")


# =====================================================================
# 1. State Definition
# =====================================================================

class PPTAgentState(TypedDict, total=False):
    messages: List[Dict[str, Any]]
    raw_messages: List[Dict[str, Any]]
    user_query: str
    intent: str  # "generate_presentation" | "generate_slide" | "modify_elements" | "optimize_layout" | "apply_theme" | "undo" | "chat"
    plan: Optional[str]
    # Tool calls drafted before a plan-mode confirmation. The resumed turn
    # executes this list instead of planning again.
    proposed_tool_calls: Optional[List[Dict[str, Any]]]
    frozen_tool_calls: Optional[List[Dict[str, Any]]]
    plan_review: Optional[Dict[str, Any]]
    plan_iteration: int
    content_review: Optional[Dict[str, Any]]
    content_iteration: int
    # Per-slide content-rework rounds already issued this turn. Each failed
    # slide may be sent back at most twice; routing uses this map, not a
    # single global counter.
    content_rework_counts: Dict[str, int]
    rework_directive: Optional[Dict[str, Any]]
    tool_calls: List[Dict[str, Any]]
    execution_plan: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    vision_critique: Optional[str]
    visual_review: Optional[Dict[str, Any]]
    correction_count: int
    content_refine_count: int
    iteration: int
    max_iterations: int
    final_summary: str
    active_slide_id: Optional[str]
    presentation_version: int
    last_target_id: Optional[str]
    confirmed_tool_ids: List[str]
    subagent_memories: Dict[str, Any]
    changed_slide_ids: List[str]
    grounding: Optional[Dict[str, Any]]
    grounding_clarification: Optional[str]
    plan_document_epoch: Optional[str]
    plan_base_revision: Optional[int]
    stale_plan: bool
    stale_replan_count: int
    # Frozen at request admission. A different live epoch during the accepted
    # turn is a terminal abort (never a replan). This turn's OWN successful
    # whole-document replacement advances `turn_document_epoch`.
    turn_document_epoch: Optional[str]
    turn_base_revision: Optional[int]
    turn_invalidated: bool
    # Session Agent-turn lease id, threaded end-to-end so the MutationGateway can
    # verify this turn owns the document freeze (S7/S8).
    agent_turn_id: Optional[str]
    # Interaction mode ("auto" | "plan"). In "plan" mode an approved plan pauses
    # for explicit user confirmation before the executor runs. `plan_preapproved`
    # marks the resumed turn that must skip planner/plan-critic and execute the
    # frozen plan directly.
    interaction_mode: str
    plan_preapproved: bool
    plan_ready: bool
    # Request-scoped client UI context (active slide / selection). Carried in the
    # graph state so a paused plan can freeze it for later confirmation.
    ui_context: Optional[Dict[str, Any]]
    ui_context_revision: int


# =====================================================================
# 2. Change Tracking & Deck-Level Review Helpers
# =====================================================================

def _slide_signature(slide: SlideIR) -> str:
    """Stable fingerprint of a slide's content for changed-slide detection."""
    try:
        payload = slide.model_dump_json()
    except Exception:
        payload = repr(slide)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _slide_signatures(pres: Optional[PresentationIR]) -> Dict[str, str]:
    if not pres:
        return {}
    return {slide.id: _slide_signature(slide) for slide in pres.slides}


def _collect_changed_slide_ids(
    pres: Optional[PresentationIR], before: Dict[str, str]
) -> List[str]:
    """Slide ids whose content changed since the `before` snapshot (deck order)."""
    if not pres:
        return []
    changed = []
    for slide in pres.slides:
        if before.get(slide.id) != _slide_signature(slide):
            changed.append(slide.id)
    return changed


def _resolve_review_slides(
    pres: Optional[PresentationIR], changed_slide_ids: Optional[List[str]]
) -> List[SlideIR]:
    """Review targets: every changed non-empty slide, else the legacy fallback."""
    targets: List[SlideIR] = []
    if pres:
        for slide_id in changed_slide_ids or []:
            slide = pres.get_slide(slide_id)
            if slide is not None and slide.elements:
                targets.append(slide)
    if targets:
        return targets
    if not pres:
        return []
    active = pres.get_active_slide()
    if active and active.elements:
        return [active]
    for slide in pres.slides:
        if slide.elements:
            return [slide]
    return []


def _aggregate_deck_reviews(
    deck_reviews: Dict[str, Dict[str, Any]],
    approved_key: str = "approved",
) -> Optional[Dict[str, Any]]:
    """Merges per-slide critic results into a deck-level review.

    Top-level fields come from the first failing review (or the first review) so
    existing consumers keep working, with per-slide detail under `slides`.
    """
    if not deck_reviews:
        return None
    failed_ids = [
        slide_id for slide_id, review in deck_reviews.items()
        if not review.get(approved_key, True)
    ]
    primary = (
        deck_reviews[failed_ids[0]] if failed_ids else next(iter(deck_reviews.values()))
    )
    return {
        **primary,
        approved_key: not failed_ids,
        "slides": deck_reviews,
        "reviewed_slide_ids": list(deck_reviews.keys()),
        "failed_slide_ids": failed_ids,
    }


# =====================================================================
# 2. Node Functions & Intent Classification
# =====================================================================

async def router_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Analyzes user message and current presentation state to classify intent."""
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")
    llm_client: Optional[Any] = configurable.get("llm_client")

    user_query = state.get("user_query", "").strip()
    if not user_query:
        return {
            "intent": "chat",
            "iteration": state.get("iteration", 0) + 1,
            "grounding": None,
            "grounding_clarification": None,
        }

    if on_event:
        await _safe_emit(on_event, {"type": "agent_thinking", "status": "routing", "text": "分析用户需求意图与画布状态..."})

    # The model is the only intent classifier. No keyword table fills in a guess.
    intent = await classify_intent_with_llm(llm_client, user_query, pres) if llm_client else None
    if not intent:
        return {
            "intent": "chat",
            "iteration": state.get("iteration", 0) + 1,
            "grounding": None,
            "grounding_clarification": (
                "模型没有给出可执行的意图，这次不会改动画布。"
                "请说明要生成文稿、修改当前页，还是调整版式。"
            ),
        }

    # Grounding gate: factual deck requests without source material must ask first.
    grounding: Optional[Dict[str, Any]] = None
    grounding_clarification: Optional[str] = None
    if intent == "generate_presentation":
        from .grounding import assess_generation_request

        # Prefer the raw transcript so grounding provenance is not corrupted by
        # model-facing context compression.
        assessment = assess_generation_request(
            user_query, state.get("raw_messages") or state.get("messages")
        )
        grounding = assessment.to_dict()
        if assessment.requires_source:
            grounding_clarification = assessment.question

    return {
        "intent": intent,
        "iteration": state.get("iteration", 0) + 1,
        "grounding": grounding,
        "grounding_clarification": grounding_clarification,
    }


async def planner_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Generates structural layout and coordinate-safe design plan.
    
    If returned here after PlanCriticSubagent rejection, incorporates feedback to refine plan.
    """
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")
    intent = state.get("intent", "chat")
    user_query = state.get("user_query", "")
    prev_plan_review = state.get("plan_review")

    if on_event:
        status_text = "根据评审建议重构优化方案大纲..." if prev_plan_review and not prev_plan_review.get("approved", True) else f"规划设计策略 ({intent})，计算 1280x720 坐标体系..."
        await _safe_emit(on_event, {"type": "agent_thinking", "status": "planning", "text": status_text})

    plan_desc = ""
    if intent == "undo":
        plan_desc = "回退上一轮图元编辑与排版指令，恢复先前稳定版本快照。"
    elif intent == "generate_presentation":
        plan_desc = f"规划生成多页精美演示文稿: 包含封面、核心架构、实施流程时间线、关键性能指标与总结展望。"
    elif intent == "generate_slide":
        if any(k in user_query for k in ["新增一页", "添加一页", "新页面", "新建页面", "新增幻灯片", "新建幻灯片", "加一页", "空白", "创建一页"]):
            plan_desc = "创建一页空白幻灯片，设置背景色并切换至新页面。"
        else:
            plan_desc = f"规划生成当前页面布局架构: 统一字号层级、计算间距与容器圆角，避免元素交叠。"
    elif intent == "optimize_layout":
        plan_desc = "计算画布几何重心，分析排版缺陷与重叠，重新规整图元对齐、呼吸留白与视觉美化。"
    elif intent == "apply_theme":
        plan_desc = "匹配全局色彩系统与图元描边规范，提升视觉对比度与统一性。"
    elif intent == "modify_elements":
        plan_desc = "定位目标图元，执行精确属性微调与样式重写。"

    # If previous audit had recommendations, incorporate into refined plan
    if prev_plan_review and prev_plan_review.get("recommendations"):
        plan_desc += f" [已吸纳规划评审优化要求: {prev_plan_review['recommendations']}]"

    proposed_tool_calls = None
    if state.get("interaction_mode") == "plan":
        from .subagents.executor import ExecutorSubagent
        memory: Optional[AgentMemory] = configurable.get("memory")
        llm_client: Optional[LLMClient] = configurable.get("llm_client")
        session = configurable.get("session")
        last_target_id = getattr(session, "last_target_id", None) if session else None
        try:
            drafted = await ExecutorSubagent.plan_task(
                intent=intent,
                user_query=user_query,
                plan_desc=plan_desc,
                pres=pres,
                memory=memory,
                llm_client=llm_client,
                last_target_id=last_target_id,
                session=session,
                on_event=on_event,
                conversation_context=state.get("messages"),
                rework_directive=state.get("rework_directive"),
                grounding=state.get("grounding"),
                ui_context=configurable.get("ui_context"),
            )
            proposed_tool_calls = list(drafted.tool_calls or [])
        except Exception as exc:
            logger.warning(f"Plan draft failed, keeping an empty frozen list: {exc}")
            proposed_tool_calls = []
        plan_desc = _format_frozen_plan(plan_desc, proposed_tool_calls)

    return {
        "plan": plan_desc,
        "proposed_tool_calls": proposed_tool_calls,
    }


async def plan_critic_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Decoupled, read-only Plan Critic Subagent auditing the proposed plan with persistent memory."""
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")
    intent = state.get("intent", "chat")
    plan_desc = state.get("plan", "")
    plan_iteration = state.get("plan_iteration", 0) + 1

    subagent_mems = dict(state.get("subagent_memories") or {})
    from .subagents.memory import SubagentSessionMemory
    plan_mem = SubagentSessionMemory.from_dict(subagent_mems.get("PlanCriticSubagent", {})) if "PlanCriticSubagent" in subagent_mems else SubagentSessionMemory("PlanCriticSubagent")

    slide_count = _planned_slide_count(state, configurable.get("pres"))

    plan_review_dict = None
    if intent in ["generate_presentation", "generate_slide", "optimize_layout"]:
        from .subagents.plan_critic import PlanCriticSubagent
        plan_review = await PlanCriticSubagent.audit_plan(
            plan_desc=plan_desc,
            target_intent=intent,
            slide_count=slide_count,
            llm_client=llm_client,
            session_memory=plan_mem,
            on_event=on_event
        )
        plan_review_dict = plan_review.to_dict()

    subagent_mems["PlanCriticSubagent"] = plan_mem.to_dict()

    return {
        "plan_review": plan_review_dict,
        "plan_iteration": plan_iteration,
        "subagent_memories": subagent_mems
    }


async def await_plan_confirmation_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Freezes an approved plan and pauses the turn for explicit user confirmation.

    Registered on the session (ephemeral, like low-confidence confirmations) and
    bound to the document identity it was drafted against. The user confirms via
    `confirm_plan`, which resumes execution with the frozen plan.
    """
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    session = configurable.get("session")
    plan = state.get("plan", "") or ""
    plan_review = state.get("plan_review")
    intent = state.get("intent", "chat")
    plan_id = f"plan_{uuid.uuid4().hex[:10]}"
    frozen_calls = state.get("proposed_tool_calls")
    if frozen_calls is None and state.get("interaction_mode") == "plan":
        frozen_calls = []

    record = None
    if session is not None and hasattr(session, "register_pending_plan"):
        record = session.register_pending_plan(
            plan_id=plan_id,
            plan=plan,
            plan_review=plan_review,
            user_query=state.get("user_query", ""),
            document_epoch=state.get("turn_document_epoch") or getattr(session, "document_epoch", None),
            expected_revision=session.document.presentation.version,
            active_slide_id=state.get("active_slide_id"),
            ui_context=state.get("ui_context"),
            ui_context_revision=state.get("ui_context_revision"),
            tool_calls=frozen_calls,
        )

    if on_event:
        await _safe_emit(on_event, {
            "type": "plan_ready",
            "plan_id": plan_id,
            "plan": plan,
            "tool_calls": list(frozen_calls or []),
            "plan_review": plan_review,
            "intent": intent,
            "document_epoch": record.get("document_epoch") if record else None,
            "expected_revision": record.get("expected_revision") if record else None,
            "session_id": getattr(session, "session_id", None),
        })

    return {
        "plan_ready": True,
        "final_summary": "计划已生成，请确认后继续执行。",
    }


async def executor_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Delegates planning to the independent ExecutorSubagent.

    The subagent is a pure planner: it returns an ExecutionPlan of tool calls and
    has no authority to mutate the presentation. `mutation_node` commits the plan
    through the MutationGateway, which is the only write path.
    """
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")
    memory: Optional[AgentMemory] = configurable.get("memory")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")

    user_query = state.get("user_query", "")
    intent = state.get("intent", "chat")
    plan_desc = state.get("plan", "")
    session = configurable.get("session")
    last_target_id = getattr(session, "last_target_id", None) if session else None
    if not last_target_id:
        last_target_id = state.get("last_target_id")

    frozen_calls = state.get("frozen_tool_calls")
    if state.get("plan_preapproved") and frozen_calls is not None and not state.get("stale_plan"):
        return {
            "execution_plan": list(frozen_calls),
            "last_target_id": last_target_id,
            "active_slide_id": pres.active_slide_id if pres else state.get("active_slide_id"),
            "plan_document_epoch": getattr(session, "document_epoch", None) if session else state.get("turn_document_epoch"),
            "plan_base_revision": pres.version if pres is not None else None,
            "stale_plan": False,
        }

    from .subagents.executor import ExecutorSubagent
    plan = await ExecutorSubagent.plan_task(
        intent=intent,
        user_query=user_query,
        plan_desc=plan_desc,
        pres=pres,
        memory=memory,
        llm_client=llm_client,
        last_target_id=last_target_id,
        session=session,
        on_event=on_event,
        conversation_context=state.get("messages"),
        rework_directive=state.get("rework_directive"),
        grounding=state.get("grounding"),
        ui_context=configurable.get("ui_context"),
    )

    # Sync active slide id
    active_slide_id = state.get("active_slide_id")
    if pres and pres.slides:
        if not pres.active_slide_id:
            pres.active_slide_id = pres.slides[0].id
        active_slide_id = pres.active_slide_id

    # Fail closed: a plan without a frozen stamp cannot be CAS-validated against a
    # session document. Never fall back to reading the live values, or a plan
    # derived from an older revision would be mislabeled as current.
    plan_epoch = plan.document_epoch
    plan_revision = plan.base_revision
    if session is not None and pres is not None and (
        plan_epoch is None or plan_revision is None
    ):
        replan_count = state.get("stale_replan_count", 0) + 1
        await _safe_emit(on_event, {
            "type": "plan_stale_replanning",
            "reason": "missing_plan_stamp",
            "expected_revision": plan_revision,
            "current_revision": pres.version,
            "attempt": replan_count,
        })
        return {
            "tool_results": [],
            "execution_plan": [],
            "stale_plan": True,
            "stale_replan_count": replan_count,
            "presentation_version": pres.version,
            "changed_slide_ids": [],
        }

    return {
        "execution_plan": plan.tool_calls,
        "last_target_id": last_target_id,
        "active_slide_id": active_slide_id,
        "plan_document_epoch": plan_epoch,
        "plan_base_revision": plan_revision,
        "stale_plan": False,
    }


def _call_id() -> str:
    return f"call_{uuid.uuid4().hex[:6]}"


def _tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": name, "arguments": arguments, "id": _call_id()}


def _clarify(question: str) -> List[Dict[str, Any]]:
    return [_tool_call("request_clarification", {"question": question})]


_OFFLINE_CONTENT_QUESTION = (
    "当前没有可用的模型，不能编排幻灯片正文。"
    "请配置模型后再生成，或直接给出每一页的标题和要点。"
)
_BLANK_PAGE_MARKERS = (
    "新增一页", "添加一页", "新页面", "新建页面", "新增幻灯片",
    "新建幻灯片", "加一页", "空白", "创建一页",
)
_LAYOUT_CONTENT_MARKERS = (
    "时间线", "里程碑", "timeline", "指标", "kpi", "数据",
    "对比", "两栏", "卡片", "特性",
)


def _format_frozen_plan(intro: str, calls: List[Dict[str, Any]]) -> str:
    """Human-readable plan that names the tool calls about to be frozen."""
    lines = [intro.strip(), "将执行的工具："]
    if not calls:
        lines.append("- 无（确认后不会改动画布）")
        return "\n".join(lines)
    for call in calls:
        args = call.get("arguments") or {}
        target = args.get("slide_id") or args.get("title") or "当前页"
        lines.append(f"- {call.get('name')}（目标: {target}）")
    return "\n".join(lines)


def _planned_slide_count(state: "PPTAgentState", pres: Optional[PresentationIR]) -> int:
    """Slide count implied by the frozen tool list, never a hardcoded 5."""
    for call in state.get("proposed_tool_calls") or []:
        name = call.get("name")
        args = call.get("arguments") or {}
        if name == "generate_presentation":
            slides = args.get("slides") or []
            return len(slides) if isinstance(slides, list) and slides else 1
        if name == "create_slide":
            return (len(pres.slides) if pres and pres.slides else 0) + 1
    if pres and pres.slides:
        return len(pres.slides)
    return 1


def _heuristic_tool_planner(
    intent: str,
    user_query: str,
    pres: Optional[PresentationIR],
    last_target_id: Optional[str] = None,
    selected_element_ids: Optional[List[str]] = None,
    primary_selected_element_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Offline planner: undo, blank create_slide, apply_theme, or a clarification.

    Selected-element edits stay, because the target id is already known.
    Keyword geometry and canned decks do not.
    """
    del last_target_id  # relative keyword nudges are no longer invented offline
    tool_calls: List[Dict[str, Any]] = []
    active_slide = pres.get_active_slide() if pres else None
    query_lower = user_query.lower()

    if intent == "undo":
        return [_tool_call("undo", {})]

    if intent == "apply_theme":
        theme_name = "monochrome_studio"
        if "蓝" in user_query:
            theme_name = "tech_blue"
        elif "绿" in user_query or "翡翠" in user_query:
            theme_name = "emerald_nature"
        elif "金" in user_query or "暖" in user_query:
            theme_name = "warm_corporate"
        elif "黑" in user_query or "极简" in user_query:
            theme_name = "monochrome_studio"
        return [_tool_call("apply_theme", {"theme_preset": theme_name})]

    if intent == "optimize_layout":
        slide_id = active_slide.id if active_slide else None
        args: Dict[str, Any] = {}
        if slide_id:
            args["slide_id"] = slide_id
        return [
            _tool_call("evaluate_layout", dict(args)),
            _tool_call("auto_fix_layout", {**args, "only_critical": False}),
        ]

    if intent == "generate_presentation":
        return _clarify(_OFFLINE_CONTENT_QUESTION)

    if intent == "generate_slide":
        wants_layout = any(marker in user_query or marker in query_lower for marker in _LAYOUT_CONTENT_MARKERS)
        wants_blank = any(marker in user_query for marker in _BLANK_PAGE_MARKERS)
        if wants_blank and not wants_layout:
            bg = "#FFFFFF"
            if active_slide and getattr(active_slide.background, "color", None):
                bg = active_slide.background.color
            if "白" in user_query and "黑" not in user_query:
                bg = "#FFFFFF"
            elif "黑" in user_query and "白" not in user_query:
                bg = "#0A0A0A"
            return [_tool_call("create_slide", {"title": "新建幻灯片", "background_color": bg})]
        return _clarify(_OFFLINE_CONTENT_QUESTION)

    if intent == "modify_elements":
        from .uicontext import DEFERENCE_TOKENS
        if any(tok in user_query for tok in DEFERENCE_TOKENS):
            targets = [t for t in (selected_element_ids or []) if t]
            target = primary_selected_element_id or (targets[0] if targets else None)
            if not target:
                return []
            updates: Dict[str, Any] = {"element_id": target}
            if "红" in user_query:
                updates["fill_color"] = "#EF4444"
            elif "蓝" in user_query:
                updates["fill_color"] = "#3B82F6"
            elif "绿" in user_query:
                updates["fill_color"] = "#10B981"
            elif "黄" in user_query:
                updates["fill_color"] = "#F59E0B"
            elements = active_slide.elements if active_slide else []
            target_el = next((element for element in elements if element.id == target), None)
            if target_el is not None:
                if any(k in user_query for k in ["放大", "变大", "大一点", "再大", "增大"]):
                    updates["width"] = float(target_el.width) * 1.2
                    updates["height"] = float(target_el.height) * 1.2
                elif any(k in user_query for k in ["缩小", "变小", "小一点", "再小"]):
                    updates["width"] = float(target_el.width) * 0.8
                    updates["height"] = float(target_el.height) * 0.8
            return [_tool_call("update_element", updates)]
        return _clarify(
            "我还不能确定您想修改哪个元素或改成什么效果。"
            "请先选中目标元素（或在指令中说明元素名称与目标属性），我再精确执行。"
        )

    return tool_calls


async def mutation_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Commits the Executor's execution plan through the MutationGateway.

    This node is the ONLY path in the agent graph allowed to write to the
    PresentationIR. It applies risk enrichment, the confirmation gate, schema
    validation, and transaction rollback for every planned tool call.
    """
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    history: Optional[HistoryManager] = configurable.get("history")
    session: Optional[Any] = configurable.get("session")
    on_event: Optional[Callable] = configurable.get("on_event")
    memory: Optional[AgentMemory] = configurable.get("memory")

    tool_calls = list(state.get("execution_plan") or state.get("tool_calls") or [])
    confirmed_ids = set(state.get("confirmed_tool_ids") or [])
    confirmed_ids.update(configurable.get("confirmed_tool_ids") or [])

    from .mutation_gateway import MutationGateway, GENERATION_TOOLS
    from .subagents.executor import ExecutorSubagent
    from .grounding import collect_generation_text, blocking_verdicts

    if pres is None:
        return {
            "tool_results": [],
            "execution_plan": [],
            "presentation_version": 1,
            "stale_plan": False,
        }

    plan_epoch = state.get("plan_document_epoch")
    plan_revision = state.get("plan_base_revision")
    turn_epoch = state.get("turn_document_epoch")
    live_epoch = getattr(session, "document_epoch", None) if session else None

    # Invariant: an ACCEPTED turn is bound to its admission epoch. If the
    # document identity changed under us (another client replaced the deck),
    # this turn is terminally invalidated - it must NEVER replan against the
    # new deck, because the user's request was made against the old one. Only
    # this turn's own successful replacement advances `turn_document_epoch`.
    external_epoch_change = session is not None and (
        (plan_epoch is not None and live_epoch != plan_epoch)
        or (turn_epoch is not None and live_epoch != turn_epoch)
    )
    if tool_calls and external_epoch_change:
        await _safe_emit(on_event, {
            "type": "turn_invalidated",
            "reason": "document_epoch_mismatch",
            "turn_document_epoch": turn_epoch,
            "current_document_epoch": live_epoch,
            "text": "演示文稿已被其他操作替换，本次指令已安全终止，请重新发起。",
        })
        return {
            "tool_results": [],
            "execution_plan": [],
            "stale_plan": False,
            "turn_invalidated": True,
            "presentation_version": pres.version,
            "changed_slide_ids": [],
        }

    # Same-epoch revision drift is a bounded replan: the deck advanced but the
    # identity did not, so replanning from the current state is safe.
    revision_changed = plan_revision is not None and pres.version != plan_revision
    if tool_calls and revision_changed:
        replan_count = state.get("stale_replan_count", 0) + 1
        await _safe_emit(on_event, {
            "type": "plan_stale_replanning",
            "reason": "stale_mutation",
            "expected_revision": plan_revision,
            "current_revision": pres.version,
            "attempt": replan_count,
        })
        return {
            "tool_results": [],
            "execution_plan": [],
            "stale_plan": True,
            "stale_replan_count": replan_count,
            "presentation_version": pres.version,
            "changed_slide_ids": [],
        }

    # Grounded generation: block planned content whose numbers are absent from
    # the user-provided source instead of fabricating facts.
    grounding = state.get("grounding") or {}
    source_text = grounding.get("source_text", "")
    enforce_grounding = bool(grounding.get("enforce_numeric_grounding"))
    placeholder_ok = bool(grounding.get("is_placeholder_request"))

    # Tool-execution-boundary grounding: enforce for ANY generation tool,
    # independent of the router intent. The router only assesses
    # `generate_presentation`, but the Executor can emit generation tools from
    # other intents (e.g. `generate_slide_layout`), so we derive the assessment
    # here as a fail-closed backstop whenever the request is factual.
    calls_generate = any(
        str(call.get("name") or call.get("tool") or "") in GENERATION_TOOLS
        for call in tool_calls
    )
    if calls_generate and not enforce_grounding:
        from .grounding import assess_generation_request

        assessment = assess_generation_request(
            state.get("user_query", ""),
            state.get("raw_messages") or state.get("messages"),
        )
        if assessment.enforce_numeric_grounding:
            source_text = assessment.source_text
            enforce_grounding = True
            placeholder_ok = assessment.is_placeholder_request

    blocked_results: List[Dict[str, Any]] = []
    unsupported_seen: List[str] = []
    if enforce_grounding:
        executable_calls = []
        for call in tool_calls:
            fn_name = str(call.get("name") or call.get("tool") or "")
            if fn_name in ("generate_presentation", "generate_slide_layout", "batch_add_cards"):
                call_text = collect_generation_text(dict(call.get("arguments") or {}))
                verdicts = blocking_verdicts(
                    call_text, source_text, placeholder_ok=placeholder_ok
                )
                if verdicts:
                    for verdict in verdicts:
                        if verdict.claim not in unsupported_seen:
                            unsupported_seen.append(verdict.claim)
                    blocked_results.append({
                        "tool": fn_name,
                        "arguments": call.get("arguments"),
                        "result": {
                            "success": False,
                            "error": "unsupported_facts",
                            "unsupported_numbers": [
                                v.claim for v in verdicts if v.category == "numeric"
                            ],
                            "grounding_verdicts": [v.to_dict() for v in verdicts],
                            "message": "生成内容包含资料中无依据的事实主张，已阻止写入以避免编造。",
                        },
                    })
                    continue
            executable_calls.append(call)
        tool_calls = executable_calls

    before_signatures = _slide_signatures(pres)

    # A plan may ask the user to disambiguate instead of writing (e.g. an
    # ambiguous modify). Surface the question and execute nothing.
    if tool_calls:
        executable = []
        clarification: Optional[str] = None
        for call in tool_calls:
            if str(call.get("name") or call.get("tool") or "") == "request_clarification":
                question = (call.get("arguments") or {}).get("question")
                if question:
                    clarification = question
            else:
                executable.append(call)
        if clarification and not executable:
            return {
                "tool_results": [],
                "execution_plan": [],
                "presentation_version": pres.version,
                "active_slide_id": state.get("active_slide_id"),
                "changed_slide_ids": [],
                "stale_plan": False,
                "grounding_clarification": clarification,
            }
        tool_calls = executable

    # The whole agent plan is ONE atomic envelope: any failed/blocked/ungrounded
    # call restores content, version, and history, and the plan is one undo step.
    batch = await MutationGateway.execute_tool_calls(
        tool_calls,
        pres,
        history,
        session=session,
        on_event=on_event,
        memory=memory,
        confirmed_ids=confirmed_ids,
        source="agent",
        subagent="ExecutorSubagent",
        atomic=True,
        document_epoch=plan_epoch if session is not None else None,
        expected_revision=plan_revision,
        grounding_source=source_text if enforce_grounding else None,
        enforce_grounding=enforce_grounding,
        agent_turn_id=state.get("agent_turn_id"),
    )
    changed_slide_ids = _collect_changed_slide_ids(pres, before_signatures)

    for token in batch.unsupported_numbers:
        if token not in unsupported_seen:
            unsupported_seen.append(token)

    await ExecutorSubagent.emit_completed(
        batch.executed_tools, on_event, error=batch.error
    )

    active_slide_id = state.get("active_slide_id")
    if pres and pres.slides:
        if not pres.active_slide_id:
            pres.active_slide_id = pres.slides[0].id
        active_slide_id = pres.active_slide_id

    result: Dict[str, Any] = {
        "tool_results": list(batch.results) + blocked_results,
        "execution_plan": [],
        "presentation_version": batch.version,
        "last_target_id": batch.last_target_id,
        "active_slide_id": active_slide_id,
        "changed_slide_ids": changed_slide_ids,
        "stale_plan": False,
        "turn_invalidated": False,
    }
    # This turn's own successful whole-document replacement legitimately moves
    # the turn onto the new document identity so its critics/rework continue.
    if batch.replaced_document:
        result["turn_document_epoch"] = batch.document_epoch
        result["turn_base_revision"] = batch.version
    if unsupported_seen:
        result["grounding_clarification"] = (
            "生成已暂停：以下数字在您提供的资料中没有依据：" + "、".join(unsupported_seen) +
            "。请补充来源，或明确说明可使用示例/占位数据。"
        )
    return result


_CITED_ELEMENT_RE = re.compile(r"元素\s*'([^']+)'")
_MAX_CONTENT_REWORK_ROUNDS = 2


def _cited_content_target_ids(review: Dict[str, Any], slide: Optional[SlideIR]) -> List[str]:
    """Element ids the content critic actually named.

    Rule issues embed ``元素 'id'``. When an LLM rejection names no id, fall
    back to text elements on that slide so a vague "需修正" still has a target
    without dragging every shape into the rework.
    """
    elements = list(slide.elements) if slide else []
    known = {el.id for el in elements}
    blobs: List[str] = [str(review.get("summary") or "")]
    blobs.extend(str(item) for item in (review.get("redundancy_issues") or []))
    blobs.extend(str(item) for item in (review.get("recommendations") or []))
    cited: List[str] = []
    for blob in blobs:
        for match in _CITED_ELEMENT_RE.finditer(blob):
            element_id = match.group(1)
            if element_id in known and element_id not in cited:
                cited.append(element_id)
    if cited:
        return cited
    return [el.id for el in elements if getattr(el, "type", "") == "text"]


def _select_content_rework_slide(
    failed_ids: List[str],
    counts: Dict[str, int],
) -> Optional[str]:
    """First failed slide that has not been handled, else one still under the cap."""
    for slide_id in failed_ids:
        if int(counts.get(slide_id, 0)) == 0:
            return slide_id
    for slide_id in failed_ids:
        if int(counts.get(slide_id, 0)) < _MAX_CONTENT_REWORK_ROUNDS:
            return slide_id
    return None


async def content_critic_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Runs decoupled, read-only content & narrative structural critique via ContentCriticSubagent with dedicated history."""
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")
    on_event: Optional[Callable] = configurable.get("on_event")
    content_iteration = state.get("content_iteration", 0) + 1
    rework_counts = {
        str(slide_id): int(count)
        for slide_id, count in (state.get("content_rework_counts") or {}).items()
    }

    subagent_mems = dict(state.get("subagent_memories") or {})
    from .subagents.memory import SubagentSessionMemory
    content_mem = SubagentSessionMemory.from_dict(subagent_mems.get("ContentCriticSubagent", {})) if "ContentCriticSubagent" in subagent_mems else SubagentSessionMemory("ContentCriticSubagent")

    review_ids = list(state.get("changed_slide_ids") or [])
    if not review_ids and state.get("rework_directive"):
        # No mutation happened on the rework pass: re-audit the previously failed slides.
        review_ids = list(state["rework_directive"].get("failed_slide_ids") or [])
    review_targets = _resolve_review_slides(pres, review_ids)

    deck_reviews: Dict[str, Dict[str, Any]] = {}
    if review_targets:
        from .subagents.content_critic import ContentCriticSubagent
        for slide in review_targets:
            c_res = await ContentCriticSubagent.audit_content(
                slide=slide,
                llm_client=llm_client,
                session_memory=content_mem,
                on_event=on_event
            )
            deck_reviews[slide.id] = c_res.to_dict()

    content_dict = _aggregate_deck_reviews(deck_reviews, approved_key="approved")
    rework_directive = None
    if content_dict and not content_dict.get("approved", True):
        failed_ids = list(content_dict.get("failed_slide_ids") or [])
        failing_slide_id = _select_content_rework_slide(failed_ids, rework_counts)
        if failing_slide_id:
            failing_review = deck_reviews[failing_slide_id]
            failing_slide = pres.get_slide(failing_slide_id) if pres else None
            issued = rework_counts.get(failing_slide_id, 0) + 1
            rework_counts[failing_slide_id] = issued
            rework_directive = {
                "source": "content_critic",
                "slide_id": failing_slide_id,
                "target_ids": _cited_content_target_ids(failing_review, failing_slide),
                "defects": list(failing_review.get("redundancy_issues") or []),
                "recommendations": list(failing_review.get("recommendations") or []),
                "summary": failing_review.get("summary", ""),
                "round": issued,
                "failed_slide_ids": failed_ids,
            }

    subagent_mems["ContentCriticSubagent"] = content_mem.to_dict()

    return {
        "content_review": content_dict,
        "content_iteration": content_iteration,
        "content_rework_counts": rework_counts,
        "rework_directive": rework_directive,
        "subagent_memories": subagent_mems
    }


async def vision_critic_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Runs comprehensive visual balance, geometric collision, and layout critique with dedicated history."""
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")
    on_event: Optional[Callable] = configurable.get("on_event")
    session = configurable.get("session")
    # Bind the review to the document revision it observed. auto_correct_node
    # discards a remediation plan whose review is now stale.
    review_document_epoch = getattr(session, "document_epoch", None) if session else None
    review_revision = pres.version if pres is not None else None

    subagent_mems = dict(state.get("subagent_memories") or {})
    from .subagents.memory import SubagentSessionMemory
    vision_mem = SubagentSessionMemory.from_dict(subagent_mems.get("VisualCriticSubagent", {})) if "VisualCriticSubagent" in subagent_mems else SubagentSessionMemory("VisualCriticSubagent")

    critique = None
    review_dict = None
    review_targets = _resolve_review_slides(pres, state.get("changed_slide_ids"))

    deck_reviews: Dict[str, Dict[str, Any]] = {}
    if review_targets and settings.enable_vision_loop:
        # Delegate each changed slide to the decoupled, context-isolated VisualCriticSubagent
        from .subagents.visual_critic import VisualCriticSubagent
        for slide in review_targets:
            review_res = await VisualCriticSubagent.audit_slide(
                slide=slide,
                llm_client=llm_client,
                include_multimodal=bool(llm_client and getattr(llm_client, "api_key", None)),
                session_memory=vision_mem,
                on_event=on_event
            )
            deck_reviews[slide.id] = review_res.to_dict()

    if deck_reviews:
        primary = next(
            (r for r in deck_reviews.values() if r.get("needs_auto_correction") or r.get("has_critical_defects")),
            next(iter(deck_reviews.values()))
        )
        review_dict = {
            **primary,
            "slides": deck_reviews,
            "reviewed_slide_ids": list(deck_reviews.keys()),
            "review_document_epoch": review_document_epoch,
            "review_revision": review_revision,
            "deck_average_score": round(
                sum(float(r.get("score", 0.0)) for r in deck_reviews.values()) / len(deck_reviews), 1
            ),
        }
        critique = primary.get("critique_summary")

    subagent_mems["VisualCriticSubagent"] = vision_mem.to_dict()

    return {
        "vision_critique": critique,
        "visual_review": review_dict,
        "subagent_memories": subagent_mems
    }


async def auto_correct_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Executes transaction-guarded, conflict-resolved remediation operations."""
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    history: Optional[HistoryManager] = configurable.get("history")
    on_event: Optional[Callable] = configurable.get("on_event")

    visual_review = state.get("visual_review", {})
    tool_results = list(state.get("tool_results", []))
    correction_count = state.get("correction_count", 0) + 1

    if on_event:
        await _safe_emit(on_event,{
            "type": "vision_loop",
            "status": "auto_correcting",
            "text": "排版自愈中: 开启事务安全执行关键缺陷修复..."
        })

    from .remediation_runner import RemediationRunner
    from ..eval.remediation import RemediationPlan, FixAction, FixActionType, DefectCategory

    def _plan_from_review(review: Dict[str, Any]) -> RemediationPlan:
        """Reconstruct a RemediationPlan from a reviewed slide dict."""
        plan_dict = review.get("remediation_plan", {})
        actions = []
        for a in plan_dict.get("actions", []):
            try:
                actions.append(FixAction(
                    action_type=FixActionType(a["action_type"]),
                    category=DefectCategory(a["category"]),
                    target_ids=a.get("target_ids", []),
                    parameters=a.get("parameters", {}),
                    reason=a.get("reason", ""),
                    priority=a.get("priority", 1),
                    confidence=a.get("confidence", 1.0),
                    source=a.get("source", "geometry_rule")
                ))
            except Exception:
                pass
        return RemediationPlan(
            actions=actions,
            has_critical=plan_dict.get("has_critical", False),
            summary=plan_dict.get("summary", "")
        )

    # Deck-level reviews carry per-slide plans; remediate every failed slide.
    slide_reviews = visual_review.get("slides") or {}
    targets: List[tuple] = [
        (slide_id, review)
        for slide_id, review in slide_reviews.items()
        if review.get("needs_auto_correction") or review.get("has_critical_defects")
    ]
    if not targets and visual_review.get("remediation_plan"):
        targets = [(visual_review.get("slide_id"), visual_review)]

    session = configurable.get("session")
    lock = getattr(session, "mutation_lock", None) if session else None
    review_epoch = visual_review.get("review_document_epoch")
    review_revision = visual_review.get("review_revision")

    async def _run_remediations() -> List[Dict[str, Any]]:
        runs: List[Dict[str, Any]] = []
        for slide_id, review in targets:
            plan = _plan_from_review(review)
            if not plan.actions:
                continue
            target_slide_id = slide_id or state.get("active_slide_id")
            runner_res = RemediationRunner.apply_plan(
                pres=pres,
                history=history,
                plan=plan,
                slide_id=target_slide_id,
                only_critical=False,
                on_event=on_event,
                session=session,
                agent_turn_id=state.get("agent_turn_id"),
            )
            runs.append({"slide_id": target_slide_id, **runner_res})
        return runs

    def _review_is_stale() -> bool:
        if session is None or pres is None:
            return False
        if review_epoch is not None and getattr(session, "document_epoch", None) != review_epoch:
            return True
        if review_revision is not None and pres.version != review_revision:
            return True
        return False

    async def _run_guarded() -> List[Dict[str, Any]]:
        # Checked while holding the lock: a repair proposed against an older
        # revision must never be applied to a newer document.
        if _review_is_stale():
            await _safe_emit(on_event, {
                "type": "vision_loop",
                "status": "stale_review_discarded",
                "text": "视觉审查对应的版本已被修改，已丢弃过期自愈方案。",
            })
            return []
        return await _run_remediations()

    if pres is None:
        runs = []
    elif lock is not None:
        async with lock:
            runs = await _run_guarded()
    else:
        runs = await _run_guarded()

    for run in runs:
        for rec in run.get("applied_records", []):
            tool_results.append({
                "tool": rec["tool"],
                "args": rec["args"],
                "result": rec["result"],
                "auto_correct": True,
                "reason": rec["reason"]
            })
            if on_event:
                await _safe_emit(on_event,{
                    "type": "tool_completed",
                    "tool": rec["tool"],
                    "result": rec["result"],
                    "presentation_version": pres.version if pres else 1
                })

        if run.get("rolled_back") and on_event:
            await _safe_emit(on_event,{
                "type": "vision_loop",
                "status": "rolled_back",
                "text": run.get("message", "自愈因质量未达标已安全回滚")
            })

    return {
        "tool_results": tool_results,
        "correction_count": correction_count,
        "presentation_version": pres.version if pres else 1
    }


async def summary_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Composes friendly professional architectural design summary for user."""
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")
    session: Optional[Any] = configurable.get("session")

    intent = state.get("intent", "chat")
    tool_results = state.get("tool_results", [])
    vision_critique = state.get("vision_critique")
    visual_review = state.get("visual_review")
    correction_count = state.get("correction_count", 0)
    user_query = state.get("user_query", "")
    grounding_clarification = state.get("grounding_clarification")

    if grounding_clarification:
        final_text = grounding_clarification
    elif state.get("turn_invalidated"):
        final_text = (
            "检测到演示文稿已被其他操作替换，本次指令已安全终止（不会在新文稿上重放）。"
            "请重新发起指令。"
        )
    elif state.get("stale_plan") and not [r for r in tool_results if r.get("executed")]:
        final_text = (
            "检测到演示文稿在规划期间发生了变化，为避免覆盖您的最新编辑，"
            "本次操作已安全取消，请重试。"
        )
    elif intent == "undo":
        final_text = "已为您成功撤销上一步修改，画布已恢复至先前的状态快照。"
    elif intent == "chat" and not tool_results:
        final_text = "你好！我是你的 PPT 协同设计架构师。我支持通过自然语言一键生成多页精美演示文稿、自动排版时间线/指标卡/对比栏、智能调色与图元微调。请告诉我你的设计需求！"
    elif not any(r.get("executed") for r in tool_results) and intent not in ("chat", "undo"):
        final_text = "这次没有可执行的修改，画布保持原样。"
    elif intent == "generate_presentation":
        final_text = (
            f"已生成《{pres.title if pres else '演示文稿'}》，共 {len(pres.slides) if pres else 0} 页。"
            "页面标题和要点来自本次指令，没有套用固定页眉。"
        )
    elif intent == "generate_slide":
        has_created = any(r.get("tool") == "create_slide" for r in tool_results)
        if has_created:
            final_text = f"已创建第 {len(pres.slides) if pres else 1} 页空白幻灯片。"
        else:
            names = [r.get("tool") for r in tool_results if r.get("executed") and r.get("tool")]
            final_text = "已执行 " + "、".join(names) + "。" if names else "这次没有可执行的修改，画布保持原样。"
    elif intent == "optimize_layout":
        executed = [r for r in tool_results if r.get("executed")]
        score = None
        applied = 0
        for record in executed:
            result = record.get("result") if isinstance(record.get("result"), dict) else {}
            if record.get("tool") == "evaluate_layout":
                score = result.get("score", score)
            if record.get("tool") == "auto_fix_layout":
                applied += int(result.get("applied_count") or 0)
        if applied <= 0:
            score_text = f"规则检查得分 {float(score):.1f}。" if isinstance(score, (int, float)) else ""
            final_text = (
                f"{score_text}没有可自动修复的溢出、出界、重叠、对比度、对齐或圆角问题。"
                "留白和配色仍只出现在评审里，版式没有被重新设计。"
            )
        else:
            final_text = (
                f"已自动修复 {applied} 处规则缺陷（溢出、出界、重叠、对比度、对齐或非法圆角）。"
                "版式没有被重新设计。"
            )
    elif intent == "apply_theme":
        final_text = "已应用全局设计主题规范，调和了背景底色、卡片填充与文字高对比度。"
    else:
        executed_names = [r["tool"] for r in tool_results if not r.get("auto_correct")]
        tool_desc = ', '.join(executed_names) if executed_names else '编辑工具'
        final_text = f"已完成针对当前幻灯片的调整。成功调用了 {tool_desc}，图元属性已实时同步更新。"

    blocked_results = [r for r in tool_results if r.get("requires_confirmation")]
    if blocked_results:
        blocked_names = ', '.join(r.get("tool", "?") for r in blocked_results)
        final_text += (
            f"\n\n[安全拦截] 操作 {blocked_names} 的语义解析置信度不足，"
            "已被 RiskPolicy 挂起，等待您确认后执行。"
        )

    failed_results = [
        r for r in tool_results
        if r.get("executed")
        and r.get("tool") not in ("undo", "redo")
        and isinstance(r.get("result"), dict)
        and r["result"].get("success") is False
    ]
    if failed_results:
        failed_names = ', '.join(r.get("tool", "?") for r in failed_results)
        final_text = (
            f"本次操作未完成：工具 {failed_names} 执行失败或未通过校验，"
            "所有改动已整体回滚，演示文稿保持原状。\n\n"
        ) + final_text

    if correction_count > 0 and visual_review:
        score_val = visual_review.get("score", 95.0)
        final_text += f"\n\n[视觉自愈闭环] 检测并自动纠偏了几何重叠与边缘贴靠缺陷，当前页面健康度达 {score_val:.1f}/100。"

    it_dict = None
    if session and visual_review:
        score_after = float(visual_review.get("score", 95.0))
        last_it = session.iterations[-1] if session.iterations else None
        score_before = float(last_it.get("score_after", 80.0) if isinstance(last_it, dict) else getattr(last_it, "score_after", 80.0)) if last_it else 80.0
        changes_summary = [{"tool": r["tool"], "arguments": r.get("arguments", {})} for r in tool_results]
        applied_fixes = [r["tool"] for r in tool_results if r.get("auto_correct")]
        it_record = AgentIteration(
            iteration=len(session.iterations) + 1,
            score_before=score_before,
            score_after=score_after,
            changes=changes_summary,
            critique=vision_critique,
            applied_fixes=applied_fixes
        )
        session.record_iteration(it_record)
        it_dict = it_record.to_dict()
        if on_event:
            await _safe_emit(on_event, {
                "type": "iteration_completed",
                "iteration": it_dict
            })

    if on_event:
        await _safe_emit(on_event, {
            "type": "agent_finished",
            "summary": final_text,
            "tools_executed": tool_results,
            "plan_review": state.get("plan_review"),
            "content_review": state.get("content_review"),
            "vision_critique": vision_critique,
            "visual_review": visual_review,
            "correction_count": correction_count,
            "iteration": it_dict,
            "presentation_version": pres.version if pres else 1
        })

    return {
        "final_summary": final_text
    }


def _build_llm_system_prompt(pres: Optional[PresentationIR], memory: Optional[AgentMemory]) -> str:
    if not pres:
        return "You are PPT-Agent-Studio assistant."

    active_slide = pres.get_active_slide()
    slide_info = [f"Slide #{s.slide_num} ('{s.id}', Title: '{s.title or 'Untitled'}', Elements: {len(s.elements)})" for s in pres.slides]
    elements_detail = []
    if active_slide:
        for el in active_slide.elements:
            desc = f"ID: '{el.id}', Type: {el.type}, Rect: ({el.x}, {el.y}, {el.width}x{el.height})"
            if hasattr(el, "text_content") and el.text_content:
                desc += f", Text: '{el.text_content.plain_text[:35]}'"
            elements_detail.append(f"  - {desc}")

    elements_str = "\n".join(elements_detail) if elements_detail else "  （当前页尚无元素）"
    memory_str = memory.build_system_context() if memory else ""

    return f"""你是一位基于 LangGraph 状态图驱动的顶级 PPT 演示文稿设计与架构专家（PPT-Agent-Studio）。
你可以调用专业工具直接操纵 PPT-IR（演示文稿中间表示）。

【画布基准与核心规则】:
- 画布分辨率严格为 1280 x 720 (16:9)。
- 标题推荐字号 30~44px，正文推荐字号 15~18px，数字指标推荐 24~36px 粗体。
- 左右边距通常建议 >= 80px，卡片间距 20~40px。

【设计语言 — 技术编辑风 / 精密仪表美学】:
- 使用小圆角（radius ≤ 3px）而非大圆角卡片；不要给每张卡叠加阴影。
- 文字是主要视觉：标题大而有力，正文克制；把数字、结论做成"主角"，而不是把所有内容塞进相同卡片。
- 每个版式只突出一个强调色元素（顶缘细条、左缘条、色块数字），其余保持中性安静。
- 用细发丝线（hairline）、编号等结构元素承载信息；只有当内容确实是序列（时间线/步骤）时才用 01/02/03 编号。
- 避免模板感：不要给每个标题都套一个"标签横幅"，不要用大号圆角胶囊徽章。

【文字精简铁律】:
- 每页幻灯片文字必须精简：标题一句话，正文用短语或要点（每条 ≤ 20 字），数字/结论直接上大号字，绝不堆砌整段文字。
- 一张卡片/列内最多 1 个结论 + 1~2 条短语要点；放不下的内容拆到下一页或删减。
- 优先用图标、色块、编号、图表等非文字元素代替大段说明。

【语言：以中文为主】:
- 本工具仅供个人使用，所有标题、正文、卡片文案一律使用中文。
- 专业术语保持中文表达即可（如"异常检测""强化学习""提示工程"）；英文缩写可保留（如 AD、RL、LLM、SOTA），但不要整段英文。
- 单位、代码、专有模型名（如 MVTec-AD、Segoe UI）保留原文。

【UI 质感：渐变与配色】:
- 可用主题强调色的双色渐变（如 accent → accent_soft）做标题/卡片的装饰色带或顶部条，让页面更有层次。
- 保持一页一个主色系，渐变只用于点缀性装饰（色带、数值块、标题下划条），不要整页渐变。

【演示文稿当前状态】:
- 标题: {pres.title}
- 幻灯片总数: {len(pres.slides)}
- 列表: {', '.join(slide_info)}

【当前正编辑的幻灯片 (ID: {active_slide.id if active_slide else 'None'}) 元素清单】:
{elements_str}

{memory_str}

【重要操作准则】:
1. 当用户要求生成完整 PPT 时，调用 generate_presentation 工具，主题可选 editorial_technical / engineering_dark / tech_blue 等。
2. 当用户要求生成时间线、指标或卡片等布局时，调用 generate_slide_layout 或 batch_add_cards。
3. 当用户要求美化页面、美化UI、排版优化、自适应规整或修复布局瑕疵时，优先调用 auto_fix_layout（自动检测并修复重叠与边距溢出），或调用 optimize_layout / align_elements / format_text。
4. 当用户要求微调特定元素或排版时，调用 update_element, format_text, optimize_layout 或 align_elements。
"""


# =====================================================================
# 3. LangGraph Workflow Graph Construction
# =====================================================================

def should_route_planner(state: PPTAgentState) -> str:
    if state.get("grounding_clarification"):
        return "summary_node"
    if state.get("intent") == "chat":
        return "summary_node"
    # A resumed plan-confirmation turn executes the frozen plan directly.
    if state.get("plan_preapproved"):
        return "executor_node"
    return "planner_node"


def should_route_plan_critic(state: PPTAgentState) -> str:
    """Decides whether to proceed to executor or loop back to planner to refine outline."""
    intent = state.get("intent", "chat")
    if intent not in ["generate_presentation", "generate_slide", "optimize_layout"]:
        if _needs_plan_confirmation(state):
            return "await_plan_confirmation_node"
        return "executor_node"

    plan_review = state.get("plan_review")
    plan_it = state.get("plan_iteration", 0)

    # If PlanCriticSubagent did not approve and within max 2 iterations, loop back to planner
    if plan_review and not plan_review.get("approved", True) and plan_it < 2:
        return "planner_node"
    if _needs_plan_confirmation(state):
        return "await_plan_confirmation_node"
    return "executor_node"


def _needs_plan_confirmation(state: PPTAgentState) -> bool:
    """True when a plan-mode turn must pause for explicit user approval."""
    if state.get("plan_preapproved"):
        return False
    if state.get("interaction_mode") != "plan":
        return False
    if state.get("intent") == "chat":
        return False
    return bool(state.get("plan"))


def should_route_mutation(state: PPTAgentState) -> str:
    """Routes a terminally invalidated turn to summary; stale plans replan.

    A turn whose document identity changed under it must NOT replan (the request
    was bound to the old deck). Same-epoch revision staleness may replan, bounded
    so a continuously-editing GUI cannot starve the turn forever.
    """
    if state.get("turn_invalidated"):
        return "summary_node"
    if state.get("stale_plan") and state.get("stale_replan_count", 0) <= 2:
        return "executor_node"
    return "content_critic_node"


def should_route_content_critic(state: PPTAgentState) -> str:
    """Loop back only when this pass named a slide that still has a rework round.

    Each failed slide is capped inside ``content_critic_node`` (two directives).
    A global ``content_iteration < 2`` check ran after the node incremented the
    counter, so the second page never received its own round.
    """
    directive = state.get("rework_directive") or {}
    if directive.get("slide_id"):
        return "executor_node"
    return "vision_critic_node"


def should_auto_correct(state: PPTAgentState) -> str:
    """Decides whether to enter layout auto-correction loop based on critical geometric defects."""
    visual_review = state.get("visual_review")
    if not visual_review:
        return "summary_node"

    plan_dict = visual_review.get("remediation_plan", {})
    has_critical = plan_dict.get("has_critical", False) or visual_review.get("has_critical_defects", False)
    auto_count = plan_dict.get("auto_executable_count", plan_dict.get("critical_count", len(visual_review.get("proposed_actions", []))))
    needs_correction = visual_review.get("needs_auto_correction", False)
    correction_count = state.get("correction_count", 0)
    max_allowed = getattr(settings, "max_visual_iterations", 3)

    if (has_critical or needs_correction) and auto_count > 0 and correction_count < max_allowed:
        return "auto_correct_node"
    return "summary_node"


def build_ppt_agent_graph() -> StateGraph:
    """Builds and compiles the complete LangGraph closed-loop workflow:
    START -> router_node -> planner_node -> plan_critic_node (loop if rejected)
          -> executor_node (plans) -> mutation_node (gateway commits)
          -> content_critic_node (loop if rejected)
          -> vision_critic_node -> auto_correct_node (loop if geometric defects)
          -> summary_node -> END
    """
    workflow = StateGraph(PPTAgentState)

    # Add Nodes
    workflow.add_node("router_node", router_node)
    workflow.add_node("planner_node", planner_node)
    workflow.add_node("plan_critic_node", plan_critic_node)
    workflow.add_node("await_plan_confirmation_node", await_plan_confirmation_node)
    workflow.add_node("executor_node", executor_node)
    workflow.add_node("mutation_node", mutation_node)
    workflow.add_node("content_critic_node", content_critic_node)
    workflow.add_node("vision_critic_node", vision_critic_node)
    workflow.add_node("auto_correct_node", auto_correct_node)
    workflow.add_node("summary_node", summary_node)

    # Add Edges
    workflow.add_edge(START, "router_node")
    workflow.add_conditional_edges("router_node", should_route_planner, {
        "planner_node": "planner_node",
        "executor_node": "executor_node",
        "summary_node": "summary_node"
    })
    workflow.add_edge("planner_node", "plan_critic_node")
    workflow.add_conditional_edges("plan_critic_node", should_route_plan_critic, {
        "planner_node": "planner_node",
        "executor_node": "executor_node",
        "await_plan_confirmation_node": "await_plan_confirmation_node"
    })
    workflow.add_edge("await_plan_confirmation_node", "summary_node")
    workflow.add_edge("executor_node", "mutation_node")
    workflow.add_conditional_edges("mutation_node", should_route_mutation, {
        "executor_node": "executor_node",
        "content_critic_node": "content_critic_node"
    })
    workflow.add_conditional_edges("content_critic_node", should_route_content_critic, {
        "executor_node": "executor_node",
        "vision_critic_node": "vision_critic_node"
    })
    workflow.add_conditional_edges("vision_critic_node", should_auto_correct, {
        "auto_correct_node": "auto_correct_node",
        "summary_node": "summary_node"
    })
    workflow.add_edge("auto_correct_node", "vision_critic_node")
    workflow.add_edge("summary_node", END)

    return workflow.compile()
