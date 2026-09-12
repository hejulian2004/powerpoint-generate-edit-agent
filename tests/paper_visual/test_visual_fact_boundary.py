"""Fact boundary: PaperIR text is authority; visual descriptions are not.

The vision analyzer is explicitly forbidden from producing numeric/scientific
facts. These tests pin the boundary using the EXISTING grounding/validator stack
(no parallel ``EvidenceAuthority`` system).
"""

from __future__ import annotations

from backend.agent.grounding import data_claim_numbers, unsupported_numbers
from backend.paper.schema import PaperIR, PaperSection
from backend.pptspec.validator import check_token_in_raw_text, parse_numeric_tokens


def _paper() -> PaperIR:
    return PaperIR(
        sections=[
            PaperSection(
                number="4",
                title="Results",
                paragraphs=[
                    "Table 1 reports that Ours achieves an accuracy of 0.90 with latency 11 ms on the benchmark."
                ],
            )
        ],
    )


def _paper_text(paper: PaperIR) -> str:
    return paper.body_section_text()


def test_visual_region_number_is_not_admissible_fact():
    paper = _paper()
    source = _paper_text(paper)

    # This is what a misbehaving vision model might wrongly emit as a region
    # description. It must NOT be treated as factual evidence.
    region_description = "A bar chart showing a 12.3% improvement over all baselines."
    unsupported = data_claim_numbers(region_description, source)
    assert unsupported, "vision-inferred numeric claim must be flagged as unsupported"


def test_paper_number_is_admissible_fact():
    paper = _paper()
    source = _paper_text(paper)

    token = next(
        t for t in parse_numeric_tokens("accuracy 0.90")
        if t.raw_text.strip() == "0.90"
    )
    assert check_token_in_raw_text(token, source) is True
    assert unsupported_numbers("accuracy 0.90", source) == []


def test_paper_ir_is_required_factual_authority():
    paper = _paper()
    source = _paper_text(paper)
    # A number that appears only in a visual description and nowhere in PaperIR
    # must remain unsupported.
    assert unsupported_numbers("latency 5 ms", source) == ["5 ms"]


def test_visual_ir_region_description_is_never_source_text():
    """PaperVisualIR fields are not scanned as grounding sources by the pipeline."""
    from backend.paper_visual.schema import PaperVisualIR

    assert not hasattr(PaperVisualIR, "grounding_text")
    assert not hasattr(PaperVisualIR, "body_section_text")
