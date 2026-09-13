"""Post-merge hardening security boundaries (PR #28).

Single home for upload isolation, outbound provider policy, API auth, and
resource budgets. Each module is pure and independently testable.
"""

from .upload_names import sanitize_upload_name
from .outbound import OutboundURLPolicy, OutboundURLRejected
from .auth import (
    is_auth_enabled,
    verify_bearer_token,
    verify_websocket_auth,
    is_loopback_host,
    ensure_remote_auth_configured,
)
from .budgets import (
    PayloadTooLarge,
    read_upload_bounded,
    validate_ooxml_zip_budget,
    get_pdf_page_count,
    validate_pdf_page_budget,
    VisionWorkLimiter,
)

__all__ = [
    "sanitize_upload_name",
    "OutboundURLPolicy",
    "OutboundURLRejected",
    "is_auth_enabled",
    "verify_bearer_token",
    "verify_websocket_auth",
    "is_loopback_host",
    "ensure_remote_auth_configured",
    "PayloadTooLarge",
    "read_upload_bounded",
    "validate_ooxml_zip_budget",
    "get_pdf_page_count",
    "validate_pdf_page_budget",
    "VisionWorkLimiter",
]
