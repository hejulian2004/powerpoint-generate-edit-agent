"""Visual Evaluator Interface and Implementations (PR12).

Provides:
- VisualEvaluator (Abstract Base Class)
- RuleBasedEvaluator (Deterministic geometric and spatial rule engine)
- OpenAICompatibleVisionEvaluator (VLM multimodal adapter for external vision LLMs)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from PIL import Image

from ..layout.constraints import estimate_text_lines
from ..layout.schema import DeckLayoutSpec, ElementType, LayoutElement, LayoutSpec, Rect
from .issues import deduplicate_issues
from .schema import IssueSeverity, IssueType, VisualIssue

logger = logging.getLogger(__name__)


class VisualEvaluator(ABC):
    """Abstract interface for slide visual critique and defect identification."""

    @abstractmethod
    def evaluate(
        self,
        slide_image: Optional[Union[Path, Image.Image]],
        layout_spec: LayoutSpec,
    ) -> List[VisualIssue]:
        """Evaluate a single slide and return identified visual issues."""
        pass

    def evaluate_deck(
        self,
        slide_images: List[Union[Path, Image.Image]],
        deck_spec: DeckLayoutSpec,
    ) -> List[VisualIssue]:
        """Evaluate all slides in a DeckLayoutSpec."""
        all_issues: List[VisualIssue] = []
        for idx, slide in enumerate(deck_spec.slides):
            img = slide_images[idx] if idx < len(slide_images) else None
            issues = self.evaluate(img, slide)
            all_issues.extend(issues)
        return deduplicate_issues(all_issues)


class RuleBasedEvaluator(VisualEvaluator):
    """Deterministic, rule-based visual and spatial constraint evaluator.

    Detects:
    - OVERFLOW: Elements exceeding canvas boundaries (x < 0, y < 0, r > W, b > H)
    - OVERLAP: Unintended overlap/collisions between foreground elements
    - TEXT_OVERFLOW: Text content clearly exceeding container bounding box
    - TEXT_DENSITY_HIGH: Excessively high character-to-area density
    - UNDER_UTILIZED_SPACE / TOO_SMALL: Media/figures taking abnormally small area (<20% of expected)
    - WRONG_SCALE: Distorted figure aspect ratio
    """

    def __init__(
        self,
        min_margin: float = 10.0,
        density_threshold: float = 0.012,  # chars per square px
        min_figure_area_ratio: float = 0.05,  # relative to total slide canvas
        char_width_ratio: float = 0.55,
    ) -> None:
        self.min_margin = min_margin
        self.density_threshold = density_threshold
        self.min_figure_area_ratio = min_figure_area_ratio
        self.char_width_ratio = char_width_ratio

    def evaluate(
        self,
        slide_image: Optional[Union[Path, Image.Image]],
        layout_spec: LayoutSpec,
    ) -> List[VisualIssue]:
        issues: List[VisualIssue] = []
        canvas = layout_spec.canvas
        canvas_area = canvas.width * canvas.height

        # 1. Canvas Bounds & Overflow Check
        for el in layout_spec.elements:
            geo = el.geometry
            if geo.x < -1e-2 or geo.y < -1e-2:
                issues.append(
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element=el.element_id,
                        description=f"Element '{el.element_id}' has negative coordinates (x={geo.x:.1f}, y={geo.y:.1f})",
                        evidence={"geometry": geo.model_dump(), "violation": "negative_origin"},
                    )
                )
            elif geo.right > canvas.width + 1e-2 or geo.bottom > canvas.height + 1e-2:
                issues.append(
                    VisualIssue(
                        slide=layout_spec.slide_id,
                        issue=IssueType.OVERFLOW,
                        severity=IssueSeverity.ERROR,
                        element=el.element_id,
                        description=(
                            f"Element '{el.element_id}' exceeds canvas bounds: "
                            f"right={geo.right:.1f}>{canvas.width}, bottom={geo.bottom:.1f}>{canvas.height}"
                        ),
                        evidence={
                            "geometry": geo.model_dump(),
                            "canvas": {"width": canvas.width, "height": canvas.height},
                            "violation": "exceeds_canvas",
                        },
                    )
                )

        # 2. Collision / Overlap Check
        fg_elements = [el for el in layout_spec.elements if el.element_type != ElementType.CONTAINER]
        for i in range(len(fg_elements)):
            for j in range(i + 1, len(fg_elements)):
                el_a = fg_elements[i]
                el_b = fg_elements[j]
                if el_a.geometry.intersects(el_b.geometry):
                    inter = el_a.geometry.intersection(el_b.geometry)
                    if inter and (inter.width > 2.0 and inter.height > 2.0):
                        inter_area = inter.width * inter.height
                        min_area = min(
                            el_a.geometry.width * el_a.geometry.height,
                            el_b.geometry.width * el_b.geometry.height,
                        )
                        overlap_ratio = inter_area / max(1.0, min_area)
                        if overlap_ratio > 0.05:
                            issues.append(
                                VisualIssue(
                                    slide=layout_spec.slide_id,
                                    issue=IssueType.OVERLAP,
                                    severity=IssueSeverity.ERROR,
                                    element=el_a.element_id,
                                    description=(
                                        f"Visual overlap detected between '{el_a.element_id}' "
                                        f"and '{el_b.element_id}' (overlap area={inter.width:.0f}x{inter.height:.0f})"
                                    ),
                                    evidence={
                                        "element_a": el_a.element_id,
                                        "element_b": el_b.element_id,
                                        "intersection": inter.model_dump(),
                                        "overlap_ratio": round(overlap_ratio, 3),
                                    },
                                )
                            )

        # 3. Text Overflow & Density Check
        for el in layout_spec.elements:
            if el.element_type in (ElementType.TEXT, ElementType.BADGE):
                content_str = self._extract_text_content(el.content)
                if not content_str.strip():
                    continue

                char_count = len(content_str)
                geo = el.geometry
                box_area = max(1.0, geo.width * geo.height)

                # Density check
                density = char_count / box_area
                if char_count > 200 and density > self.density_threshold:
                    issues.append(
                        VisualIssue(
                            slide=layout_spec.slide_id,
                            issue=IssueType.TEXT_DENSITY_HIGH,
                            severity=IssueSeverity.WARNING,
                            element=el.element_id,
                            description=(
                                f"Text density too high in element '{el.element_id}': "
                                f"{char_count} chars in {geo.width:.0f}x{geo.height:.0f} box"
                            ),
                            evidence={"char_count": char_count, "density": round(density, 4)},
                        )
                    )

                # Overflow heuristic
                font_size = 18.0
                if el.style and el.style.text and el.style.text.font_size:
                    font_size = el.style.text.font_size

                padding = el.style.padding if el.style and el.style.padding else 0.0
                lines_needed = estimate_text_lines(
                    text=content_str,
                    box_width=geo.width,
                    font_size=font_size,
                    padding=padding,
                )

                line_h = font_size * 1.25
                required_height = lines_needed * line_h + 2 * padding

                if required_height > geo.height * 1.15:
                    issues.append(
                        VisualIssue(
                            slide=layout_spec.slide_id,
                            issue=IssueType.TEXT_OVERFLOW,
                            severity=IssueSeverity.ERROR,
                            element=el.element_id,
                            description=(
                                f"Text overflow in element '{el.element_id}': "
                                f"requires ~{required_height:.0f}px height, allocated only {geo.height:.0f}px"
                            ),
                            evidence={
                                "char_count": char_count,
                                "lines_needed": lines_needed,
                                "required_height": round(required_height, 1),
                                "actual_height": round(geo.height, 1),
                            },
                        )
                    )

        # 4. Under-utilized Space / Too Small Media Check
        for el in layout_spec.elements:
            if el.element_type == ElementType.FIGURE:
                geo = el.geometry
                fig_area = geo.width * geo.height
                area_ratio = fig_area / canvas_area

                if area_ratio < self.min_figure_area_ratio or geo.width < 120.0 or geo.height < 90.0:
                    issues.append(
                        VisualIssue(
                            slide=layout_spec.slide_id,
                            issue=IssueType.TOO_SMALL,
                            severity=IssueSeverity.WARNING,
                            element=el.element_id,
                            description=(
                                f"Figure element '{el.element_id}' is undersized: "
                                f"{geo.width:.0f}x{geo.height:.0f} occupies only {area_ratio*100:.1f}% of canvas"
                            ),
                            evidence={
                                "geometry": geo.model_dump(),
                                "area_ratio": round(area_ratio, 4),
                                "min_expected_ratio": self.min_figure_area_ratio,
                            },
                        )
                    )

                # Wrong scale / aspect ratio check
                aspect_ratio = geo.aspect_ratio
                if aspect_ratio < 0.25 or aspect_ratio > 4.5:
                    issues.append(
                        VisualIssue(
                            slide=layout_spec.slide_id,
                            issue=IssueType.WRONG_SCALE,
                            severity=IssueSeverity.WARNING,
                            element=el.element_id,
                            description=(
                                f"Figure element '{el.element_id}' has distorted aspect ratio: {aspect_ratio:.2f}"
                            ),
                            evidence={"aspect_ratio": round(aspect_ratio, 3)},
                        )
                    )

        return deduplicate_issues(issues)

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(str(item) for item in content)
        if isinstance(content, dict):
            return " ".join(str(v) for v in content.values())
        return str(content)


class OpenAICompatibleVisionEvaluator(VisualEvaluator):
    """Multimodal Vision Language Model adapter for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o",
        client_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = model
        self._client_fn = client_fn

    def is_configured(self) -> bool:
        return bool(self.api_key or self._client_fn)

    def evaluate(
        self,
        slide_image: Optional[Union[Path, Image.Image]],
        layout_spec: LayoutSpec,
    ) -> List[VisualIssue]:
        if not self.is_configured():
            # Graceful degradation to empty issues when external key is not provided
            return []

        payload = self.build_request_payload(slide_image, layout_spec)

        try:
            if self._client_fn:
                response = self._client_fn(payload)
            else:
                import urllib.request

                req = urllib.request.Request(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    response = json.loads(resp.read().decode("utf-8"))

            return self.parse_vlm_response(response, layout_spec.slide_id)
        except Exception as exc:
            logger.warning("OpenAICompatibleVisionEvaluator request failed: %s", exc)
            return []

    def build_request_payload(
        self,
        slide_image: Optional[Union[Path, Image.Image]],
        layout_spec: LayoutSpec,
    ) -> Dict[str, Any]:
        """Construct multimodal message payload for OpenAI chat API."""
        user_content: List[Dict[str, Any]] = []

        # System / context prompt
        prompt_text = (
            f"You are a professional PowerPoint slide visual critic. "
            f"Evaluate the visual presentation quality of slide '{layout_spec.slide_id}'.\n"
            f"Layout elements:\n"
        )
        for el in layout_spec.elements:
            geo = el.geometry
            prompt_text += (
                f"- ID: {el.element_id}, Type: {el.element_type.value}, "
                f"BBox: [x={geo.x:.0f}, y={geo.y:.0f}, w={geo.width:.0f}, h={geo.height:.0f}]\n"
            )

        prompt_text += (
            "\nAnalyze for: OVERFLOW, OVERLAP, TEXT_OVERFLOW, TOO_SMALL, BAD_ALIGNMENT, LOW_CONTRAST. "
            "Respond strictly in JSON array format: "
            '[{"slide": "<slide_id>", "issue": "<ISSUE_TYPE>", "severity": "WARNING|ERROR", '
            '"element": "<element_id>", "description": "<details>", "evidence": {}}]'
        )
        user_content.append({"type": "text", "text": prompt_text})

        # Image content if provided
        if slide_image is not None:
            b64_data = self._encode_image_base64(slide_image)
            if b64_data:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_data}"},
                    }
                )

        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an automated slide visual critique evaluator."},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
        }

    @staticmethod
    def _encode_image_base64(image_input: Union[Path, Image.Image]) -> Optional[str]:
        try:
            if isinstance(image_input, (str, Path)):
                data = Path(image_input).read_bytes()
                return base64.b64encode(data).decode("utf-8")
            elif isinstance(image_input, Image.Image):
                buf = io.BytesIO()
                image_input.save(buf, format="PNG")
                return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            return None
        return None

    @staticmethod
    def parse_vlm_response(response: Dict[str, Any], default_slide_id: str) -> List[VisualIssue]:
        """Extract and validate VisualIssue objects from VLM response JSON."""
        try:
            choices = response.get("choices", [])
            if not choices:
                return []
            content = choices[0].get("message", {}).get("content", "")
            # Clean possible markdown fence
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            raw_issues = json.loads(content)
            if isinstance(raw_issues, dict) and "issues" in raw_issues:
                raw_issues = raw_issues["issues"]
            if not isinstance(raw_issues, list):
                raw_issues = [raw_issues]

            issues: List[VisualIssue] = []
            for item in raw_issues:
                if not item.get("slide"):
                    item["slide"] = default_slide_id
                issues.append(VisualIssue.from_dict(item))
            return issues
        except Exception as exc:
            logger.warning("Failed to parse VLM response JSON: %s", exc)
            return []
