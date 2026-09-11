"""Phase 1 contract: no production code may bypass the replacement transaction.

All whole-document replacement (upload / generation / import / restore) must go
through `PPTSession.commit_replacement` / `commit_checkpoint_restore`, which own
the mutation lock and enforce the epoch/revision CAS. The CAS-bypassing
primitive `_unsafe_install_for_bootstrap` is private and test-only.
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"

# Tokens that indicate an unconditional / lock-bypassing document replacement.
FORBIDDEN_TOKENS = (
    "_unsafe_install_for_bootstrap",
    "_restore_checkpoint_unchecked",
    "replace_presentation(",
    "import_pptx_bytes(",
    "restore_checkpoint(",
)


def _production_sources():
    for path in BACKEND_ROOT.rglob("*.py"):
        # session.py defines the private primitive; it is the only allowed home.
        if path.name == "session.py":
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def test_no_production_replacement_bypass():
    offenders = []
    for path in _production_sources():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {token}")
    assert not offenders, (
        "Production code bypasses the CAS-guarded replacement transaction:\n"
        + "\n".join(offenders)
    )


def test_production_replacements_use_the_transaction_api():
    routes = (BACKEND_ROOT / "api" / "routes.py").read_text(encoding="utf-8")
    generation = (BACKEND_ROOT / "agent" / "graphs" / "generation.py").read_text(
        encoding="utf-8"
    )
    assert "commit_replacement(" in routes
    assert "commit_replacement(" in generation
