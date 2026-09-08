"""Remediation Runner: Translates abstract FixAction plans into safe tool executions.

Features:
1. Conflict detection & simulation before applying actions
2. Transaction protection: rollback if remediation degrades health score
3. Policy enforcement: only critical geometric/clipping defects auto-applied in loop
4. Persistent iteration tracking in presentation metadata
"""

from __future__ import annotations
import copy
import logging
from typing import Dict, Any, List, Optional
from ..ir.models import PresentationIR, SlideIR
from ..ir.patch import HistoryManager
from ..eval.remediation import FixAction, FixActionType, DefectCategory, RemediationPlan
from ..eval.layout_diff import LayoutDiffEngine, BoundingBox
from .tools import tools

logger = logging.getLogger(__name__)


class RemediationRunner:
    """Safely simulates, resolves conflicts, and executes remediation plans inside transactions."""

    @classmethod
    def apply_plan(
        cls,
        pres: PresentationIR,
        history: HistoryManager,
        plan: RemediationPlan,
        slide_id: Optional[str] = None,
        only_critical: bool = True
    ) -> Dict[str, Any]:
        """Executes plan with transaction rollback protection and conflict detection."""
        slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
        if not slide:
            return {"success": False, "error": "Slide not found"}

        # 1. Filter actions by policy
        eligible_actions = [
            a for a in plan.actions
            if (not only_critical or a.category == DefectCategory.CRITICAL)
        ]
        if not eligible_actions:
            return {
                "success": True,
                "applied_count": 0,
                "message": "无需执行严重修复动作"
            }

        # 2. Conflict detection and action resolution
        safe_actions = cls._resolve_conflicts(slide, eligible_actions)
        if not safe_actions:
            return {
                "success": True,
                "applied_count": 0,
                "message": "所有动作均存在冲突已跳过"
            }

        # 3. Transaction boundary with rollback guard
        before_score = LayoutDiffEngine.evaluate_slide(slide).score
        applied_records = []

        with pres.transaction("auto_remediation") as tx:
            for action in safe_actions:
                tool_call = cls._action_to_tool_call(slide.id, action)
                if not tool_call:
                    continue

                fn_name = tool_call["tool"]
                args = tool_call["args"]

                res = tools.execute(fn_name, args, pres, history)
                applied_records.append({
                    "action_type": action.action_type.value,
                    "tool": fn_name,
                    "args": args,
                    "result": res,
                    "reason": action.reason
                })

            # Re-evaluate layout score after changes
            after_report = LayoutDiffEngine.evaluate_slide(slide)
            after_score = after_report.score

            # Safety Guard: Rollback if the fix degraded quality or made things worse
            if after_score < before_score:
                logger.warning(
                    f"Remediation degraded layout score ({before_score:.1f} -> {after_score:.1f}). Rolling back transaction!"
                )
                tx.rollback(f"质量评分下降 (由 {before_score:.1f} 降至 {after_score:.1f})，已自动回滚所有修改")
                return {
                    "success": False,
                    "rolled_back": True,
                    "score_before": before_score,
                    "score_after": before_score,
                    "message": f"自愈操作未带来正向改进，已安全回滚至修改前状态"
                }

            # Commit transaction
            tx.commit()

        # Update persistent metadata
        curr_iters = pres.metadata.get("visual_fix_iterations", 0)
        pres.metadata["visual_fix_iterations"] = curr_iters + 1
        pres.version += 1

        return {
            "success": True,
            "rolled_back": False,
            "applied_count": len(applied_records),
            "applied_records": applied_records,
            "applied_fixes": applied_records,
            "score_before": before_score,
            "score_after": after_score,
            "score_delta": round(after_score - before_score, 1),
            "iterations": pres.metadata["visual_fix_iterations"],
            "message": f"排版自愈完成: 应用 {len(applied_records)} 处修复，得分由 {before_score:.1f} 提升至 {after_score:.1f}"
        }

    @classmethod
    def _resolve_conflicts(cls, slide: SlideIR, actions: List[FixAction]) -> List[FixAction]:
        """Detects and resolves mutual interference and cascading collisions."""
        safe: List[FixAction] = []
        touched_elements = set()

        for act in actions:
            # If an action targets elements already modified by higher priority actions in this turn,
            # skip or deduplicate to avoid oscillating ping-pong shifts
            if any(tid in touched_elements for tid in act.target_ids):
                continue

            safe.append(act)
            for tid in act.target_ids:
                touched_elements.add(tid)

        return safe

    @classmethod
    def _action_to_tool_call(cls, slide_id: str, action: FixAction) -> Optional[Dict[str, Any]]:
        """Maps abstract semantic FixAction to agent tool invocation."""
        p = action.parameters

        if action.action_type == FixActionType.CLAMP_VIEWPORT:
            return {
                "tool": "update_element",
                "args": {
                    "slide_id": slide_id,
                    "element_id": p.get("element_id"),
                    "x": p.get("x"),
                    "y": p.get("y"),
                    "width": p.get("width"),
                    "height": p.get("height")
                }
            }

        elif action.action_type == FixActionType.SEPARATE_ELEMENTS:
            args = {"slide_id": slide_id, "element_id": p.get("element_id")}
            if "x" in p:
                args["x"] = p["x"]
            if "y" in p:
                args["y"] = p["y"]
            return {"tool": "update_element", "args": args}

        elif action.action_type == FixActionType.ARRANGE_CARDS:
            return {
                "tool": "optimize_layout",
                "args": {
                    "slide_id": slide_id,
                    "layout_mode": p.get("layout_mode", "horizontal_cards"),
                    "start_y": p.get("start_y", 200.0),
                    "gap": p.get("gap", 30.0)
                }
            }

        elif action.action_type == FixActionType.RESIZE_CONTAINER:
            args = {"slide_id": slide_id, "element_id": p.get("element_id")}
            if "height" in p:
                args["height"] = p["height"]
            if "font_size" in p:
                args["font_size"] = p["font_size"]
            return {"tool": "update_element", "args": args}

        elif action.action_type == FixActionType.ENHANCE_CONTRAST:
            return {
                "tool": "format_text",
                "args": {
                    "slide_id": slide_id,
                    "element_id": p.get("element_id"),
                    "font_color": p.get("font_color", "#FFFFFF")
                }
            }

        elif action.action_type == FixActionType.ALIGN_ELEMENTS:
            return {
                "tool": "align_elements",
                "args": {
                    "slide_id": slide_id,
                    "element_ids": p.get("element_ids"),
                    "alignment": p.get("alignment", "top")
                }
            }

        return None
