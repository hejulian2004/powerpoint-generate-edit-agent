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

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .errors import (
    IncompleteTableError,
    InvalidEvidenceReferenceError,
    UnsupportedFactRelationError,
    UnsupportedNumericError,
    UnsupportedTextualFactError,
    ValidationError,
)
from .schema import (
    CanonicalPPTSpec,
    ClaimEvidence,
    EquationEvidence,
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


def extract_non_numeric_semantic_text(text: str) -> str:
    """Extract non-numeric semantic remainder from a text string after removing structured numeric tokens.

    Invariant:
    - Strips structured numeric spans (using _STRUCTURED_NUMERIC_RE)
    - Strips outer punctuation, brackets, quotes, and whitespace
    - Returns exact remaining semantic text for factual textual grounding check (no stemming, no synonyms)
    """
    if not text or not str(text).strip():
        return ""
    # Strip all structured numeric expressions
    remainder = _STRUCTURED_NUMERIC_RE.sub(" ", str(text))
    # Strip common outer punctuation, brackets, quotes, and normalize whitespace
    remainder = re.sub(r"\s+", " ", remainder).strip()
    remainder = remainder.strip("\"'`.,;:!?()[]{}~#")
    return remainder


def _is_purely_numeric(text: str) -> bool:
    """Check if a string represents purely numeric/symbol data handled by NumericToken."""
    return extract_non_numeric_semantic_text(text) == ""


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
            if ev.value:
                sem_val = extract_non_numeric_semantic_text(ev.value)
                if sem_val:
                    fields.append(FactualTextField(fact_type="metric_value_text", content=sem_val, context=f"Metric value '{ev.name}' ({ev.id})"))
        elif isinstance(ev, MetricGroupEvidence):
            if ev.group_name:
                fields.append(FactualTextField(fact_type="metric_group_name", content=ev.group_name, context=f"MetricGroup '{ev.group_name}' ({ev.id})"))
            for m in ev.metrics:
                if m.name:
                    fields.append(FactualTextField(fact_type="metric_entry_name", content=m.name, context=f"MetricGroup entry '{m.name}' ({ev.id})"))
                if m.value:
                    sem_val = extract_non_numeric_semantic_text(m.value)
                    if sem_val:
                        fields.append(FactualTextField(fact_type="metric_value_text", content=sem_val, context=f"MetricGroup '{ev.group_name}' -> '{m.name}' value ({ev.id})"))
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


def find_closest_locator_for_caption(
    raw_input: str,
    caption: str,
    max_dist: int = 200,
) -> List[Tuple[str, str]]:
    """Finds (locator_type, number) for all occurrences of caption in raw_input."""
    results: List[Tuple[str, str]] = []
    cap_clean = caption.strip()
    if not cap_clean:
        return results

    cap_re = re.compile(re.escape(cap_clean), re.IGNORECASE)
    matches = list(cap_re.finditer(raw_input))
    if not matches:
        words = [w for w in cap_clean.split() if len(w) > 2]
        if words:
            word_pattern = r"\b" + r"\b.*?\b".join(re.escape(w) for w in words[:3]) + r"\b"
            matches = list(re.finditer(word_pattern, raw_input, re.IGNORECASE))

    locator_pattern = re.compile(r"((?:Figure|Fig\.?|Table|图|表)\s*(\d+)(?!\d))", re.IGNORECASE)

    for m in matches:
        cap_start = m.start()
        cap_end = m.end()

        before_start = max(0, cap_start - max_dist)
        before_text = raw_input[before_start:cap_start]
        locs_before = list(locator_pattern.finditer(before_text))

        after_end = min(len(raw_input), cap_end + max_dist)
        after_text = raw_input[cap_end:after_end]
        locs_after = list(locator_pattern.finditer(after_text))

        best_loc: Optional[Tuple[str, str]] = None

        if locs_before:
            last_before = locs_before[-1]
            intervening = before_text[last_before.end():]
            if "\n\n" not in intervening:
                prefix = last_before.group(1).split()[0]
                num = last_before.group(2)
                best_loc = (prefix, num)

        if not best_loc and locs_after:
            first_after = locs_after[0]
            intervening = after_text[:first_after.start()]
            if "\n\n" not in intervening:
                prefix = first_after.group(1).split()[0]
                num = first_after.group(2)
                best_loc = (prefix, num)

        if best_loc:
            results.append(best_loc)

    return results


def validate_source_locator(
    raw_input: str,
    label: Optional[str] = None,
    page: Optional[int] = None,
    caption: Optional[str] = None,
    window_chars: int = 200,
) -> bool:
    """Validate that a Figure/Table label and/or source_page exist in raw_input.

    If label and page/caption are provided, enforces that page/caption must appear within a contextual
    window (+/- window_chars) of the label in the raw input, and no conflicting locator intervenes.
    Supports Chinese compact locators (e.g. '图7展示' -> Figure 7, without matching '图70').
    """
    if not label and page is None and not caption:
        return True

    def has_page_in_text(text: str, p: int) -> bool:
        p_pattern = rf"(?i)(?:page|p\.|第)\s*{p}(?:\s*页|(?!\d))"
        return bool(re.search(p_pattern, text))

    intervening_locator_re = re.compile(r"(?i)(?:Figure|Fig\.?|Table|图|表)\s*\d+(?!\d)")

    if label:
        num_match = re.search(r"((?:Figure|Fig\.?|Table|图|表)\s*(\d+))", label, re.IGNORECASE)
        if num_match:
            label_prefix = num_match.group(1).split()[0]
            n_val = num_match.group(2)
            is_fig = bool(re.match(r"(?i)fig|figure|图", label_prefix))
            if is_fig:
                label_re = re.compile(rf"(?:Figure|Fig\.?|图)\s*{n_val}(?!\d)", re.IGNORECASE)
            else:
                label_re = re.compile(rf"(?:Table|表)\s*{n_val}(?!\d)", re.IGNORECASE)

            matches = list(label_re.finditer(raw_input))
            if not matches:
                return False

            # Caption binding check: ensure caption is contextually bound to this exact locator
            if caption and caption.strip():
                bound_locators = find_closest_locator_for_caption(raw_input, caption)
                if bound_locators:
                    matched_caption = False
                    for b_prefix, b_num in bound_locators:
                        b_is_fig = bool(re.match(r"(?i)fig|figure|图", b_prefix))
                        if b_num == n_val and b_is_fig == is_fig:
                            matched_caption = True
                            break
                    if not matched_caption:
                        return False
                else:
                    if not is_text_grounded(caption, raw_input):
                        return False

            if page is not None:
                bound = False
                for m in matches:
                    start = max(0, m.start() - window_chars)
                    end = min(len(raw_input), m.end() + window_chars)
                    window_text = raw_input[start:end]

                    before_m = raw_input[start:m.start()]
                    after_m = raw_input[m.end():end]

                    if not has_page_in_text(window_text, page):
                        continue
                    p_match = re.search(rf"(?i)(?:page|p\.|第)\s*{page}(?:\s*页|(?!\d))", after_m)
                    if p_match:
                        intervening = after_m[:p_match.start()]
                        if intervening_locator_re.search(intervening):
                            continue
                    p_match_before = re.search(rf"(?i)(?:page|p\.|第)\s*{page}(?:\s*页|(?!\d))", before_m)
                    if p_match_before:
                        intervening = before_m[p_match_before.end():]
                        if intervening_locator_re.search(intervening):
                            continue

                    bound = True
                    break
                return bound
            return True
        else:
            if not is_text_grounded(label, raw_input):
                return False
            if page is not None and not has_page_in_text(raw_input, page):
                return False
            if caption and not is_text_grounded(caption, raw_input):
                return False
            return True
    else:
        if page is not None and not has_page_in_text(raw_input, page):
            return False
        if caption and not is_text_grounded(caption, raw_input):
            return False
        return True


def _clean_table_cell(cell: Any) -> str:
    s = str(cell).strip()
    s = re.sub(r"[*_`~]", "", s).strip()
    return s


def _cells_match(c1: Any, c2: Any) -> bool:
    s1 = _clean_table_cell(c1)
    s2 = _clean_table_cell(c2)
    if s1.lower() == s2.lower():
        return True
    norm1 = normalize_for_textual_match(s1)
    norm2 = normalize_for_textual_match(s2)
    if norm1 and norm2 and norm1 == norm2:
        return True
    toks1 = parse_numeric_tokens(s1)
    toks2 = parse_numeric_tokens(s2)
    if toks1 and toks2 and len(toks1) == len(toks2):
        if all(t1.is_equivalent(t2) for t1, t2 in zip(toks1, toks2)):
            return True
    return False


def extract_candidate_tables(raw_input: str) -> List[Tuple[List[str], List[List[str]]]]:
    """Extracts candidate structured tables (columns, rows) from Markdown and JSON in raw_input."""
    candidates: List[Tuple[List[str], List[List[str]]]] = []

    # 1. Parse Markdown tables
    lines = raw_input.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "|" in line:
            table_lines = [line]
            j = i + 1
            while j < len(lines) and "|" in lines[j]:
                table_lines.append(lines[j].strip())
                j += 1

            if len(table_lines) >= 2:
                cols: List[str] = []
                rows: List[List[str]] = []
                divider_found = False

                for t_line in table_lines:
                    cells = [c.strip() for c in t_line.strip("|").split("|")]
                    if not cells or all(c == "" for c in cells):
                        continue
                    if all(re.match(r"^:?-+:?$", c) for c in cells):
                        divider_found = True
                        continue
                    if not cols:
                        cols = cells
                    else:
                        rows.append(cells)

                if divider_found and cols and rows:
                    candidates.append((cols, rows))
                elif not divider_found and len(table_lines) >= 2:
                    header = [c.strip() for c in table_lines[0].strip("|").split("|") if c.strip()]
                    body_rows = [
                        [c.strip() for c in l.strip("|").split("|") if c.strip()]
                        for l in table_lines[1:]
                    ]
                    if header and body_rows:
                        candidates.append((header, body_rows))

            i = j
        else:
            i += 1

    # 2. Parse JSON / fenced code block JSON tables
    json_candidates: List[Any] = []
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_input, re.IGNORECASE):
        try:
            json_candidates.append(json.loads(match.group(1)))
        except Exception:
            pass
    raw_stripped = raw_input.strip()
    if raw_stripped.startswith(("{", "[")):
        try:
            json_candidates.append(json.loads(raw_stripped))
        except Exception:
            pass

    for obj in json_candidates:
        if isinstance(obj, dict):
            if "columns" in obj and "rows" in obj and isinstance(obj["columns"], list) and isinstance(obj["rows"], list):
                candidates.append((obj["columns"], obj["rows"]))
            if "evidence" in obj and isinstance(obj["evidence"], list):
                for ev in obj["evidence"]:
                    if isinstance(ev, dict) and ev.get("kind") == "table":
                        cols = ev.get("columns", [])
                        rows = ev.get("rows", [])
                        if cols and rows:
                            candidates.append((cols, rows))
        elif isinstance(obj, list) and obj:
            if all(isinstance(item, dict) for item in obj):
                cols = list(obj[0].keys())
                rows = [[str(item.get(c, "")) for c in cols] for item in obj]
                candidates.append((cols, rows))

    return candidates


def validate_complete_table_binding(
    raw_input: str,
    table: TableEvidence,
) -> bool:
    """Validate that table structure (columns and rows) provenance can be proven from raw_input.

    Prevents cross-row, cross-column, or numeric recombination hallucinations by proving
    that the exact relation of headers and ordered cell contents exists as a coherent table
    in raw_input.
    """
    if not table.columns or not table.rows:
        return False

    candidates = extract_candidate_tables(raw_input)
    if not candidates:
        return False

    tbl_cols = table.columns
    tbl_rows = table.rows

    for cand_cols, cand_rows in candidates:
        if len(cand_cols) != len(tbl_cols):
            continue
        if not all(_cells_match(tc, cc) for tc, cc in zip(tbl_cols, cand_cols)):
            continue

        if len(cand_rows) < len(tbl_rows):
            continue

        matched = False
        if len(cand_rows) == len(tbl_rows):
            all_rows_match = True
            for tr, cr in zip(tbl_rows, cand_rows):
                if len(tr) != len(cr) or not all(_cells_match(tc, cc) for tc, cc in zip(tr, cr)):
                    all_rows_match = False
                    break
            if all_rows_match:
                matched = True
        else:
            for start_idx in range(len(cand_rows) - len(tbl_rows) + 1):
                sub_cr = cand_rows[start_idx : start_idx + len(tbl_rows)]
                all_rows_match = True
                for tr, cr in zip(tbl_rows, sub_cr):
                    if len(tr) != len(cr) or not all(_cells_match(tc, cc) for tc, cc in zip(tr, cr)):
                        all_rows_match = False
                        break
                if all_rows_match:
                    matched = True
                    break

        if matched:
            return True

    return False


def validate_metric_binding(
    raw_input: str,
    name: str,
    value: str,
    method: Optional[str] = None,
    unit: Optional[str] = None,
    window_chars: int = 200,
) -> bool:
    """Validate that a Metric name and value belong to the same local factual relation in raw_input.

    Guarantees:
    - Locates occurrences of name in raw_input.
    - Within a local window (+/- window_chars), searches for candidate value (equivalent NumericTokens and semantic remainders).
    - Between name and the candidate value, strictly forbids:
      * JSON object boundaries ('{' or '}')
      * Paragraph boundaries (double newlines '\\n\\s*\\n')
      * New metric / key-value declarations (newline followed by bullet or field name with colon/equal)
      * Other intervening unequal NumericTokens (which belong to a different metric)
    - If method is specified, requires method to also appear in the same bounded local window.
    """
    if not name or not value or not raw_input:
        return False

    name_clean = name.strip()
    if not name_clean:
        return False

    # Extract target numeric token from value if present
    target_toks = parse_numeric_tokens(value)
    target_tok: Optional[NumericToken] = None
    if target_toks:
        t = target_toks[0]
        unit_clean = unit.strip() if unit else None
        target_tok = NumericToken(
            raw_text=t.raw_text,
            value=t.value,
            comparator=t.comparator,
            percent=t.percent or (unit_clean == "%"),
            uncertainty=t.uncertainty,
            unit=t.unit or (unit_clean if unit_clean != "%" else None),
        )

    target_semantic = extract_non_numeric_semantic_text(value)

    # Find occurrences of name in raw_input (case-insensitive literal match)
    # Escape name for regex search
    pattern = re.compile(re.escape(name_clean), re.IGNORECASE)
    matches = list(pattern.finditer(raw_input))
    if not matches:
        # Fallback: check normalized textual match
        name_norm = normalize_for_textual_match(name_clean)
        if not name_norm:
            return False
        # Try finding words
        words = [re.escape(w) for w in name_clean.split() if w]
        if words:
            flex_pattern = re.compile(r"\s+".join(words), re.IGNORECASE)
            matches = list(flex_pattern.finditer(raw_input))

    if not matches:
        return False

    # Forbidden patterns in intervening text between name and value
    new_metric_decl_re = re.compile(
        r"(?:\r?\n)\s*(?:[-*•]?\s*[\w\u4e00-\u9fa5]{1,25}\s*[:：=])",
        re.UNICODE,
    )
    double_newline_re = re.compile(r"\r?\n\s*\r?\n")

    for m in matches:
        start = max(0, m.start() - window_chars)
        end = min(len(raw_input), m.end() + window_chars)

        # Candidate 1: value is AFTER name
        after_text = raw_input[m.end():end]
        # Candidate 2: value is BEFORE name
        before_text = raw_input[start:m.start()]

        def check_intervening(inter: str, cand_tok: Optional[NumericToken]) -> bool:
            # Cannot cross JSON object boundaries
            if "{" in inter or "}" in inter:
                return False
            # Cannot cross paragraph boundaries
            if double_newline_re.search(inter):
                return False
            # Cannot cross new metric / key-value declaration
            if new_metric_decl_re.search(inter):
                return False
            # Cannot cross an intervening different numeric token
            inter_toks = parse_numeric_tokens(inter)
            if cand_tok is not None:
                # Any token in inter that is NOT equivalent to cand_tok is a collision
                for it in inter_toks:
                    if not it.is_equivalent(cand_tok):
                        return False
            elif inter_toks:
                # If target is non-numeric, any numeric token in between is a collision
                return False
            return True

        # Check in after_text
        if target_tok is not None:
            raw_tokens_after = list(_STRUCTURED_NUMERIC_RE.finditer(after_text))
            for tok_match in raw_tokens_after:
                parsed_candidates = parse_numeric_tokens(tok_match.group(0))
                for pt in parsed_candidates:
                    if target_tok.is_equivalent(pt):
                        inter = after_text[:tok_match.start()]
                        if check_intervening(inter, target_tok):
                            # Verify target_semantic if any
                            if target_semantic and not is_text_grounded(target_semantic, after_text[:tok_match.end() + 50]):
                                continue
                            # Verify method if required (must also satisfy intervening constraints with name/value)
                            if method:
                                # Determine actual scope from name start to value end (or vice versa)
                                scope_start = m.start()
                                scope_end = m.end() + tok_match.end()
                                # Method could be before name or after value
                                method_bound = False
                                method_pattern = re.compile(re.escape(method.strip()), re.IGNORECASE)
                                for mm in method_pattern.finditer(raw_input[start:end]):
                                    actual_m_start = start + mm.start()
                                    actual_m_end = start + mm.end()
                                    # Method must connect without crossing forbidden boundaries
                                    if actual_m_end <= scope_start:
                                        conn = raw_input[actual_m_end:scope_start]
                                        if check_intervening(conn, None):
                                            method_bound = True
                                            break
                                    elif actual_m_start >= scope_end:
                                        conn = raw_input[scope_end:actual_m_start]
                                        if check_intervening(conn, None):
                                            method_bound = True
                                            break
                                    elif actual_m_start >= scope_start and actual_m_end <= scope_end:
                                        method_bound = True
                                        break
                                if not method_bound:
                                    continue
                            return True

        if target_semantic and target_tok is None:
            # Pure non-numeric target (e.g. "high", "excellent")
            sem_match = re.search(re.escape(target_semantic), after_text, re.IGNORECASE)
            if sem_match:
                inter = after_text[:sem_match.start()]
                if check_intervening(inter, None):
                    if method:
                        scope_start = m.start()
                        scope_end = m.end() + sem_match.end()
                        method_bound = False
                        method_pattern = re.compile(re.escape(method.strip()), re.IGNORECASE)
                        for mm in method_pattern.finditer(raw_input[start:end]):
                            actual_m_start = start + mm.start()
                            actual_m_end = start + mm.end()
                            if actual_m_end <= scope_start:
                                conn = raw_input[actual_m_end:scope_start]
                                if check_intervening(conn, None):
                                    method_bound = True
                                    break
                            elif actual_m_start >= scope_end:
                                conn = raw_input[scope_end:actual_m_start]
                                if check_intervening(conn, None):
                                    method_bound = True
                                    break
                            elif actual_m_start >= scope_start and actual_m_end <= scope_end:
                                method_bound = True
                                break
                        if not method_bound:
                            continue
                    return True

        # Check in before_text
        if target_tok is not None:
            raw_tokens_before = list(_STRUCTURED_NUMERIC_RE.finditer(before_text))
            for tok_match in reversed(raw_tokens_before):
                parsed_candidates = parse_numeric_tokens(tok_match.group(0))
                for pt in parsed_candidates:
                    if target_tok.is_equivalent(pt):
                        inter = before_text[tok_match.end():]
                        if check_intervening(inter, target_tok):
                            if target_semantic and not is_text_grounded(target_semantic, before_text[max(0, tok_match.start() - 50):]):
                                continue
                            if method:
                                scope_start = start + tok_match.start()
                                scope_end = m.end()
                                method_bound = False
                                method_pattern = re.compile(re.escape(method.strip()), re.IGNORECASE)
                                for mm in method_pattern.finditer(raw_input[start:end]):
                                    actual_m_start = start + mm.start()
                                    actual_m_end = start + mm.end()
                                    if actual_m_end <= scope_start:
                                        conn = raw_input[actual_m_end:scope_start]
                                        if check_intervening(conn, None):
                                            method_bound = True
                                            break
                                    elif actual_m_start >= scope_end:
                                        conn = raw_input[scope_end:actual_m_start]
                                        if check_intervening(conn, None):
                                            method_bound = True
                                            break
                                    elif actual_m_start >= scope_start and actual_m_end <= scope_end:
                                        method_bound = True
                                        break
                                if not method_bound:
                                    continue
                            return True

        if target_semantic and target_tok is None:
            sem_matches = list(re.finditer(re.escape(target_semantic), before_text, re.IGNORECASE))
            if sem_matches:
                last_sem = sem_matches[-1]
                inter = before_text[last_sem.end():]
                if check_intervening(inter, None):
                    if method:
                        scope_start = start + last_sem.start()
                        scope_end = m.end()
                        method_bound = False
                        method_pattern = re.compile(re.escape(method.strip()), re.IGNORECASE)
                        for mm in method_pattern.finditer(raw_input[start:end]):
                            actual_m_start = start + mm.start()
                            actual_m_end = start + mm.end()
                            if actual_m_end <= scope_start:
                                conn = raw_input[actual_m_end:scope_start]
                                if check_intervening(conn, None):
                                    method_bound = True
                                    break
                            elif actual_m_start >= scope_end:
                                conn = raw_input[scope_end:actual_m_start]
                                if check_intervening(conn, None):
                                    method_bound = True
                                    break
                            elif actual_m_start >= scope_start and actual_m_end <= scope_end:
                                method_bound = True
                                break
                        if not method_bound:
                            continue
                    return True

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
                if not validate_source_locator(raw_input, label=ev.label, page=ev.source_page, caption=ev.caption):
                    err = f"UNSUPPORTED_SOURCE_LOCATOR: Figure locator '{ev.label}' (page: {ev.source_page}) is not grounded in raw input."
                    errors.append(err)
                    if self.strict:
                        raise UnsupportedTextualFactError(fact_type="figure_locator", content=ev.label, context=f"Figure {ev.id}")
            elif isinstance(ev, TableEvidence):
                if ev.source_reference or ev.source_page is not None:
                    if not validate_source_locator(raw_input, label=ev.source_reference, page=ev.source_page, caption=ev.caption):
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

        # 6. Composite Metric Relation Guard
        # Enforces local contextual binding between metric name (and method if present) and its value,
        # preventing LLM from cross-recombining independently valid facts.
        for ev in spec.evidence:
            if isinstance(ev, MetricEvidence):
                if ev.name and ev.value:
                    if not validate_metric_binding(
                        raw_input,
                        name=ev.name,
                        value=ev.value,
                        method=ev.method,
                        unit=ev.unit,
                    ):
                        err = f"UNSUPPORTED_FACT_RELATION: Metric '{ev.name}' is not contextually bound to value '{ev.value}' (method: {ev.method}) in raw input."
                        errors.append(err)
                        if self.strict:
                            raise UnsupportedFactRelationError(
                                fact_type="metric",
                                subject=ev.name,
                                relation="has_value",
                                target=ev.value,
                                context=f"Metric {ev.id}",
                            )
            elif isinstance(ev, MetricGroupEvidence):
                for m in ev.metrics:
                    if m.name and m.value:
                        if not validate_metric_binding(
                            raw_input,
                            name=m.name,
                            value=m.value,
                            method=None,
                            unit=m.unit,
                        ):
                            err = f"UNSUPPORTED_FACT_RELATION: MetricGroup entry '{m.name}' is not contextually bound to value '{m.value}' in raw input."
                            errors.append(err)
                            if self.strict:
                                raise UnsupportedFactRelationError(
                                    fact_type="metric_entry",
                                    subject=m.name,
                                    relation="has_value",
                                    target=m.value,
                                    context=f"MetricGroup '{ev.group_name}' -> '{m.name}' ({ev.id})",
                                )

        # 7. Complete Table Structure Relation Guard
        # Only after individual numeric and textual tokens pass (steps 3 & 4),
        # verify that the overall table structure (ordered columns and rows) is proven
        # from raw_input. If structure cannot be provenance-bound, demote complete_table to False,
        # ensuring it renders as a ShapeElementIR placeholder rather than an editable TableElementIR,
        # without fatal-rejecting legitimately grounded tokens.
        for ev in spec.evidence:
            if isinstance(ev, TableEvidence) and ev.complete_table:
                if not validate_complete_table_binding(raw_input, ev):
                    ev.complete_table = False
                    msg = f"Table '{ev.id}' structure could not be provenance-bound; demoted to placeholder."
                    warnings.append(msg)

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
