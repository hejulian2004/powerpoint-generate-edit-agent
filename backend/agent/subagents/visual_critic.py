"""Independent Visual Critic Subagent (Blind Auditor).

This subagent performs completely decoupled visual and aesthetic reviews of PPT slides.
Architecture Principles:
1. Zero Context Leakage:
   Does NOT inherit conversational history, user prompts, planner thoughts, or author intent.
   Only receives the raw visual snapshot and objective element bounding boxes.
2. Independent & Objective Judgement:
   Main agent pauses execution and yields control to the subagent.
   Subagent acts strictly as a third-party art director and layout auditor.
3. Structured Output & Score Fusion:
   Outputs structured defect diagnostics, remediation suggestions, and aesthetic scores,
   which are then handed back to the main agent upon wake-up.
"""

from __future__ import annotations
import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
from ...ir.models import SlideIR
from ...eval.layout_diff import LayoutDiffEngine, LayoutHealthReport
from ...eval.remediation import RemediationPlan
from ...eval.renderer_snapshot import SlideSnapshotRenderer, RendererMode

logger = logging.getLogger(__name__)

CRITIC_SUBAGENT_SYSTEM_PROMPT = """你是一位完全独立、严苛客观的第三方 PPT 视觉艺术总监与版式排版审计专家（Visual Critic Subagent）。
你受聘对主创设计的 PPT 幻灯片进行纯粹的视觉排版与美观度盲审。文字与结构已由前置内容专家评审完毕，你专注于视觉布局、几何结构、排版对齐与美学质感，不再处理文字语义内容。

【评审核心准则（专注于视觉排版与美学质感）】:
1. 留白呼吸感：页面图元总覆盖率是否合理（保持 15%~55% 优雅留白，严禁挤满 >65%），重要区块之间是否有舒适边距。
2. 几何与网格对齐：卡片、标题与正文是否严格吸附于栅格系统，是否有意外错位、重叠或贴边溢出。
3. 字阶比例与排版层级：大标题、副标题、说明文字是否有鲜明的层级比（字阶比 >= 1.5），层级秩序是否明确。
4. 配色克制与质感：色彩是否调和舒适，严禁大面积刺眼高饱和纯色；独立强调色是否收敛在 1~2 种。
5. 图元质感规范：卡片圆角必须极小克制（radius <= 3px）或直角，严禁出现粗糙的大圆角卡片；阴影必须柔和内敛。

【输出格式要求】:
请严格保持客观、理性、设计艺术总监的专业口吻，指出排版与视觉美学问题，并在末尾输出：
【排版与视觉诊断】: 简明列出 1~2 点几何或美学硬伤（如无硬伤注明排版优良）
【美化优化建议】: 简明列出 1~2 点对齐、留白或配色优化动作
【美学评分: XX/100】（0-100的整数分：优秀排版85-95，普通平庸70-80，排版硬伤<70）
"""


@dataclass
class SubagentReviewResult:
    """Consolidated outcome of the independent Subagent visual critique."""
    slide_id: str
    health_report: LayoutHealthReport
    remediation_plan: RemediationPlan
    multimodal_feedback: Optional[str] = None
    vision_status: Dict[str, Any] = field(default_factory=dict)
    needs_auto_correction: bool = False
    snapshot_uri: Optional[str] = None
    subagent_info: Dict[str, Any] = field(default_factory=lambda: {
        "subagent_name": "VisualCriticSubagent",
        "context_isolated": True,
        "role": "independent_auditor"
    })

    @property
    def proposed_actions(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.remediation_plan.actions]

    @property
    def critique_summary(self) -> str:
        parts = [self.health_report.summary()]
        if self.multimodal_feedback:
            parts.append(f"【独立视觉审计意见】: {self.multimodal_feedback}")
        if self.remediation_plan.actions:
            crit_cnt = len(self.remediation_plan.critical_actions)
            struct_cnt = len(self.remediation_plan.structural_actions)
            parts.append(f"已生成排版优化方案: {crit_cnt} 项严重修复，{struct_cnt} 项结构建议。")
        return " \n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "score": self.health_report.score,
            "has_critical_defects": self.health_report.has_critical_defects,
            "defects_count": len(self.health_report.defects),
            "critique_summary": self.critique_summary,
            "health_report": self.health_report.to_dict(),
            "remediation_plan": self.remediation_plan.to_dict(),
            "proposed_actions": self.proposed_actions,
            "multimodal_feedback": self.multimodal_feedback,
            "vision_status": self.vision_status,
            "needs_auto_correction": self.needs_auto_correction,
            "snapshot_uri": self.snapshot_uri,
            "subagent_info": self.subagent_info
        }


class VisualCriticSubagent:
    """Independent visual critic subagent.

    Guarantees:
    - Complete Context Isolation: Never receives conversation history, memory, or author agent reasoning.
    - Blind Review: Evaluates solely the visual raster snapshot + element geometry manifest.
    - Lifecycle Broadcasting: Main agent pauses while subagent audits; subagent signals completion.
    """

    @classmethod
    def format_slide_element_manifest(cls, slide: SlideIR) -> str:
        """Formats a compact structured layout manifest for the subagent."""
        lines = [f"Slide #{slide.slide_num} (Canvas: {slide.width}x{slide.height}, Elements: {len(slide.elements)}):"]
        for el in slide.elements:
            desc = f"- [ID: '{el.id}'] Type: {el.type}, Rect: ({el.x:.0f}, {el.y:.0f}, {el.width:.0f}x{el.height:.0f})"
            if hasattr(el, "text_content") and el.text_content and el.text_content.plain_text:
                desc += f", Text: '{el.text_content.plain_text[:30]}'"
            lines.append(desc)
        return "\n".join(lines)

    @classmethod
    async def audit_slide(
        cls,
        slide: SlideIR,
        llm_client: Optional[Any] = None,
        include_multimodal: bool = True,
        session_memory: Optional[Any] = None,
        on_event: Optional[Callable] = None
    ) -> SubagentReviewResult:
        """Executes the decoupled, context-isolated visual audit on a single slide with dedicated history."""
        round_idx = (len(session_memory.entries) + 1) if session_memory else 1
        # 1. Main Agent pauses: broadcast subagent start event
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "started",
                "subagent": "VisualCriticSubagent",
                "main_agent_status": "paused_waiting",
                "slide_id": slide.id,
                "round": round_idx,
                "text": "主 Agent 已暂停等候，独立第三方视觉评测 Subagent 介入盲审..."
            })
            await cls._safe_emit(on_event, {
                "type": "visual_remediation",
                "phase": "evaluating",
                "status": "evaluating",
                "slide_id": slide.id,
                "text": "独立视觉 Subagent 进行几何与多模态审美盲审中..."
            })

        # 2. Objective geometric, contrast, and rule-based aesthetic inspection
        health_report = LayoutDiffEngine.evaluate_slide(slide)

        # 3. Formulate tool-agnostic remediation plan
        from ...eval.visual_critic import VisualCritic
        remediation_plan = VisualCritic.plan_remediations(slide, health_report)
        needs_correction = len(remediation_plan.auto_executable_actions) > 0

        # 4. Raster snapshot metadata
        meta = SlideSnapshotRenderer.get_render_metadata(slide, mode=RendererMode.DETERMINISTIC)
        multimodal_feedback = None
        vision_status: Dict[str, Any] = {
            "vision_available": False,
            "mode": meta.quality,
            "renderer": meta.renderer,
            "capability": meta.capability.to_dict(),
            "fallback": None,
            "subagent": "VisualCriticSubagent",
            "context_isolated": True,
            "message": "未配置或未启用 Vision 模型客户端，采用纯几何与对比度定量评测"
        }

        # 5. Multimodal blind evaluation with STRICT context isolation
        has_vision_api = bool(llm_client and getattr(llm_client, "api_key", None))
        if include_multimodal and has_vision_api:
            try:
                snapshot_uri = SlideSnapshotRenderer.render_data_uri(slide)
                manifest = cls.format_slide_element_manifest(slide)

                user_prompt = (
                    f"请对当前幻灯片执行客观盲审评测。\n"
                    f"几何健康得分: {health_report.score:.1f}/100。"
                )
                if health_report.defects:
                    user_prompt += f" 检测到潜在缺陷: {'; '.join(d.description for d in health_report.defects[:3])}。"
                if meta.renderer == "pillow" or meta.quality == "geometry_only":
                    user_prompt += "\n当前截图可能缺少字体和特效信息。请优先依据图元坐标清册判断结构。"

                user_prompt += f"\n\n【画布图元坐标清册】:\n{manifest}"

                # STRICT ISOLATION: No conversation context, no author thoughts
                isolated_messages = [
                    {"role": "system", "content": CRITIC_SUBAGENT_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": snapshot_uri, "detail": "low"}}
                        ]
                    }
                ]

                res = await llm_client.chat_completion(isolated_messages, role="vision", max_tokens=600)
                multimodal_feedback = res["choices"][0]["message"].get("content", "视觉分析完成")

                # Extract aesthetic score from independent subagent review
                if multimodal_feedback:
                    m = re.search(r'【美学评分[:：]\s*(\d{1,3})\s*(?:/\s*100)?】', multimodal_feedback)
                    if m:
                        vm_score = max(0.0, min(100.0, float(m.group(1))))
                        rule_aesthetic = health_report.quality_score.aesthetics
                        # 50% rule-based + 50% independent subagent aesthetic rating
                        fused_aesthetic = round(0.50 * rule_aesthetic + 0.50 * vm_score, 1)
                        health_report.quality_score.aesthetics = fused_aesthetic

                        # Recompute total score
                        qs = health_report.quality_score
                        new_total = round(
                            0.30 * qs.geometry +
                            0.20 * qs.readability +
                            0.15 * qs.contrast +
                            0.15 * qs.balance +
                            0.20 * qs.aesthetics,
                            1
                        )
                        qs.total = new_total
                        health_report.score = new_total

                vision_status = {
                    "vision_available": True,
                    "mode": "multimodal",
                    "renderer": meta.renderer,
                    "capability": meta.capability.to_dict(),
                    "fallback": None,
                    "subagent": "VisualCriticSubagent",
                    "context_isolated": True,
                    "message": "视觉质检 Subagent 独立盲审完成"
                }
            except Exception as e:
                logger.warning(f"Subagent vision critique failed, falling back: {e}")
                multimodal_feedback = None
                vision_status = {
                    "vision_available": False,
                    "mode": "geometry_only",
                    "renderer": meta.renderer,
                    "capability": meta.capability.to_dict(),
                    "fallback": "geometry_only",
                    "subagent": "VisualCriticSubagent",
                    "context_isolated": True,
                    "message": f"视觉 Subagent 模型调用异常 ({str(e)})，自动回退到几何与对比度规则评测"
                }

        # 6. Snapshot URI
        try:
            snapshot_uri = SlideSnapshotRenderer.render_data_uri(slide)
        except Exception as e:
            logger.debug(f"Snapshot URI generation failed: {e}")
            snapshot_uri = None

        result = SubagentReviewResult(
            slide_id=slide.id,
            health_report=health_report,
            remediation_plan=remediation_plan,
            multimodal_feedback=multimodal_feedback,
            vision_status=vision_status,
            needs_auto_correction=needs_correction,
            snapshot_uri=snapshot_uri
        )

        # 6.5 Record into dedicated subagent session memory
        if session_memory:
            session_memory.record_audit(
                input_digest=f"Slide #{slide.slide_num} ({len(slide.elements)} elements)",
                approved=not needs_correction and health_report.score >= 80.0,
                score=health_report.score,
                critique_summary=result.critique_summary,
                defects_or_risks=[d.description for d in health_report.defects[:3]],
                recommendations=[a.reason for a in remediation_plan.actions[:3]]
            )

        # 7. Broadcast Subagent completed: resumes main agent
        if on_event:
            await cls._safe_emit(on_event, {
                "type": "subagent_lifecycle",
                "phase": "completed",
                "subagent": "VisualCriticSubagent",
                "main_agent_status": "resumed",
                "slide_id": slide.id,
                "score": result.health_report.score,
                "aesthetic_score": result.health_report.quality_score.aesthetics,
                "text": f"视觉评测 Subagent 盲审完成 [美学:{result.health_report.quality_score.aesthetics:.0f}, 健康分:{result.health_report.score:.1f}]，唤醒主 Agent 继续执行"
            })
            await cls._safe_emit(on_event, {
                "type": "visual_remediation",
                "phase": "diagnosed",
                "status": "diagnosed",
                "slide_id": slide.id,
                "score": result.health_report.score,
                "quality_score": result.health_report.quality_score.to_dict(),
                "defects_count": len(result.health_report.defects),
                "critical_count": result.health_report.critical_count,
                "auto_executable_count": len(result.remediation_plan.auto_executable_actions),
                "actions": [a.to_dict() for a in result.remediation_plan.actions],
                "needs_auto_correction": result.needs_auto_correction,
                "subagent_feedback": result.multimodal_feedback,
                "text": f"排版体检完成: 健康分 {result.health_report.score:.1f}/100 [几何:{result.health_report.quality_score.geometry:.0f}, 可读:{result.health_report.quality_score.readability:.0f}, 对比:{result.health_report.quality_score.contrast:.0f}, 平衡:{result.health_report.quality_score.balance:.0f}, 美观:{result.health_report.quality_score.aesthetics:.0f}]"
            })
            await cls._safe_emit(on_event, {
                "type": "vision_critique_completed",
                "score": result.health_report.score,
                "quality_score": result.health_report.quality_score.to_dict(),
                "defects_count": len(result.health_report.defects),
                "summary": result.critique_summary,
                "needs_auto_correction": result.needs_auto_correction
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
            logger.debug(f"Subagent event emission ignored: {e}")
