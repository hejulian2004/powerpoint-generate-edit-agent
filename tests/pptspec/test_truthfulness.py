"""Unit tests for Truthfulness Guard & Numeric Provenance Guard (PR13 Step 1)."""

import pytest
from backend.presentation.schema import SlideType
from backend.pptspec.errors import (
    UnsupportedNumericError,
    UnsupportedTextualFactError,
    InvalidEvidenceReferenceError,
)
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    PresentationConfig,
    SourceDocument,
    ClaimEvidence,
    MetricEvidence,
    MetricGroupEvidence,
    MetricEntry,
    TableEvidence,
    FigureReferenceEvidence,
    SlideRequest,
)
from backend.pptspec.validator import (
    NumericToken,
    collect_factual_numeric_tokens,
    validate_truthfulness,
    TruthfulnessValidator,
    normalize_for_textual_match,
)


def test_truthfulness_numeric_provenance_valid():
    raw_input = """
    We evaluate our proposed AnomalyAgent on three benchmarks.
    AnomalyAgent achieves an accuracy of 89.5% and F1 score of 0.884.
    AnomalyAgent achieves high precision.
    Latency is reduced to 45ms.
    Refer to Figure 3 on page 5.
    """

    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(
            title="AnomalyAgent Paper",
            duration_minutes=15,  # Structural number 15 not in raw_input - should NOT raise!
        ),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="89.5%"),
            MetricEvidence(id="m2", name="F1", value="0.884"),
            MetricEvidence(id="m3", name="Latency", value="45", unit="ms"),
            FigureReferenceEvidence(id="fig3", label="Figure 3", source_page=5),  # 3 and 5 are label/page
            ClaimEvidence(id="c1", content="AnomalyAgent achieves high precision."),
        ],
        slides=[
            SlideRequest(
                id="slide_01",  # 01 is slide id - should NOT raise!
                type=SlideType.RESULT,
                title="Performance",
                evidence_refs=["m1", "m2", "m3", "fig3", "c1"],
            )
        ],
    )

    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True
    assert len(res.errors) == 0


def test_truthfulness_rejects_unsupported_numeric_value():
    raw_input = """
    Our model achieved an accuracy of 89.5%.
    """

    # Spec hallucinates 93.7% which does not exist in raw_input
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m_real", name="Accuracy", value="89.5%"),
            MetricEvidence(id="m_fake", name="SOTA Accuracy", value="93.7%"),
        ],
        slides=[
            SlideRequest(
                id="s1",
                type=SlideType.RESULT,
                title="Results",
                evidence_refs=["m_real", "m_fake"],
            )
        ],
    )

    # In strict mode, should raise UnsupportedNumericError
    with pytest.raises(UnsupportedNumericError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert "93.7" in str(exc_info.value)

    # In non-strict mode, should report error without raising
    validator = TruthfulnessValidator(strict=False)
    res = validator.validate(raw_input, spec)
    assert res.valid is False
    assert any("93.7" in err for err in res.errors)


def test_structural_numbers_are_exempt_from_provenance():
    raw_input = "We present a simple study without numeric metrics. A purely qualitative claim without numbers."

    spec = CanonicalPPTSpec(
        spec_version="1.0",  # "1.0"
        presentation=PresentationConfig(
            title="Paper Study",
            duration_minutes=20,  # "20"
        ),
        evidence=[
            FigureReferenceEvidence(id="fig_9", label="Figure 9", source_page=42),  # "9", "42"
            ClaimEvidence(id="c1", content="A purely qualitative claim without numbers."),
        ],
        slides=[
            SlideRequest(
                id="slide_99",  # "99"
                type=SlideType.CONCLUSION,
                title="Conclusion",
                evidence_refs=["fig_9", "c1"],
            )
        ],
    )

    # None of 1.0, 20, 9, 42, 99 are in raw_input, but they are structural and must be exempt!
    tokens = collect_factual_numeric_tokens(spec)
    assert len(tokens) == 0

    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True


def test_invalid_evidence_reference_guard():
    raw_input = "We introduce our framework. Existing claim."

    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Paper Study"),
        evidence=[
            ClaimEvidence(id="ev_exist", content="Existing claim."),
        ],
        slides=[
            SlideRequest(
                id="s1",
                type=SlideType.BACKGROUND,
                title="Background",
                evidence_refs=["ev_exist", "ev_ghost"],  # ev_ghost does not exist
            )
        ],
    )

    with pytest.raises(InvalidEvidenceReferenceError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert "ev_ghost" in str(exc_info.value)


def test_textual_provenance_rejects_hallucinated_claim():
    """Textual provenance guard rejects claims not grounded in raw text."""
    raw_input = "Our method is evaluated on standard benchmarks."

    # Spec invents a qualitative finding not present in raw_input
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Qualitative Finding"),
        evidence=[
            ClaimEvidence(id="c_fake", content="Our model outperforms human experts by a wide margin."),
        ],
        slides=[
            SlideRequest(id="s1", type=SlideType.RESULT, title="Result", evidence_refs=["c_fake"])
        ],
    )

    with pytest.raises(UnsupportedTextualFactError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert "outperforms human experts" in str(exc_info.value)

    # In non-strict mode: valid is False, error is captured
    res = validate_truthfulness(raw_input, spec, strict=False)
    assert res.valid is False
    assert any("UNSUPPORTED_TEXTUAL_FACT" in e for e in res.errors)


def test_textual_provenance_rejects_hallucinated_author_or_venue():
    """SourceDocument authors and venue must be grounded in raw input."""
    raw_input = "Paper by Alice and Bob presented at ICSE 2024."

    # Hallucinated author Charlie
    spec_fake_author = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Paper"),
        source_document=SourceDocument(authors=["Alice", "Charlie"], venue="ICSE 2024"),
        slides=[SlideRequest(id="s1", type=SlideType.TITLE, title="Title")],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_author, strict=True)

    # Hallucinated venue NeurIPS 2024
    spec_fake_venue = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Paper"),
        source_document=SourceDocument(authors=["Alice", "Bob"], venue="NeurIPS 2024"),
        slides=[SlideRequest(id="s1", type=SlideType.TITLE, title="Title")],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_venue, strict=True)


def test_comparator_and_unit_strict_equivalence():
    """Comparator and unit semantics must be enforced."""
    # <0.05 is NOT equivalent to 0.05
    tok_lt = NumericToken(raw_text="<0.05", value="0.05", comparator="<")
    tok_eq = NumericToken(raw_text="0.05", value="0.05")
    assert not tok_lt.is_equivalent(tok_eq)

    # 10% is NOT equivalent to 10
    tok_pct = NumericToken(raw_text="10%", value="10", percent=True)
    tok_num = NumericToken(raw_text="10", value="10", percent=False)
    assert not tok_pct.is_equivalent(tok_num)

    # 0.5ms is NOT equivalent to 0.5s
    tok_ms = NumericToken(raw_text="0.5ms", value="0.5", unit="ms")
    tok_s = NumericToken(raw_text="0.5s", value="0.5", unit="s")
    assert not tok_ms.is_equivalent(tok_s)


def test_complex_units_and_chinese_units():
    """Verify parsing and validation of compound units (tokens/s, GB/s, °C) and Chinese units (分钟, 毫秒)."""
    raw_input = """
    Our system achieves 35 tokens/s throughput and bandwidth of 16 GB/s.
    Operating temperature remains under 45°C.
    Mean recovery time is 120 分钟, with peak latency under 250 毫秒.
    """

    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Hardware Benchmark"),
        evidence=[
            MetricEvidence(id="m1", name="Throughput", value="35", unit="tokens/s"),
            MetricEvidence(id="m2", name="Bandwidth", value="16", unit="GB/s"),
            MetricEvidence(id="m3", name="Temperature", value="45", unit="°C"),
            MetricEvidence(id="m4", name="Recovery", value="120", unit="分钟"),
            MetricEvidence(id="m5", name="Latency", value="250", unit="毫秒"),
        ],
        slides=[
            SlideRequest(
                id="s1",
                type=SlideType.RESULT,
                title="Specs",
                evidence_refs=["m1", "m2", "m3", "m4", "m5"],
            )
        ],
    )

    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True
    assert len(res.errors) == 0


def test_textual_provenance_figure_and_table_captions():
    """Figure and Table non-empty captions must be grounded in raw input."""
    raw_input = "Figure 1: Pipeline Overview. Table 2: Benchmark Results."

    # Grounded captions pass
    spec_valid = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Valid Captions"),
        evidence=[
            FigureReferenceEvidence(id="f1", label="Figure 1", caption="Pipeline Overview", source_page=1),
            TableEvidence(id="t1", columns=["A"], rows=[["1"]], caption="Benchmark Results", source_reference="Table 2"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Title", evidence_refs=["f1", "t1"])],
    )
    assert validate_truthfulness(raw_input, spec_valid, strict=True).valid is True

    # Hallucinated figure caption fails
    spec_fake_fig = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Fake Fig Caption"),
        evidence=[
            FigureReferenceEvidence(id="f1", label="Figure 1", caption="A Completely Invented Architecture Diagram", source_page=1),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Title", evidence_refs=["f1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_fig, strict=True)

    # Hallucinated table caption fails
    spec_fake_tbl = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Fake Table Caption"),
        evidence=[
            TableEvidence(id="t1", columns=["A"], rows=[["1"]], caption="A Fabricated Table Caption", source_reference="Table 2"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Title", evidence_refs=["t1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_tbl, strict=True)
