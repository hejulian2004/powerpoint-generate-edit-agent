"""Tests for Figure & Table Selection (PR7.2)."""

from pathlib import Path

from backend.paper.parser import extract_paper
from backend.presentation.figure_selector import (
    classify_figure_role,
    classify_table_role,
    select_visuals_for_slide,
)
from backend.presentation.schema import SlideType

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_figure_classification_and_selection():
    paper = extract_paper(FIXTURE_PDF)
    assert len(paper.figures) >= 3
    assert len(paper.tables) >= 2

    # Method overview should pick figure1 (framework overview)
    figs_overview, tabs_overview = select_visuals_for_slide(
        SlideType.METHOD_OVERVIEW,
        paper,
    )
    assert "figure1" in figs_overview

    # Result slide should pick table1 or result figure
    figs_res, tabs_res = select_visuals_for_slide(
        SlideType.RESULT,
        paper,
    )
    assert len(tabs_res) > 0 or len(figs_res) > 0
    if tabs_res:
        assert "table1" in tabs_res or "table2" in tabs_res

    # Ablation slide should pick table2 or ablation figure
    figs_abl, tabs_abl = select_visuals_for_slide(
        SlideType.ABLATION,
        paper,
    )
    assert len(tabs_abl) > 0 or len(figs_abl) > 0
