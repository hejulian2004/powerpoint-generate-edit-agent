"""Visual Critic & Evaluation System.

Performs domain-level layout inspection, multimodal aesthetic critique,
and produces tool-decoupled remediation plans.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from ..ir.models import SlideIR, PresentationIR
from .layout_diff import LayoutDiffEngine, LayoutHealthReport, LayoutDefect
from .remediation import (
    FixAction,
    FixActionType,
    DefectCategory,
    RemediationPlan
)

logger = logging.getLogger(__name__)


@dataclass
class VisualReviewResult:
    """Consolidated outcome of the visual critique loop."""
    slide_id: str
    health_report: LayoutHealthReport
    remediation_plan: RemediationPlan
    multimodal_feedback: Optional[str] = None
    vision_status: Dict[str, Any] = field(default_factory=dict)
    needs_auto_correction: bool = False
    snapshot_uri: Optional[str] = None

    @property
    def proposed_actions(self) -> List[Dict[str, Any]]:
        """Backward-compatibility accessor returning dict form of actions."""
        return [a.to_dict() for a in self.remediation_plan.actions]

    @property
    def critique_summary(self) -> str:
        parts = [self.health_report.summary()]
        if self.multimodal_feedback:
            parts.append(f"多模态审美建议: {self.multimodal_feedback}")
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
            "snapshot_uri": self.snapshot_uri
        }


class VisualCritic:
    """Inspects slide layouts and generates abstract remediation plans decoupled from agent tools."""

    @classmethod
    async def review_slide(
        cls,
        slide: SlideIR,
        llm_client: Optional[Any] = None,
        include_multimodal: bool = True
    ) -> VisualReviewResult:
        """Conducts full diagnostic inspection on the slide."""
        # 1. Geometric & contrast rule-based analysis
        health_report = LayoutDiffEngine.evaluate_slide(slide)

        # 2. Formulate tool-agnostic remediation plan
        remediation_plan = cls.plan_remediations(slide, health_report)

        # 3. Policy: ONLY critical defects with confidence >= 0.9 (viewport clipping, severe collisions, text overflows)
        # trigger auto-correction in the background loop. Aesthetic / structural styling is never forced.
        needs_correction = len(remediation_plan.auto_executable_actions) > 0

        # 4. Multimodal Vision Model critique with clear fallback state reporting
        from .renderer_snapshot import SlideSnapshotRenderer, RendererMode
        meta = SlideSnapshotRenderer.get_render_metadata(slide, mode=RendererMode.DETERMINISTIC)

        multimodal_feedback = None
        vision_status: Dict[str, Any] = {
            "vision_available": False,
            "mode": meta.quality,
            "renderer": meta.renderer,
            "capability": meta.capability.to_dict(),
            "fallback": None,
            "message": "未配置或未启用 Vision 模型客户端，采用纯几何与对比度定量评测"
        }

        has_vision_api = bool(llm_client and getattr(llm_client, "api_key", None))
        if include_multimodal and has_vision_api:
            try:
                from ..agent.vision import VisionEngine
                prompt = (
                    f"请分析当前 PPT 幻灯片的构图、层级与设计质感。"
                    f"几何检测发现健康得分: {health_report.score:.1f}/100。"
                )
                if health_report.defects:
                    prompt += f" 检测到缺陷: {'; '.join(d.description for d in health_report.defects[:3])}。"
                if meta.renderer == "pillow" or meta.quality == "geometry_only":
                    prompt += " 当前截图可能缺少字体和特效信息。请优先依据element manifest判断结构。"
                prompt += " 请提供一到两句专业排版优化指导。"

                multimodal_feedback = await VisionEngine.review_slide_visually(
                    slide=slide,
                    client=llm_client,
                    prompt=prompt
                )
                vision_status = {
                    "vision_available": True,
                    "mode": "multimodal",
                    "renderer": meta.renderer,
                    "capability": meta.capability.to_dict(),
                    "fallback": None,
                    "message": "Vision 多模态模型评审完成"
                }
            except Exception as e:
                logger.warning(f"Multimodal vision critique failed, falling back: {e}")
                multimodal_feedback = None
                vision_status = {
                    "vision_available": False,
                    "mode": "geometry_only",
                    "renderer": meta.renderer,
                    "capability": meta.capability.to_dict(),
                    "fallback": "geometry_only",
                    "message": f"Vision 模型调用异常 ({str(e)})，自动回退到几何与对比度规则评测"
                }

        # 5. Generate high-precision raster snapshot URI
        from .renderer_snapshot import SlideSnapshotRenderer
        try:
            snapshot_uri = SlideSnapshotRenderer.render_data_uri(slide)
        except Exception as e:
            logger.debug(f"Snapshot URI generation failed: {e}")
            snapshot_uri = None

        return VisualReviewResult(
            slide_id=slide.id,
            health_report=health_report,
            remediation_plan=remediation_plan,
            multimodal_feedback=multimodal_feedback,
            vision_status=vision_status,
            needs_auto_correction=needs_correction,
            snapshot_uri=snapshot_uri
        )

    @classmethod
    def plan_remediations(
        cls,
        slide: SlideIR,
        health_report: LayoutHealthReport
    ) -> RemediationPlan:
        """Translates layout defects into tool-agnostic semantic FixAction operations."""
        actions: List[FixAction] = []
        handled_elements = set()

        for defect in health_report.defects:
            fix = defect.suggested_fix
            if not fix:
                continue

            action_type_str = fix.get("action")

            # 1. Text Overflow (CRITICAL: container/font sizes must resolve first)
            if defect.defect_type == "text_overflow":
                eid = fix.get("element_id")
                suggested_h = fix.get("suggested_height")
                suggested_font_sz = fix.get("suggested_font_size")
                if eid and eid not in handled_elements:
                    actions.append(FixAction(
                        action_type=FixActionType.RESIZE_CONTAINER,
                        category=DefectCategory.CRITICAL,
                        target_ids=[eid],
                        parameters={
                            "element_id": eid,
                            "height": suggested_h,
                            "font_size": suggested_font_sz
                        },
                        reason=f"扩展容器避免文字裁剪溢出: {defect.description}",
                        priority=10,
                        confidence=0.96,
                        source="geometry_rule"
                    ))
                    handled_elements.add(eid)

            # 2. Viewport Clipping (CRITICAL: pull back into view boundaries)
            elif defect.defect_type == "viewport_clipping":
                eid = fix.get("element_id")
                if eid and eid not in handled_elements:
                    actions.append(FixAction(
                        action_type=FixActionType.CLAMP_VIEWPORT,
                        category=DefectCategory.CRITICAL,
                        target_ids=[eid],
                        parameters={
                            "element_id": eid,
                            "x": fix.get("x"),
                            "y": fix.get("y"),
                            "width": fix.get("width"),
                            "height": fix.get("height")
                        },
                        reason=f"修正视口边缘溢出: {defect.description}",
                        priority=9,
                        confidence=0.98,
                        source="geometry_rule"
                    ))
                    handled_elements.add(eid)

            # 3. Collision & Overlap (CRITICAL: separate cards or layout mode)
            elif defect.defect_type == "collision_overlap":
                cards = [
                    e for e in slide.elements
                    if e.id in defect.element_ids and e.width >= 100.0
                ]
                if len(cards) >= 2:
                    actions.append(FixAction(
                        action_type=FixActionType.ARRANGE_CARDS,
                        category=DefectCategory.CRITICAL,
                        target_ids=[c.id for c in cards],
                        parameters={
                            "element_ids": [c.id for c in cards],
                            "layout_mode": "horizontal_cards",
                            "start_y": min(c.y for c in cards),
                            "gap": 30.0
                        },
                        reason=f"规整多卡片相互重叠: {defect.description}",
                        priority=8,
                        confidence=0.92,
                        source="geometry_rule"
                    ))
                elif action_type_str == "adjust_spacing":
                    eid_b = fix.get("element_id_b")
                    suggested_x = fix.get("suggested_b_x")
                    if eid_b and suggested_x is not None and eid_b not in handled_elements:
                        actions.append(FixAction(
                            action_type=FixActionType.SEPARATE_ELEMENTS,
                            category=DefectCategory.CRITICAL,
                            target_ids=[eid_b],
                            parameters={
                                "element_id": eid_b,
                                "x": suggested_x
                            },
                            reason=f"平移分离异常重叠图元: {defect.description}",
                            priority=8,
                            confidence=0.92,
                            source="geometry_rule"
                        ))
                        handled_elements.add(eid_b)

            # 4. Low Contrast (CRITICAL or STRUCTURAL based on severity)
            elif defect.defect_type == "low_contrast":
                eid = fix.get("element_id")
                font_color = fix.get("font_color", "#FFFFFF")
                if eid and eid not in handled_elements:
                    cat = DefectCategory.CRITICAL if defect.severity == "critical" else DefectCategory.STRUCTURAL
                    conf = 0.95 if cat == DefectCategory.CRITICAL else 0.75
                    prio = 7 if cat == DefectCategory.CRITICAL else 4
                    actions.append(FixAction(
                        action_type=FixActionType.ENHANCE_CONTRAST,
                        category=cat,
                        target_ids=[eid],
                        parameters={
                            "element_id": eid,
                            "font_color": font_color
                        },
                        reason=f"提升文字 WCAG 可读对比度: {defect.description}",
                        priority=prio,
                        confidence=conf,
                        source="geometry_rule"
                    ))
                    handled_elements.add(eid)

            # 5. Misalignment (STRUCTURAL - Advisory only)
            elif defect.defect_type == "misaligned":
                align_targets = defect.element_ids
                if align_targets and not any(tid in handled_elements for tid in align_targets):
                    actions.append(FixAction(
                        action_type=FixActionType.ALIGN_ELEMENTS,
                        category=DefectCategory.STRUCTURAL,
                        target_ids=align_targets,
                        parameters={
                            "element_ids": align_targets,
                            "alignment": fix.get("align_type", "top")
                        },
                        reason=f"对齐规整几何卡片: {defect.description}",
                        priority=2,
                        confidence=0.65,
                        source="geometry_rule"
                    ))

        # Sort actions by priority descending
        actions.sort(key=lambda a: a.priority, reverse=True)
        has_critical = any(a.category == DefectCategory.CRITICAL for a in actions)

        summary_msg = f"共规划 {len(actions)} 项排版治理动作（包含 {sum(1 for a in actions if a.category == DefectCategory.CRITICAL)} 项严重错误修复）"
        return RemediationPlan(actions=actions, has_critical=has_critical, summary=summary_msg)
