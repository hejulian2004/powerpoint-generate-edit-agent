"""Free-form LLM layout plan schema.

Deliberately contains NO ``layout_type`` / ``template_name`` / composition enum.
The model emits absolute geometry and styling directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LayoutElementPlan(BaseModel):
    """One absolutely-positioned element proposed by the LLM."""

    element_id: str = Field(..., description="Unique element id within the slide")
    source_block_id: Optional[str] = Field(
        None, description="SlideSpec block id this element renders (or null)"
    )
    element_type: str = Field("TEXT", description="TEXT|FIGURE|TABLE|BADGE|CONTAINER")

    x: float = Field(..., description="Left offset on the 1280x720 canvas")
    y: float = Field(..., description="Top offset on the 1280x720 canvas")
    width: float = Field(..., description="Element width")
    height: float = Field(..., description="Element height")
    z_index: int = Field(0, description="Stacking order")

    content: Any = Field(None, description="Text or figure/table payload")

    font_family: Optional[str] = None
    font_size: Optional[float] = None
    font_weight: Optional[str] = None
    text_color: Optional[str] = None

    fill_color: Optional[str] = None
    border_color: Optional[str] = None
    border_width: Optional[float] = None
    corner_radius: Optional[float] = None

    alignment: Optional[str] = None
    vertical_alignment: Optional[str] = None
    line_height: Optional[float] = None
    italic: Optional[bool] = None
    padding: Optional[float] = None
    opacity: float = Field(1.0, ge=0.0, le=1.0)

    source_evidence_ids: List[str] = Field(default_factory=list)


class LLMLayoutPlan(BaseModel):
    """The LLM's complete layout for a single slide."""

    slide_id: str = Field(..., description="Target slide id")
    design_rationale: str = Field("", description="Why the layout looks like this")
    visual_focal_point: Optional[str] = Field(
        None, description="element_id that should dominate the slide"
    )
    reading_flow: str = Field("", description="Intended reading order")
    elements: List[LayoutElementPlan] = Field(default_factory=list)

    def element_ids(self) -> List[str]:
        return [e.element_id for e in self.elements]

    def get_element(self, element_id: str) -> Optional[LayoutElementPlan]:
        for element in self.elements:
            if element.element_id == element_id:
                return element
        return None

    def to_dict(self, **kwargs: Any) -> Dict[str, Any]:
        return self.model_dump(mode="json", **kwargs)

    def to_json_file(self, path: Any) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return out

    @classmethod
    def from_json_file(cls, path: Any) -> "LLMLayoutPlan":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = ["LayoutElementPlan", "LLMLayoutPlan"]
