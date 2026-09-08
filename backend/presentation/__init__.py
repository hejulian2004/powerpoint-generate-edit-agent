"""Research Presentation Planner Package (PR7.2).

Transforms PaperIR into a structured, academic presentation plan (PresentationPlan)
without jumping directly into slide layouts or PPTX rendering.

Public Exports:
- SlideType: Enumeration of academic slide categories.
- SlidePlan: Intermediate representation of an individual slide.
- PresentationPlan: Complete presentation structure and deck metadata.
- generate_presentation_plan / agenerate_presentation_plan: Main planner entry points.
- rank_sections: Section importance and role ranking.
- select_visuals_for_slide: Figure and table selector.
- enrich_presentation_plan / aenrich_presentation_plan: Optional LLM text refiner.
"""

from .enricher import aenrich_presentation_plan, enrich_presentation_plan
from .figure_selector import select_visuals_for_slide
from .planner import agenerate_presentation_plan, generate_presentation_plan
from .ranking import RankedSection, SectionCategory, rank_sections
from .schema import PresentationPlan, SlidePlan, SlideType
from .templates import PresentationProfile, SlideTemplateSlot, get_profile

__all__ = [
    "SlideType",
    "SlidePlan",
    "PresentationPlan",
    "generate_presentation_plan",
    "agenerate_presentation_plan",
    "rank_sections",
    "RankedSection",
    "SectionCategory",
    "select_visuals_for_slide",
    "enrich_presentation_plan",
    "aenrich_presentation_plan",
    "PresentationProfile",
    "SlideTemplateSlot",
    "get_profile",
]
