"""RoleClassifier: Semantic classification of PPT slide elements.

Classifies elements into functional roles:
- slide_title: Primary slide headline
- subtitle: Supporting header or deck subtitle
- card: Visual container enclosing content
- body: Paragraphs, lists, and explanations
- metric: Large KPI numbers, stats, and badges
- image: Illustrative or photographic assets
- connector: Arrows, flow lines, and visual links
- footer: Page numbers, copyrights, and dates
- decorative: Pure aesthetic accents, small divider lines
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Any, Set
from ..ir.models import (
    SlideIR, ElementIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, ImageElementIR, TableElementIR, GroupElementIR
)
from ..eval.layout_diff import BoundingBox


class SemanticRole(str, Enum):
    SLIDE_TITLE = "slide_title"
    SUBTITLE = "subtitle"
    CARD = "card"
    BODY = "body"
    METRIC = "metric"
    IMAGE = "image"
    CONNECTOR = "connector"
    FOOTER = "footer"
    DECORATIVE = "decorative"


@dataclass
class ElementClassification:
    element_id: str
    role: SemanticRole
    importance: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.element_id,
            "role": self.role.value,
            "importance": round(self.importance, 2),
            "confidence": round(self.confidence, 2),
            "tags": list(self.tags)
        }


class RoleClassifier:
    """Classifies elements based on spatial position, typography, styling, and content."""

    @classmethod
    def classify_slide(cls, slide: SlideIR) -> Dict[str, ElementClassification]:
        """Classifies all elements on a slide."""
        elements = slide.all_elements(recursive=False)
        boxes = {el.id: BoundingBox.from_element(el) for el in elements}
        results: Dict[str, ElementClassification] = {}

        # 1. Identify which shapes are containers (enclose other elements)
        containers: Set[str] = set()
        for p_id, p_box in boxes.items():
            p_elem = next(e for e in elements if e.id == p_id)
            if not isinstance(p_elem, (ShapeElementIR, GroupElementIR)):
                continue
            for c_id, c_box in boxes.items():
                if p_id != c_id and p_box.contains(c_box, tolerance=4.0):
                    containers.add(p_id)
                    break

        # 2. Identify the primary title element via scoring
        max_font_size = 0.0
        for el in elements:
            font_sz = cls._get_max_font_size(el)
            if font_sz > max_font_size:
                max_font_size = font_sz

        best_title_id: Optional[str] = None
        best_title_score = -1.0

        for el in elements:
            text_str = cls._get_plain_text(el)
            if not text_str:
                continue
            box = boxes[el.id]
            font_sz = cls._get_max_font_size(el)
            eid_lower = el.id.lower()
            name_lower = (el.name or "").lower()

            is_title_kw = any(k in eid_lower or k in name_lower for k in ["title", "heading", "headline", "hdr", "header", "topic"])
            is_badge_or_footer = any(k in eid_lower or k in name_lower for k in ["badge", "footer", "meta", "page", "date", "oral"])

            cand_score = 0.0
            if is_badge_or_footer:
                cand_score -= 80.0
            if is_title_kw:
                cand_score += 60.0
            if box.top < 220:
                cand_score += (220.0 - box.top) * 0.2
            if max_font_size > 0:
                cand_score += (font_sz / max_font_size) * 50.0
            if font_sz >= 24.0:
                cand_score += 30.0

            if cand_score > best_title_score and cand_score > 30.0:
                best_title_score = cand_score
                best_title_id = el.id

        # 3. Classify individual elements
        title_assigned = False

        for el in elements:
            box = boxes[el.id]
            font_sz = cls._get_max_font_size(el)
            text_str = cls._get_plain_text(el)
            eid_lower = el.id.lower()
            name_lower = (el.name or "").lower()

            # Connectors
            if isinstance(el, ConnectorElementIR):
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.CONNECTOR,
                    importance=0.4,
                    confidence=0.98,
                    tags=["flow", "link"]
                )
                continue

            # Images
            if isinstance(el, ImageElementIR):
                is_small_icon = (el.width <= 48 and el.height <= 48)
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.DECORATIVE if is_small_icon else SemanticRole.IMAGE,
                    importance=0.3 if is_small_icon else 0.75,
                    confidence=0.95,
                    tags=["icon"] if is_small_icon else ["visual", "media"]
                )
                continue

            # Containers / Cards
            if el.id in containers:
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.CARD,
                    importance=0.7,
                    confidence=0.92,
                    tags=["container", "card_background"]
                )
                continue

            # Footer / Slide notes
            if box.top >= 640 or (font_sz <= 11.0 and box.top >= 600) or any(k in eid_lower or k in name_lower for k in ["footer", "page", "slide_num"]):
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.FOOTER,
                    importance=0.2,
                    confidence=0.9,
                    tags=["footer", "meta"]
                )
                continue

            # Metrics / KPI numbers (e.g. "$1.2M", "99.9%", "45K", "+120%", or standalone numbers)
            if cls._is_metric_text(text_str, font_sz):
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.METRIC,
                    importance=0.85,
                    confidence=0.88,
                    tags=["metric", "kpi", "highlight"]
                )
                continue

            # Title candidate
            is_best_title = (best_title_id is not None and el.id == best_title_id)
            is_title_keyword = any(k in eid_lower or k in name_lower for k in ["title", "heading", "headline", "hdr", "header", "topic"])
            is_large_text = (box.top < 220 and font_sz >= 22.0 and font_sz >= max_font_size * 0.85)

            if (is_best_title or (not title_assigned and not best_title_id and text_str and (is_title_keyword or is_large_text))):
                title_assigned = True
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.SLIDE_TITLE,
                    importance=1.0,
                    confidence=0.95,
                    tags=["heading", "slide_title"]
                )
                continue

            # Subtitle candidate (under title, medium font)
            if title_assigned and text_str and box.top < 320 and 15.0 <= font_sz < 24.0:
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.SUBTITLE,
                    importance=0.8,
                    confidence=0.85,
                    tags=["subheading", "deck"]
                )
                continue

            # Decorative shape (tiny elements or line shapes with no text)
            if (box.width <= 32 and box.height <= 32) or ((box.height <= 4 or box.width <= 4) and not text_str):
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.DECORATIVE,
                    importance=0.1,
                    confidence=0.9,
                    tags=["accent", "divider"]
                )
                continue

            # Default: Body text or Card shape
            if text_str:
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.BODY,
                    importance=0.6,
                    confidence=0.8,
                    tags=["paragraph", "content"]
                )
            else:
                results[el.id] = ElementClassification(
                    element_id=el.id,
                    role=SemanticRole.CARD,
                    importance=0.5,
                    confidence=0.7,
                    tags=["shape"]
                )

        # 4. Fallback promotion if no title was explicitly tagged
        if not title_assigned:
            body_text_candidates = [
                (boxes[eid].top, eid)
                for eid, cl in results.items()
                if cl.role == SemanticRole.BODY and boxes[eid].top < 240
            ]
            if body_text_candidates:
                body_text_candidates.sort(key=lambda item: item[0])
                promoted_id = body_text_candidates[0][1]
                results[promoted_id].role = SemanticRole.SLIDE_TITLE
                results[promoted_id].importance = 1.0
                results[promoted_id].tags.append("slide_title")

        return results

    @staticmethod
    def _get_max_font_size(elem: ElementIR) -> float:
        tc = getattr(elem, "text_content", None)
        if not tc or not tc.paragraphs:
            return 0.0
        max_sz = 0.0
        for p in tc.paragraphs:
            for r in p.runs:
                if r.font and r.font.size and r.font.size > max_sz:
                    max_sz = r.font.size
        return max_sz

    @staticmethod
    def _get_plain_text(elem: ElementIR) -> str:
        tc = getattr(elem, "text_content", None)
        if tc:
            return tc.plain_text.strip()
        return ""

    @staticmethod
    def _is_metric_text(text: str, font_sz: float) -> bool:
        if not text:
            return False
        clean = text.strip()
        # Regex for KPIs: e.g. 99%, $10M, +25%, 4.8/5, 1,200+, 50K
        kpi_pattern = r"^[\$€¥]?\s*[-+]?\d+([.,]\d+)?\s*(%|[kKmMbBtT]|pts|x|\+)?$"
        if re.match(kpi_pattern, clean):
            return True
        if font_sz >= 28.0 and any(c.isdigit() for c in clean) and len(clean) < 15:
            return True
        return False
