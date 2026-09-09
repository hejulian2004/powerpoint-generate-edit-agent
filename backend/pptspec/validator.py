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
from typing import Any, Dict, List, Optional, Set, Tuple, Union

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

@dataclass(frozen=True)
class NumericToken:
    """Structured representation of a factual numeric token including value, uncertainty, and units."""

    raw_text: str
    value: str
    percent: bool = False
    uncertainty: Optional[str] = None
    unit: Optional[str] = None

    def is_equivalent(self, other: "NumericToken") -> bool:
        """Determines numeric equivalence strictly preserving %, uncertainty, and unit."""
        if self.percent != other.percent:
            return False
        if (self.uncertainty or "") != (other.uncertainty or ""):
            return False
        if (self.unit or "").lower() != (other.unit or "").lower():
            return False
        try:
            return abs(float(self.value) - float(other.value)) < 1e-9
        except ValueError:
            return self.value == other.value


# Regex matching numbers with optional +/- uncertainty, %, and attached unit
_STRUCTURED_NUMERIC_RE = re.compile(
    r"(?P<val>[+-]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s*(?:±|\+/-)\s*(?P<unc>\d+(?:\.\d+)?))?"
    r"(?:\s*(?P<pct>%))?"
    r"(?:(?<=[0-9%])(?P<unit>[a-zA-Z]{1,6}))?"
)


def parse_numeric_tokens(text: str) -> List[NumericToken]:
    """Parse distinct structured NumericTokens from a text string."""
    if not text:
        return []

    tokens: List[NumericToken] = []
    for match in _STRUCTURED_NUMERIC_RE.finditer(text):
        val_str = match.group("val")
        if not val_str or val_str in ("+", "-", "%", "+-", "-+"):
            continue

        unc_str = match.group("unc")
        pct_str = match.group("pct")
        unit_str = match.group("unit")

        # Handle 'percent' or 'pct' unit
        is_percent = bool(pct_str)
        if unit_str and unit_str.lower() in ("percent", "pct"):
            is_percent = True
            unit_str = None

        raw_match = match.group(0).strip()
        tokens.append(
            NumericToken(
                raw_text=raw_match,
                value=val_str,
                percent=is_percent,
                uncertainty=unc_str,
                unit=unit_str,
            )
        )
    return tokens


def extract_numeric_tokens(text: str) -> List[str]:
    """Extract string representations of numeric tokens for backward compatibility."""
    return [tok.raw_text for tok in parse_numeric_tokens(text)]


def collect_factual_numeric_tokens(spec: CanonicalPPTSpec) -> List[Tuple[NumericToken, str]]:
    """Extract (NumericToken, context_description) for all FACTUAL numbers in the spec.

    Explicitly excludes:
    - spec.presentation.duration_minutes
    - spec.spec_version
    - slide IDs / block IDs
    - evidence IDs
    - source_page numbers
    - Figure and Table label numbers (e.g. 'Figure 3' -> 3 is a label, not an experimental result)
    - slide instructions (layout directives only)
    """
    results: List[Tuple[NumericToken, str]] = []

    for ev in spec.evidence:
        if isinstance(ev, MetricEvidence):
            context = f"Metric '{ev.name}' ({ev.id})"
            toks = parse_numeric_tokens(ev.value)
            if ev.unit and toks:
                unit_clean = ev.unit.strip()
                toks = [
                    NumericToken(
                        raw_text=t.raw_text,
                        value=t.value,
                        percent=t.percent or (unit_clean == "%"),
                        uncertainty=t.uncertainty,
                        unit=t.unit or (unit_clean if unit_clean != "%" else None),
                    )
                    for t in toks
                ]
            for tok in toks:
                results.append((tok, context))

        elif isinstance(ev, MetricGroupEvidence):
            for m in ev.metrics:
                context = f"MetricGroup '{ev.group_name}' -> '{m.name}' ({ev.id})"
                toks = parse_numeric_tokens(m.value)
                if m.unit and toks:
                    unit_clean = m.unit.strip()
                    toks = [
                        NumericToken(
                            raw_text=t.raw_text,
                            value=t.value,
                            percent=t.percent or (unit_clean == "%"),
                            uncertainty=t.uncertainty,
                            unit=t.unit or (unit_clean if unit_clean != "%" else None),
                        )
                        for t in toks
                    ]
                for tok in toks:
                    results.append((tok, context))

        elif isinstance(ev, TableEvidence):
            # Only examine rows, column names might contain general text
            for r_idx, row in enumerate(ev.rows):
                for c_idx, cell in enumerate(row):
                    context = f"Table '{ev.id}' row {r_idx} col {c_idx}"
                    for tok in parse_numeric_tokens(str(cell)):
                        results.append((tok, context))

        elif isinstance(ev, ClaimEvidence):
            # Claims may contain numbers (e.g. 'reduced latency by 45%')
            context = f"Claim ({ev.id})"
            for tok in parse_numeric_tokens(ev.content):
                results.append((tok, context))

        elif isinstance(ev, QuoteEvidence):
            context = f"Quote ({ev.id})"
            for tok in parse_numeric_tokens(ev.content):
                results.append((tok, context))

    return results


def check_token_in_raw_text(token: Union[NumericToken, str], raw_text: str) -> bool:
    """Check if token or its exact numeric equivalent exists in the raw text."""
    if not token or not raw_text:
        return False

    if isinstance(token, str):
        tok_objs = parse_numeric_tokens(token)
        if not tok_objs:
            return False
        token = tok_objs[0]

    raw_tokens = parse_numeric_tokens(raw_text)
    return any(token.is_equivalent(r_tok) for r_tok in raw_tokens)


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
        checked_tokens: Set[NumericToken] = set()

        for token, context in factual_tokens:
            if token in checked_tokens:
                continue
            checked_tokens.add(token)

            if not check_token_in_raw_text(token, raw_input):
                err = f"UNSUPPORTED_NUMERIC_VALUE: Factual number '{token.raw_text}' in {context} is not grounded in raw input."
                errors.append(err)
                if self.strict:
                    raise UnsupportedNumericError(token=token.raw_text, context=context)

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
