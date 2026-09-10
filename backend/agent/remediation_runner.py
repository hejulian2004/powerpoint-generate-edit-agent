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
from ..eval.remediation import (
    FixAction, FixActionType, DefectCategory, RemediationPlan, FidelityRemediationGenerator
)
from ..eval.layout_diff import LayoutDiffEngine, BoundingBox
from ..eval.fidelity import FidelityEvaluator, FidelityRegressionGuard
from .mutation_gateway import MutationGateway

logger = logging.getLogger(__name__)


def _emit_remediation_event(on_event: Optional[Any], ev: Dict[str, Any]):
    """Safely emits visual_remediation telemetry event to sync or async listener."""
    if not on_event:
        return
    import asyncio
    import inspect
    try:
        if inspect.iscoroutinefunction(on_event):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(on_event(ev))
            except RuntimeError:
                asyncio.run(on_event(ev))
        else:
            on_event(ev)
    except Exception as e:
        logger.debug(f"Telemetry event emission ignored: {e}")


class RemediationRunner:
    """Safely simulates, resolves conflicts, and executes remediation plans inside transactions."""

    @classmethod
    def apply_plan(
        cls,
        pres: PresentationIR,
        history: HistoryManager,
        plan: RemediationPlan,
        slide_id: Optional[str] = None,
        only_critical: bool = True,
        max_iterations: Optional[int] = None,
        on_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Executes plan with transaction rollback protection and conflict detection."""
        slide = pres.get_slide(slide_id) if slide_id else pres.get_active_slide()
        if not slide:
            return {"success": False, "error": "Slide not found"}

        # 0. Check configurable visual iteration limit
        from ..config import settings
        curr_iters = pres.metadata.get("visual_fix_iterations", 0)
        max_allowed = max_iterations if max_iterations is not None else getattr(settings, "max_visual_iterations", 3)
        if curr_iters >= max_allowed:
            return {
                "success": False,
                "error": f"已达到最大自愈迭代次数限制 ({curr_iters}/{max_allowed})",
                "iterations": curr_iters,
                "max_iterations": max_allowed
            }

        # 1. Filter actions by policy (gated on confidence >= 0.9 and CRITICAL severity)
        if only_critical:
            eligible_actions = [a for a in plan.actions if a.is_auto_applicable]
        else:
            eligible_actions = list(plan.actions)

        if not eligible_actions:
            return {
                "success": True,
                "applied_count": 0,
                "message": "无需执行严重修复动作"
            }

        # 2. Priority & Confidence sorting: container/text sizing (prio 10) precedes
        # viewport clamping (prio 9), collision separation (prio 8), contrast (prio 7), alignment (prio 2)
        eligible_actions.sort(key=lambda a: (a.priority, a.confidence), reverse=True)

        # 3. Conflict detection and action resolution
        safe_actions = cls._resolve_conflicts(slide, eligible_actions)
        if not safe_actions:
            return {
                "success": True,
                "applied_count": 0,
                "message": "所有动作均存在冲突已跳过"
            }

        # 3. Transaction boundary with rollback guard (preserves IR state and history depth)
        before_report = LayoutDiffEngine.evaluate_slide(slide)
        before_score = before_report.score
        before_qs = before_report.quality_score
        applied_records = []

        with pres.transaction("auto_remediation", history=history) as tx:
            for action in safe_actions:
                tool_call = cls._action_to_tool_call(slide.id, action)
                if not tool_call:
                    continue

                fn_name = tool_call["tool"]
                args = tool_call["args"]

                _emit_remediation_event(on_event, {
                    "type": "visual_remediation",
                    "phase": "fixing",
                    "status": "fixing",
                    "slide_id": slide.id,
                    "action": action.to_dict(),
                    "text": f"正在应用修复 ({action.action_type.value}): {action.reason}"
                })

                res = MutationGateway.execute_one_sync(
                    fn_name, args, pres, history, on_event=on_event, source="remediation"
                )
                applied_records.append({
                    "action_type": action.action_type.value,
                    "tool": fn_name,
                    "args": args,
                    "result": res,
                    "reason": action.reason
                })

            # Re-evaluate multidimensional layout score after changes
            after_report = LayoutDiffEngine.evaluate_slide(slide)
            after_score = after_report.score
            after_qs = after_report.quality_score

            # Safety Guard: Rollback if composite quality score degrades
            if after_score < before_score:
                logger.warning(
                    f"Remediation degraded layout score ({before_score:.1f} -> {after_score:.1f}) "
                    f"[G: {before_qs.geometry:.1f}->{after_qs.geometry:.1f}, "
                    f"R: {before_qs.readability:.1f}->{after_qs.readability:.1f}, "
                    f"C: {before_qs.contrast:.1f}->{after_qs.contrast:.1f}, "
                    f"B: {before_qs.balance:.1f}->{after_qs.balance:.1f}]. Rolling back transaction!"
                )
                tx.rollback(
                    f"综合质量评分下降 (由 {before_score:.1f} 降至 {after_score:.1f} "
                    f"[G:{after_qs.geometry:.0f}, R:{after_qs.readability:.0f}, "
                    f"C:{after_qs.contrast:.0f}, B:{after_qs.balance:.0f}])，已自动回滚所有修改"
                )
                _emit_remediation_event(on_event, {
                    "type": "visual_remediation",
                    "phase": "rolled_back",
                    "status": "rolled_back",
                    "slide_id": slide.id,
                    "score_before": before_score,
                    "score_after": before_score,
                    "quality_score_before": before_qs.to_dict(),
                    "quality_score_after": before_qs.to_dict(),
                    "text": f"排版自愈未达预期 (得分 {before_score:.1f} -> {after_score:.1f})，已安全回滚"
                })
                return {
                    "success": False,
                    "rolled_back": True,
                    "score_before": before_score,
                    "score_after": before_score,
                    "quality_score_before": before_qs.to_dict(),
                    "quality_score_after": before_qs.to_dict(),
                    "message": f"自愈操作未带来正向改进，已安全回滚至修改前状态"
                }

            # Commit transaction
            tx.commit()

        # Update persistent metadata
        curr_iters = pres.metadata.get("visual_fix_iterations", 0)
        pres.metadata["visual_fix_iterations"] = curr_iters + 1
        pres.version += 1

        _emit_remediation_event(on_event, {
            "type": "visual_remediation",
            "phase": "committed",
            "status": "committed",
            "slide_id": slide.id,
            "iteration": pres.metadata["visual_fix_iterations"],
            "score_before": before_score,
            "score_after": after_score,
            "delta": round(after_score - before_score, 1),
            "quality_score_before": before_qs.to_dict(),
            "quality_score_after": after_qs.to_dict(),
            "applied_count": len(applied_records),
            "text": f"排版自愈事务提交完成，质量分由 {before_score:.1f} 提升至 {after_score:.1f}"
        })

        return {
            "success": True,
            "rolled_back": False,
            "applied_count": len(applied_records),
            "applied_records": applied_records,
            "applied_fixes": applied_records,
            "score_before": before_score,
            "score_after": after_score,
            "score_delta": round(after_score - before_score, 1),
            "quality_score_before": before_qs.to_dict(),
            "quality_score_after": after_qs.to_dict(),
            "iterations": pres.metadata["visual_fix_iterations"],
            "message": f"排版自愈完成: 应用 {len(applied_records)} 处修复，得分由 {before_score:.1f} 提升至 {after_score:.1f}"
        }

    @classmethod
    def _resolve_conflicts(cls, slide: SlideIR, actions: List[FixAction]) -> List[FixAction]:
        """Detects and resolves mutual interference and cascading collisions."""
        # Ensure strict priority and confidence ordering so high priority fixes claim targets first
        sorted_actions = sorted(
            actions,
            key=lambda a: (getattr(a, "priority", 1), getattr(a, "confidence", 1.0)),
            reverse=True
        )
        safe: List[FixAction] = []
        touched_elements = set()

        for act in sorted_actions:
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

        elif action.action_type in [FixActionType.ALIGN_ELEMENTS, FixActionType.FIX_ALIGNMENT]:
            return {
                "tool": "align_elements",
                "args": {
                    "slide_id": slide_id,
                    "element_ids": p.get("element_ids"),
                    "alignment": p.get("alignment", "top")
                }
            }

        elif action.action_type == FixActionType.FIX_GEOMETRY:
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

        elif action.action_type == FixActionType.FIX_FONT:
            args = {"slide_id": slide_id, "element_id": p.get("element_id")}
            if "font_family" in p:
                args["font_family"] = p["font_family"]
            if "font_size" in p:
                args["font_size"] = p["font_size"]
            return {"tool": "format_text", "args": args}

        elif action.action_type == FixActionType.FIX_COLOR:
            args = {"slide_id": slide_id, "element_id": p.get("element_id")}
            if "fill_color" in p:
                args["fill_color"] = p["fill_color"]
            if "font_color" in p:
                args["font_color"] = p["font_color"]
            if "border_color" in p:
                args["border_color"] = p["border_color"]
            return {"tool": "update_element", "args": args}

        elif action.action_type == FixActionType.FIX_THEME_REF:
            args = {"slide_id": slide_id, "element_id": p.get("element_id")}
            if "resolved_color" in p:
                args["fill_color"] = p["resolved_color"]
            elif "fill_color" in p:
                args["fill_color"] = p["fill_color"]
            return {"tool": "update_element", "args": args}

        return None

    @classmethod
    def apply_fidelity_repair(
        cls,
        pres: PresentationIR,
        history: HistoryManager,
        baseline_slide: SlideIR,
        current_slide_id: Optional[str] = None,
        on_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Evaluates fidelity against baseline, generates repairs, and applies inside atomic transaction."""
        curr_slide = pres.get_slide(current_slide_id) if current_slide_id else pres.get_active_slide()
        if not curr_slide:
            return {"success": False, "error": "Slide not found"}

        before_score = FidelityEvaluator.evaluate_slides(baseline_slide, curr_slide)
        if before_score.total >= 95.0:
            return {
                "success": True,
                "repaired": False,
                "score_before": before_score.total,
                "score_after": before_score.total,
                "message": "Slide fidelity already satisfies threshold (>=95%)"
            }

        plan = FidelityRemediationGenerator.generate_plan(baseline_slide, curr_slide)
        if not plan.actions:
            return {
                "success": True,
                "repaired": False,
                "score_before": before_score.total,
                "score_after": before_score.total,
                "message": "No actionable fidelity defects detected"
            }

        applied_records = []
        with pres.transaction("fidelity_repair", history=history) as tx:
            for action in plan.actions:
                tool_call = cls._action_to_tool_call(curr_slide.id, action)
                if not tool_call:
                    continue
                res = MutationGateway.execute_one_sync(
                    tool_call["tool"], tool_call["args"], pres, history, on_event=on_event, source="remediation"
                )
                applied_records.append({
                    "action_type": action.action_type.value,
                    "result": res,
                    "reason": action.reason
                })

            after_score = FidelityEvaluator.evaluate_slides(baseline_slide, curr_slide)

            # PR6.1 Regression guard: accept only if the composite total does not drop AND
            # no sub-dimension regresses beyond its per-metric limit (geometry 5 / text,
            # style, visual 10). This prevents a repair that raises one sub-score (e.g.
            # font) while regressing another (e.g. geometry) from being committed.
            guard = FidelityRegressionGuard()
            accepted, reasons = guard.accepts(before_score, after_score)
            if not accepted:
                logger.warning(
                    "Fidelity repair rejected by FidelityRegressionGuard for slide %s: %s",
                    curr_slide.id, "; ".join(reasons)
                )
                tx.rollback(f"Fidelity repair rejected: {'; '.join(reasons)}")
                return {
                    "success": False,
                    "rolled_back": True,
                    "score_before": before_score.total,
                    "score_after": after_score.total,
                    "policy_reasons": reasons,
                    "message": "Fidelity repairs failed the per-dimension regression guard and were rolled back"
                }

            tx.commit()

        return {
            "success": True,
            "rolled_back": False,
            "score_before": before_score.total,
            "score_after": after_score.total,
            "applied_count": len(applied_records),
            "applied_records": applied_records
        }
