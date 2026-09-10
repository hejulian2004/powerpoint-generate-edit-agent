"""Independent Plan Critic Subagent (Blind Outline & Strategy Auditor).

Decoupled subagent that objectively audits presentation structural plans,
slide outlines, and layout strategies before execution.
Architecture Principles:
1. Zero Context Leakage:
   Does NOT inherit author conversational history, memory reflections, or author agent thoughts.
   Only receives the raw structural plan manifest and abstract topic intent.
2. Independent & Objective Judgement:
   Main agent pauses execution and yields control to this subagent.
   Evaluates content density, narrative logic flow, rhythm, and structural balance.
3. Remediation & Actionable Optimization:
   Outputs structured critique, approval flag, and refined plan recommendations.
"""

from __future__ import annotations
import inspect
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List

logger = logging.getLogger(__name__)

PLAN_CRITIC_SYSTEM_PROMPT = """你是一位完全独立、严苛客观的第三方 PPT 策划架构评审总监（Plan Critic Subagent）。
你受聘对一份 PPT 制作大纲与架构规划（Presentation Plan）进行客观盲审。你不知道作者的交谈历史、作者思维过程或背景偏好，仅从严苛的读者与观众视角进行批判性审查。

【评审核心准则（严苛客观）】:
1. 叙事逻辑与闭环：整套方案（或单页规划）是否有清晰的起点、递进、论证支撑与收尾结论，避免散乱流水账。
2. 页面信息承载与精简度：严禁单页堆砌过多概念，每页核心主题必须唯一，信息密度要适中，避免臃肿冗长。
3. 结构节奏感（Rhythm）：是否有合理的概览、深挖、佐证对比或成果展示，节奏是否张弛有度。
4. 落地可行性与排版友好度：规划的版式或卡片数量（如3~4列或时间线）是否适合 16:9 画布呈现，避免不可行的密集排列。

【输出格式要求】:
请严格保持客观、理性、建设性的批判口吻，输出以下格式：
【架构优点】: 简述 1 点清晰优势
【潜在风险】: 指出 1~2 点结构硬伤或冗余风险（若结构优异可标明无明显风险）
【优化建议】: 给出 1~2 条具体的大纲/内容修剪建议
【评审结论】: 通过 / 需修正（两者选一）
【规划健康分: XX/100】（0-100的整数分：优秀规划85-95，普通平庸70-84，结构硬伤<70）
"""


@dataclass
class PlanCriticResult:
    """Consolidated outcome of the independent Plan Critic Subagent."""
    approved: bool
    score: float
    critique_summary: str
    strengths: str
    risks: str
    recommendations: str
    refined_plan_notes: Optional[str] = None
    subagent_info: Dict[str, Any] = field(default_factory=lambda: {
        "subagent_name": "PlanCriticSubagent",
        "context_isolated": True,
        "role": "independent_plan_auditor"
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approved": self.approved,
            "score": self.score,
            "critique_summary": self.critique_summary,
            "strengths": self.strengths,
            "risks": self.risks,
            "recommendations": self.recommendations,
            "refined_plan_notes": self.refined_plan_notes,
            "subagent_info": self.subagent_info
        }


class PlanCriticSubagent:
    """Independent Plan Critic Subagent.

    Guarantees:
    - Context Isolation: Evaluates solely the structural outline/plan string, zero chat history.
    - Lifecycle Broadcasting: Main agent pauses while subagent audits; subagent signals completion.
    """

    @classmethod
    async def audit_plan(
        cls,
        plan_desc: str,
        target_intent: str,
        slide_count: int = 1,
        llm_client: Optional[Any] = None,
        session_memory: Optional[Any] = None,
        on_event: Optional[Callable] = None
    ) -> PlanCriticResult:
        """Executes the decoupled, context-isolated plan audit with dedicated memory across rounds."""
        # 1. Main Agent pauses: broadcast subagent start
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "started",
                "subagent": "PlanCriticSubagent",
                "main_agent_status": "paused_waiting",
                "round": (len(session_memory.entries) + 1) if session_memory else 1,
                "text": "主 Agent 已暂停等候，独立方案评审 Subagent 介入规划大纲盲审..."
            })
            await cls._safe_emit(on_event, {
                "type": "plan_critique",
                "status": "evaluating",
                "text": "独立 Plan Subagent 审查叙事结构与信息承载力..."
            })

        # 2. Rule-based pre-validation for outline structure
        rule_score = 90.0
        rule_risks: List[str] = []
        rule_recs: List[str] = []

        if len(plan_desc.strip()) < 10:
            rule_score -= 25.0
            rule_risks.append("规划描述过于简略，缺少具体栏位划分与版块定义。")
            rule_recs.append("丰富结构说明，明确各区块定位。")

        if slide_count > 12:
            rule_score -= 15.0
            rule_risks.append("单次规划页数过多，存在信息过载与主题发散风险。")
            rule_recs.append("控制核心页数在 5~8 页，聚焦核心观点。")

        # 3. Multimodal/LLM blind evaluation with strict context isolation
        critique_text = ""
        has_llm = bool(llm_client and getattr(llm_client, "api_key", None) and not str(llm_client.api_key).startswith("mock_"))

        if has_llm:
            try:
                rework_context = ""
                if session_memory and session_memory.entries:
                    rework_context = f"\n\n【Subagent 专属历史审查记忆（对比上一轮返工整改情况）】:\n{session_memory.get_rework_context_summary()}\n请重点核验上一轮指出缺陷是否已被实质修正。"

                blind_user_content = (
                    f"【目标任务分类】: {target_intent}\n"
                    f"【规划幻灯片页数】: {slide_count}\n"
                    f"【待审大纲架构规划】:\n{plan_desc}"
                    f"{rework_context}\n\n"
                    f"请独立客观进行批判性审查。"
                )

                # STRICT ISOLATION: No conversation context, no author thoughts
                isolated_messages = [
                    {"role": "system", "content": PLAN_CRITIC_SYSTEM_PROMPT},
                    {"role": "user", "content": blind_user_content}
                ]

                resp = await llm_client.chat_completion(
                    messages=isolated_messages,
                    role="reasoning",
                    max_tokens=600
                )
                critique_text = resp["choices"][0]["message"].get("content", "")
            except Exception as e:
                logger.warning(f"PlanCriticSubagent LLM call error: {e}")

        # 4. Parse critique output
        strengths = "规划清晰聚焦目标任务。"
        risks = "; ".join(rule_risks) if rule_risks else "无明显架构硬伤。"
        recommendations = "; ".join(rule_recs) if rule_recs else "保持文字精炼，突出主结论。"
        approved = True
        final_score = rule_score

        if critique_text:
            # Extract structured sections
            m_str = re.search(r'【架构优点[:：]?】\s*(.*?)(?=\n【|\Z)', critique_text, re.DOTALL)
            m_risk = re.search(r'【潜在风险[:：]?】\s*(.*?)(?=\n【|\Z)', critique_text, re.DOTALL)
            m_rec = re.search(r'【优化建议[:：]?】\s*(.*?)(?=\n【|\Z)', critique_text, re.DOTALL)
            m_conc = re.search(r'【评审结论[:：]?】\s*(.*?)(?=\n【|\Z)', critique_text, re.DOTALL)
            m_score = re.search(r'【规划健康分[:：]?\s*(\d{1,3})\s*(?:/\s*100)?】', critique_text)

            if m_str:
                strengths = m_str.group(1).strip()
            if m_risk:
                risks = m_risk.group(1).strip()
            if m_rec:
                recommendations = m_rec.group(1).strip()
            if m_conc:
                approved = "需修正" not in m_conc.group(1)
            if m_score:
                parsed_score = float(m_score.group(1))
                final_score = round(0.4 * rule_score + 0.6 * parsed_score, 1)
        else:
            approved = final_score >= 70.0

        summary = f"大纲评审得分: {final_score:.1f}/100 [{ '通过' if approved else '需调整' }]。建议: {recommendations}"

        result = PlanCriticResult(
            approved=approved,
            score=final_score,
            critique_summary=summary,
            strengths=strengths,
            risks=risks,
            recommendations=recommendations,
            refined_plan_notes=f"评审修正指导: {recommendations}" if not approved else None
        )

        # 4.5 Persist audit round into Subagent dedicated session memory
        if session_memory:
            session_memory.record_audit(
                input_digest=plan_desc[:120],
                approved=approved,
                score=final_score,
                critique_summary=summary,
                defects_or_risks=[risks] if risks else [],
                recommendations=[recommendations] if recommendations else []
            )

        # 5. Broadcast Subagent completed: resumes main agent
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "completed",
                "subagent": "PlanCriticSubagent",
                "main_agent_status": "resumed",
                "approved": result.approved,
                "score": result.score,
                "text": f"方案评审 Subagent 盲审完成 [规划分:{result.score:.1f}]，唤醒主 Agent 继续执行"
            })
            await cls._safe_emit(on_event, {
                "type": "plan_critique",
                "status": "completed",
                "approved": result.approved,
                "score": result.score,
                "summary": result.critique_summary
            })

        return result

    @staticmethod
    async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]):
        if not on_event:
            return
        try:
            if inspect.iscoroutinefunction(on_event):
                await on_event(data)
            else:
                res = on_event(data)
                if inspect.isawaitable(res):
                    await res
        except Exception as e:
            logger.debug(f"Plan Subagent event emission ignored: {e}")
