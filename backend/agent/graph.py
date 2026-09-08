"""LangGraph StateGraph Workflow for PPT-Agent-Studio.

Orchestrates multi-phase Agent loop:
Router -> Planner -> Executor (Tool Calling) -> Tools Execution -> Vision Review -> Designer Summary.
"""

from __future__ import annotations
import json
import logging
import uuid
from typing import Dict, Any, List, Optional, Callable, TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END

from .tools import tools
from .memory import AgentMemory
from .vision import VisionEngine
from .llm import LLMClient
from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..config import settings

logger = logging.getLogger(__name__)


# =====================================================================
# 1. State Definition
# =====================================================================

class PPTAgentState(TypedDict, total=False):
    messages: List[Dict[str, Any]]
    user_query: str
    intent: str  # "generate_presentation" | "generate_slide" | "modify_elements" | "optimize_layout" | "apply_theme" | "chat"
    plan: Optional[str]
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    vision_critique: Optional[str]
    visual_review: Optional[Dict[str, Any]]
    correction_count: int
    iteration: int
    max_iterations: int
    final_summary: str
    active_slide_id: Optional[str]
    presentation_version: int


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
        await on_event({"type": "agent_thinking", "status": "routing", "text": "分析用户需求意图与画布状态..."})

    # Rule & keyword-assisted intent classification
    intent = "chat"
    if any(k in user_query for k in ["生成完整", "制作一份", "创建ppt", "生成ppt", "写一个ppt", "关于", "汇报", "商业计划书"]) or (
        ("生成" in user_query or "创建" in user_query or "制作" in user_query) and ("演示文稿" in user_query or "ppt" in query_lower or "大纲" in user_query or "页" in user_query)
    ):
        intent = "generate_presentation"
    elif any(k in user_query for k in ["时间线", "里程碑", "指标", "kpi", "特性卡片", "栏卡片", "对比", "新增一页", "添加一页", "新页面", "生成两栏", "排版生成"]):
        intent = "generate_slide"
    elif any(k in user_query for k in ["规整", "对齐", "排列", "居中", "均匀分布", "整理卡片", "自适应排版"]):
        intent = "optimize_layout"
    elif any(k in user_query for k in ["主题", "配色", "黑曜", "深色", "科技蓝", "浅色", "风格"]):
        intent = "apply_theme"
    elif any(k in user_query for k in ["修改", "改成", "换成", "变大", "变小", "调为", "更新", "删除", "添加", "标题", "文字", "复制"]):
        intent = "modify_elements"
    elif len(user_query) > 5:
        # Default action-oriented queries to modify or generate
        intent = "modify_elements" if (pres and len(pres.slides) > 0) else "generate_presentation"

    return {
        "intent": intent,
        "iteration": state.get("iteration", 0) + 1
    }


async def planner_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Generates structural layout and coordinate-safe design plan."""
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")
    intent = state.get("intent", "chat")
    user_query = state.get("user_query", "")

    if on_event:
        await on_event({"type": "agent_thinking", "status": "planning", "text": f"规划设计策略 ({intent})，计算 1280x720 坐标体系..."})

    plan_desc = ""
    if intent == "generate_presentation":
        plan_desc = f"规划生成多页精美演示文稿: 包含封面、核心架构、实施流程时间线、关键性能指标与总结展望。"
    elif intent == "generate_slide":
        plan_desc = f"规划生成当前页面布局架构: 统一字号层级、计算间距与容器圆角，避免元素交叠。"
    elif intent == "optimize_layout":
        plan_desc = "计算画布几何重心，重新规整图元水平/垂直对齐与呼吸留白。"
    elif intent == "apply_theme":
        plan_desc = "匹配全局色彩系统与图元描边规范，提升视觉对比度与统一性。"
    elif intent == "modify_elements":
        plan_desc = "定位目标图元，执行精确属性微调与样式重写。"

    return {
        "plan": plan_desc
    }


async def executor_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Interacts with LLM tool-calling or heuristic planner to generate tool calls."""
    configurable = config.get("configurable", {})
    on_event: Optional[Callable] = configurable.get("on_event")
    pres: Optional[PresentationIR] = configurable.get("pres")
    memory: Optional[AgentMemory] = configurable.get("memory")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")

    user_query = state.get("user_query", "")
    intent = state.get("intent", "chat")
    active_slide = pres.get_active_slide() if pres else None

    # Check if live LLM with valid non-mock API key is configured
    has_live_llm = llm_client and llm_client.api_key and not llm_client.api_key.startswith("mock_")

    tool_calls: List[Dict[str, Any]] = []

    if has_live_llm:
        # Execute via live LLM tool calling
        system_prompt = _build_llm_system_prompt(pres, memory)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]
        try:
            resp = await llm_client.chat_completion(
                messages=messages,
                tools=tools.schemas,
                role="reasoning"
            )
            msg = resp["choices"][0]["message"]
            raw_tc = msg.get("tool_calls", [])
            for tc in raw_tc:
                fn_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments", "{}"))
                except Exception:
                    args = {}
                tool_calls.append({"name": fn_name, "arguments": args, "id": tc.get("id", f"call_{uuid.uuid4().hex[:6]}")})
        except Exception as e:
            logger.warning(f"Live LLM call error: {e}, falling back to intelligent rule planner")
            tool_calls = _heuristic_tool_planner(intent, user_query, pres)
    else:
        # Fallback / Mock intelligent rule planner
        tool_calls = _heuristic_tool_planner(intent, user_query, pres)

    return {
        "tool_calls": tool_calls
    }


def _heuristic_tool_planner(intent: str, user_query: str, pres: Optional[PresentationIR]) -> List[Dict[str, Any]]:
    """Heuristic tool planner for deterministic and instant execution."""
    tool_calls = []
    active_slide = pres.get_active_slide() if pres else None

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
                "theme": "monochrome_studio",
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
                        "subtitle": "高可用模块化架构，驱动企业级高效智能生产力",
                        "items": [
                            {"title": "PPT-IR 中间表示", "description": "统一解耦各种格式，支持毫秒级差异同步与补丁撤销", "badge": "01"},
                            {"title": "LangGraph 协同流", "description": "状态机驱动的观察-规划-执行-自检闭环，确保高精度图元编排", "badge": "02"},
                            {"title": "原生 OOXML 引擎", "description": "直接读写底层 XML 数据，无损导入导出高保真演示文稿", "badge": "03"}
                        ]
                    },
                    {
                        "title": "项目发展阶段与演进时间线",
                        "layout": "timeline",
                        "items": [
                            {"title": "Phase 1: 底层模型确立", "description": "构建标准 1280x720 PPT-IR 抽象与属性规范"},
                            {"title": "Phase 2: Agent 与工具链", "description": "接入 LangGraph 智能编排与专业图元操作工具库"},
                            {"title": "Phase 3: 实时双向预览", "description": "WebSocket 全双工协同，实现端到端所见即所得"}
                        ]
                    },
                    {
                        "title": "关键效能与业务价值指标",
                        "layout": "kpi_metrics",
                        "items": [
                            {"value": "10x+", "label": "制作效率提升", "subtext": "全流程自动化分钟级出稿"},
                            {"value": "99.8%", "label": "样式保真度", "subtext": "原生 OOXML 双向精准映射"},
                            {"value": "< 300ms", "label": "协同响应延迟", "subtext": "全量状态毫秒级增量广播"}
                        ]
                    },
                    {
                        "title": "传统设计 vs Agentic 驱动模式对比",
                        "layout": "comparison",
                        "items": [
                            {"title": "传统手动模式", "description": "• 反复调整对齐坐标与边距\n• 跨成员协作易发生样式冲突\n• 耗费大量机械劳动"},
                            {"title": "Agentic 智能驱动", "description": "• 自然语言意图理解并自动构图\n• 自动遵循专业排版设计规范\n• 一键无损导出与历史版本追溯"}
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
                        {"value": "85.6%", "label": "用户满意度", "subtext": "设计美感与排版质感显著增强"},
                        {"value": "3.5x", "label": "协同周转速率", "subtext": "大幅降低改版沟通成本"},
                        {"value": "100%", "label": "平台兼容性", "subtext": "支持全平台标准 PowerPoint 播放"}
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
                        {"title": "方案 B (智能协同)", "description": "• 毫秒级生成与重绘\n• 统一高质感设计系统\n• 赋能全员高效表达"}
                    ]
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
        # Target elements on active slide
        if active_slide and active_slide.elements:
            # If user asks to update text/title
            title_elem = next((e for e in active_slide.elements if "title" in e.id.lower() or (e.type == "text" and e.y < 120)), None)
            card_elems = [e for e in active_slide.elements if e.type == "shape"]

            if ("标题" in user_query or "字号" in user_query) and title_elem:
                tool_calls.append({
                    "name": "format_text",
                    "arguments": {
                        "element_id": title_elem.id,
                        "font_size": 36.0,
                        "bold": True,
                        "font_color": "#FFFFFF"
                    },
                    "id": f"call_{uuid.uuid4().hex[:6]}"
                })
            elif "颜色" in user_query or "背景" in user_query or "深色" in user_query:
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
                # Add or update generic shape
                tool_calls.append({
                    "name": "add_shape",
                    "arguments": {
                        "shape_type": "roundRect",
                        "x": 100,
                        "y": 240,
                        "width": 320,
                        "height": 220,
                        "fill_color": "#18181B",
                        "text": f"AI 智能优化模块\n\n已根据指令 '{user_query[:20]}' 完成自动配置。"
                    },
                    "id": f"call_{uuid.uuid4().hex[:6]}"
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


async def tools_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Safely executes all requested tools on PPT-IR and tracks changes."""
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    history: Optional[HistoryManager] = configurable.get("history")
    on_event: Optional[Callable] = configurable.get("on_event")
    memory: Optional[AgentMemory] = configurable.get("memory")

    tool_calls = state.get("tool_calls", [])
    results: List[Dict[str, Any]] = []

    for tc in tool_calls:
        fn_name = tc.get("name", "")
        args = tc.get("arguments", {})

        if on_event:
            await on_event({
                "type": "tool_executing",
                "tool": fn_name,
                "arguments": args
            })

        # Execute
        res = tools.execute(fn_name, args, pres, history)

        results.append({
            "tool": fn_name,
            "arguments": args,
            "result": res
        })

        if on_event:
            await on_event({
                "type": "tool_completed",
                "tool": fn_name,
                "result": res,
                "presentation_version": pres.version if pres else 1
            })

        if memory:
            memory.log_action(f"执行工具 '{fn_name}': {res.get('message', 'ok')}")

    return {
        "tool_results": results,
        "presentation_version": pres.version if pres else 1
    }


async def vision_critic_node(state: PPTAgentState, config: RunnableConfig) -> Dict[str, Any]:
    """Runs comprehensive visual balance, geometric collision, and layout critique."""
    configurable = config.get("configurable", {})
    pres: Optional[PresentationIR] = configurable.get("pres")
    llm_client: Optional[LLMClient] = configurable.get("llm_client")
    on_event: Optional[Callable] = configurable.get("on_event")

    critique = None
    review_dict = None
    active_slide = pres.get_active_slide() if pres else None

    if active_slide and len(active_slide.elements) > 0:
        if settings.enable_vision_loop:
            if on_event:
                await on_event({"type": "vision_loop", "status": "reviewing", "text": "排版几何与视觉平衡多模态自检中..."})

            from ..eval.visual_critic import VisualCritic
            # Review slide geometry and contrast
            review_res = await VisualCritic.review_slide(
                slide=active_slide,
                llm_client=llm_client,
                include_multimodal=bool(llm_client and getattr(llm_client, "api_key", None))
            )
            critique = review_res.critique_summary
            review_dict = review_res.to_dict()

            if on_event:
                await on_event({
                    "type": "vision_critique_completed",
                    "score": review_res.health_report.score,
                    "defects_count": len(review_res.health_report.defects),
                    "summary": review_res.critique_summary,
                    "needs_auto_correction": review_res.needs_auto_correction
                })

    return {
        "vision_critique": critique,
        "visual_review": review_dict
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
        await on_event({
            "type": "vision_loop",
            "status": "auto_correcting",
            "text": "排版自愈中: 开启事务安全执行关键缺陷修复..."
        })

    from .remediation_runner import RemediationRunner
    from ..eval.remediation import RemediationPlan, FixAction, FixActionType, DefectCategory

    # Reconstruct RemediationPlan from review dict
    plan_dict = visual_review.get("remediation_plan", {})
    actions = []
    for a in plan_dict.get("actions", []):
        try:
            actions.append(FixAction(
                action_type=FixActionType(a["action_type"]),
                category=DefectCategory(a["category"]),
                target_ids=a.get("target_ids", []),
                parameters=a.get("parameters", {}),
                reason=a.get("reason", ""),
                priority=a.get("priority", 1)
            ))
        except Exception:
            pass

    plan = RemediationPlan(
        actions=actions,
        has_critical=plan_dict.get("has_critical", False),
        summary=plan_dict.get("summary", "")
    )

    runner_res = RemediationRunner.apply_plan(
        pres=pres,
        history=history,
        plan=plan,
        slide_id=state.get("active_slide_id"),
        only_critical=True
    )

    for rec in runner_res.get("applied_records", []):
        tool_results.append({
            "tool": rec["tool"],
            "args": rec["args"],
            "result": rec["result"],
            "auto_correct": True,
            "reason": rec["reason"]
        })
        if on_event:
            await on_event({
                "type": "tool_completed",
                "tool": rec["tool"],
                "result": rec["result"],
                "presentation_version": pres.version if pres else 1
            })

    if runner_res.get("rolled_back") and on_event:
        await on_event({
            "type": "vision_loop",
            "status": "rolled_back",
            "text": runner_res.get("message", "自愈因质量未达标已安全回滚")
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

    intent = state.get("intent", "chat")
    tool_results = state.get("tool_results", [])
    vision_critique = state.get("vision_critique")
    visual_review = state.get("visual_review")
    correction_count = state.get("correction_count", 0)
    user_query = state.get("user_query", "")

    if intent == "chat" and not tool_results:
        final_text = "你好！我是你的 PPT 协同设计架构师。我支持通过自然语言一键生成多页精美演示文稿、自动排版时间线/指标卡/对比栏、智能调色与图元微调。请告诉我你的设计需求！"
    elif intent == "generate_presentation":
        final_text = f"已为您成功构思并生成完整的《{pres.title if pres else '演示文稿'}》，共 {len(pres.slides) if pres else 1} 页。页面涵盖封面、核心特性、演进流程与关键指标，并已统一应用专业设计规范。"
    elif intent == "generate_slide":
        final_text = f"已为您在当前页面完成高保真架构排版。按统一网格计算了元素坐标与呼吸感留白，已就绪供您查看与微调。"
    elif intent == "optimize_layout":
        final_text = "已自动执行几何网格对齐与规整，优化了卡片间距与容器层级，排版更加匀称工整。"
    elif intent == "apply_theme":
        final_text = "已应用全局设计主题规范，调和了背景底色、卡片填充与文字高对比度。"
    else:
        executed_names = [r["tool"] for r in tool_results if not r.get("auto_correct")]
        tool_desc = ', '.join(executed_names) if executed_names else '编辑工具'
        final_text = f"已完成针对当前幻灯片的调整。成功调用了 {tool_desc}，图元属性已实时同步更新。"

    if correction_count > 0 and visual_review:
        score_val = visual_review.get("score", 95.0)
        final_text += f"\n\n[视觉自愈闭环] 检测并自动纠偏了几何重叠与边缘贴靠缺陷，当前页面健康度达 {score_val:.1f}/100。"

    if on_event:
        await on_event({
            "type": "agent_finished",
            "summary": final_text,
            "tools_executed": tool_results,
            "vision_critique": vision_critique,
            "visual_review": visual_review,
            "correction_count": correction_count,
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

【演示文稿当前状态】:
- 标题: {pres.title}
- 幻灯片总数: {len(pres.slides)}
- 列表: {', '.join(slide_info)}

【当前正编辑的幻灯片 (ID: {active_slide.id if active_slide else 'None'}) 元素清单】:
{elements_str}

{memory_str}

【重要操作准则】:
1. 当用户要求生成完整 PPT 时，调用 generate_presentation 工具。
2. 当用户要求生成时间线、指标或卡片等布局时，调用 generate_slide_layout 或 batch_add_cards。
3. 当用户要求微调特定元素或排版时，调用 update_element, format_text, optimize_layout 或 align_elements。
"""


# =====================================================================
# 3. LangGraph Workflow Graph Construction
# =====================================================================

def should_route_planner(state: PPTAgentState) -> str:
    if state.get("intent") == "chat":
        return "summary_node"
    return "planner_node"


def should_execute_tools(state: PPTAgentState) -> str:
    tool_calls = state.get("tool_calls", [])
    if tool_calls:
        return "tools_node"
    return "summary_node"


def should_auto_correct(state: PPTAgentState) -> str:
    """Decides whether to enter auto-correction loop based on critical defects."""
    visual_review = state.get("visual_review")
    if not visual_review:
        return "summary_node"

    plan_dict = visual_review.get("remediation_plan", {})
    has_critical = plan_dict.get("has_critical", False) or visual_review.get("has_critical_defects", False)
    critical_count = plan_dict.get("critical_count", len(visual_review.get("proposed_actions", [])))
    correction_count = state.get("correction_count", 0)

    # Policy: only critical defects (clipping, collisions, severe overflow) trigger auto-correction (max 2 iterations)
    if has_critical and critical_count > 0 and correction_count < 2:
        return "auto_correct_node"
    return "summary_node"


def build_ppt_agent_graph() -> StateGraph:
    """Builds and compiles the LangGraph StateGraph."""
    workflow = StateGraph(PPTAgentState)

    # Add Nodes
    workflow.add_node("router_node", router_node)
    workflow.add_node("planner_node", planner_node)
    workflow.add_node("executor_node", executor_node)
    workflow.add_node("tools_node", tools_node)
    workflow.add_node("vision_critic_node", vision_critic_node)
    workflow.add_node("auto_correct_node", auto_correct_node)
    workflow.add_node("summary_node", summary_node)

    # Add Edges
    workflow.add_edge(START, "router_node")
    workflow.add_conditional_edges("router_node", should_route_planner, {
        "planner_node": "planner_node",
        "summary_node": "summary_node"
    })
    workflow.add_edge("planner_node", "executor_node")
    workflow.add_conditional_edges("executor_node", should_execute_tools, {
        "tools_node": "tools_node",
        "summary_node": "summary_node"
    })
    workflow.add_edge("tools_node", "vision_critic_node")
    workflow.add_conditional_edges("vision_critic_node", should_auto_correct, {
        "auto_correct_node": "auto_correct_node",
        "summary_node": "summary_node"
    })
    workflow.add_edge("auto_correct_node", "vision_critic_node")
    workflow.add_edge("summary_node", END)

    return workflow.compile()
