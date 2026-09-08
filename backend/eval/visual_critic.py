"""Visual Critic & Auto-Correction Engine.

Combines rule-based geometric evaluation with multimodal vision analysis to produce
comprehensive visual critiques and executable auto-remediation tool plans.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from ..ir.models import SlideIR, PresentationIR
from .layout_diff import LayoutDiffEngine, LayoutHealthReport, LayoutDefect

logger = logging.getLogger(__name__)


@dataclass
class VisualReviewResult:
    """Consolidated outcome of the visual critique loop."""
    slide_id: str
    health_report: LayoutHealthReport
    multimodal_feedback: Optional[str] = None
    proposed_actions: List[Dict[str, Any]] = field(default_factory=list)
    needs_auto_correction: bool = False

    @property
    def critique_summary(self) -> str:
        parts = [self.health_report.summary()]
        if self.multimodal_feedback:
            parts.append(f"审美多模态建议: {self.multimodal_feedback}")
        if self.proposed_actions:
            parts.append(f"已生成 {len(self.proposed_actions)} 项自动优化修复策略。")
        return " \n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "score": self.health_report.score,
            "has_critical_defects": self.health_report.has_critical_defects,
            "defects_count": len(self.health_report.defects),
            "critique_summary": self.critique_summary,
            "health_report": self.health_report.to_dict(),
            "multimodal_feedback": self.multimodal_feedback,
            "proposed_actions": self.proposed_actions,
            "needs_auto_correction": self.needs_auto_correction
        }


class VisualCritic:
    """Inspects slide layouts and generates corrective tool actions."""

    # Score threshold below which corrective intervention is recommended
    CORRECTION_SCORE_THRESHOLD = 80.0

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

        # 2. Determine if auto-correction is required
        needs_correction = (
            health_report.has_critical_defects or
            health_report.score < cls.CORRECTION_SCORE_THRESHOLD
        )

        # 3. Formulate proposed repair operations
        proposed_actions = cls.plan_remediations(slide, health_report)

        # 4. Optional Multimodal Vision Model critique
        multimodal_feedback = None
        if include_multimodal and llm_client:
            try:
                from ..agent.vision import VisionEngine
                prompt = (
                    f"请分析当前 PPT 幻灯片的构图、层级与设计质感。"
                    f"几何检测发现健康得分: {health_report.score:.1f}/100。"
                )
                if health_report.defects:
                    prompt += f" 检测到缺陷: {'; '.join(d.description for d in health_report.defects[:3])}。"
                prompt += " 请提供一到两句专业排版优化指导。"

                multimodal_feedback = await VisionEngine.review_slide_visually(
                    slide=slide,
                    client=llm_client,
                    prompt=prompt
                )
            except Exception as e:
                logger.warning(f"Multimodal vision critique failed: {e}")
                multimodal_feedback = None

        return VisualReviewResult(
            slide_id=slide.id,
            health_report=health_report,
            multimodal_feedback=multimodal_feedback,
            proposed_actions=proposed_actions,
            needs_auto_correction=needs_correction
        )

    @classmethod
    def plan_remediations(
        cls,
        slide: SlideIR,
        health_report: LayoutHealthReport
    ) -> List[Dict[str, Any]]:
        """Translates layout defects into concrete tool call invocations."""
        actions: List[Dict[str, Any]] = []
        handled_elements = set()

        for defect in health_report.defects:
            fix = defect.suggested_fix
            if not fix:
                continue

            action_type = fix.get("action")

            # Remediate Viewport Clipping
            if defect.defect_type == "viewport_clipping" and action_type == "update_element":
                eid = fix.get("element_id")
                if eid and eid not in handled_elements:
                    actions.append({
                        "tool": "update_element",
                        "arguments": {
                            "slide_id": slide.id,
                            "element_id": eid,
                            "x": fix.get("x"),
                            "y": fix.get("y"),
                            "width": fix.get("width"),
                            "height": fix.get("height")
                        },
                        "reason": f"修复视口裁剪溢出 ({defect.description})"
                    })
                    handled_elements.add(eid)

            # Remediate Collision & Overlap
            elif defect.defect_type == "collision_overlap":
                # Check if multiple shape cards are overlapping
                cards = [
                    e for e in slide.elements
                    if e.id in defect.element_ids and e.width >= 100.0
                ]
                if len(cards) >= 2:
                    # Trigger layout optimization for the cards
                    actions.append({
                        "tool": "optimize_layout",
                        "arguments": {
                            "slide_id": slide.id,
                            "layout_mode": "horizontal_cards",
                            "start_y": min(c.y for c in cards),
                            "gap": 30.0
                        },
                        "reason": f"规整图元异常重叠 ({defect.description})"
                    })
                elif action_type == "adjust_spacing":
                    eid_b = fix.get("element_id_b")
                    suggested_x = fix.get("suggested_b_x")
                    if eid_b and suggested_x is not None and eid_b not in handled_elements:
                        actions.append({
                            "tool": "update_element",
                            "arguments": {
                                "slide_id": slide.id,
                                "element_id": eid_b,
                                "x": suggested_x
                            },
                            "reason": f"平移分离重叠图元 ({defect.description})"
                        })
                        handled_elements.add(eid_b)

            # Remediate Low Contrast
            elif defect.defect_type == "low_contrast" and action_type == "update_font_color":
                eid = fix.get("element_id")
                font_color = fix.get("font_color", "#FFFFFF")
                if eid and eid not in handled_elements:
                    actions.append({
                        "tool": "format_text",
                        "arguments": {
                            "slide_id": slide.id,
                            "element_id": eid,
                            "font_color": font_color
                        },
                        "reason": f"提升文本 WCAG 对比度至清晰可读 ({defect.description})"
                    })
                    handled_elements.add(eid)

            # Remediate Text Overflow
            elif defect.defect_type == "text_overflow" and action_type == "resize_or_reformat":
                eid = fix.get("element_id")
                suggested_h = fix.get("suggested_height")
                suggested_font_sz = fix.get("suggested_font_size")
                if eid and eid not in handled_elements:
                    args = {"slide_id": slide.id, "element_id": eid}
                    if suggested_h:
                        args["height"] = suggested_h
                    if suggested_font_sz:
                        args["font_size"] = suggested_font_sz

                    actions.append({
                        "tool": "update_element",
                        "arguments": args,
                        "reason": f"扩充容器高度以容纳溢出文字 ({defect.description})"
                    })
                    handled_elements.add(eid)

        return actions
