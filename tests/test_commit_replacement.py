"""CAS-guarded whole-document replacement transaction tests.

`commit_replacement` owns the mutation lock and both CAS checks so a generation /
import / restore that started at revision N can never blindly overwrite the
revisions a user created while it was running.
"""

import asyncio

from backend.ir.models import PresentationIR, SlideIR
from backend.session.session import (
    DOCUMENT_EPOCH_MISMATCH,
    MISSING_REPLACEMENT_STAMP,
    STALE_GENERATION,
    PPTSession,
)


def _pres(title="Base", version=7):
    pres = PresentationIR(title=title, version=version)
    slide = SlideIR(id="slide_1", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def test_commit_replacement_succeeds_and_rotates_epoch():
    async def _run():
        session = PPTSession(session_id="sess_replace_ok", pres=_pres(version=7))
        epoch_before = session.document_epoch

        generated = _pres(title="Generated", version=1)
        result = await session.commit_replacement(
            generated,
            expected_epoch=epoch_before,
            expected_revision=7,
            checkpoint_description="generated",
        )

        assert result.committed is True
        assert result.error is None
        assert result.old_epoch == epoch_before
        assert result.old_revision == 7
        assert session.pres is generated
        assert session.document_epoch != epoch_before
        assert result.document_epoch == session.document_epoch
        assert result.version == session.pres.version

    asyncio.run(_run())


def test_commit_replacement_rejects_stale_revision():
    async def _run():
        session = PPTSession(session_id="sess_replace_stale", pres=_pres(version=7))
        epoch_before = session.document_epoch
        base_pres = session.pres

        # The user edited while generation was running.
        session.pres.version = 9

        generated = _pres(title="Generated", version=1)
        result = await session.commit_replacement(
            generated,
            expected_epoch=epoch_before,
            expected_revision=7,
        )

        assert result.committed is False
        assert result.error == STALE_GENERATION
        assert session.pres is base_pres
        assert session.pres.version == 9
        assert session.document_epoch == epoch_before

    asyncio.run(_run())


def test_commit_replacement_rejects_epoch_mismatch():
    async def _run():
        session = PPTSession(session_id="sess_replace_epoch", pres=_pres(version=7))
        base_pres = session.pres

        generated = _pres(title="Generated", version=1)
        result = await session.commit_replacement(
            generated,
            expected_epoch="some-old-epoch",
            expected_revision=7,
        )

        assert result.committed is False
        assert result.error == DOCUMENT_EPOCH_MISMATCH
        assert session.pres is base_pres

    asyncio.run(_run())


def test_commit_replacement_without_stamps_fails_closed():
    """Production callers must supply both stamps; None must NOT silently replace."""

    async def _run():
        session = PPTSession(session_id="sess_replace_naive", pres=_pres(version=7))
        base_pres = session.pres
        generated = _pres(title="Generated", version=1)

        result = await session.commit_replacement(
            generated,
            expected_epoch=None,
            expected_revision=None,
        )
        assert result.committed is False
        assert result.error == MISSING_REPLACEMENT_STAMP
        assert session.pres is base_pres

    asyncio.run(_run())


def test_commit_checkpoint_restore_rejects_stale_revision():
    async def _run():
        session = PPTSession(session_id="sess_restore_stale", pres=_pres(version=3))
        checkpoint = session.create_checkpoint(description="baseline")
        epoch_before = session.document_epoch
        current = session.pres

        session.pres.version = 5

        result = await session.commit_checkpoint_restore(
            checkpoint.id,
            expected_epoch=epoch_before,
            expected_revision=3,
        )

        assert result.committed is False
        assert session.pres is current
        assert session.pres.version == 5

    asyncio.run(_run())


def test_commit_checkpoint_restore_succeeds_and_rotates_epoch():
    async def _run():
        session = PPTSession(session_id="sess_restore_ok", pres=_pres(version=3))
        checkpoint = session.create_checkpoint(description="baseline")
        epoch_before = session.document_epoch

        result = await session.commit_checkpoint_restore(
            checkpoint.id,
            expected_epoch=epoch_before,
            expected_revision=3,
        )

        assert result.committed is True
        assert session.document_epoch != epoch_before

    asyncio.run(_run())
