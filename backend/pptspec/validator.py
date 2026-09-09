"""Truthfulness Guard and Canonical PPTSpec Validator (PR13).

Guarantees factual provenance:
1. Numeric Provenance Guard:
   Ensures every factual numeric token (metrics, benchmark results, table cells,
   numerical claims) originates from the raw external user input.
   Explicitly exempts non-factual structural metadata (spec_version, duration,
   slide IDs, block IDs, page citations, figure/table labels).
2. Evidence Reference Guard:
   Ensures every evidence_ref on every slide resolves to an existing EvidenceItem.
3. Table Completeness Guard:
   Ensures incomplete tables are flagged as placeholders and never invent dummy data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .errors import (
    IncompleteTableError,
    InvalidEvidenceReferenceError,
    UnsupportedNumericError,
    ValidationError,
)
from .schema import (
    CanonicalPPTSpec,
    ClaimEvidence,
    FigureReferenceEvidence,
    MetricEvidence,
    MetricGroupEvidence,
    QuoteEvidence,
    TableEvidence,
)

# Regular expression to extract numbers including decimals, percentages, scientific notation, and +/- prefixes
_NUMERIC_PATTERN = re.compile(
    r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?"
)


def extract_numeric_tokens(text: str) -> List[str]:
    """Extract distinct numeric tokens from a factual text string."""
    if not text:
        return []
    raw_tokens = _NUMERIC_PATTERN.findall(text)
    # Strip trailing punctuation if attached
    cleaned: List[str] = []
    for tok in raw_tokens:
        tok = tok.strip()
        if not tok:
            continue
        # If token is just a solitary sign or empty, ignore
        if tok in ("+", "-", "%", "+-", "-+"):
            continue
        cleaned.append(tok)
    return cleaned


def collect_factual_numeric_tokens(spec: CanonicalPPTSpec) -> List[Tuple[str, str]]:
    """Extract (token, context_description) for all FACTUAL numbers in the spec.

    Explicitly excludes:
    - spec.presentation.duration_minutes
    - spec.spec_version
    - slide IDs / block IDs
    - evidence IDs
    - source_page numbers
    - Figure and Table label numbers (e.g. 'Figure 3' -> 3 is a label, not an experimental result)
    """
    results: List[Tuple[str, str]] = []

    for ev in spec.evidence:
        if isinstance(ev, MetricEvidence):
            context = f"Metric '{ev.name}' ({ev.id})"
            for tok in extract_numeric_tokens(ev.value):
                results.append((tok, context))

        elif isinstance(ev, MetricGroupEvidence):
            for m in ev.metrics:
                context = f"MetricGroup '{ev.group_name}' -> '{m.name}' ({ev.id})"
                for tok in extract_numeric_tokens(m.value):
                    results.append((tok, context))

        elif isinstance(ev, TableEvidence):
            # Only examine rows, column names might contain general text
            for r_idx, row in enumerate(ev.rows):
                for c_idx, cell in enumerate(row):
                    context = f"Table '{ev.id}' row {r_idx} col {c_idx}"
                    for tok in extract_numeric_tokens(str(cell)):
                        results.append((tok, context))

        elif isinstance(ev, ClaimEvidence):
            # Claims may contain numbers (e.g. 'reduced latency by 45%')
            context = f"Claim ({ev.id})"
            for tok in extract_numeric_tokens(ev.content):
                results.append((tok, context))

        elif isinstance(ev, QuoteEvidence):
            context = f"Quote ({ev.id})"
            for tok in extract_numeric_tokens(ev.content):
                results.append((tok, context))

    # Also check any factual statements directly written inside slide instructions if any
    for slide in spec.slides:
        for inst in slide.instructions:
            for tok in extract_numeric_tokens(inst):
                results.append((tok, f"Slide '{slide.id}' instruction"))

    return results


def _clean_token_for_search(token: str) -> str:
    """Normalize a number token for substring matching."""
    return token.strip().rstrip("%").lstrip("+")


def check_token_in_raw_text(token: str, raw_text: str) -> bool:
    """Check if token or its exact numeric equivalent exists in the raw text."""
    if not token or not raw_text:
        return False

    # 1. Exact string match
    if token in raw_text:
        return True

    clean_tok = _clean_token_for_search(token)
    if clean_tok and clean_tok in raw_text:
        return True

    # 2. Check numeric value equivalence (e.g. 0.5 vs .5, 10% vs 10 %)
    try:
        val = float(clean_tok)
        # Search all numbers in raw text
        raw_numbers = extract_numeric_tokens(raw_text)
        for r_num in raw_numbers:
            r_clean = _clean_token_for_search(r_num)
            try:
                if abs(float(r_clean) - val) < 1e-9:
                    return True
            except ValueError:
                continue
    except ValueError:
        pass

    return False


@dataclass
class TruthfulnessValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    factual_token_count: int = 0


class TruthfulnessValidator:
    """Validates adherence to PR13 factual truthfulness requirements."""

    def __init__(self, strict: bool = True):
        self.strict = strict

    def validate(
        self,
        raw_input: str,
        spec: CanonicalPPTSpec,
    ) -> TruthfulnessValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Evidence Reference Guard
        evidence_ids: Set[str] = {ev.id for ev in spec.evidence}
        for slide in spec.slides:
            for ref in slide.evidence_refs:
                if ref not in evidence_ids:
                    err = f"INVALID_EVIDENCE_REFERENCE: Slide '{slide.id}' references non-existent evidence '{ref}'."
                    errors.append(err)
                    if self.strict:
                        raise InvalidEvidenceReferenceError(slide_id=slide.id, evidence_id=ref)

        # 2. Table Completeness & Integrity Guard
        for ev in spec.evidence:
            if isinstance(ev, TableEvidence):
                if ev.complete_table:
                    expected_cols = len(ev.columns)
                    for r_idx, row in enumerate(ev.rows):
                        if len(row) != expected_cols:
                            ev.complete_table = False
                            msg = f"Table '{ev.id}' row {r_idx} length ({len(row)}) != columns ({expected_cols}). Demoting to placeholder."
                            warnings.append(msg)
                            break
                elif not ev.complete_table and ev.rows:
                    warnings.append(f"Table '{ev.id}' marked incomplete; will be rendered as placeholder.")

        # 3. Numeric Provenance Guard
        factual_tokens = collect_factual_numeric_tokens(spec)
        checked_tokens: Set[str] = set()

        for token, context in factual_tokens:
            if token in checked_tokens:
                continue
            checked_tokens.add(token)

            if not check_token_in_raw_text(token, raw_input):
                err = f"UNSUPPORTED_NUMERIC_VALUE: Factual number '{token}' in {context} is not grounded in raw input."
                errors.append(err)
                if self.strict:
                    raise UnsupportedNumericError(token=token, context=context)

        valid = len(errors) == 0
        return TruthfulnessValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            factual_token_count=len(factual_tokens),
        )


def validate_truthfulness(
    raw_input: str,
    spec: CanonicalPPTSpec,
    strict: bool = True,
) -> TruthfulnessValidationResult:
    """Convenience functional interface for Truthfulness validation."""
    validator = TruthfulnessValidator(strict=strict)
    return validator.validate(raw_input, spec)
