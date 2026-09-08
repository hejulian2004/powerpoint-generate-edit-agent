"""Research Presentation Templates (PR7.2).

Defines standard academic slide profiles for computer science research talks:
1. research_15min (12 slides): 15-minute lab seminar / conference talk.
2. research_10min (8 slides): 10-minute fast overview / spotlight presentation.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional

from ..schema import SlideType


class SlideTemplateSlot(NamedTuple):
    """Specification for a planned slide slot in a profile."""

    slide_type: SlideType
    title_template: str
    objective_template: str
    primary_category: str
    notes_hint: str
    fallback_type: Optional[SlideType] = None


class PresentationProfile(NamedTuple):
    """Template profile configuration."""

    name: str
    target_duration_minutes: int
    audience: str
    slots: List[SlideTemplateSlot]


RESEARCH_15MIN_SLOTS: List[SlideTemplateSlot] = [
    SlideTemplateSlot(
        slide_type=SlideType.TITLE,
        title_template="{paper_title}",
        objective_template="Introduce the research topic, authors, and primary contribution.",
        primary_category="title",
        notes_hint="Welcome the audience and state the main thesis in 30 seconds.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.BACKGROUND,
        title_template="Research Background & Context",
        objective_template="Establish the domain setting, practical relevance, and emerging trends.",
        primary_category="background",
        notes_hint="Highlight why this field matters today and the real-world deployment setting.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.PROBLEM,
        title_template="Problem Definition & Challenges",
        objective_template="Articulate the core problem formulation, fundamental bottlenecks, and failure modes.",
        primary_category="problem",
        notes_hint="Explain why existing paradigms fail or encounter severe bottlenecks.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.MOTIVATION,
        title_template="Key Insight & Motivation",
        objective_template="Present the central hypothesis and conceptual motivation behind the proposed solution.",
        primary_category="motivation",
        notes_hint="Connect the identified bottleneck directly to the proposed core intuition.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.RELATED_WORK,
        title_template="Related Work & Comparison",
        objective_template="Contextualize against prior art and contrast core technical differentiators.",
        primary_category="related_work",
        notes_hint="Succinctly contrast prior methods and position this work's uniqueness.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.METHOD_OVERVIEW,
        title_template="Methodology: Overall Framework",
        objective_template="Provide an end-to-end architectural walk-through of the system pipeline.",
        primary_category="method",
        notes_hint="Walk through the overall framework using the architecture diagram.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.METHOD_DETAIL,
        title_template="Core Mechanism & Formulation",
        objective_template="Explain primary algorithmic components, representations, and mathematical formulation.",
        primary_category="method_detail",
        notes_hint="Detail key mathematical formulations or agent action spaces.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.METHOD_DETAIL,
        title_template="Training & Optimization Pipeline",
        objective_template="Describe loss objectives, optimization algorithms, and training dynamics.",
        primary_category="method_algorithm",
        notes_hint="Describe training objectives, policy optimization, or pipeline guarantees.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.EXPERIMENT_SETUP,
        title_template="Experimental Setup & Benchmarks",
        objective_template="Outline datasets, evaluation metrics, baselines, and implementation protocols.",
        primary_category="experiment_setup",
        notes_hint="Present the datasets, baseline selection, and rigorous evaluation metrics.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.RESULT,
        title_template="Main Results & Comparative Evaluation",
        objective_template="Demonstrate quantitative superiority and empirical breakthroughs over SOTA baselines.",
        primary_category="result",
        notes_hint="Highlight quantitative performance gains and statistical significance.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.ABLATION,
        title_template="Ablation Studies & Analysis",
        objective_template="Dissect contribution of individual components, hyperparameter sensitivity, and trade-offs.",
        primary_category="ablation",
        notes_hint="Prove each proposed component is necessary via ablation evidence.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.CONCLUSION,
        title_template="Conclusion & Future Horizons",
        objective_template="Summarize principal takeaways, acknowledge limitations, and outline future directions.",
        primary_category="conclusion",
        notes_hint="Conclude with high-level takeaways and invite questions.",
    ),
]


RESEARCH_10MIN_SLOTS: List[SlideTemplateSlot] = [
    SlideTemplateSlot(
        slide_type=SlideType.TITLE,
        title_template="{paper_title}",
        objective_template="Introduce research topic, authors, and main proposition.",
        primary_category="title",
        notes_hint="Deliver a crisp opening pitch in 20 seconds.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.BACKGROUND,
        title_template="Background & Key Bottlenecks",
        objective_template="Explain the core challenge and why existing approaches fall short.",
        primary_category="background",
        notes_hint="Cover problem setting and motivation concisely.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.METHOD_OVERVIEW,
        title_template="Proposed Approach: Overall Architecture",
        objective_template="Outline the end-to-end framework and primary algorithmic innovation.",
        primary_category="method",
        notes_hint="Guide the audience through the framework diagram.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.METHOD_DETAIL,
        title_template="Key Technical Mechanics",
        objective_template="Highlight the most critical component enabling performance breakthroughs.",
        primary_category="method_detail",
        notes_hint="Focus only on the single most novel technical insight.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.EXPERIMENT_SETUP,
        title_template="Experimental Benchmark Setup",
        objective_template="Summarize evaluation benchmarks, key metrics, and comparative baselines.",
        primary_category="experiment_setup",
        notes_hint="Set the stage for empirical results briefly.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.RESULT,
        title_template="Key Empirical Findings & Comparison",
        objective_template="Present main quantitative performance gains against leading competitors.",
        primary_category="result",
        notes_hint="Showcase the headline metric improvements.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.LIMITATION,
        title_template="Discussion & Limitations",
        objective_template="Acknowledge computational costs, edge cases, and scope boundaries.",
        primary_category="limitation",
        notes_hint="Demonstrate scholarly rigor by addressing known limitations.",
    ),
    SlideTemplateSlot(
        slide_type=SlideType.CONCLUSION,
        title_template="Summary & Key Takeaways",
        objective_template="Reiterate the main message and potential impact.",
        primary_category="conclusion",
        notes_hint="Deliver memorable final conclusions and open for Q&A.",
    ),
]


PROFILES: Dict[str, PresentationProfile] = {
    "research_15min": PresentationProfile(
        name="research_15min",
        target_duration_minutes=15,
        audience="Research Lab / Academic Seminar",
        slots=RESEARCH_15MIN_SLOTS,
    ),
    "research_10min": PresentationProfile(
        name="research_10min",
        target_duration_minutes=10,
        audience="Conference Spotlight / Quick Seminar",
        slots=RESEARCH_10MIN_SLOTS,
    ),
}


def get_profile(name: str = "research_15min") -> PresentationProfile:
    """Retrieve template profile by name, falling back to research_15min."""
    if name not in PROFILES:
        return PROFILES["research_15min"]
    return PROFILES[name]
