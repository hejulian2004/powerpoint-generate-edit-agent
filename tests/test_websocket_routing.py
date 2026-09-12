"""Transport scoping for chat-turn events.

A `turn_rejected` is terminal for exactly ONE request and must reach only its
originating socket: another window attached to the same session (which may even
be the legitimate writer) must not render a spurious error/thinking state for a
request it never issued. Ordinary admitted-turn events still broadcast.
"""

import asyncio

from backend.server import websocket as ws_module


class _FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


class _FakeSession:
    session_id = "sess_route"


def test_turn_rejected_is_origin_only(monkeypatch):
    calls = []

    async def fake_broadcast(payload, session_id=None):
        calls.append((payload, session_id))

    monkeypatch.setattr(ws_module.store, "broadcast", fake_broadcast)

    async def _run():
        sock = _FakeSocket()
        await ws_module._chat_event_router(
            sock, _FakeSession(), {"type": "turn_rejected", "error": "request_stale"}
        )
        assert sock.sent == [{
            "type": "turn_rejected",
            "error": "request_stale",
            "session_id": "sess_route",
        }]
        assert calls == []

    asyncio.run(_run())


def test_admitted_turn_events_broadcast(monkeypatch):
    calls = []

    async def fake_broadcast(payload, session_id=None):
        calls.append((payload, session_id))

    monkeypatch.setattr(ws_module.store, "broadcast", fake_broadcast)

    async def _run():
        sock = _FakeSocket()
        await ws_module._chat_event_router(
            sock, _FakeSession(), {"type": "agent_thinking", "text": "planning"}
        )
        assert sock.sent == []
        assert calls == [(
            {"type": "agent_thinking", "text": "planning", "session_id": "sess_route"},
            "sess_route",
        )]

    asyncio.run(_run())
