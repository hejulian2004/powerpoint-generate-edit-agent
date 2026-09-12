"""Phase 1 contract: no *new* legacy direct mutation of session state.

State ownership moved into per-session services. The compatibility properties on
``PPTSession`` remain readable so existing call sites keep working, but production
code must not write those legacy attributes directly. Writes go through the
service APIs (``session.document.*``, ``session.confirmations.*``,
``session.memory.*``, ``session.history_service.*``).

This test scans ``backend/`` for direct assignments to the legacy surface.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"

LEGACY_ATTRS = (
    "pres",
    "document_epoch",
    "messages",
    "pending_confirmations",
    "completed_mutations",
    "mutation_lock",
    "checkpoint_mgr",
    "agent_memory",
    "last_target_id",
    "last_action_type",
)

_ATTRS = "|".join(LEGACY_ATTRS)
WRITE_RE = re.compile(
    rf"(?:session|self\.active_session)\.(?:{_ATTRS})\s*="
)
APPEND_RE = re.compile(
    r"(?:session|self\.active_session)\.messages\.append\("
)


def _production_sources():
    for path in BACKEND_ROOT.rglob("*.py"):
        if path.name == "session.py":
            # The aggregate defines the compatibility surface.
            continue
        if "services" in path.parts:
            # Services own the state; their attributes are not the legacy surface.
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_new_legacy_direct_mutation():
    offenders = []
    for path in _production_sources():
        text = path.read_text(encoding="utf-8")
        for pattern in (WRITE_RE, APPEND_RE):
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{line}: {match.group(0).strip()}")
    assert not offenders, (
        "Production code writes the legacy session surface directly; use the "
        "service API instead:\n" + "\n".join(offenders)
    )
