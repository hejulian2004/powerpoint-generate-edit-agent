"""API authentication boundary for remote exposure (PR #28 Phase 0).

Contract:
- local mode: bind 127.0.0.1 by default, PPT_API_TOKEN optional.
- remote mode: non-loopback bind + no PPT_API_TOKEN => startup failure.
- explicit secure mode: PPT_API_TOKEN configured => REST + WebSocket BOTH
  enforce auth. WebSocket auth happens BEFORE session ownership is granted.

Browser WebSockets cannot set ``Authorization`` headers, so the token may be
presented via the ``Sec-WebSocket-Protocol`` header (subprotocol negotiation)
as ``ppt-token.<TOKEN>``. Permanent tokens are never accepted via URL query
string.
"""

from __future__ import annotations

import hmac
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_WS_TOKEN_SUBPROTOCOL_PREFIX = "ppt-token."


def _get_settings():  # lazy to avoid import cycles at module load
    from ..config import settings

    return settings


def is_auth_enabled() -> bool:
    try:
        return bool((_get_settings().ppt_api_token or "").strip())
    except Exception:
        return False


def verify_bearer_token(auth_header: Optional[str]) -> bool:
    """Constant-time check of ``Authorization: Bearer <token>``."""
    if not is_auth_enabled():
        return True
    if not auth_header:
        return False
    scheme, _, credential = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    expected = (_get_settings().ppt_api_token or "").strip()
    return hmac.compare_digest(credential.strip(), expected)


def _token_from_subprotocols(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    for part in raw.split(","):
        token = part.strip()
        if token.startswith(_WS_TOKEN_SUBPROTOCOL_PREFIX):
            return token[len(_WS_TOKEN_SUBPROTOCOL_PREFIX):].strip()
        # Also accept the raw token as a subprotocol for non-browser clients
        # that control the handshake manually.
        if token and "." not in token and len(token) >= 8:
            # Heuristic: a bare subprotocol that matches the configured token.
            # Verified by the caller with compare_digest.
            return token
    return None


def verify_websocket_auth(websocket) -> bool:  # type: ignore[no-untyped-def]
    """Verify a WebSocket handshake BEFORE granting session ownership."""
    if not is_auth_enabled():
        return True
    headers = getattr(websocket, "headers", {}) or {}
    # Starlette headers are case-insensitive; be tolerant of plain dicts.
    def _get(name: str) -> Optional[str]:
        try:
            return headers.get(name) or headers.get(name.lower())
        except Exception:
            return None

    if verify_bearer_token(_get("authorization")):
        # verify_bearer_token returns True when auth disabled; here auth IS
        # enabled, so re-check explicitly against the configured token.
        auth = _get("authorization") or ""
        _, _, credential = auth.partition(" ")
        expected = (_get_settings().ppt_api_token or "").strip()
        if credential.strip() and hmac.compare_digest(credential.strip(), expected):
            return True
    # Browser path: token via Sec-WebSocket-Protocol.
    subprotocols = _get("sec-websocket-protocol")
    candidate = _token_from_subprotocols(subprotocols)
    if candidate:
        expected = (_get_settings().ppt_api_token or "").strip()
        if candidate and hmac.compare_digest(candidate, expected):
            return True
    return False


def websocket_auth_subprotocol(websocket) -> Optional[str]:  # type: ignore[no-untyped-def]
    """Return the subprotocol to select when the client offered a token one."""
    headers = getattr(websocket, "headers", {}) or {}
    try:
        raw = headers.get("sec-websocket-protocol") or headers.get(
            "Sec-WebSocket-Protocol"
        )
    except Exception:
        raw = None
    if not raw:
        return None
    for part in str(raw).split(","):
        token = part.strip()
        if token.startswith(_WS_TOKEN_SUBPROTOCOL_PREFIX):
            return token
    return None


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1")


def ensure_remote_auth_configured() -> None:
    """Fail fast when a non-loopback bind has no API token configured."""
    s = _get_settings()
    host = (getattr(s, "host", "") or "").strip()
    token = (getattr(s, "ppt_api_token", "") or "").strip()
    if host and not is_loopback_host(host) and not token:
        raise RuntimeError(
            "REMOTE_EXPOSURE_WITHOUT_AUTH: "
            f"HOST={host!r} binds a non-loopback interface but PPT_API_TOKEN "
            "is not configured. Bind 127.0.0.1 for local use or set "
            "PPT_API_TOKEN to expose remotely."
        )


__all__ = [
    "is_auth_enabled",
    "verify_bearer_token",
    "verify_websocket_auth",
    "websocket_auth_subprotocol",
    "is_loopback_host",
    "ensure_remote_auth_configured",
]
