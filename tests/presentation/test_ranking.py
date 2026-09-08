"""Tests for Section Importance Ranking (PR7.2)."""

from pathlib import Path

from backend.paper.parser import extract_paper
from backend.presentation.ranking import classify_section_category, rank_sections

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_classify_section_category():
    assert classify_section_category("1. Introduction") == "background"
    assert classify_section_category("Related Work") == "related_work"
    assert classify_section_category("3. Problem Definition") == "problem"
    assert classify_section_category("4. Method") == "method"
    assert classify_section_category("5. Experiments") == "experiment"
    assert classify_section_category("6. Conclusion") == "conclusion"
    assert classify_section_category("References") == "ignored"
    assert classify_section_category("Appendix A") == "ignored"


def test_rank_sections_on_anomaly_agent():
    paper = extract_paper(FIXTURE_PDF)
    ranked = rank_sections(paper)
    assert len(ranked) == len(paper.sections)

    # Method & Experiments should rank high
    top_categories = [r.category for r in ranked[:3]]
    assert "method" in top_categories or "experiment" in top_categories

    # Check scores ordering
    scores = [r.importance_score for r in ranked]
    assert scores == sorted(scores, reverse=True)

    # Verify References/Appendix if any gets lowest score
    ignored = [r for r in ranked if r.category == "ignored"]
    for ign in ignored:
        assert ign.importance_score <= 0.1
