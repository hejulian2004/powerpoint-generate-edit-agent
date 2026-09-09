"""Unit tests for CanonicalPPTSpec Schema (PR13 Step 1)."""

import pytest
from pydantic import ValidationError

from backend.presentation.schema import SlideType
from backend.slidespec.schema import VisualIntent
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    PresentationConfig,
    SourcePolicy,
    SourceDocument,
    ClaimEvidence,
    MetricEvidence,
    MetricGroupEvidence,
    MetricEntry,
    TableEvidence,
    FigureReferenceEvidence,
    EquationEvidence,
    QuoteEvidence,
    SlideRequest,
    AssetRequirement,
    EvidenceKind,
)


def test_canonical_spec_valid():
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(
            title="Transformer Interpretability Study",
            language="zh-CN",
            duration_minutes=15,
        ),
        source_policy=SourcePolicy(),
        source_document=SourceDocument(title="Attention Is All You Need", year=2017),
        evidence=[
            ClaimEvidence(id="ev_c1", content="Self-attention replaces recurrence completely."),
            MetricEvidence(id="ev_m1", name="BLEU", value="28.4", unit="points"),
            FigureReferenceEvidence(id="ev_fig1", label="Figure 1", caption="Model Architecture", source_page=3),
            TableEvidence(
                id="ev_tbl1",
                columns=["Model", "BLEU"],
                rows=[["Transformer (base)", "27.3"], ["Transformer (big)", "28.4"]],
                caption="BLEU Comparison",
            ),
        ],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.TITLE,
                title="Attention Is All You Need",
                objective="Introduce the paper",
                evidence_refs=["ev_c1"],
            ),
            SlideRequest(
                id="slide_02",
                type=SlideType.RESULT,
                title="Translation Performance",
                visual_intent=VisualIntent.BENCHMARK_COMPARISON,
                evidence_refs=["ev_m1", "ev_tbl1", "ev_fig1"],
            ),
        ],
    )

    assert spec.spec_version == "1.0"
    assert len(spec.slides) == 2
    assert len(spec.evidence) == 4
    assert spec.get_evidence("ev_m1") is not None
    assert spec.get_evidence("non_existent") is None


def test_canonical_spec_extra_forbid():
    """Verify that internal schema forbids any extra fields."""
    with pytest.raises(ValidationError):
        PresentationConfig(title="Test", unknown_field="invalid")  # type: ignore

    with pytest.raises(ValidationError):
        SlideRequest(
            id="s1",
            type=SlideType.BACKGROUND,
            title="BG",
            rogue_data=123,  # type: ignore
        )

    with pytest.raises(ValidationError):
        CanonicalPPTSpec(
            spec_version="1.0",
            presentation=PresentationConfig(title="Test"),
            unexpected_top_level="hacked",  # type: ignore
        )


def test_table_evidence_dimension_validation():
    # Matching rows and columns -> complete_table is True
    t1 = TableEvidence(
        id="t1",
        columns=["Col A", "Col B"],
        rows=[["1", "2"], ["3", "4"]],
    )
    assert t1.complete_table is True

    # Row length mismatch -> complete_table becomes False
    t2 = TableEvidence(
        id="t2",
        columns=["Col A", "Col B"],
        rows=[["1", "2"], ["3"]],  # Missing second column
    )
    assert t2.complete_table is False

    # Empty rows -> complete_table is False
    t3 = TableEvidence(
        id="t3",
        columns=["Col A"],
        rows=[],
    )
    assert t3.complete_table is False


def test_asset_requirements_extraction():
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Asset Test"),
        evidence=[
            FigureReferenceEvidence(id="fig_1", label="Figure 3", source_page=5, caption="Overview"),
            FigureReferenceEvidence(id="fig_2", label="Figure 4", source_page=7),
            TableEvidence(id="tbl_inc", columns=["A", "B"], rows=[["1"]], caption="Partial Results", complete_table=False),
            TableEvidence(id="tbl_comp", columns=["A", "B"], rows=[["1", "2"]], caption="Full Results", complete_table=True),
        ],
        slides=[
            SlideRequest(
                id="s_method",
                type=SlideType.METHOD_OVERVIEW,
                title="Method",
                evidence_refs=["fig_1", "tbl_inc"],
            ),
            SlideRequest(
                id="s_result",
                type=SlideType.RESULT,
                title="Results",
                evidence_refs=["fig_2", "tbl_comp"],
            ),
        ],
    )

    reqs = spec.get_asset_requirements()
    # Should include 2 figures and 1 incomplete table (complete table does not need manual insertion)
    assert len(reqs) == 3
    fig_reqs = [r for r in reqs if r.asset_type == "figure"]
    tbl_reqs = [r for r in reqs if r.asset_type == "table"]
    assert len(fig_reqs) == 2
    assert len(tbl_reqs) == 1
    assert fig_reqs[0].label == "Figure 3"
    assert fig_reqs[0].page == 5
    assert tbl_reqs[0].label == "Partial Results"
