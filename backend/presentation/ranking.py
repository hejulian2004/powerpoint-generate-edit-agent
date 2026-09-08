"""Section Importance Ranking & Academic Role Classification (PR7.2).

Analyzes PaperIR sections and scores their presentation importance (0.0 to 1.0)
along with classifying each section into canonical research roles:
- background
- problem
- motivation
- related_work
- method
- experiment
- ablation
- limitation
- conclusion
- ignored (references, appendix, acknowledgments)
"""

from __future__ import annotations

import re
from typing import Dict, List, Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from ..paper.schema import PaperIR, PaperSection

# Canonical roles in computer science paper presentation
SectionCategory = Literal[
    "title",
    "background",
    "problem",
    "motivation",
    "related_work",
    "method",
    "experiment",
    "ablation",
    "limitation",
    "conclusion",
    "ignored",
]


class RankedSection(BaseModel):
    """Section metadata augmented with relevance score and presentation category."""

    section: PaperSection
    category: SectionCategory = Field(..., description="Canonical presentation role")
    importance_score: float = Field(..., ge=0.0, le=1.0, description="Normalized relevance (0.0-1.0)")
    word_count: int = Field(0, description="Estimated words in paragraphs")
    figure_mentions: int = Field(0, description="Count of Fig./Figure references")
    table_mentions: int = Field(0, description="Count of Table references")


_IGNORE_PATTERNS = [
    re.compile(r"^references?$", re.IGNORECASE),
    re.compile(r"^bibliography$", re.IGNORECASE),
    re.compile(r"^acknowledg[e]?ments?$", re.IGNORECASE),
    re.compile(r"^appendix.*$", re.IGNORECASE),
    re.compile(r"^broader impact.*$", re.IGNORECASE),
]

_CATEGORY_PATTERNS: List[tuple[SectionCategory, re.Pattern]] = [
    ("limitation", re.compile(r"\b(limitation[s]?|threats to validity)\b", re.IGNORECASE)),
    ("ablation", re.compile(r"\b(ablation|ablation study|parameter sensitivity)\b", re.IGNORECASE)),
    ("experiment", re.compile(r"\b(experiment[s]?|evaluation|empirical study|results?|benchmark)\b", re.IGNORECASE)),
    ("method", re.compile(r"\b(method|methodology|approach|proposed framework|architecture|model|formulation|algorithm)\b", re.IGNORECASE)),
    ("problem", re.compile(r"\b(problem (definition|formulation|statement)|preliminar(y|ies))\b", re.IGNORECASE)),
    ("motivation", re.compile(r"\b(motivation|key insight|intuition)\b", re.IGNORECASE)),
    ("related_work", re.compile(r"\b(related work|literature review|prior art|background and related work)\b", re.IGNORECASE)),
    ("conclusion", re.compile(r"\b(conclusion[s]?|summary and future work|discussion and conclusion)\b", re.IGNORECASE)),
    ("background", re.compile(r"\b(introduction|background|overview)\b", re.IGNORECASE)),
]

# Baseline category weights (computer science research emphasis: Method & Results lead)
_CATEGORY_BASE_WEIGHTS: Dict[SectionCategory, float] = {
    "method": 1.0,
    "experiment": 0.95,
    "ablation": 0.90,
    "problem": 0.85,
    "motivation": 0.80,
    "background": 0.70,
    "conclusion": 0.65,
    "related_work": 0.60,
    "limitation": 0.55,
    "title": 0.50,
    "ignored": 0.05,
}


def classify_section_category(title: str) -> SectionCategory:
    """Classify a section title into canonical research presentation category."""
    clean_title = title.strip().lower()

    # Check ignore list
    for pat in _IGNORE_PATTERNS:
        if pat.search(clean_title):
            return "ignored"

    # Match category patterns
    for cat, pat in _CATEGORY_PATTERNS:
        if pat.search(clean_title):
            return cat

    return "method"  # Default substantive fallback for numbered body sections


def _count_words(text: str) -> int:
    return len(text.split())


def _count_pattern(text: str, pattern: re.Pattern) -> int:
    return len(pattern.findall(text))


_FIG_PAT = re.compile(r"\b(?:fig\.?|figure)\s*\d+", re.IGNORECASE)
_TAB_PAT = re.compile(r"\b(?:table|tab\.?)\s*\d+", re.IGNORECASE)


def rank_sections(paper: PaperIR) -> List[RankedSection]:
    """Score and categorize all sections in the given PaperIR."""
    if not paper.sections:
        return []

    ranked: List[RankedSection] = []
    max_words = 1

    # First pass: collect metrics
    temp_metrics = []
    for sec in paper.sections:
        body = " ".join(sec.paragraphs)
        w_count = _count_words(body)
        f_count = _count_pattern(body, _FIG_PAT)
        t_count = _count_pattern(body, _TAB_PAT)
        category = classify_section_category(sec.title)
        if w_count > max_words:
            max_words = w_count
        temp_metrics.append((sec, category, w_count, f_count, t_count))

    # Second pass: calculate normalized importance score
    for sec, category, w_count, f_count, t_count in temp_metrics:
        if category == "ignored":
            score = 0.05
        else:
            base = _CATEGORY_BASE_WEIGHTS.get(category, 0.50)
            # Bonus for having figures / tables mentioned (+0.05 each, capped at +0.10)
            visual_bonus = min(0.10, (f_count + t_count) * 0.03)
            # Length penalty for empty/nearly empty sections (<30 words)
            length_factor = 1.0 if w_count >= 30 else max(0.4, w_count / 30.0)

            score = min(1.0, (base + visual_bonus) * length_factor)

        ranked.append(
            RankedSection(
                section=sec,
                category=category,
                importance_score=round(score, 3),
                word_count=w_count,
                figure_mentions=f_count,
                table_mentions=t_count,
            )
        )

    # Sort descending by importance score, maintaining stable order for ties
    return sorted(ranked, key=lambda r: r.importance_score, reverse=True)


def get_sections_by_category(
    ranked: List[RankedSection],
    category: SectionCategory,
) -> List[RankedSection]:
    """Filter ranked sections by presentation category."""
    return [r for r in ranked if r.category == category]
