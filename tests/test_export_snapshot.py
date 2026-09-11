"""Phase 5: export renders from an immutable epoch/revision-pinned deep copy."""

import asyncio

from backend.session.manager import session_manager
from backend.state.store import create_default_demo_presentation


def _session(session_id: str):
    return session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )


def test_export_snapshot_is_deep_copy_pinned_to_epoch_and_revision():
    session = _session("export_snapshot_pin")
    snapshot = asyncio.run(session.snapshot_for_export())

    assert snapshot.document_epoch == session.document_epoch
    assert snapshot.version == session.pres.version

    # Mutating the snapshot (render-side) must never touch the live document.
    snapshot.presentation.title = "MUTATED_BY_RENDER"
    assert session.pres.title != "MUTATED_BY_RENDER"


def test_export_snapshot_survives_later_replacement():
    session = _session("export_snapshot_stable")
    snapshot = asyncio.run(session.snapshot_for_export())
    epoch_before = snapshot.document_epoch
    version_before = snapshot.version

    session._unsafe_install_for_bootstrap(create_default_demo_presentation())

    # The captured copy keeps the identity it was rendered against.
    assert snapshot.document_epoch == epoch_before
    assert snapshot.version == version_before
    assert session.document_epoch != epoch_before
