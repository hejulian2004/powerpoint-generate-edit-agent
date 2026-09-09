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
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .errors import (
    IncompleteTableError,
    InvalidEvidenceReferenceError,
    UnsupportedNumericError,
    UnsupportedTextualFactError,
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
    """Structured representation of a factual numeric token including value, comparator, uncertainty, and units."""

    raw_text: str
    value: str
    comparator: Optional[str] = None  # "<", "<=", ">", ">="
    percent: bool = False
    uncertainty: Optional[str] = None
    unit: Optional[str] = None

    def is_equivalent(self, other: "NumericToken") -> bool:
        """Determines numeric equivalence strictly preserving comparator, %, uncertainty, and unit."""
        if (self.comparator or "") != (other.comparator or ""):
            return False
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


_KNOWN_UNITS = (
    r"tokens/s|GB/s|MB/s|KB/s|FPS|fps|ms|µs|us|ns|s|min|GB|MB|KB|TB|GHz|MHz|Hz|°C|分钟|秒|毫秒|小时"
)

# Regex matching numbers with optional comparator, +/- uncertainty, %, and attached unit
_STRUCTURED_NUMERIC_RE = re.compile(
    r"(?P<cmp><=|>=|≤|≥|<|>)?\s*"
    r"(?P<val>[+-]?(?:\d+\.\d+|\.\d+|\d+)(?:[eE][+-]?\d+)?)"
    r"(?:\s*(?:±|\+/-)\s*(?P<unc>\d+(?:\.\d+)?))?"
    r"(?:"
    r"(?:\s*(?P<pct>%))"
    r"|"
    r"(?:\s*(?P<unit>" + _KNOWN_UNITS + r"))"
    r"|"
    r"(?:(?<=[0-9])(?P<unit_attached>[a-zA-Z]{1,6}))"
    r")?",
    re.UNICODE,
)


def _normalize_comparator(cmp_str: Optional[str]) -> Optional[str]:
    if not cmp_str:
        return None
    cmp_clean = cmp_str.strip()
    if cmp_clean == "≤":
        return "<="
    if cmp_clean == "≥":
        return ">="
    return cmp_clean


def parse_numeric_tokens(text: str) -> List[NumericToken]:
    """Parse distinct structured NumericTokens from a text string."""
    if not text:
        return []

    tokens: List[NumericToken] = []
    for match in _STRUCTURED_NUMERIC_RE.finditer(text):
        val_str = match.group("val")
        if not val_str or val_str in ("+", "-", "%", "+-", "-+"):
            continue

        cmp_str = _normalize_comparator(match.group("cmp"))
        unc_str = match.group("unc")
        pct_str = match.group("pct")
        unit_str = match.group("unit") or match.group("unit_attached")

        # Handle 'percent' or 'pct' unit
        is_percent = bool(pct_str)
        if unit_str and unit_str.lower() in ("percent", "pct"):
            is_percent = True
            unit_str = None

        # Ignore ordinal suffixes
        if unit_str and unit_str.lower() in ("st", "nd", "rd", "th"):
            unit_str = None

        raw_match = match.group(0).strip()
        tokens.append(
            NumericToken(
                raw_text=raw_match,
                value=val_str,
                comparator=cmp_str,
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
                        comparator=t.comparator,
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
                            comparator=t.comparator,
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


def normalize_for_textual_match(text: str) -> str:
    """Normalize text for strict literal-grounding checks:
    - Unicode normalization (NFKC)
    - Strip Markdown markup (links, bold, italic, code, headings, blockquotes)
    - Collapse whitespace/newlines to single space
    - Lowercase
    - Strip leading/trailing punctuation and quotes
    """
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", str(text))
    # Replace markdown links [text](url) -> text
    norm = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", norm)
    # Remove images ![alt](url) -> alt
    norm = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", norm)
    # Remove bold, italics, code, headers, blockquotes, bullets
    norm = re.sub(r"[*_`#>]", " ", norm)
    # Collapse multiple whitespace/newlines
    norm = re.sub(r"\s+", " ", norm).strip().lower()
    # Strip outer quotes / punctuation
    norm = norm.strip("\"'`.,;:!?()[]{}")
    return norm


def is_text_grounded(target: str, raw_text: str) -> bool:
    """Determine whether target text is grounded in raw_text via strict literal normalization."""
    if not target or not target.strip():
        return True
    if not raw_text or not raw_text.strip():
        return False
    target_norm = normalize_for_textual_match(target)
    if not target_norm:
        return True
    raw_norm = normalize_for_textual_match(raw_text)
    return target_norm in raw_norm


@dataclass(frozen=True)
class FactualTextField:
    """Represents a factual textual field that enters the presentation and requires provenance grounding."""

    fact_type: str
    content: str
    context: str


def _is_purely_numeric(text: str) -> bool:
    """Check if a string represents purely numeric/symbol data handled by NumericToken."""
    cleaned = text.strip()
    if not cleaned:
        return True
    # Strip common numeric decorations
    stripped = re.sub(r"[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", "", cleaned)
    stripped = re.sub(r"[\s%±<>=≤≥.,:;()\[\]/-]", "", stripped)
    return len(stripped) == 0


def collect_factual_text_fields(spec: CanonicalPPTSpec) -> List[FactualTextField]:
    """Collect all factual textual fields across the spec that will enter presentation output.

    Exempts presentation/layout instructions (presentation.title, slide.title, slide.objective, slide.instructions).
    """
    fields: List[FactualTextField] = []

    for ev in spec.evidence:
        if isinstance(ev, ClaimEvidence):
            if ev.content:
                fields.append(FactualTextField(fact_type="claim", content=ev.content, context=f"Claim ({ev.id})"))
        elif isinstance(ev, QuoteEvidence):
            if ev.content:
                fields.append(FactualTextField(fact_type="quote", content=ev.content, context=f"Quote ({ev.id})"))
            if ev.speaker_or_section:
                fields.append(FactualTextField(fact_type="speaker_or_section", content=ev.speaker_or_section, context=f"Quote speaker ({ev.id})"))
        elif isinstance(ev, MetricEvidence):
            if ev.name:
                fields.append(FactualTextField(fact_type="metric_name", content=ev.name, context=f"Metric name ({ev.id})"))
            if ev.method:
                fields.append(FactualTextField(fact_type="metric_method", content=ev.method, context=f"Metric method ({ev.id})"))
        elif isinstance(ev, MetricGroupEvidence):
            if ev.group_name:
                fields.append(FactualTextField(fact_type="metric_group_name", content=ev.group_name, context=f"MetricGroup '{ev.group_name}' ({ev.id})"))
            for m in ev.metrics:
                if m.name:
                    fields.append(FactualTextField(fact_type="metric_entry_name", content=m.name, context=f"MetricGroup entry '{m.name}' ({ev.id})"))
        elif isinstance(ev, TableEvidence):
            if ev.caption:
                fields.append(FactualTextField(fact_type="table_caption", content=ev.caption, context=f"Table caption ({ev.id})"))
            for c_idx, col in enumerate(ev.columns):
                if col and not _is_purely_numeric(col):
                    fields.append(FactualTextField(fact_type="table_column", content=col, context=f"Table '{ev.id}' col {c_idx}"))
            for r_idx, row in enumerate(ev.rows):
                for c_idx, cell in enumerate(row):
                    cell_str = str(cell).strip()
                    if cell_str and not _is_purely_numeric(cell_str):
                        fields.append(FactualTextField(fact_type="table_cell", content=cell_str, context=f"Table '{ev.id}' row {r_idx} col {c_idx}"))
        elif isinstance(ev, FigureReferenceEvidence):
            if ev.caption:
                fields.append(FactualTextField(fact_type="figure_caption", content=ev.caption, context=f"Figure caption ({ev.id})"))
        elif isinstance(ev, EquationEvidence):
            if ev.latex:
                fields.append(FactualTextField(fact_type="equation_latex", content=ev.latex, context=f"Equation latex ({ev.id})"))
            if ev.description:
                fields.append(FactualTextField(fact_type="equation_description", content=ev.description, context=f"Equation description ({ev.id})"))

    if spec.source_document:
        if spec.source_document.title:
            fields.append(FactualTextField(fact_type="source_document_title", content=spec.source_document.title, context="source_document.title"))
        if spec.source_document.venue:
            fields.append(FactualTextField(fact_type="venue", content=spec.source_document.venue, context="source_document.venue"))
        for author in spec.source_document.authors:
            if author:
                fields.append(FactualTextField(fact_type="author", content=author, context="source_document.authors"))

    return fields


def validate_source_locator(
    raw_input: str,
    label: Optional[str] = None,
    page: Optional[int] = None,
    window_chars: int = 200,
) -> bool:
    """Validate that a Figure/Table label and/or source_page exist in raw_input.

    If both label and page are provided, enforces that page must appear within a contextual
    window (+/- window_chars) of the label in the raw input.
    """
    if not label and page is None:
        return True

    def has_page_in_text(text: str, p: int) -> bool:
        p_pattern = rf"(?i)(?:page|p\.|第)\s*{p}(?:\s*页|\b)"
        return bool(re.search(p_pattern, text))

    if label:
        num_match = re.search(r"((?:Figure|Fig\.?|Table|图|表)\s*(\d+))", label, re.IGNORECASE)
        if num_match:
            label_prefix = num_match.group(1).split()[0]
            n_val = num_match.group(2)
            if re.match(r"(?i)fig|figure|图", label_prefix):
                label_re = re.compile(rf"(?:Figure|Fig\.?|图)\s*{n_val}\b", re.IGNORECASE)
            else:
                label_re = re.compile(rf"(?:Table|表)\s*{n_val}\b", re.IGNORECASE)

            matches = list(label_re.finditer(raw_input))
            if not matches:
                return False

            if page is not None:
                bound = False
                for m in matches:
                    start = max(0, m.start() - window_chars)
                    end = min(len(raw_input), m.end() + window_chars)
                    window_text = raw_input[start:end]
                    if has_page_in_text(window_text, page):
                        # Ensure no other figure/table label appears between m and the page citation in window
                        before_m = raw_input[start:m.start()]
                        after_m = raw_input[m.end():end]
                        # If page is after m, check if another locator intervenes
                        p_match = re.search(rf"(?i)(?:page|p\.|第)\s*{page}(?:\s*页|\b)", after_m)
                        if p_match:
                            intervening = after_m[:p_match.start()]
                            if re.search(r"(?i)(?:Figure|Fig\.?|Table|图|表)\s*\d+\b", intervening):
                                continue
                        # If page is before m, check if another locator intervenes
                        p_match_before = re.search(rf"(?i)(?:page|p\.|第)\s*{page}(?:\s*页|\b)", before_m)
                        if p_match_before:
                            intervening = before_m[p_match_before.end():]
                            if re.search(r"(?i)(?:Figure|Fig\.?|Table|图|表)\s*\d+\b", intervening):
                                continue
                        bound = True
                        break
                return bound
            return True
        else:
            if not is_text_grounded(label, raw_input):
                return False
            if page is not None:
                return has_page_in_text(raw_input, page)
            return True
    else:
        return has_page_in_text(raw_input, page)


def is_text_grounded(target: str, raw_text: str) -> bool:
    """Determine whether target text is grounded in raw_text via strict literal normalization."""
    if not target or not target.strip():
        return True
    if not raw_text or not raw_text.strip():
        return False
    target_norm = normalize_for_textual_match(target)
    if not target_norm:
        return True
    raw_norm = normalize_for_textual_match(raw_text)
    return target_norm in raw_norm


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

        # 4. Textual Provenance Guard (Strict Literal Grounding)
        # Verifies that non-numeric factual text strings across all evidence items and source document
        # originate directly from raw input.
        factual_text_fields = collect_factual_text_fields(spec)
        for tf in factual_text_fields:
            if tf.content and not is_text_grounded(tf.content, raw_input):
                err = f"UNSUPPORTED_TEXTUAL_FACT: Factual text [{tf.fact_type}] '{tf.content}' in {tf.context} is not grounded in raw input."
                errors.append(err)
                if self.strict:
                    raise UnsupportedTextualFactError(fact_type=tf.fact_type, content=tf.content, context=tf.context)

        # 5. Source Locator & Contextual Binding Guard
        # Enforces that figure/table labels, references, and page citations exist in raw input
        # and that label + page citations are contextually bound.
        for ev in spec.evidence:
            if isinstance(ev, FigureReferenceEvidence):
                if not validate_source_locator(raw_input, label=ev.label, page=ev.source_page):
                    err = f"UNSUPPORTED_SOURCE_LOCATOR: Figure locator '{ev.label}' (page: {ev.source_page}) is not grounded in raw input."
                    errors.append(err)
                    if self.strict:
                        raise UnsupportedTextualFactError(fact_type="figure_locator", content=ev.label, context=f"Figure {ev.id}")
            elif isinstance(ev, TableEvidence):
                if ev.source_reference or ev.source_page is not None:
                    if not validate_source_locator(raw_input, label=ev.source_reference, page=ev.source_page):
                        err = f"UNSUPPORTED_SOURCE_LOCATOR: Table locator '{ev.source_reference}' (page: {ev.source_page}) is not grounded in raw input."
                        errors.append(err)
                        if self.strict:
                            raise UnsupportedTextualFactError(fact_type="table_locator", content=ev.source_reference or f"page {ev.source_page}", context=f"Table {ev.id}")
            elif getattr(ev, "source_page", None) is not None:
                if not validate_source_locator(raw_input, label=None, page=ev.source_page):
                    err = f"UNSUPPORTED_SOURCE_LOCATOR: Evidence page citation '{ev.source_page}' is not grounded in raw input."
                    errors.append(err)
                    if self.strict:
                        raise UnsupportedTextualFactError(fact_type="source_page", content=str(ev.source_page), context=f"Evidence {ev.id}")

        if spec.source_document and spec.source_document.year is not None:
            year_str = str(spec.source_document.year)
            if not re.search(rf"\b{year_str}\b", raw_input):
                err = f"UNSUPPORTED_TEXTUAL_FACT: Source document year '{year_str}' is not found in raw input."
                errors.append(err)
                if self.strict:
                    raise UnsupportedTextualFactError(fact_type="year", content=year_str, context="source_document.year")

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
