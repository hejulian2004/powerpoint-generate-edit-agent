"""Unit tests for Truthfulness Guard & Numeric Provenance Guard (PR13 Step 1)."""

import pytest
from backend.presentation.schema import SlideType
from backend.pptspec.errors import (
    UnsupportedNumericError,
    UnsupportedTextualFactError,
    UnsupportedFactRelationError,
    InvalidEvidenceReferenceError,
)
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    PresentationConfig,
    SourceDocument,
    ClaimEvidence,
    EquationEvidence,
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
    raw_input = "We present a simple study without numeric metrics. A purely qualitative claim without numbers. Figure 9 is shown on page 42."

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
    raw_input = "Figure 1 on page 1: Pipeline Overview. Table 2: Benchmark Results."

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


def test_textual_provenance_rejects_hallucinated_metric_name():
    """Metric name and method must be grounded in raw input, not fabricated."""
    raw_input = "The model achieved 92.4%."

    # Spec hallucinates metric name 'ImageNet Accuracy'
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Presentation Title"),
        evidence=[
            MetricEvidence(id="m1", name="ImageNet Accuracy", value="92.4%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Results", evidence_refs=["m1"])],
    )

    with pytest.raises(UnsupportedTextualFactError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert "ImageNet Accuracy" in str(exc_info.value)


def test_textual_provenance_rejects_hallucinated_table_text_cell():
    """Table textual cells (e.g. baseline or method names) must be grounded in raw input."""
    raw_input = """
    Table 1: Main Performance
    | Accuracy |
    | 89.5% |
    """

    # Spec hallucinates method name column and row values
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Presentation Title"),
        evidence=[
            TableEvidence(
                id="t1",
                source_reference="Table 1",
                columns=["Method", "Accuracy"],
                rows=[["InventedTransformerSOTA", "89.5%"]],
                complete_table=True,
            )
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Results", evidence_refs=["t1"])],
    )

    with pytest.raises(UnsupportedTextualFactError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert any(term in str(exc_info.value) for term in ("Method", "InventedTransformerSOTA"))


def test_source_locator_rejects_hallucinated_figure_table_page():
    """Figure/Table identifiers and page citations must exist in raw input."""
    raw_input = "We evaluate our framework in Figure 3 on page 5 and Table 1."

    # Hallucinated Figure 99
    spec_fake_fig = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[FigureReferenceEvidence(id="f1", label="Figure 99", source_page=5)],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="T", evidence_refs=["f1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_fig, strict=True)

    # Hallucinated Table 99
    spec_fake_tbl = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[TableEvidence(id="t1", source_reference="Table 99", columns=["A"], rows=[["1"]], complete_table=True)],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="T", evidence_refs=["t1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_tbl, strict=True)

    # Hallucinated Page 99
    spec_fake_page = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[FigureReferenceEvidence(id="f1", label="Figure 3", source_page=99)],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="T", evidence_refs=["f1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_fake_page, strict=True)


def test_source_locator_rejects_wrong_page_binding():
    """Figure 7 and Page 12 both exist in text, but Figure 7 is NOT on Page 12 -> must be rejected."""
    raw_input = """
    Figure 7 shows the overview architecture on page 2.
    In the ablation study, Figure 9 is shown on page 12 with detailed breakdown.
    """

    # Wrong binding: Figure 7 with source_page = 12
    spec_wrong_bind = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[FigureReferenceEvidence(id="f1", label="Figure 7", source_page=12)],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="T", evidence_refs=["f1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec_wrong_bind, strict=True)

    # Correct binding: Figure 7 with source_page = 2
    spec_correct_bind = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[FigureReferenceEvidence(id="f1", label="Figure 7", source_page=2)],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="T", evidence_refs=["f1"])],
    )
    assert validate_truthfulness(raw_input, spec_correct_bind, strict=True).valid is True


def test_equation_textual_provenance_grounded():
    """Equation Evidence with latex and description grounded in raw_input passes validation."""
    raw_input = """
    We formulate the loss function as:
    $$\\mathcal{L} = \\alpha \\mathcal{L}_{cls} + \\beta \\mathcal{L}_{reg}$$
    where the description is multi-task weighted objective.
    """
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            EquationEvidence(
                id="eq1",
                latex="\\mathcal{L} = \\alpha \\mathcal{L}_{cls} + \\beta \\mathcal{L}_{reg}",
                description="multi-task weighted objective",
            )
        ],
        slides=[SlideRequest(id="s1", type=SlideType.METHOD_DETAIL, title="Loss", evidence_refs=["eq1"])],
    )
    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True


def test_equation_textual_provenance_rejects_hallucination():
    """Equation Evidence with hallucinated latex or description raises UnsupportedTextualFactError."""
    raw_input = "We evaluate the model without showing formal mathematical equations."
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            EquationEvidence(
                id="eq1",
                latex="E = mc^2",
                description="mass-energy equivalence",
            )
        ],
        slides=[SlideRequest(id="s1", type=SlideType.METHOD_DETAIL, title="Equation", evidence_refs=["eq1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec, strict=True)


def test_metric_text_value_rejects_hallucination():
    """MetricEvidence with non-numeric text value (e.g. 'excellent') not in raw_input must be rejected."""
    raw_input = "Accuracy is thoroughly discussed across benchmark datasets."
    # LLM hallucinates metric value="excellent"
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="excellent")
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec, strict=True)


def test_metric_mixed_value_rejects_hallucinated_suffix():
    """Metric with valid numeric value 92.4% but hallucinated semantic suffix '(best)' must be rejected."""
    raw_input = "Our model achieves an accuracy of 92.4% on ImageNet."
    # LLM appends hallucinated '(best)' to value
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92.4% (best)")
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    with pytest.raises(UnsupportedTextualFactError):
        validate_truthfulness(raw_input, spec, strict=True)


def test_metric_mixed_value_grounded_passes():
    """Metric with mixed value whose numeric and semantic parts are both grounded passes."""
    raw_input = "Our model achieves an accuracy of 92.4% (best) on ImageNet."
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92.4% (best)")
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True


def test_metric_name_value_binding_valid():
    """Valid metric where name and value are bound in local context passes."""
    raw_input = """
    Evaluation Report:
    Accuracy: 92.4%
    F1 Score: 89.5%
    """
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92.4%"),
            MetricEvidence(id="m2", name="F1 Score", value="89.5%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1", "m2"])],
    )
    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True


def test_metric_name_value_binding_rejects_cross_metric_recombination():
    """Accuracy 80.0% and F1 92.4% -> spec recombining Accuracy: 92.4% must raise UnsupportedFactRelationError."""
    raw_input = """
    Evaluation Report:
    Accuracy: 80.0%
    F1: 92.4%
    """
    # LLM swaps values: pairs Accuracy with 92.4%
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92.4%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    with pytest.raises(UnsupportedFactRelationError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert exc_info.value.code == "UNSUPPORTED_FACT_RELATION"
    assert "Accuracy" in str(exc_info.value)
    assert "92.4%" in str(exc_info.value)


def test_metric_group_binding_rejects_cross_metric_recombination():
    """MetricGroup entries must bind their own entry.name with entry.value without cross-entry leakage."""
    raw_input = """
    Benchmark:
    Precision: 75.0%
    Recall: 90.0%
    """
    # Precision paired with 90.0% inside MetricGroup
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricGroupEvidence(
                id="mg1",
                group_name="Benchmark",
                metrics=[
                    MetricEntry(name="Precision", value="90.0%"),
                ],
            )
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["mg1"])],
    )
    with pytest.raises(UnsupportedFactRelationError) as exc_info:
        validate_truthfulness(raw_input, spec, strict=True)
    assert exc_info.value.code == "UNSUPPORTED_FACT_RELATION"


def test_metric_binding_same_line_multiple_metrics():
    """Compact single line containing multiple metrics (e.g. 'Accuracy: 80.0%, F1: 92.4%') passes for correct pairs."""
    raw_input = "Final results: Accuracy: 80.0%, F1: 92.4%."
    # Both correct pairs
    spec = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="80.0%"),
            MetricEvidence(id="m2", name="F1", value="92.4%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1", "m2"])],
    )
    res = validate_truthfulness(raw_input, spec, strict=True)
    assert res.valid is True

    # Recombined pair on same line must fail
    spec_bad = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92.4%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    with pytest.raises(UnsupportedFactRelationError):
        validate_truthfulness(raw_input, spec_bad, strict=True)


def test_metric_binding_json_neighbor_objects():
    """In raw JSON input, neighboring metric objects must not cross '{' or '}' boundaries to recombine."""
    raw_input = """[
        {"name": "Accuracy", "value": "80.0%"},
        {"name": "F1", "value": "92.4%"}
    ]"""
    # Cross-object recombination: Accuracy with 92.4%
    spec_bad = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92.4%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    with pytest.raises(UnsupportedFactRelationError):
        validate_truthfulness(raw_input, spec_bad, strict=True)

    # Valid objects pass
    spec_good = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="80.0%"),
            MetricEvidence(id="m2", name="F1", value="92.4%"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1", "m2"])],
    )
    res = validate_truthfulness(raw_input, spec_good, strict=True)
    assert res.valid is True


def test_metric_method_binding_rejects_cross_method_value():
    """Same metric name under different methods must bind to the correct method value."""
    raw_input = """
    Baseline Accuracy: 80%
    Ours Accuracy: 92%
    """
    # Spec pairs method="Baseline" with 92%
    spec_bad = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="92%", method="Baseline"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1"])],
    )
    with pytest.raises(UnsupportedFactRelationError):
        validate_truthfulness(raw_input, spec_bad, strict=True)

    # Correct pair method="Baseline" with 80%
    spec_good = CanonicalPPTSpec(
        presentation=PresentationConfig(title="Test"),
        evidence=[
            MetricEvidence(id="m1", name="Accuracy", value="80%", method="Baseline"),
            MetricEvidence(id="m2", name="Accuracy", value="92%", method="Ours"),
        ],
        slides=[SlideRequest(id="s1", type=SlideType.RESULT, title="Res", evidence_refs=["m1", "m2"])],
    )
    res = validate_truthfulness(raw_input, spec_good, strict=True)
    assert res.valid is True


