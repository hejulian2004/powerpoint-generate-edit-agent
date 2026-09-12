"""Phase 4: the backend workspace is the sole cold-start authority."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.api.routes import _resolve_session, workspace_bootstrap
from backend.config import settings
from backend.session.manager import session_manager
from backend.workspace import runtime
from backend.workspace.manager import WorkspaceManager
from backend.workspace.repository import SQLiteRepository


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    repo = SQLiteRepository(tmp_path / "bootstrap.db")
    session_manager.clear()
    manager = WorkspaceManager(session_manager, repo, debounce_seconds=60)
    runtime.set_workspace_manager(manager)
    try:
        yield manager
    finally:
        runtime.set_workspace_manager(None)
        asyncio.run(manager.close())
        session_manager.clear()


def test_bootstrap_creates_then_reuses_one_session(workspace):
    first = asyncio.run(workspace_bootstrap(hint=None))
    assert first["is_new"] is True
    sid = first["session_id"]
    assert first["snapshot"]["presentation"]["slides"]

    second = asyncio.run(workspace_bootstrap(hint=None))
    assert second["is_new"] is False
    assert second["session_id"] == sid


def test_bootstrap_hint_is_only_a_hint(workspace):
    first = asyncio.run(workspace_bootstrap(hint=None))
    sid = first["session_id"]

    ghost = asyncio.run(workspace_bootstrap(hint="sess_ghost"))
    assert ghost["session_id"] == sid


def test_resolve_session_uses_workspace_last_active(workspace):
    created = asyncio.run(workspace_bootstrap(hint=None))
    assert _resolve_session(None).session_id == created["session_id"]


def test_resolve_session_requires_id_without_workspace(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    runtime.set_workspace_manager(None)
    with pytest.raises(HTTPException) as excinfo:
        _resolve_session(None)
    assert excinfo.value.status_code == 400


def test_resolve_session_rejects_unknown_explicit_id(workspace):
    with pytest.raises(HTTPException) as excinfo:
        _resolve_session("sess_missing")
    assert excinfo.value.status_code == 404
