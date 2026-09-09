"""PPTSpec: Flexible PPTSpec Ingestion & Canonical Schema Module (PR13)."""

from .schema import (
    CanonicalPPTSpec,
    PresentationConfig,
    SourcePolicy,
    SourceDocument,
    EvidenceItem,
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
)
from .errors import (
    PPTSpecError,
    NormalizationError,
    ValidationError,
    UnsupportedNumericError,
    InvalidEvidenceReferenceError,
    IncompleteTableError,
)
from .validator import (
    TruthfulnessValidator,
    validate_truthfulness,
    collect_factual_numeric_tokens,
)
from .prompt_template import (
    get_general_prompt,
    get_strict_prompt,
)

from .parser import (
    InputFormat,
    detect_format,
    extract_json_payload,
    parse_markdown_or_text_outline,
    parse_presentation_input,
)
from .normalizer import (
    NormalizationResult,
    normalize_presentation_input,
    normalize_dict_to_canonical_spec,
    compute_spec_summary,
)

from .compiler import (
    compile_slide_request_to_slide_spec,
    compile_pptspec_to_deckspec,
)

from .artifact import (
    NormalizationArtifact,
    NormalizationArtifactStore,
    artifact_store,
)

__all__ = [
    "CanonicalPPTSpec",
    "PresentationConfig",
    "SourcePolicy",
    "SourceDocument",
    "EvidenceItem",
    "ClaimEvidence",
    "MetricEvidence",
    "MetricGroupEvidence",
    "MetricEntry",
    "TableEvidence",
    "FigureReferenceEvidence",
    "EquationEvidence",
    "QuoteEvidence",
    "SlideRequest",
    "AssetRequirement",
    "PPTSpecError",
    "NormalizationError",
    "ValidationError",
    "UnsupportedNumericError",
    "InvalidEvidenceReferenceError",
    "IncompleteTableError",
    "TruthfulnessValidator",
    "validate_truthfulness",
    "collect_factual_numeric_tokens",
    "get_general_prompt",
    "get_strict_prompt",
    "InputFormat",
    "detect_format",
    "extract_json_payload",
    "parse_markdown_or_text_outline",
    "parse_presentation_input",
    "NormalizationResult",
    "normalize_presentation_input",
    "normalize_dict_to_canonical_spec",
    "compute_spec_summary",
    "compile_slide_request_to_slide_spec",
    "compile_pptspec_to_deckspec",
]
