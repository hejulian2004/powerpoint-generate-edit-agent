"""Phase 3: durable persistence (SQLite single-writer, snapshots, debounce/flush)."""

from __future__ import annotations

import asyncio

from backend.agent.mutation_gateway import STALE_MUTATION, MutationGateway
from backend.ir.models import PresentationIR, SlideIR, TextContentIR, TextElementIR
from backend.session.checkpoint import SessionCheckpoint
from backend.session.factory import SessionFactory
from backend.session.manager import SessionManager
from backend.session.session import PPTSession
from backend.session.snapshot import (
    session_to_snapshot,
    snapshot_to_session,
)
from backend.workspace.manager import WorkspaceManager
from backend.workspace.persistence import SessionPersistenceService
from backend.workspace.repository import SQLiteRepository


def _pres(title: str = "Persist Deck") -> PresentationIR:
    pres = PresentationIR(title=title)
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title_node", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Hello"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _move_call(x: float) -> dict:
    return {
        "name": "update_element",
        "arguments": {"slide_id": "slide_1", "element_id": "title_node", "x": x},
        "id": f"call_{x}",
    }


def _session_with_state(session_id: str = "sess_snap") -> PPTSession:
    session = SessionFactory.create(_pres(), session_id=session_id)
    session.add_message(role="user", content="make it bold")
    session.agent_memory.update_preference("style", "bold")
    session.agent_memory.log_action("adjusted title")
    session.create_checkpoint(description="after tweak", score=8.5)
    return session


def test_snapshot_roundtrip_restores_persistent_state():
    session = _session_with_state()
    session.document.presentation.version = 7

    snapshot = session_to_snapshot(session)
    restored = snapshot_to_session(snapshot)

    assert restored.session_id == session.session_id
    assert restored.document.epoch == session.document.epoch
    assert restored.pres.title == session.pres.title
    assert restored.pres.version == 7
    assert [m["content"] for m in restored.memory.messages] == ["make it bold"]
    assert restored.agent_memory.preferences["style"] == "bold"
    assert restored.agent_memory.recent_activities == ["adjusted title"]
    assert len(restored.checkpoint_service.items) == len(session.checkpoint_service.items)


def test_checkpoint_snapshot_roundtrip_preserves_ir_payload():
    session = _session_with_state()
    checkpoint = session.checkpoint_service.items[-1]
    payload = checkpoint.to_snapshot()
    assert "presentation" in payload

    revived = SessionCheckpoint.from_snapshot(payload)
    assert revived.id == checkpoint.id
    assert revived.pres_snapshot.title == checkpoint.pres_snapshot.title
    assert revived.description == checkpoint.description
    assert revived.score == checkpoint.score


def test_restore_suppresses_phantom_baseline():
    session = SessionFactory.create(_pres(), session_id="sess_no_phantom", init_baseline=False)
    session.create_checkpoint(description="only one")
    snapshot = session_to_snapshot(session)
    assert len(snapshot.checkpoints) == 1

    restored = snapshot_to_session(snapshot)
    assert len(restored.checkpoint_service.items) == 1
    assert restored.checkpoint_service.items[0].description == "only one"


def test_ephemeral_state_is_never_persisted_or_restored():
    session = _session_with_state("sess_ephemeral")
    session.register_pending_confirmation(
        call_id="pending_1",
        tool="update_element",
        arguments={"x": 1.0},
        confidence=0.4,
        presentation_version=session.pres.version,
    )
    assert session.get_pending_confirmation("pending_1") is not None

    snapshot = session_to_snapshot(session)
    payload = snapshot.__dict__
    assert "pending_confirmations" not in payload
    assert "completed_mutations" not in payload

    restored = snapshot_to_session(snapshot)
    assert restored.get_pending_confirmation("pending_1") is None
    assert restored.pending_confirmations == {}
    assert restored.completed_mutations == {}


def test_sqlite_repository_roundtrip_and_workspace(tmp_path):
    async def _run():
        db = tmp_path / "ws.db"
        repo = SQLiteRepository(db)
        session = _session_with_state("sess_sql")
        await repo.save(session_to_snapshot(session))
        assert await repo.list_ids() == ["sess_sql"]

        loaded = await repo.load("sess_sql")
        assert loaded is not None
        assert loaded.presentation["title"] == "Persist Deck"

        from backend.session.snapshot import WorkspaceSnapshot
        await repo.save_workspace(
            WorkspaceSnapshot(last_active_session_id="sess_sql", session_ids=["sess_sql"])
        )
        ws = await repo.load_workspace()
        assert ws.last_active_session_id == "sess_sql"
        await repo.close()

        # Reopen: persistence survives a simulated restart.
        repo2 = SQLiteRepository(db)
        assert await repo2.list_ids() == ["sess_sql"]
        await repo2.close()

    asyncio.run(_run())


def test_activate_moves_pointer_and_restores(tmp_path):
    async def _run():
        db = tmp_path / "activate.db"
        repo = SQLiteRepository(db)
        manager = SessionManager()
        workspace = WorkspaceManager(manager, repo, debounce_seconds=60)

        a = await workspace.create_session(_pres("A"), session_id="sess_a")
        b = await workspace.create_session(_pres("B"), session_id="sess_b")
        assert workspace.last_active_session_id == "sess_b"

        await workspace.activate("sess_a")
        assert workspace.last_active_session_id == "sess_a"

        ws = await repo.load_workspace()
        assert ws.last_active_session_id == "sess_a"
        assert set(ws.session_ids) == {"sess_a", "sess_b"}
        await workspace.close()

        # Fresh manager restores the last active session.
        repo2 = SQLiteRepository(db)
        manager2 = SessionManager()
        workspace2 = WorkspaceManager(manager2, repo2, debounce_seconds=60)
        restored = await workspace2.restore_last_active()
        assert restored is not None
        assert restored.session_id == "sess_a"
        assert restored.pres.title == "A"
        await workspace2.close()

    asyncio.run(_run())


def test_graceful_shutdown_flushes_dirty_latest_revision(tmp_path):
    async def _run():
        db = tmp_path / "shutdown.db"
        repo = SQLiteRepository(db)
        workspace = WorkspaceManager(SessionManager(), repo, debounce_seconds=60)
        session = await workspace.create_session(_pres(), session_id="sess_dirty")

        session.pres.title = "Latest"
        session.pres.version += 1
        session.schedule_persist()
        assert "sess_dirty" in workspace.persistence.dirty_session_ids

        await workspace.close()

        repo2 = SQLiteRepository(db)
        loaded = await repo2.load("sess_dirty")
        assert loaded.presentation["title"] == "Latest"
        assert loaded.presentation["version"] == session.pres.version
        await repo2.close()

    asyncio.run(_run())


def test_debounced_schedule_coalesces_writes():
    async def _run():
        class _CountingRepo:
            def __init__(self):
                self.saves = 0

            async def save(self, snapshot):
                self.saves += 1

        repo = _CountingRepo()
        session = SessionFactory.create(_pres(), session_id="sess_debounce")
        service = SessionPersistenceService(
            repo, lambda sid: session if sid == "sess_debounce" else None,
            debounce_seconds=0.05,
        )
        session.persistence = service

        session.schedule_persist()
        session.schedule_persist()
        session.schedule_persist()
        await asyncio.sleep(0.15)
        assert repo.saves == 1

        await service.close()

    asyncio.run(_run())


def test_restart_after_commit_rejects_lost_ack_replay(tmp_path):
    """Contract P1 / scenario 16: a lost-ACK replay after restart must not reapply."""

    async def _run():
        db = tmp_path / "restart.db"
        repo = SQLiteRepository(db)
        workspace = WorkspaceManager(SessionManager(), repo, debounce_seconds=60)
        session = await workspace.create_session(_pres(), session_id="sess_restart")

        base_version = session.pres.version
        first = await MutationGateway.execute_tool_calls(
            [_move_call(120.0)], session.pres, session.history, session=session,
            source="user_direct", bypass_confirmation=True,
            mutation_id="lost_ack_1", document_epoch=session.document_epoch,
            expected_revision=base_version, require_stamps=True,
        )
        assert first.success
        committed_version = session.pres.version
        committed_x = session.pres.slides[0].elements[0].x
        await workspace.close()

        # Restart: new manager, same db.
        repo2 = SQLiteRepository(db)
        workspace2 = WorkspaceManager(SessionManager(), repo2, debounce_seconds=60)
        restored = await workspace2.restore_last_active()
        assert restored is not None
        assert restored.pres.version == committed_version

        # Resend with the ORIGINAL (pre-commit) stamps: must be rejected as stale,
        # never applied a second time.
        replay = await MutationGateway.execute_tool_calls(
            [_move_call(120.0)], restored.pres, restored.history, session=restored,
            source="user_direct", bypass_confirmation=True,
            mutation_id="lost_ack_1", document_epoch=restored.document_epoch,
            expected_revision=base_version, require_stamps=True,
        )
        assert not replay.success
        assert replay.error == STALE_MUTATION
        assert restored.pres.version == committed_version
        assert restored.pres.slides[0].elements[0].x == committed_x
        await workspace2.close()

    asyncio.run(_run())
