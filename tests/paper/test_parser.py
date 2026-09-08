"""PR7.1 acceptance tests for the Paper Understanding Core.

Validates that a paper PDF is converted into a deterministic, structure-complete
``PaperIR`` (title / sections / figure & table counts), that it serializes to a
golden ``paper_ir.json`` round-trip, and that the optional LLM enrichment layer
degrades gracefully without a live API key.
"""

from pathlib import Path

import pytest

from backend.paper import (
    PaperIR,
    apply_enrichment,
    extract_paper,
)

FIXTURE = Path("tests/fixtures/paper/anomaly_agent.pdf")

EXPECTED_TITLE = (
    "AnomalyAgent: Tool-Augmented Reinforcement Learning for "
    "Industrial Anomaly Synthesis"
)

EXPECTED_SECTIONS = [
    ("1", "Introduction"),
    ("2", "Related Work"),
    ("3", "Problem Definition"),
    ("4", "Method"),
    ("5", "Experiments"),
    ("6", "Conclusion"),
]


def _paper() -> PaperIR:
    assert FIXTURE.exists(), f"Missing fixture: {FIXTURE}"
    return extract_paper(FIXTURE)


def test_parser_title():
    paper = _paper()
    assert paper.title == EXPECTED_TITLE


def test_parser_sections_order_and_page():
    paper = _paper()
    numbered = [(s.number, s.title) for s in paper.sections if s.number]
    assert numbered == EXPECTED_SECTIONS
    # sections appear in increasing page order
    pages = [s.page for s in paper.sections if s.number]
    assert pages == sorted(pages)
    assert pages[0] >= 1


def test_parser_sections_clean_number_title():
    paper = _paper()
    intro = paper.sections[0]
    assert intro.number == "1"
    assert intro.title == "Introduction"
    # numeric prefix should not leak into the title field
    assert not intro.title.startswith("1.")


def test_parser_section_paragraph_content():
    paper = _paper()
    intro = paper.sections[0]
    assert len(intro.paragraphs) >= 3
    joined = " ".join(intro.paragraphs).lower()
    assert "anomaly" in joined
    assert "reinforcement learning" in joined


def test_parser_abstract_present():
    paper = _paper()
    assert paper.abstract.strip() != ""
    assert "industrial anomaly" in paper.abstract.lower()


def test_parser_figure_count_and_captions():
    paper = _paper()
    assert len(paper.figures) == 3
    ids = [f.id for f in paper.figures]
    assert ids == ["figure1", "figure2", "figure3"]
    captions = " ".join(f.caption for f in paper.figures).lower()
    assert "framework" in captions
    assert "reward curve" in captions


def test_parser_figure_raster_region():
    paper = _paper()
    for fig in paper.figures:
        assert fig.is_raster is True, f"{fig.id} should map to a raster region"
        assert fig.bbox is not None
        assert fig.bbox.width > 0 and fig.bbox.height > 0
        assert fig.page >= 1


def test_parser_table_count_and_captions():
    paper = _paper()
    assert len(paper.tables) == 2
    assert paper.tables[0].id == "table1"
    assert paper.tables[1].id == "table2"
    assert "Detection AUROC" in paper.tables[0].caption
    assert "Ablation" in paper.tables[1].caption


def test_parser_metadata():
    paper = _paper()
    assert paper.metadata.page_count >= 1
    assert paper.metadata.authors  # at least one author line captured
    assert paper.source_filename == "anomaly_agent.pdf"


def test_extract_is_deterministic():
    first = extract_paper(FIXTURE).to_dict()
    second = extract_paper(FIXTURE).to_dict()
    assert first == second


def test_paper_ir_json_roundtrip(tmp_path: Path):
    paper = _paper()
    out = tmp_path / "paper_ir.json"
    written = paper.to_json_file(out)
    assert written.exists()
    loaded = PaperIR.from_json_file(out)
    assert loaded.to_dict() == paper.to_dict()


def test_semantic_fields_default_empty():
    paper = _paper()
    assert paper.contributions == []
    assert paper.methodology == []
    assert paper.experiments == []
    assert paper.limitations == []
    assert paper.extraction.semantic_status == "extracted"


def test_enrich_unchanged_without_api_key():
    paper = extract_paper(FIXTURE, enrich=True)
    # Without a live (non-mock) API key, enrichment is a no-op.
    assert paper.extraction.semantic_status == "extracted"
    assert paper.contributions == []


def test_apply_enrichment_merges_semantics():
    paper = _paper()
    enriched = apply_enrichment(
        paper,
        {
            "contributions": ["Tool-Augmented RL", "Industrial anomaly synthesis"],
            "methodology": ["Policy network with tool-selection head"],
            "experiments": ["12.4% AUROC gain over baselines"],
            "limitations": ["Requires annotated seed data"],
        },
    )
    assert enriched.extraction.semantic_status == "enriched"
    assert enriched.contributions == ["Tool-Augmented RL", "Industrial anomaly synthesis"]
    assert len(enriched.methodology) == 1
    assert len(enriched.experiments) == 1
    assert len(enriched.limitations) == 1
    # original PaperIR is not mutated
    assert paper.extraction.semantic_status == "extracted"
    assert paper.contributions == []


def test_apply_enrichment_sanitizes_malformed():
    paper = _paper()
    enriched = apply_enrichment(paper, {"contributions": "single string", "methodology": 42})
    assert enriched.contributions == ["single string"]
    assert enriched.methodology == []


@pytest.mark.parametrize(
    "fixture",
    ["tests/fixtures/paper/anomaly_agent.pdf"],
)
def test_acceptance_counts(fixture: str):
    """The PR7.1 acceptance gate: exact structural counts for the demo paper."""
    paper = extract_paper(fixture)
    assert paper.title == EXPECTED_TITLE
    assert [s.number for s in paper.sections if s.number] == ["1", "2", "3", "4", "5", "6"]
    assert len(paper.figures) == 3
    assert len(paper.tables) == 2