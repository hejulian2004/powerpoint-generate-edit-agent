"""Visual Layout Diff and Geometry Evaluation Engine.

Provides deep geometric inspection, collision detection, viewport boundary clipping,
text overflow estimation, WCAG 2.1 color contrast analysis, and automated remediation hints.
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Union
from ..ir.models import (
    SlideIR,
    ElementIR,
    ShapeElementIR,
    TextElementIR,
    ConnectorElementIR,
    ImageElementIR,
    GroupElementIR,
    TableElementIR
)


# =====================================================================
# 1. Geometric Primitive: BoundingBox
# =====================================================================

@dataclass
class BoundingBox:
    """Axis-aligned bounding box on the 1280x720 canvas."""
    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + (self.width / 2.0)

    @property
    def center_y(self) -> float:
        return self.y + (self.height / 2.0)

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def intersects(self, other: BoundingBox) -> bool:
        """Returns True if this box intersects with another box."""
        return not (
            self.right <= other.left or
            self.left >= other.right or
            self.bottom <= other.top or
            self.top >= other.bottom
        )

    def intersection(self, other: BoundingBox) -> Optional[BoundingBox]:
        """Calculates the intersection box if overlapping."""
        if not self.intersects(other):
            return None
        ix1 = max(self.left, other.left)
        iy1 = max(self.top, other.top)
        ix2 = min(self.right, other.right)
        iy2 = min(self.bottom, other.bottom)
        return BoundingBox(x=ix1, y=iy1, width=max(0.0, ix2 - ix1), height=max(0.0, iy2 - iy1))

    def iou(self, other: BoundingBox) -> float:
        """Intersection over Union (IoU) metric (0.0 to 1.0)."""
        inter = self.intersection(other)
        if not inter:
            return 0.0
        inter_area = inter.area
        union_area = self.area + other.area - inter_area
        if union_area <= 0.0:
            return 0.0
        return inter_area / union_area

    def overlap_ratio_with(self, other: BoundingBox) -> float:
        """Calculates intersection area relative to THIS box's area."""
        inter = self.intersection(other)
        if not inter or self.area <= 0.0:
            return 0.0
        return inter.area / self.area

    def contains(self, other: BoundingBox, tolerance: float = 2.0) -> bool:
        """Checks if this box completely encloses the other box within tolerance."""
        return (
            self.left - tolerance <= other.left and
            self.top - tolerance <= other.top and
            self.right + tolerance >= other.right and
            self.bottom + tolerance >= other.bottom
        )

    @classmethod
    def from_element(cls, elem: ElementIR) -> BoundingBox:
        """Constructs BoundingBox from an ElementIR instance."""
        if isinstance(elem, ConnectorElementIR):
            min_x = min(elem.start_x, elem.end_x)
            min_y = min(elem.start_y, elem.end_y)
            w = max(abs(elem.end_x - elem.start_x), 1.0)
            h = max(abs(elem.end_y - elem.start_y), 1.0)
            return cls(x=min_x, y=min_y, width=w, height=h)
        return cls(x=elem.x, y=elem.y, width=elem.width, height=elem.height)


# =====================================================================
# 2. Color & WCAG 2.1 Accessibility
# =====================================================================

def parse_hex_color(hex_str: Optional[str], default: Tuple[int, int, int] = (0, 0, 0)) -> Tuple[int, int, int]:
    """Parses a 3 or 6 digit hex color string into an (R, G, B) tuple."""
    if not hex_str:
        return default
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join([c * 2 for c in cleaned])
    if len(cleaned) == 6:
        try:
            return (
                int(cleaned[0:2], 16),
                int(cleaned[2:4], 16),
                int(cleaned[4:6], 16)
            )
        except ValueError:
            return default
    return default


def calculate_relative_luminance(rgb: Tuple[int, int, int]) -> float:
    """Calculates relative luminance according to WCAG 2.1 formula."""
    r_s, g_s, b_s = [val / 255.0 for val in rgb]
    r_lin = r_s / 12.92 if r_s <= 0.03928 else math.pow((r_s + 0.055) / 1.055, 2.4)
    g_lin = g_s / 12.92 if g_s <= 0.03928 else math.pow((g_s + 0.055) / 1.055, 2.4)
    b_lin = b_s / 12.92 if b_s <= 0.03928 else math.pow((b_s + 0.055) / 1.055, 2.4)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def calculate_contrast_ratio(color1: Union[str, Tuple[int, int, int]], color2: Union[str, Tuple[int, int, int]]) -> float:
    """Calculates WCAG contrast ratio between two colors (range 1.0:1 to 21.0:1)."""
    rgb1 = parse_hex_color(color1) if isinstance(color1, str) else color1
    rgb2 = parse_hex_color(color2) if isinstance(color2, str) else color2

    l1 = calculate_relative_luminance(rgb1)
    l2 = calculate_relative_luminance(rgb2)

    lighter = max(l1, l2)
    darker = min(l1, l2)

    ratio = (lighter + 0.05) / (darker + 0.05)
    return round(ratio, 2)


# =====================================================================
# 3. Defect & Report Data Structures
# =====================================================================

@dataclass
class VisualQualityScore:
    """Multidimensional visual quality score evaluation.

    Weights:
    - geometry: 40% (viewport boundary, margin intrusion, collision & overlap)
    - readability: 25% (text overflow, container fitting, font size)
    - contrast: 15% (WCAG 2.1 contrast ratios)
    - balance: 20% (alignment consistency, distribution, spacing)
    """
    geometry: float = 100.0
    readability: float = 100.0
    contrast: float = 100.0
    balance: float = 100.0
    total: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "geometry": round(self.geometry, 1),
            "readability": round(self.readability, 1),
            "contrast": round(self.contrast, 1),
            "balance": round(self.balance, 1),
            "total": round(self.total, 1),
        }


@dataclass
class LayoutDefect:
    """Defect detected during visual inspection."""
    defect_type: str  # "collision_overlap" | "viewport_clipping" | "margin_intrusion" | "text_overflow" | "low_contrast" | "misaligned"
    severity: str     # "critical" | "warning" | "info"
    element_ids: List[str]
    description: str
    details: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "defect_type": self.defect_type,
            "severity": self.severity,
            "element_ids": self.element_ids,
            "description": self.description,
            "details": self.details,
            "suggested_fix": self.suggested_fix
        }


@dataclass
class LayoutHealthReport:
    """Consolidated layout quality and accessibility audit report."""
    slide_id: str
    score: float                         # 0.0 - 100.0 (composite total)
    quality_score: VisualQualityScore = field(default_factory=VisualQualityScore)
    defects: List[LayoutDefect] = field(default_factory=list)
    passed_checks: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_critical_defects(self) -> bool:
        return any(d.severity == "critical" for d in self.defects)

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.defects if d.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.defects if d.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for d in self.defects if d.severity == "info")

    def summary(self) -> str:
        if not self.defects:
            return f"页面排版极佳 (得分: {self.score:.1f}/100)，无明显重叠、溢出或对比度缺陷。"
        crit = f"{self.critical_count} 个严重缺陷" if self.critical_count > 0 else "无严重缺陷"
        warn = f"{self.warning_count} 个警告" if self.warning_count > 0 else ""
        counts = ", ".join(filter(bool, [crit, warn]))
        top_defects = "; ".join(d.description for d in self.defects[:3])
        return (
            f"页面健康分: {self.score:.1f}/100 [几何:{self.quality_score.geometry:.0f}, "
            f"可读:{self.quality_score.readability:.0f}, 对比:{self.quality_score.contrast:.0f}, "
            f"平衡:{self.quality_score.balance:.0f}] ({counts})。主要建议: {top_defects}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "score": round(self.score, 1),
            "quality_score": self.quality_score.to_dict(),
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "defects": [d.to_dict() for d in self.defects],
            "passed_checks": self.passed_checks,
            "stats": self.stats
        }


# =====================================================================
# 4. Layout Diff & Quality Evaluation Engine
# =====================================================================

class LayoutDiffEngine:
    """Core evaluation engine for analyzing slide geometry, contrast, and layout health."""

    DEFAULT_CANVAS_WIDTH = 1280.0
    DEFAULT_CANVAS_HEIGHT = 720.0
    SAFE_MARGIN_X = 32.0
    SAFE_MARGIN_Y = 32.0

    @classmethod
    def evaluate_slide(cls, slide: SlideIR) -> LayoutHealthReport:
        """Executes full diagnostic suite on a slide and returns a LayoutHealthReport."""
        defects: List[LayoutDefect] = []
        passed_checks: List[str] = []

        canvas_w = slide.width or cls.DEFAULT_CANVAS_WIDTH
        canvas_h = slide.height or cls.DEFAULT_CANVAS_HEIGHT

        # 1. Viewport Boundary & Clipping
        clipping_defects = cls._check_viewport_boundaries(slide, canvas_w, canvas_h)
        if clipping_defects:
            defects.extend(clipping_defects)
        else:
            passed_checks.append("viewport_bounds_safe")

        # 2. Collision and Accidental Overlap Detection
        overlap_defects = cls._check_element_overlaps(slide)
        if overlap_defects:
            defects.extend(overlap_defects)
        else:
            passed_checks.append("no_accidental_overlaps")

        # 3. Text Overflow Estimation
        overflow_defects = cls._check_text_overflows(slide)
        if overflow_defects:
            defects.extend(overflow_defects)
        else:
            passed_checks.append("text_fits_containers")

        # 4. WCAG Contrast Analysis
        contrast_defects = cls._check_color_contrast(slide)
        if contrast_defects:
            defects.extend(contrast_defects)
        else:
            passed_checks.append("accessible_contrast_ratios")

        # 5. Grid & Alignment Consistency
        align_defects = cls._check_alignment_consistency(slide)
        if align_defects:
            defects.extend(align_defects)
        else:
            passed_checks.append("clean_grid_alignment")

        # Multidimensional Quality Scoring (Geometry 40%, Readability 25%, Contrast 15%, Balance 20%)
        # 1. Geometry dimension (clipping & overlaps)
        geom_penalty = 0.0
        for d in clipping_defects:
            geom_penalty += 20.0 if d.severity == "critical" else 8.0
        for d in overlap_defects:
            geom_penalty += 20.0 if d.severity == "critical" else 8.0
        geometry_score = max(0.0, min(100.0, 100.0 - geom_penalty))

        # 2. Readability dimension (text overflows)
        read_penalty = 0.0
        for d in overflow_defects:
            read_penalty += 25.0 if d.severity == "critical" else 10.0
        readability_score = max(0.0, min(100.0, 100.0 - read_penalty))

        # 3. Contrast dimension (WCAG 2.1 color contrast)
        contrast_penalty = 0.0
        for d in contrast_defects:
            contrast_penalty += 30.0 if d.severity == "critical" else 15.0
        contrast_score = max(0.0, min(100.0, 100.0 - contrast_penalty))

        # 4. Balance dimension (grid alignment & distribution)
        balance_penalty = 0.0
        for d in align_defects:
            balance_penalty += 15.0 if d.severity == "warning" else 8.0
        balance_score = max(0.0, min(100.0, 100.0 - balance_penalty))

        # 5. Weighted composite total
        total_score = round(
            0.40 * geometry_score +
            0.25 * readability_score +
            0.15 * contrast_score +
            0.20 * balance_score,
            1
        )
        quality_score = VisualQualityScore(
            geometry=round(geometry_score, 1),
            readability=round(readability_score, 1),
            contrast=round(contrast_score, 1),
            balance=round(balance_score, 1),
            total=total_score
        )

        stats = {
            "total_elements": len(slide.elements),
            "shapes": sum(1 for e in slide.elements if isinstance(e, ShapeElementIR)),
            "texts": sum(1 for e in slide.elements if isinstance(e, TextElementIR)),
            "connectors": sum(1 for e in slide.elements if isinstance(e, ConnectorElementIR)),
            "groups": sum(1 for e in slide.elements if isinstance(e, GroupElementIR)),
            "images": sum(1 for e in slide.elements if isinstance(e, ImageElementIR)),
        }

        return LayoutHealthReport(
            slide_id=slide.id,
            score=total_score,
            quality_score=quality_score,
            defects=defects,
            passed_checks=passed_checks,
            stats=stats
        )

    # -----------------------------------------------------------------
    # Check 1: Viewport Boundary & Margin Intrusion
    # -----------------------------------------------------------------
    @classmethod
    def _check_viewport_boundaries(
        cls,
        slide: SlideIR,
        canvas_w: float,
        canvas_h: float
    ) -> List[LayoutDefect]:
        defects = []

        for elem in slide.elements:
            # Skip connectors for viewport bounds
            if isinstance(elem, ConnectorElementIR):
                continue

            # Check if this is a background element covering >= 90% of canvas
            is_full_bleed = (
                elem.width >= (canvas_w * 0.9) and
                elem.height >= (canvas_h * 0.9)
            )
            if is_full_bleed:
                continue

            box = BoundingBox.from_element(elem)

            # Hard clipping (extending beyond 0, 0, canvas_w, canvas_h)
            clipped_left = box.left < -2.0
            clipped_top = box.top < -2.0
            clipped_right = box.right > (canvas_w + 2.0)
            clipped_bottom = box.bottom > (canvas_h + 2.0)

            if clipped_left or clipped_top or clipped_right or clipped_bottom:
                clip_dirs = []
                if clipped_left: clip_dirs.append(f"左侧溢出 {abs(box.left):.1f}px")
                if clipped_top: clip_dirs.append(f"顶部溢出 {abs(box.top):.1f}px")
                if clipped_right: clip_dirs.append(f"右侧溢出 {(box.right - canvas_w):.1f}px")
                if clipped_bottom: clip_dirs.append(f"底部溢出 {(box.bottom - canvas_h):.1f}px")

                # Suggested fix: clamp coordinates into view
                new_x = max(cls.SAFE_MARGIN_X, min(box.x, canvas_w - box.width - cls.SAFE_MARGIN_X))
                new_y = max(cls.SAFE_MARGIN_Y, min(box.y, canvas_h - box.height - cls.SAFE_MARGIN_Y))
                new_w = min(box.width, canvas_w - (cls.SAFE_MARGIN_X * 2))
                new_h = min(box.height, canvas_h - (cls.SAFE_MARGIN_Y * 2))

                defects.append(LayoutDefect(
                    defect_type="viewport_clipping",
                    severity="critical",
                    element_ids=[elem.id],
                    description=f"元素 '{elem.id}' 超出画布视口边界 ({', '.join(clip_dirs)})",
                    details={
                        "element_id": elem.id,
                        "box": {"x": box.x, "y": box.y, "width": box.width, "height": box.height},
                        "canvas": {"width": canvas_w, "height": canvas_h}
                    },
                    suggested_fix={
                        "action": "update_element",
                        "element_id": elem.id,
                        "x": round(new_x, 1),
                        "y": round(new_y, 1),
                        "width": round(new_w, 1),
                        "height": round(new_h, 1)
                    }
                ))
            else:
                # Margin intrusion warning
                margin_intrusions = []
                if box.left < 16.0: margin_intrusions.append(f"靠左边距仅 {box.left:.1f}px")
                if box.top < 16.0: margin_intrusions.append(f"靠顶边距仅 {box.top:.1f}px")
                if (canvas_w - box.right) < 16.0: margin_intrusions.append(f"靠右边距仅 {(canvas_w - box.right):.1f}px")
                if (canvas_h - box.bottom) < 16.0: margin_intrusions.append(f"靠底边距仅 {(canvas_h - box.bottom):.1f}px")

                if margin_intrusions:
                    defects.append(LayoutDefect(
                        defect_type="margin_intrusion",
                        severity="warning",
                        element_ids=[elem.id],
                        description=f"元素 '{elem.id}' 贴近视口安全边距边缘 ({', '.join(margin_intrusions)})",
                        details={"element_id": elem.id, "intrusions": margin_intrusions}
                    ))

        return defects

    # -----------------------------------------------------------------
    # Check 2: Element Collisions & Accidental Overlaps
    # -----------------------------------------------------------------
    @classmethod
    def _check_element_overlaps(cls, slide: SlideIR) -> List[LayoutDefect]:
        defects = []
        elements = [e for e in slide.elements if not isinstance(e, ConnectorElementIR)]
        n = len(elements)

        # Helper: test if an element is a large background rectangle
        def is_slide_background(elem: ElementIR) -> bool:
            return elem.width >= 1000.0 and elem.height >= 550.0

        for i in range(n):
            elem_a = elements[i]
            if is_slide_background(elem_a):
                continue

            box_a = BoundingBox.from_element(elem_a)

            for j in range(i + 1, n):
                elem_b = elements[j]
                if is_slide_background(elem_b):
                    continue

                box_b = BoundingBox.from_element(elem_b)

                if not box_a.intersects(box_b):
                    continue

                # Check containment: if one fully contains another, this is likely intentional container nesting
                # e.g., card containing text/icon or button containing label
                a_contains_b = box_a.contains(box_b, tolerance=4.0)
                b_contains_a = box_b.contains(box_a, tolerance=4.0)

                if a_contains_b or b_contains_a:
                    # Valid parent container / child nesting
                    continue

                # Calculate IoU and mutual overlap ratio
                iou = box_a.iou(box_b)
                overlap_a = box_a.overlap_ratio_with(box_b)
                overlap_b = box_b.overlap_ratio_with(box_a)

                # Flag significant collision:
                # 1. High IoU (e.g. >= 0.08)
                # 2. Or either element has >= 25% of its area occluded without containment
                is_both_text = (
                    isinstance(elem_a, TextElementIR) and isinstance(elem_b, TextElementIR)
                )

                if iou >= 0.08 or overlap_a >= 0.25 or overlap_b >= 0.25 or (is_both_text and iou >= 0.03):
                    severity = "critical" if (is_both_text or iou >= 0.20) else "warning"

                    # Suggest horizontal separation fix if side-by-side or vertical separation if stacked
                    suggested_fix = None
                    if box_a.center_x < box_b.center_x:
                        # Shift b to right or reduce widths
                        suggested_fix = {
                            "action": "adjust_spacing",
                            "element_id_a": elem_a.id,
                            "element_id_b": elem_b.id,
                            "suggested_b_x": round(box_a.right + 20.0, 1)
                        }
                    else:
                        suggested_fix = {
                            "action": "adjust_spacing",
                            "element_id_a": elem_b.id,
                            "element_id_b": elem_a.id,
                            "suggested_b_x": round(box_b.right + 20.0, 1)
                        }

                    defects.append(LayoutDefect(
                        defect_type="collision_overlap",
                        severity=severity,
                        element_ids=[elem_a.id, elem_b.id],
                        description=f"图元 '{elem_a.id}' 与 '{elem_b.id}' 发生异常重叠遮挡 (IoU: {iou:.2f}, 遮挡比: {max(overlap_a, overlap_b):.1%})",
                        details={
                            "iou": round(iou, 3),
                            "overlap_a": round(overlap_a, 3),
                            "overlap_b": round(overlap_b, 3),
                            "box_a": {"x": box_a.x, "y": box_a.y, "width": box_a.width, "height": box_a.height},
                            "box_b": {"x": box_b.x, "y": box_b.y, "width": box_b.width, "height": box_b.height}
                        },
                        suggested_fix=suggested_fix
                    ))

        return defects

    # -----------------------------------------------------------------
    # Check 3: Text Overflow & Container Capacity
    # -----------------------------------------------------------------
    @classmethod
    def _check_text_overflows(cls, slide: SlideIR) -> List[LayoutDefect]:
        defects = []

        for elem in slide.elements:
            if not hasattr(elem, "text_content") or not elem.text_content:
                continue

            tc = elem.text_content
            plain_text = tc.plain_text or ""
            if not plain_text.strip():
                continue

            # Estimate required text height
            # Compute based on paragraphs, runs, font size, and element width
            avail_w = max(20.0, elem.width - 24.0)  # account for internal padding
            total_est_height = 0.0

            for para in tc.paragraphs:
                p_text = "".join(r.text for r in para.runs)
                if not p_text:
                    continue

                # Determine effective font size
                sizes = [r.font.size for r in para.runs if r.font and r.font.size]
                font_sz = max(sizes) if sizes else 16.0
                line_height = font_sz * (para.line_spacing if para.line_spacing else 1.25)

                # Estimate character width:
                # CJK chars (~1.0 * font_sz), ASCII (~0.55 * font_sz)
                cjk_chars = len(re.findall(r'[一-鿿]', p_text))
                ascii_chars = len(p_text) - cjk_chars
                text_pixel_width = (cjk_chars * font_sz * 1.05) + (ascii_chars * font_sz * 0.55)

                # Estimated lines wrapped
                lines = max(1, math.ceil(text_pixel_width / avail_w))
                para_h = lines * line_height + (para.space_after or 0.0) + (para.space_before or 0.0)
                total_est_height += para_h

            # Check if estimated text height significantly exceeds container height
            avail_h = elem.height - 16.0
            if total_est_height > avail_h * 1.25 and (total_est_height - avail_h) > 20.0:
                overflow_px = total_est_height - avail_h
                defects.append(LayoutDefect(
                    defect_type="text_overflow",
                    severity="warning",
                    element_ids=[elem.id],
                    description=f"元素 '{elem.id}' 文字内容高度 ({total_est_height:.0f}px) 超过容器高度 ({elem.height:.0f}px)，约溢出 {overflow_px:.0f}px",
                    details={
                        "element_id": elem.id,
                        "estimated_text_height": round(total_est_height, 1),
                        "container_height": elem.height,
                        "overflow_px": round(overflow_px, 1)
                    },
                    suggested_fix={
                        "action": "resize_or_reformat",
                        "element_id": elem.id,
                        "suggested_height": round(total_est_height + 24.0, 1),
                        "suggested_font_size": round(font_sz * 0.85, 1)
                    }
                ))

        return defects

    # -----------------------------------------------------------------
    # Check 4: WCAG 2.1 Color Contrast
    # -----------------------------------------------------------------
    @classmethod
    def _check_color_contrast(cls, slide: SlideIR) -> List[LayoutDefect]:
        defects = []
        slide_bg_color = slide.background.color if slide.background and slide.background.color else "#FFFFFF"

        # Collect filled shapes to determine underlying background
        filled_shapes = []
        for elem in slide.elements:
            if isinstance(elem, ShapeElementIR) and elem.style and elem.style.fill and elem.style.fill.type == "solid":
                if elem.style.fill.color:
                    filled_shapes.append(elem)

        for elem in slide.elements:
            if not hasattr(elem, "text_content") or not elem.text_content:
                continue

            tc = elem.text_content
            if not tc.plain_text or not tc.plain_text.strip():
                continue

            # Determine background color for this text:
            # 1. If shape itself has a solid fill color
            effective_bg = None
            if hasattr(elem, "style") and elem.style and elem.style.fill and elem.style.fill.type == "solid" and elem.style.fill.color:
                effective_bg = elem.style.fill.color
            else:
                # Check if there is an underlying filled shape covering this element
                box = BoundingBox.from_element(elem)
                for shape in reversed(filled_shapes):
                    if shape.id == elem.id:
                        continue
                    shape_box = BoundingBox.from_element(shape)
                    if shape_box.contains(box, tolerance=6.0):
                        effective_bg = shape.style.fill.color
                        break

            if not effective_bg:
                effective_bg = slide_bg_color

            # Check each run's font color against effective_bg
            for para in tc.paragraphs:
                for run in para.runs:
                    if not run.text.strip():
                        continue
                    text_color = run.font.color if (run.font and run.font.color) else "#000000"
                    font_size = run.font.size if (run.font and run.font.size) else 16.0
                    is_bold = bool(run.font and run.font.bold)

                    ratio = calculate_contrast_ratio(text_color, effective_bg)

                    # WCAG thresholds:
                    # Normal text: AA requires 4.5:1, AAA requires 7.0:1
                    # Large text (>= 18pt or >= 14pt bold): AA requires 3.0:1
                    is_large = font_size >= 18.0 or (font_size >= 14.0 and is_bold)
                    min_ratio = 3.0 if is_large else 4.5

                    if ratio < 2.5:
                        # Critical low contrast (almost unreadable)
                        better_text_color = "#FFFFFF" if calculate_relative_luminance(parse_hex_color(effective_bg)) < 0.5 else "#0F172A"
                        defects.append(LayoutDefect(
                            defect_type="low_contrast",
                            severity="critical",
                            element_ids=[elem.id],
                            description=f"元素 '{elem.id}' 文本对比度过低 ({ratio:.2f}:1，文字: {text_color}, 背景: {effective_bg})，严重影响可读性",
                            details={
                                "element_id": elem.id,
                                "contrast_ratio": ratio,
                                "text_color": text_color,
                                "bg_color": effective_bg,
                                "font_size": font_size
                            },
                            suggested_fix={
                                "action": "update_font_color",
                                "element_id": elem.id,
                                "font_color": better_text_color
                            }
                        ))
                    elif ratio < min_ratio:
                        # Warning low contrast
                        better_text_color = "#FFFFFF" if calculate_relative_luminance(parse_hex_color(effective_bg)) < 0.5 else "#1E293B"
                        defects.append(LayoutDefect(
                            defect_type="low_contrast",
                            severity="warning",
                            element_ids=[elem.id],
                            description=f"元素 '{elem.id}' 文本对比度略低 ({ratio:.2f}:1，建议达 {min_ratio}:1)",
                            details={
                                "element_id": elem.id,
                                "contrast_ratio": ratio,
                                "text_color": text_color,
                                "bg_color": effective_bg
                            },
                            suggested_fix={
                                "action": "update_font_color",
                                "element_id": elem.id,
                                "font_color": better_text_color
                            }
                        ))

        return defects

    # -----------------------------------------------------------------
    # Check 5: Alignment & Grid Consistency
    # -----------------------------------------------------------------
    @classmethod
    def _check_alignment_consistency(cls, slide: SlideIR) -> List[LayoutDefect]:
        defects = []
        cards = [
            e for e in slide.elements
            if isinstance(e, ShapeElementIR) and e.width >= 100.0 and e.height >= 80.0
        ]
        if len(cards) < 2:
            return defects

        # Check for nearly-aligned elements (misalignment between 2px and 14px)
        for i in range(len(cards)):
            for j in range(i + 1, len(cards)):
                c1, c2 = cards[i], cards[j]
                # Y-alignment check for horizontal items
                dy = abs(c1.y - c2.y)
                if 2.0 < dy <= 12.0 and abs(c1.x - c2.x) > 50.0:
                    defects.append(LayoutDefect(
                        defect_type="misaligned",
                        severity="info",
                        element_ids=[c1.id, c2.id],
                        description=f"卡片 '{c1.id}' 与 '{c2.id}' 顶部未严格对齐 (相差 {dy:.1f}px)",
                        details={"element_id_1": c1.id, "element_id_2": c2.id, "y1": c1.y, "y2": c2.y},
                        suggested_fix={
                            "action": "align_elements",
                            "align_type": "top",
                            "element_ids": [c1.id, c2.id]
                        }
                    ))
        return defects


# =====================================================================
# 5. Slide Comparison / Diff Helper
# =====================================================================

@dataclass
class SlideDiffResult:
    """Represents differences and health delta between two slide versions."""
    added_element_ids: List[str]
    removed_element_ids: List[str]
    modified_element_ids: List[str]
    score_before: float
    score_after: float
    score_delta: float
    resolved_defects: List[LayoutDefect]
    new_defects: List[LayoutDefect]

    def summary(self) -> str:
        delta_str = f"+{self.score_delta:.1f}" if self.score_delta >= 0 else f"{self.score_delta:.1f}"
        return (
            f"版本对比完成: 健康分由 {self.score_before:.1f} -> {self.score_after:.1f} ({delta_str})。 "
            f"新增 {len(self.added_element_ids)} 项，移除 {len(self.removed_element_ids)} 项，"
            f"修改 {len(self.modified_element_ids)} 项，修复 {len(self.resolved_defects)} 个缺陷。"
        )


def compare_slides(before_slide: SlideIR, after_slide: SlideIR) -> SlideDiffResult:
    """Computes geometric, structural and health score differences between two slide states."""
    report_before = LayoutDiffEngine.evaluate_slide(before_slide)
    report_after = LayoutDiffEngine.evaluate_slide(after_slide)

    before_ids = {e.id: e for e in before_slide.elements}
    after_ids = {e.id: e for e in after_slide.elements}

    added = [eid for eid in after_ids if eid not in before_ids]
    removed = [eid for eid in before_ids if eid not in after_ids]
    modified = []

    for eid in after_ids:
        if eid in before_ids:
            e_before = before_ids[eid]
            e_after = after_ids[eid]
            if (
                abs(e_before.x - e_after.x) > 0.5 or
                abs(e_before.y - e_after.y) > 0.5 or
                abs(e_before.width - e_after.width) > 0.5 or
                abs(e_before.height - e_after.height) > 0.5
            ):
                modified.append(eid)

    # Defect diff
    after_defect_keys = {
        (d.defect_type, tuple(sorted(d.element_ids))) for d in report_after.defects
    }
    before_defect_keys = {
        (d.defect_type, tuple(sorted(d.element_ids))) for d in report_before.defects
    }

    resolved = [
        d for d in report_before.defects
        if (d.defect_type, tuple(sorted(d.element_ids))) not in after_defect_keys
    ]
    new_defects = [
        d for d in report_after.defects
        if (d.defect_type, tuple(sorted(d.element_ids))) not in before_defect_keys
    ]

    return SlideDiffResult(
        added_element_ids=added,
        removed_element_ids=removed,
        modified_element_ids=modified,
        score_before=report_before.score,
        score_after=report_after.score,
        score_delta=report_after.score - report_before.score,
        resolved_defects=resolved,
        new_defects=new_defects
    )
