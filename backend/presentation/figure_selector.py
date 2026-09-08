"""Figure and Table Selection for Academic Slides (PR7.2).

Inspects figures and tables extracted in PaperIR and binds them to the most appropriate
slide types:
- METHOD_OVERVIEW: architecture / framework / pipeline / overview diagrams.
- RESULT: main comparative tables / performance bar charts / accuracy curves.
- ABLATION: ablation tables / component breakdown figures.
- EXPERIMENT_SETUP: dataset distribution / sample visualizations.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..paper.schema import PaperFigure, PaperIR, PaperSection, PaperTable
from .schema import SlideType

_OVERVIEW_PATTERNS = re.compile(r"\b(overview|architecture|framework|pipeline|workflow|system model|diagram)\b", re.IGNORECASE)
_ABLATION_PATTERNS = re.compile(r"\b(ablation|component|variant|sensitivity|hyperparameter|module breakdown)\b", re.IGNORECASE)
_RESULT_PATTERNS = re.compile(r"\b(result|comparison|performance|benchmark|accuracy|f1|precision|roc|auc|speed|efficiency|sota)\b", re.IGNORECASE)
_SETUP_PATTERNS = re.compile(r"\b(dataset|benchmark setting|distribution|sample|setup|example|case)\b", re.IGNORECASE)


def classify_figure_role(fig: PaperFigure) -> str:
    """Classify the likely communicative role of a figure based on its caption."""
    caption = fig.caption.lower()
    if _OVERVIEW_PATTERNS.search(caption) or fig.id in ("figure1", "fig1"):
        return "method_overview"
    if _ABLATION_PATTERNS.search(caption):
        return "ablation"
    if _RESULT_PATTERNS.search(caption):
        return "result"
    if _SETUP_PATTERNS.search(caption):
        return "experiment_setup"
    return "general"


def classify_table_role(table: PaperTable) -> str:
    """Classify the likely communicative role of a table based on its caption and header."""
    text = (table.caption + " " + " ".join(table.header)).lower()
    if _ABLATION_PATTERNS.search(text):
        return "ablation"
    if _RESULT_PATTERNS.search(text) or table.id in ("table1", "tab1"):
        return "result"
    if _SETUP_PATTERNS.search(text):
        return "experiment_setup"
    return "general"


def select_visuals_for_slide(
    slide_type: SlideType,
    paper: PaperIR,
    matched_sections: Optional[List[PaperSection]] = None,
    assigned_figures: Optional[set[str]] = None,
    assigned_tables: Optional[set[str]] = None,
) -> Tuple[List[str], List[str]]:
    """Select the most appropriate figures and tables for a slide.

    Returns:
        (source_figures, source_tables) - lists of IDs (e.g. ['figure1'], ['table1']).
    """
    assigned_figs = assigned_figures if assigned_figures is not None else set()
    assigned_tabs = assigned_tables if assigned_tables is not None else set()

    selected_figs: List[str] = []
    selected_tabs: List[str] = []

    matched_sec_nums = {s.number for s in (matched_sections or []) if s.number}

    if slide_type == SlideType.METHOD_OVERVIEW:
        # High priority: overview / architecture diagram
        for fig in paper.figures:
            if fig.id in assigned_figs:
                continue
            role = classify_figure_role(fig)
            if role in ("method_overview", "general") and fig.id in ("figure1", "fig1"):
                selected_figs.append(fig.id)
                assigned_figs.add(fig.id)
                break
        # Fallback if figure1 was already used or not named figure1
        if not selected_figs:
            for fig in paper.figures:
                if fig.id in assigned_figs:
                    continue
                if classify_figure_role(fig) == "method_overview":
                    selected_figs.append(fig.id)
                    assigned_figs.add(fig.id)
                    break

    elif slide_type == SlideType.METHOD_DETAIL:
        # Check for intermediate figures referenced in method section
        for fig in paper.figures:
            if fig.id in assigned_figs:
                continue
            if classify_figure_role(fig) in ("general", "method_overview"):
                selected_figs.append(fig.id)
                assigned_figs.add(fig.id)
                break

    elif slide_type == SlideType.RESULT:
        # Primary: Main comparative table or result figure
        for tab in paper.tables:
            if tab.id in assigned_tabs:
                continue
            if classify_table_role(tab) == "result":
                selected_tabs.append(tab.id)
                assigned_tabs.add(tab.id)
                break

        # Also look for a result figure if available
        for fig in paper.figures:
            if fig.id in assigned_figs:
                continue
            if classify_figure_role(fig) == "result":
                selected_figs.append(fig.id)
                assigned_figs.add(fig.id)
                break

    elif slide_type == SlideType.ABLATION:
        # Prioritize ablation table or ablation figure
        for tab in paper.tables:
            if tab.id in assigned_tabs:
                continue
            if classify_table_role(tab) == "ablation":
                selected_tabs.append(tab.id)
                assigned_tabs.add(tab.id)
                break
        for fig in paper.figures:
            if fig.id in assigned_figs:
                continue
            if classify_figure_role(fig) == "ablation":
                selected_figs.append(fig.id)
                assigned_figs.add(fig.id)
                break

        # Fallback: if no dedicated ablation table, any unused table
        if not selected_tabs and not selected_figs:
            for tab in paper.tables:
                if tab.id not in assigned_tabs:
                    selected_tabs.append(tab.id)
                    assigned_tabs.add(tab.id)
                    break

    elif slide_type == SlideType.EXPERIMENT_SETUP:
        # Setup tables (e.g. dataset statistics)
        for tab in paper.tables:
            if tab.id in assigned_tabs:
                continue
            if classify_table_role(tab) == "experiment_setup":
                selected_tabs.append(tab.id)
                assigned_tabs.add(tab.id)
                break

    return selected_figs, selected_tabs
