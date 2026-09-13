"""Cross-platform upload filename sanitization (PR #28 Phase 0).

``UploadFile.filename`` is fully client-controlled and must NEVER participate
in filesystem path construction. The server always writes to a fixed,
server-generated name (e.g. ``tmp/input.pdf``); the client name survives only
as display metadata after sanitization.

``Path(name).name`` alone is insufficient: on a Linux server
``Path("..\\evil.pdf").name`` keeps the backslash because Windows separators
are not recognized. This helper normalizes both separators explicitly.
"""

from __future__ import annotations


def sanitize_upload_name(value: object, fallback: str = "upload.pdf") -> str:
    """Return a safe display-only filename derived from client input.

    - Normalizes both POSIX (``/``) and Windows (``\\``) separators.
    - Strips NUL bytes and surrounding whitespace.
    - Truncates to 255 chars (common filesystem display limit).
    - Falls back when the result is empty, ``.`` or ``..``.
    """
    text = value if isinstance(value, str) else ""
    # Normalize Windows separators first so Linux servers also split them.
    text = text.replace("\\", "/")
    # Keep only the final path segment (POSIX separator).
    text = text.rsplit("/", 1)[-1]
    # Strip NUL bytes (path truncation attacks) and whitespace.
    text = text.replace("\x00", "").strip()
    # Guard against lone dot segments that remain ambiguous as metadata.
    if not text or text in (".", ".."):
        return fallback
    if len(text) > 255:
        text = text[:255]
    return text or fallback


__all__ = ["sanitize_upload_name"]
