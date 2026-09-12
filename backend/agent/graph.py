"""LangGraph StateGraph Workflow for PPT-Agent-Studio.

Orchestrates multi-phase Agent loop:
Router -> Planner -> Executor (Tool Calling) -> Tools Execution -> Vision Review -> Designer Summary.
"""

from __future__ import annotations
import hashlib
import json
import logging
import uuid
from typing import Dict, Any, List, Optional, Callable, TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from .memory import AgentMemory
from .vision import VisionEngine
from .llm import LLMClient
from .action import AgentAction, ActionResolver
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
    plan_review: Optional[Dict[str, Any]]
    plan_iteration: int
    content_review: Optional[Dict[str, Any]]
    content_iteration: int
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
# 2. Node Functions
# =====================================================================

async def router_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Analyzes user message and current presentation state to classify intent."""
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")

    user_query = state.get("user_query", "").strip()
    query_lower = user_query.lower()

    if on_event:
        await _safe_emit(on_event,{"type": "agent_thinking", "status": "routing", "text": "分析用户需求意图与画布状态..."})

    # Rule & keyword-assisted intent classification
    intent = "chat"
    if any(k in user_query for k in ["撤销刚才修改", "撤销修改", "撤销操作", "撤销刚才", "撤销", "undo", "回退"]):
        intent = "undo"
    elif any(k in user_query for k in ["生成完整", "制作一份", "创建ppt", "生成ppt", "写一个ppt", "关于", "汇报", "商业计划书"]) or (
        ("生成" in user_query or "创建" in user_query or "制作" in user_query) and ("演示文稿" in user_query or "ppt" in query_lower or "大纲" in user_query or "页" in user_query)
    ):
        intent = "generate_presentation"
    elif any(k in user_query for k in ["时间线", "里程碑", "指标", "kpi", "特性卡片", "栏卡片", "对比", "新增一页", "添加一页", "新页面", "生成两栏", "排版生成"]):
        intent = "generate_slide"
    elif any(k in user_query for k in ["规整", "对齐", "排列", "居中", "均匀分布", "整理卡片", "自适应排版", "拥挤", "太挤", "紧凑", "排版杂乱"]):
        intent = "optimize_layout"
    elif any(k in user_query for k in ["主题", "配色", "黑曜", "深色", "科技蓝", "浅色", "风格"]):
        intent = "apply_theme"
    elif any(k in user_query for k in ["修改", "改成", "换成", "变大", "变小", "调为", "更新", "删除", "添加", "标题", "文字", "复制", "移动", "位置", "右侧", "左侧", "再往", "往下", "往上", "往左", "往右", "突出"]):
        intent = "modify_elements"
    elif len(user_query) > 5:
        # Default action-oriented queries to modify or generate
        intent = "modify_elements" if (pres and len(pres.slides) > 0) else "generate_presentation"

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
        plan_desc = "计算画布几何重心，重新规整图元水平/垂直对齐与呼吸留白。"
    elif intent == "apply_theme":
        plan_desc = "匹配全局色彩系统与图元描边规范，提升视觉对比度与统一性。"
    elif intent == "modify_elements":
        plan_desc = "定位目标图元，执行精确属性微调与样式重写。"

    # If previous audit had recommendations, incorporate into refined plan
    if prev_plan_review and prev_plan_review.get("recommendations"):
        plan_desc += f" [已吸纳规划评审优化要求: {prev_plan_review['recommendations']}]"

    return {
        "plan": plan_desc
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

    slide_count = 5 if intent == "generate_presentation" else 1

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
        )

    if on_event:
        await _safe_emit(on_event, {
            "type": "plan_ready",
            "plan_id": plan_id,
            "plan": plan,
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


def _heuristic_tool_planner(
    intent: str,
    user_query: str,
    pres: Optional[PresentationIR],
    last_target_id: Optional[str] = None,
    selected_element_ids: Optional[List[str]] = None,
    primary_selected_element_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Heuristic tool planner using AgentAction contract for deterministic execution."""
    tool_calls = []
    active_slide = pres.get_active_slide() if pres else None

    if intent == "undo":
        tool_calls.append({
            "name": "undo",
            "arguments": {},
            "id": f"call_{uuid.uuid4().hex[:6]}"
        })
        return tool_calls

    if intent == "generate_presentation":
        # Extract topic or use sensible default
        topic = user_query
        for prefix in ["生成关于", "制作一份关于", "制作关于", "生成一份", "创建关于", "生成", "制作", "创建"]:
            if topic.startswith(prefix):
                topic = topic[len(prefix):].strip()
        topic = topic.replace("的ppt", "").replace("的演示文稿", "").strip() or "AI 智能创新方案"

        tool_calls.append({
            "name": "generate_presentation",
            "arguments": {
                "topic": topic,
                "theme": "editorial_technical",
                "replace": True,
                "slides": [
                    {
                        "title": f"{topic} · 战略白皮书",
                        "layout": "title_slide",
                        "subtitle": "基于 AI Agent 中间表示与多模态视觉自省的下一代技术架构",
                    },
                    {
                        "title": "系统核心功能矩阵",
                        "layout": "card_grid",
                        "subtitle": "高可用模块化架构，驱动高效智能生产力",
                        "items": [
                            {"title": "PPT-IR 中间表示", "description": "统一解耦各种格式，支持增量差异同步与补丁撤销", "badge": "01"},
                            {"title": "LangGraph 协同流", "description": "状态机驱动的观察-规划-执行-自检闭环，确保图元编排精度", "badge": "02"},
                            {"title": "原生 OOXML 引擎", "description": "直接读写底层 XML 数据，高保真导入导出演示文稿", "badge": "03"}
                        ]
                    },
                    {
                        "title": "项目发展阶段与演进时间线",
                        "layout": "timeline",
                        "items": [
                            {"title": "Phase 1: 底层模型确立", "description": "构建标准 PPT-IR 抽象与属性规范"},
                            {"title": "Phase 2: Agent 与工具链", "description": "接入 LangGraph 智能编排与专业图元操作工具库"},
                            {"title": "Phase 3: 实时双向预览", "description": "WebSocket 全双工协同，实现端到端所见即所得"}
                        ]
                    },
                    {
                        "title": "关键效能与业务价值指标",
                        "layout": "kpi_metrics",
                        "items": [
                            {"value": "—", "label": "制作效率提升", "subtext": "全流程自动化出稿"},
                            {"value": "—", "label": "样式保真度", "subtext": "原生 OOXML 双向映射"},
                            {"value": "—", "label": "协同响应延迟", "subtext": "全量状态增量广播"}
                        ]
                    },
                    {
                        "title": "传统设计 vs Agentic 驱动模式对比",
                        "layout": "comparison",
                        "items": [
                            {"title": "传统手动模式", "description": "• 反复调整对齐坐标与边距\n• 跨成员协作易发生样式冲突\n• 耗费大量机械劳动"},
                            {"title": "Agentic 智能驱动", "description": "• 自然语言意图理解并自动构图\n• 自动遵循专业排版设计规范\n• 一键导出与历史版本追溯"}
                        ]
                    }
                ]
            },
            "id": f"call_{uuid.uuid4().hex[:6]}"
        })

    elif intent == "generate_slide":
        if "时间线" in user_query or "里程碑" in user_query or "timeline" in user_query.lower():
            tool_calls.append({
                "name": "generate_slide_layout",
                "arguments": {
                    "layout_type": "timeline",
                    "title": "发展历程与里程碑规划",
                    "items": [
                        {"title": "需求调研", "description": "定义核心业务场景与用户画像"},
                        {"title": "技术攻关", "description": "攻克 PPT-IR 转换与 Agent 闭环"},
                        {"title": "产品发布", "description": "全功能上线并实现规模化交付"}
                    ]
                },
                "id": f"call_{uuid.uuid4().hex[:6]}"
            })
        elif "指标" in user_query or "kpi" in user_query.lower() or "数据" in user_query:
            tool_calls.append({
                "name": "generate_slide_layout",
                "arguments": {
                    "layout_type": "kpi_metrics",
                    "title": "核心关键绩效指标 (KPI)",
                    "items": [
                        {"value": "—", "label": "用户满意度", "subtext": "设计美感与排版质感增强"},
                        {"value": "—", "label": "协同周转速率", "subtext": "降低改版沟通成本"},
                        {"value": "—", "label": "平台兼容性", "subtext": "支持标准 PowerPoint 播放"}
                    ]
                },
                "id": f"call_{uuid.uuid4().hex[:6]}"
            })
        elif "对比" in user_query or "两栏" in user_query:
            tool_calls.append({
                "name": "generate_slide_layout",
                "arguments": {
                    "layout_type": "comparison",
                    "title": "方案对比与选型分析",
                    "items": [
                        {"title": "方案 A (传统模式)", "description": "• 成本高、周期长\n• 灵活性差\n• 难以快速规模化复制"},
                            {"title": "方案 B (智能协同)", "description": "• 快速生成与重绘\n• 统一高质感设计系统\n• 赋能全员高效表达"}
                    ]
                },
                "id": f"call_{uuid.uuid4().hex[:6]}"
            })
        elif any(k in user_query for k in ["新增一页", "添加一页", "新页面", "新建页面", "新增幻灯片", "新建幻灯片", "加一页", "空白", "创建一页"]):
            bg = "#0A0A0A"
            if active_slide and getattr(active_slide.background, "color", None):
                bg = active_slide.background.color
            if "白" in user_query and "黑" not in user_query:
                bg = "#FFFFFF"
            elif "黑" in user_query and "白" not in user_query:
                bg = "#0A0A0A"

            tool_calls.append({
                "name": "create_slide",
                "arguments": {
                    "title": "新建幻灯片",
                    "background_color": bg
                },
                "id": f"call_{uuid.uuid4().hex[:6]}"
            })
        else:
            # Default card grid
            tool_calls.append({
                "name": "generate_slide_layout",
                "arguments": {
                    "layout_type": "card_grid",
                    "title": "核心产品功能与架构特性",
                    "items": [
                        {"title": "智能意图解析", "description": "基于 LangGraph 图状态机，精准分流生成与编辑指令", "badge": "01"},
                        {"title": "原生图元工具箱", "description": "提供完备的卡片、连线、对齐与排版等原子级操作能力", "badge": "02"},
                        {"title": "视觉多模态校验", "description": "结合画布几何计算与视觉模型，主动修正视觉瑕疵", "badge": "03"}
                    ]
                },
                "id": f"call_{uuid.uuid4().hex[:6]}"
            })

    elif intent == "optimize_layout":
        tool_calls.append({
            "name": "optimize_layout",
            "arguments": {
                "layout_mode": "horizontal_cards",
                "start_y": 240,
                "gap": 32
            },
            "id": f"call_{uuid.uuid4().hex[:6]}"
        })

    elif intent == "apply_theme":
        theme_name = "monochrome_studio"
        if "蓝" in user_query:
            theme_name = "tech_blue"
        elif "绿" in user_query or "翡翠" in user_query:
            theme_name = "emerald_nature"
        elif "金" in user_query or "暖" in user_query:
            theme_name = "warm_corporate"
        elif "黑" in user_query or "极简" in user_query:
            theme_name = "monochrome_studio"

        tool_calls.append({
            "name": "apply_theme",
            "arguments": {"theme_preset": theme_name},
            "id": f"call_{uuid.uuid4().hex[:6]}"
        })

    elif intent == "modify_elements":
        # Deictic references ("这个/它/选中的") bind to the requesting client's
        # selection, or fail closed with a clarification (empty plan). Never fall
        # back to last_target_id or textual guessing.
        from .uicontext import DEFERENCE_TOKENS
        if any(tok in user_query for tok in DEFERENCE_TOKENS):
            targets = [t for t in (selected_element_ids or []) if t]
            target = primary_selected_element_id or (targets[0] if targets else None)
            if not target:
                return tool_calls
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
            target_el = next((e for e in elements if e.id == target), None)
            if target_el is not None:
                if any(k in user_query for k in ["放大", "变大", "大一点", "再大", "增大"]):
                    updates["width"] = float(target_el.width) * 1.2
                    updates["height"] = float(target_el.height) * 1.2
                elif any(k in user_query for k in ["缩小", "变小", "小一点", "再小"]):
                    updates["width"] = float(target_el.width) * 0.8
                    updates["height"] = float(target_el.height) * 0.8
            tool_calls.append({
                "name": "update_element",
                "arguments": updates,
                "id": f"call_{uuid.uuid4().hex[:6]}",
            })
            return tool_calls

        # Target elements on active slide using AgentAction contract
        if active_slide and active_slide.elements:
            target_ref = last_target_id or "title"

            # 1. Relative movement (multi-turn context sensitive)
            if any(k in user_query for k in ["再往下", "往下一点", "往下挪", "下移", "再往下", "低一点"]):
                act = AgentAction(action_type="update_element", target=target_ref, parameters={"y": 50.0}, relative=True, reason="User requested downward adjustment")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})
            elif any(k in user_query for k in ["再往上", "往上一点", "往上挪", "上移", "再往上", "高一点"]):
                act = AgentAction(action_type="update_element", target=target_ref, parameters={"y": -50.0}, relative=True, reason="User requested upward adjustment")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})
            elif any(k in user_query for k in ["再往右", "往右一点", "往右挪", "右移", "再往右"]):
                act = AgentAction(action_type="update_element", target=target_ref, parameters={"x": 50.0}, relative=True, reason="User requested rightward adjustment")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})
            elif any(k in user_query for k in ["再往左", "往左一点", "往左挪", "左移", "再往左"]):
                act = AgentAction(action_type="update_element", target=target_ref, parameters={"x": -50.0}, relative=True, reason="User requested leftward adjustment")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})

            # 2. Prominent title / styling
            elif any(k in user_query for k in ["突出", "醒目", "加大标题", "放大标题", "让标题更突出", "更突出"]):
                act = AgentAction(action_type="resize_text", target="title", parameters={"font_size": 42.0, "bold": True}, reason="User requested prominent title")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})

            # 3. Explicit repositioning / layout moving instructions
            elif ("移动" in user_query or "move" in user_query.lower() or "位置" in user_query or "放" in user_query) and ("右" in user_query or "right" in user_query.lower()):
                act = AgentAction(action_type="update_element", target="title", parameters={"x": 900.0}, reason="User moved title to right")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})
            elif ("移动" in user_query or "move" in user_query.lower() or "位置" in user_query or "放" in user_query) and ("左" in user_query or "left" in user_query.lower()):
                act = AgentAction(action_type="update_element", target="title", parameters={"x": 100.0}, reason="User moved title to left")
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})
            elif ("标题" in user_query or "字号" in user_query):
                act = AgentAction(action_type="format_text", target="title", parameters={"font_size": 36.0, "bold": True, "font_color": "#FFFFFF"})
                tc = ActionResolver.action_to_tool_call(act, pres, last_target_id=last_target_id)
                if tc:
                    tool_calls.append({**tc, "id": f"call_{uuid.uuid4().hex[:6]}"})
            elif "颜色" in user_query or "背景" in user_query or "深色" in user_query:
                card_elems = [e for e in active_slide.elements if e.type == "shape"]
                if card_elems:
                    tool_calls.append({
                        "name": "update_element",
                        "arguments": {
                            "element_id": card_elems[0].id,
                            "fill_color": "#1C1D24",
                            "border_color": "#3A3D4D"
                        },
                        "id": f"call_{uuid.uuid4().hex[:6]}"
                    })
                else:
                    tool_calls.append({
                        "name": "apply_theme",
                        "arguments": {"theme_preset": "monochrome_studio"},
                        "id": f"call_{uuid.uuid4().hex[:6]}"
                    })
            else:
                # Ambiguous modify: never invent a generic shape with fabricated
                # copy. Ask the user to disambiguate instead.
                tool_calls.append({
                    "name": "request_clarification",
                    "arguments": {
                        "question": (
                            "我还不能确定您想修改哪个元素或改成什么效果。"
                            "请先选中目标元素（或在指令中说明元素名称与目标属性/样式），"
                            "我再精确执行，避免误改。"
                        )
                    },
                    "id": f"call_{uuid.uuid4().hex[:6]}",
                })
        else:
            # Empty slide, add text & card
            tool_calls.append({
                "name": "add_text",
                "arguments": {
                    "text": user_query if len(user_query) < 25 else "PPT-Agent 智能演示平台",
                    "x": 100,
                    "y": 80,
                    "width": 1080,
                    "height": 60,
                    "font_size": 34,
                    "font_color": "#FFFFFF",
                    "bold": True
                },
                "id": f"call_{uuid.uuid4().hex[:6]}"
            })

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


async def content_critic_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Runs decoupled, read-only content & narrative structural critique via ContentCriticSubagent with dedicated history."""
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")
    on_event: Optional[Callable] = configurable.get("on_event")
    content_iteration = state.get("content_iteration", 0) + 1

    subagent_mems = dict(state.get("subagent_memories") or {})
    from .subagents.memory import SubagentSessionMemory
    content_mem = SubagentSessionMemory.from_dict(subagent_mems.get("ContentCriticSubagent", {})) if "ContentCriticSubagent" in subagent_mems else SubagentSessionMemory("ContentCriticSubagent")

    review_ids = list(state.get("changed_slide_ids") or [])
    if not review_ids and state.get("rework_directive"):
        # No mutation happened on the rework pass: re-audit the previously failed slides.
        review_ids = list(state["rework_directive"].get("failed_slide_ids") or [])
    review_targets = _resolve_review_slides(pres, review_ids)
    if review_targets and pres:
        pres.active_slide_id = review_targets[0].id

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
        failing_slide_id = content_dict["failed_slide_ids"][0]
        failing_review = deck_reviews[failing_slide_id]
        failing_slide = pres.get_slide(failing_slide_id) if pres else None
        rework_directive = {
            "source": "content_critic",
            "slide_id": failing_slide_id,
            "target_ids": [
                el.id for el in (failing_slide.elements if failing_slide else [])
                if getattr(el, "type", "") in ("text", "shape")
            ],
            "defects": list(failing_review.get("redundancy_issues") or []),
            "recommendations": list(failing_review.get("recommendations") or []),
            "summary": failing_review.get("summary", ""),
            "round": content_iteration,
            "failed_slide_ids": list(content_dict["failed_slide_ids"]),
        }

    subagent_mems["ContentCriticSubagent"] = content_mem.to_dict()

    return {
        "content_review": content_dict,
        "content_iteration": content_iteration,
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
    if review_targets and pres:
        pres.active_slide_id = review_targets[0].id

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
                only_critical=True,
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
    elif intent == "generate_presentation":
        final_text = f"已为您成功构思并生成完整的《{pres.title if pres else '演示文稿'}》，共 {len(pres.slides) if pres else 1} 页。页面涵盖封面、核心特性、演进流程与关键指标，并已统一应用专业设计规范。"
    elif intent == "generate_slide":
        has_created = any(r.get("tool") == "create_slide" for r in tool_results)
        if has_created:
            final_text = f"已为您成功创建第 {len(pres.slides) if pres else 1} 页空白幻灯片，画布已自动切换至新页面，您可以开始自由添加内容。"
        else:
            final_text = f"已为您在当前页面完成高保真架构排版。按统一网格计算了元素坐标与呼吸感留白，已就绪供您查看与微调。"
    elif intent == "optimize_layout":
        final_text = "已自动执行几何网格对齐与规整，优化了卡片间距与容器层级，排版更加匀称工整。"
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
- 使用小圆角（radius ≤ 2px）而非大圆角卡片；不要给每张卡叠加阴影。
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
3. 当用户要求微调特定元素或排版时，调用 update_element, format_text, optimize_layout 或 align_elements。
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
    """Decides whether to proceed to visual critic or loop back to executor to refine text."""
    content_review = state.get("content_review")
    content_it = state.get("content_iteration", 0)

    # If ContentCriticSubagent did not approve and within max 2 iterations, loop back to executor
    if content_review and not content_review.get("approved", True) and content_it < 2:
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
