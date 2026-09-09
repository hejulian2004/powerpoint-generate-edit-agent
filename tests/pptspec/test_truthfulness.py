"""Unit tests for Truthfulness Guard & Numeric Provenance Guard (PR13 Step 1)."""

import pytest
from backend.presentation.schema import SlideType
from backend.pptspec.errors import (
    UnsupportedNumericError,
    InvalidEvidenceReferenceError,
)
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    PresentationConfig,
    ClaimEvidence,
    MetricEvidence,
    MetricGroupEvidence,
    MetricEntry,
    TableEvidence,
    FigureReferenceEvidence,
    SlideRequest,
)
from backend.pptspec.validator import (
    collect_factual_numeric_tokens,
    validate_truthfulness,
    TruthfulnessValidator,
)


def test_truthfulness_numeric_provenance_valid():
    raw_input = """
    We evaluate our proposed AnomalyAgent on three benchmarks.
    AnomalyAgent achieves an accuracy of 89.5% and F1 score of 0.884.
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
    raw_input = "We present a simple study without numeric metrics."

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
    raw_input = "We introduce our framework."

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
