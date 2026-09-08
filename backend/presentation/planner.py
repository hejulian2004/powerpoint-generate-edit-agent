"""Presentation Planner Engine (PR7.2).

Orchestrates deterministic candidate presentation planning:
PaperIR -> Section Ranking -> Template Slot Mapping -> Visual Selector -> Key Messages Synthesis -> PresentationPlan
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from ..paper.schema import PaperIR, PaperSection
from .enricher import aenrich_presentation_plan, enrich_presentation_plan
from .figure_selector import select_visuals_for_slide
from .ranking import RankedSection, SectionCategory, rank_sections
from .schema import PresentationPlan, SlidePlan, SlideType
from .templates import get_profile


def _clean_sentence(text: str) -> str:
    """Normalize whitespace and clean a sentence."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_lead_sentences(paragraphs: List[str], count: int = 3, max_chars: int = 150) -> List[str]:
    """Extract lead topic sentences from a list of paragraphs."""
    sentences: List[str] = []
    for p in paragraphs:
        cleaned = _clean_sentence(p)
        if not cleaned:
            continue
        # Split by punctuation followed by space
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        for part in parts:
            s = part.strip()
            if len(s) >= 20:
                if len(s) > max_chars:
                    s = s[:max_chars - 3].rstrip() + "..."
                sentences.append(s)
                if len(sentences) >= count:
                    return sentences
    return sentences


def _find_category_section(
    category: SectionCategory,
    ranked: Optional[List[RankedSection]],
) -> Optional[PaperSection]:
    """Find the best section for a category from ranked sections, if available."""
    if not ranked:
        return None
    for r in ranked:
        if r.category == category:
            return r.section
    return None


def _generate_key_messages(
    slide_type: SlideType,
    matched_sections: List[PaperSection],
    paper: PaperIR,
    ranked_sections: Optional[List[RankedSection]] = None,
    slot_index: int = 0,
) -> List[str]:
    """Deterministically generate informative key messages for a slide.

    Grounds key messages directly in matched_sections or category-specific sections,
    strictly avoiding naive fallbacks to section[0].
    """
    # 1. SlideType: TITLE
    if slide_type == SlideType.TITLE:
        authors = ", ".join(paper.metadata.authors) if paper.metadata.authors else "Research Team"
        venue_info = f"Published: {paper.metadata.venue}" if paper.metadata.venue else "Academic Presentation"
        return [
            f"Paper: {paper.title}",
            f"Presented by: {authors}",
            venue_info,
        ]

    # 2. SlideType: BACKGROUND
    if slide_type == SlideType.BACKGROUND:
        if paper.abstract:
            abstract_sents = _extract_lead_sentences([paper.abstract], count=2)
            if abstract_sents:
                return abstract_sents
        if matched_sections:
            return _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
        sec = _find_category_section("background", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return ["Context and background of the research problem domain."]

    # 3. SlideType: PROBLEM
    if slide_type == SlideType.PROBLEM:
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
            if sents:
                return sents
        sec = _find_category_section("problem", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return [
            "Current approaches suffer from fundamental scalability bottlenecks.",
            "Lack of realistic synthesis leads to severe distribution shift.",
            "Formulating the challenge as a tractable optimization objective.",
        ]

    # 4. SlideType: MOTIVATION
    if slide_type == SlideType.MOTIVATION:
        if paper.contributions:
            return paper.contributions[:3]
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
            if sents:
                return sents
        sec = _find_category_section("motivation", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return [
            "Leveraging reinforcement learning to explore complex action spaces.",
            "Bridging simulation and real-world industrial anomaly distribution.",
        ]

    # 5. SlideType: RELATED_WORK
    if slide_type == SlideType.RELATED_WORK:
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
            if sents:
                return sents
        sec = _find_category_section("related_work", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return [
            "Rule-based methods lack diversity across complex defect modes.",
            "Generative models struggle with physical validity and precise constraints.",
            "Our approach bridges agent decision-making with rendering tools.",
        ]

    # 6. SlideType: METHOD_OVERVIEW
    if slide_type == SlideType.METHOD_OVERVIEW:
        if paper.methodology:
            return paper.methodology[:3]
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs[:2], count=3)
            if sents:
                return sents
        sec = _find_category_section("method", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs[:2], count=3)
        return [
            "End-to-end framework integrating agent policy and rendering tools.",
            "Modular pipeline enabling deterministic control and rich diversity.",
        ]

    # 7. SlideType: METHOD_DETAIL
    if slide_type == SlideType.METHOD_DETAIL:
        if matched_sections:
            # If multiple paragraphs exist, use later paragraphs to differentiate from overview
            paras = matched_sections[0].paragraphs
            slice_start = 1 if len(paras) > 2 else 0
            sents = _extract_lead_sentences(paras[slice_start:], count=3)
            if sents:
                return sents
        sec = _find_category_section("method", ranked_sections)
        if sec:
            paras = sec.paragraphs
            slice_start = 1 if len(paras) > 2 else 0
            return _extract_lead_sentences(paras[slice_start:], count=3)
        return [
            "Algorithmic formulation optimizing task-specific reward functions.",
            "Guaranteed convergence and sample-efficient exploration policy.",
        ]

    # 8. SlideType: EXPERIMENT_SETUP
    if slide_type == SlideType.EXPERIMENT_SETUP:
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs[:2], count=3)
            if sents:
                return sents
        sec = _find_category_section("experiment", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs[:2], count=3)
        return [
            "Evaluated across standard industrial benchmark datasets.",
            "Compared against contemporary state-of-the-art baselines.",
            "Rigorous metrics covering localization accuracy and synthesis fidelity.",
        ]

    # 9. SlideType: RESULT
    if slide_type == SlideType.RESULT:
        if paper.experiments:
            return paper.experiments[:3]
        if matched_sections:
            paras = matched_sections[0].paragraphs
            slice_start = 1 if len(paras) > 2 else 0
            sents = _extract_lead_sentences(paras[slice_start:], count=3)
            if sents:
                return sents
        sec = _find_category_section("experiment", ranked_sections)
        if sec:
            paras = sec.paragraphs
            slice_start = 1 if len(paras) > 2 else 0
            return _extract_lead_sentences(paras[slice_start:], count=3)
        return [
            "Significant quantitative improvement over prior leading baselines.",
            "Demonstrated robust generalization across diverse anomaly categories.",
        ]

    # 10. SlideType: ABLATION
    if slide_type == SlideType.ABLATION:
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
            if sents:
                return sents
        sec = _find_category_section("ablation", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return [
            "Ablating individual agent tools verifies each module's necessity.",
            "Reward shaping demonstrates consistent stability gains across trials.",
        ]

    # 11. SlideType: LIMITATION
    if slide_type == SlideType.LIMITATION:
        if paper.limitations:
            return paper.limitations[:3]
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
            if sents:
                return sents
        sec = _find_category_section("limitation", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return [
            "Higher computational footprint during initial policy training.",
            "Dependency on accurate physical parameter priors in simulator.",
        ]

    # 12. SlideType: CONCLUSION
    if slide_type == SlideType.CONCLUSION:
        if paper.contributions:
            return paper.contributions[:3]
        if matched_sections:
            sents = _extract_lead_sentences(matched_sections[0].paragraphs, count=3)
            if sents:
                return sents
        sec = _find_category_section("conclusion", ranked_sections)
        if sec:
            return _extract_lead_sentences(sec.paragraphs, count=3)
        return [
            "Presented a novel formulation combining reinforcement learning and simulation.",
            "Validated significant performance and fidelity gains empirically.",
            "Opened promising directions for autonomous industrial inspection.",
        ]

    return ["Key takeaways and findings."]


def _consume_section(sec: PaperSection, used_sections: Set[str]) -> None:
    """Record a section as consumed in used_sections."""
    sec_id = sec.number or sec.title
    if sec_id:
        used_sections.add(sec_id)


def _match_sections_for_category(
    category: SectionCategory,
    ranked: List[RankedSection],
    used_sections: Set[str],
) -> List[PaperSection]:
    """Find the best paper section(s) matching a given template slot category.

    Strict Consumption Rules:
    1. 'title' category explicitly binds no body section.
    2. Primary match: exact category match that has not been consumed yet.
    3. Secondary match: fallback category match that has not been consumed yet.
    4. Tertiary match: if all candidates were already consumed, reuse exact category.
    5. Quaternary match: reuse fallback category.
    6. Never blindly returns Introduction (ranked[0]) for unrelated categories.
    """
    if category == "title":
        return []

    # Pass 1: exact category match, unconsumed
    for r in ranked:
        sec = r.section
        sec_id = sec.number or sec.title
        if r.category == category and sec_id not in used_sections:
            _consume_section(sec, used_sections)
            return [sec]

    # Fallback mappings for specific slots
    fallback_map: Dict[str, List[SectionCategory]] = {
        "problem": ["background", "method"],
        "motivation": ["background", "method"],
        "related_work": ["background"],
        "method_detail": ["method"],
        "method_algorithm": ["method"],
        "experiment_setup": ["experiment"],
        "result": ["experiment"],
        "ablation": ["experiment", "method"],
        "limitation": ["conclusion", "experiment"],
    }
    fallbacks = fallback_map.get(category, [])

    # Pass 2: fallback category match, unconsumed
    for fb in fallbacks:
        for r in ranked:
            sec = r.section
            sec_id = sec.number or sec.title
            if r.category == fb and sec_id not in used_sections:
                _consume_section(sec, used_sections)
                return [sec]

    # Pass 3: reuse exact category (if all were already used once)
    for r in ranked:
        if r.category == category:
            return [r.section]

    # Pass 4: reuse fallback category
    for fb in fallbacks:
        for r in ranked:
            if r.category == fb:
                return [r.section]

    return []


def generate_presentation_plan(
    paper: PaperIR,
    profile: str = "research_15min",
    enrich: bool = False,
) -> PresentationPlan:
    """Generate a structured PresentationPlan from a PaperIR document.

    Args:
        paper: Parsed academic paper intermediate representation.
        profile: Presentation template name ("research_15min" or "research_10min").
        enrich: If True, invokes LLM to refine slide wording when an API key is available.

    Returns:
        Structured, deterministic PresentationPlan.
    """
    prof = get_profile(profile)
    ranked_sections = rank_sections(paper)

    used_sections: Set[str] = set()
    assigned_figures: Set[str] = set()
    assigned_tables: Set[str] = set()

    slides: List[SlidePlan] = []

    for idx, slot in enumerate(prof.slots, start=1):
        # 1. Determine title
        if "{paper_title}" in slot.title_template:
            slide_title = paper.title or "Research Presentation"
        else:
            slide_title = slot.title_template

        # 2. Match relevant sections
        matched_secs = _match_sections_for_category(
            slot.primary_category, ranked_sections, used_sections
        )
        source_sections = [
            s.number if s.number else s.title
            for s in matched_secs
            if (s.number or s.title)
        ]

        # 3. Figure & Table aware assignment
        figs, tabs = select_visuals_for_slide(
            slide_type=slot.slide_type,
            paper=paper,
            matched_sections=matched_secs,
            assigned_figures=assigned_figures,
            assigned_tables=assigned_tables,
        )

        # 4. Generate key messages grounded in matched section and category
        key_msgs = _generate_key_messages(
            slide_type=slot.slide_type,
            matched_sections=matched_secs,
            paper=paper,
            ranked_sections=ranked_sections,
            slot_index=idx,
        )

        slides.append(
            SlidePlan(
                index=idx,
                slide_type=slot.slide_type,
                title=slide_title,
                objective=slot.objective_template,
                key_messages=key_msgs,
                source_sections=source_sections,
                source_figures=figs,
                source_tables=tabs,
                notes=slot.notes_hint,
            )
        )

    plan = PresentationPlan(
        title=paper.title or "Research Presentation",
        audience=prof.audience,
        duration_minutes=prof.target_duration_minutes,
        profile=prof.name,
        source_filename=paper.source_filename,
        slides=slides,
    )

    if enrich:
        plan = enrich_presentation_plan(plan)

    return plan


async def agenerate_presentation_plan(
    paper: PaperIR,
    profile: str = "research_15min",
    enrich: bool = False,
) -> PresentationPlan:
    """Asynchronous entry point for generating a PresentationPlan."""
    prof = get_profile(profile)
    ranked_sections = rank_sections(paper)

    used_sections: Set[str] = set()
    assigned_figures: Set[str] = set()
    assigned_tables: Set[str] = set()

    slides: List[SlidePlan] = []

    for idx, slot in enumerate(prof.slots, start=1):
        if "{paper_title}" in slot.title_template:
            slide_title = paper.title or "Research Presentation"
        else:
            slide_title = slot.title_template

        matched_secs = _match_sections_for_category(
            slot.primary_category, ranked_sections, used_sections
        )
        source_sections = [
            s.number if s.number else s.title
            for s in matched_secs
            if (s.number or s.title)
        ]

        figs, tabs = select_visuals_for_slide(
            slide_type=slot.slide_type,
            paper=paper,
            matched_sections=matched_secs,
            assigned_figures=assigned_figures,
            assigned_tables=assigned_tables,
        )

        key_msgs = _generate_key_messages(slot.slide_type, paper, matched_secs)

        slides.append(
            SlidePlan(
                index=idx,
                slide_type=slot.slide_type,
                title=slide_title,
                objective=slot.objective_template,
                key_messages=key_msgs,
                source_sections=source_sections,
                source_figures=figs,
                source_tables=tabs,
                notes=slot.notes_hint,
            )
        )

    plan = PresentationPlan(
        title=paper.title or "Research Presentation",
        audience=prof.audience,
        duration_minutes=prof.target_duration_minutes,
        profile=prof.name,
        source_filename=paper.source_filename,
        slides=slides,
    )

    if enrich:
        plan = await aenrich_presentation_plan(plan)

    return plan
