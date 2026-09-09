"""PPTSpec Error Types (PR13).

Provides actionable, domain-specific exceptions for parsing, normalization,
and truthfulness validation.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any


class PPTSpecError(Exception):
    """Base exception for all PPTSpec-related failures."""

    def __init__(self, message: str, code: str = "PPT_SPEC_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class NormalizationError(PPTSpecError):
    """Raised when external input cannot be normalized into a valid CanonicalPPTSpec."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code="NORMALIZATION_FAILED", details=details)


class ValidationError(PPTSpecError):
    """Raised when CanonicalPPTSpec violates internal integrity or constraints."""

    def __init__(self, message: str, code: str = "VALIDATION_FAILED", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, code=code, details=details)


class UnsupportedNumericError(ValidationError):
    """Raised by Truthfulness Guard when a factual number in the spec has no provenance in raw input."""

    def __init__(self, token: str, context: str = "", details: Optional[Dict[str, Any]] = None):
        msg = f"Unsupported numeric value '{token}' not found in original AI output. Context: {context}"
        d = details or {}
        d["token"] = token
        d["context"] = context
        super().__init__(msg, code="UNSUPPORTED_NUMERIC_VALUE", details=d)


class UnsupportedTextualFactError(ValidationError):
    """Raised by Truthfulness Guard when non-numeric factual text in the spec has no grounding in raw input."""

    def __init__(self, fact_type: str, content: str, context: str = "", details: Optional[Dict[str, Any]] = None):
        msg = f"Unsupported textual fact [{fact_type}] '{content}' not grounded in raw input. Context: {context}"
        d = details or {}
        d["fact_type"] = fact_type
        d["content"] = content
        d["context"] = context
        super().__init__(msg, code="UNSUPPORTED_TEXTUAL_FACT", details=d)


class InvalidEvidenceReferenceError(ValidationError):
    """Raised when a slide references an evidence ID that does not exist in the spec."""

    def __init__(self, slide_id: str, evidence_id: str, details: Optional[Dict[str, Any]] = None):
        msg = f"Slide '{slide_id}' references unknown evidence ID '{evidence_id}'."
        d = details or {}
        d["slide_id"] = slide_id
        d["evidence_id"] = evidence_id
        super().__init__(msg, code="INVALID_EVIDENCE_REFERENCE", details=d)


class IncompleteTableError(ValidationError):
    """Raised when table rows/columns are mismatched or data is missing when expecting complete table."""

    def __init__(self, table_id: str, message: str, details: Optional[Dict[str, Any]] = None):
        d = details or {}
        d["table_id"] = table_id
        super().__init__(f"Incomplete table '{table_id}': {message}", code="INCOMPLETE_TABLE", details=d)
