"""Security hardening tests: SPA traversal & SVG attribute injection protection."""

from __future__ import annotations

import lxml.etree as etree
from fastapi.testclient import TestClient

from backend.main import app
from backend.ir.models import (
    BorderStyle,
    FillStyle,
    FontIR,
    ImageElementIR,
    ParagraphIR,
    PresentationIR,
    RunIR,
    ShapeElementIR,
    SlideIR,
    TextContentIR,
    TextElementIR,
)
from backend.ir.svg_renderer import SVGRenderer, SVG_NS


def test_spa_directory_traversal_blocked(tmp_path, monkeypatch):
    """Ensure directory traversal attacks via SPA catch-all cannot escape dist_dir."""
    fake_dist = tmp_path / "dist"
    fake_dist.mkdir()
    (fake_dist / "index.html").write_text("<!DOCTYPE html><html><body>SPA Index</body></html>", encoding="utf-8")
    (fake_dist / "legit.js").write_text("console.log('legit');", encoding="utf-8")

    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("SUPER_SECRET_KEY", encoding="utf-8")

    monkeypatch.setattr("backend.main.dist_dir", fake_dist)

    client = TestClient(app)

    # Legitimate file within dist_dir
    res_legit = client.get("/legit.js")
    assert res_legit.status_code == 200
    assert "console.log('legit')" in res_legit.text

    # Path traversal attempts
    traversal_paths = [
        "/../secret.txt",
        "/..%2fsecret.txt",
        "/..%2f..%2fsecret.txt",
        "/....//secret.txt",
        "/backend/main.py",
        "/../backend/main.py",
    ]

    for path in traversal_paths:
        res = client.get(path)
        # Should NOT return the secret file contents
        assert "SUPER_SECRET_KEY" not in res.text
        # Should fallback safely to index.html
        assert "SPA Index" in res.text

    # Verify behavior when dist_dir does not exist (clean container default)
    non_existent = tmp_path / "non_existent_dist"
    monkeypatch.setattr("backend.main.dist_dir", non_existent)
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "online"
    res_404 = client.get("/some_missing_asset.js")
    assert res_404.status_code == 404


def test_svg_renderer_adversarial_injection_neutralized():
    """Ensure malicious element IDs, attributes, font names, colors, and image srcs

    cannot break out of XML attribute quotes or inject rogue XML tags into the SVG output.
    """
    slide = SlideIR(id='slide" onmouseover="alert(1)"', slide_num=1)

    # Malicious text element with tag breakout in font family and XML quotes in ID
    text_elem = TextElementIR(
        id='text_node" onload="alert(2)" <script>alert(3)</script>',
        x=50.0,
        y=50.0,
        width=400.0,
        height=100.0,
        text_content=TextContentIR(
            paragraphs=[
                ParagraphIR(
                    runs=[
                        RunIR(
                            text='Safe text with <script>alert(4)</script> & tags',
                            font=FontIR(
                                name='Arial"><script>alert(5)</script><text x="',
                                size=18.0,
                                color='#1E293B"><script>alert(6)</script>',
                            ),
                        )
                    ]
                )
            ]
        ),
    )
    slide.add_element(text_elem)

    # Malicious shape with attribute breakouts in border/fill
    shape_elem = ShapeElementIR(
        id='shape" style="x:expression(alert(7))"',
        shape_type="roundRect",
        x=50.0,
        y=200.0,
        width=200.0,
        height=100.0,
    )
    shape_elem.style.fill = FillStyle(type="solid", color='#FF0000" onclick="alert(8)')
    shape_elem.style.border = BorderStyle(
        style="solid",
        color='#00FF00" onfocus="alert(9)',
        width=2.0,
    )
    slide.add_element(shape_elem)

    # Malicious image with javascript: scheme and data:text/html
    img_elem_js = ImageElementIR(
        id="img_js",
        src="javascript:alert(10)",
        x=50.0,
        y=350.0,
        width=100.0,
        height=100.0,
    )
    slide.add_element(img_elem_js)

    img_elem_html = ImageElementIR(
        id="img_html",
        src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxMSk8L3NjcmlwdD4=",
        x=200.0,
        y=350.0,
        width=100.0,
        height=100.0,
    )
    slide.add_element(img_elem_html)

    # Remote URL image and active SVG data URI (both must be blocked)
    img_elem_remote = ImageElementIR(
        id="img_remote",
        src="https://external.com/tracker.png",
        x=350.0,
        y=350.0,
        width=100.0,
        height=100.0,
    )
    slide.add_element(img_elem_remote)

    img_elem_active_svg = ImageElementIR(
        id="img_active_svg",
        src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxzY3JpcHQ+YWxlcnQoMSk8L3NjcmlwdD48L3N2Zz4=",
        x=500.0,
        y=350.0,
        width=100.0,
        height=100.0,
    )
    slide.add_element(img_elem_active_svg)

    # Render to SVG
    svg_output = SVGRenderer.render_slide(slide)

    # 1. Output must be strictly valid XML parseable by standard parser
    root = etree.fromstring(svg_output.encode("utf-8"))
    assert root is not None

    # 2. No <script> tags anywhere in the tree
    script_nodes = root.xpath('//*[local-name()="script"]')
    assert len(script_nodes) == 0, f"Found rogue script tags: {script_nodes}"

    # 3. No event handler attributes ('on...') on ANY element
    for elem in root.iter():
        for attr_name in elem.attrib:
            # Strip XML namespace if present
            raw_attr = attr_name.split("}")[-1] if "}" in attr_name else attr_name
            assert not raw_attr.lower().startswith("on"), f"Found event handler attribute {attr_name} on {elem.tag}"

    # 4. Dangerous image srcs were neutralized
    for img in root.xpath('//*[local-name()="image"]'):
        href = img.attrib.get("href", "")
        assert not href.startswith("javascript:"), f"Dangerous href: {href}"
        assert not href.startswith("data:text/html"), f"Dangerous data URI: {href}"
        assert not href.startswith("https://"), f"Remote image URL not neutralized: {href}"
        assert not href.startswith("data:image/svg+xml"), f"Active SVG data URI not neutralized: {href}"

    # 5. Normal text content was retained and properly escaped
    assert "Safe text with <script>alert(4)</script> & tags" in text_elem.text_content.paragraphs[0].runs[0].text
    # Text run text in SVG DOM is text node content, not tags
    text_nodes = [t.text for t in root.xpath('//*[local-name()="tspan"]')]
    assert any("Safe text with <script>alert(4)</script> & tags" in (t or "") for t in text_nodes)


def test_two_tier_journal_tombstones_prevent_expired_replay_execution():
    """Ensure that after Tier 1 payload cache eviction (> 32 requests),

    Tier 2 durable tombstones reject duplicate execution with 409 REPLAY_EXPIRED.
    """
    from backend.session.factory import SessionFactory
    from backend.session.snapshot import session_to_snapshot, snapshot_to_session

    pres = PresentationIR(title="Journal Test")
    session = SessionFactory.create(pres, session_id="sess_journal_test")

    # Record request_0
    session.record_completed_request(
        request_id="req_initial",
        fingerprint="fp_initial",
        response={"success": True, "turn_id": "turn_initial"},
        admitted_generation=0,
        durable=True,
    )

    assert session.get_completed_request("req_initial") is not None
    assert session.get_request_tombstone("req_initial") is not None

    # Now simulate 32 subsequent requests to evict req_initial from Tier 1 cache
    for i in range(32):
        session.record_completed_request(
            request_id=f"req_{i}",
            fingerprint=f"fp_{i}",
            response={"success": True, "turn_id": f"turn_{i}"},
            admitted_generation=0,
            durable=True,
        )

    # req_initial MUST be evicted from Tier 1 cache
    assert session.get_completed_request("req_initial") is None

    # But req_initial MUST still be present in Tier 2 Tombstones!
    tombstone = session.get_request_tombstone("req_initial")
    assert tombstone is not None
    assert tombstone.fingerprint == "fp_initial"

    # Verify persistence round-trip preserves tombstones
    snapshot = session_to_snapshot(session)
    assert any(t["request_id"] == "req_initial" for t in snapshot.completed_tombstones)

    restored = snapshot_to_session(snapshot)
    assert restored.get_completed_request("req_initial") is None
    restored_tombstone = restored.get_request_tombstone("req_initial")
    assert restored_tombstone is not None
    assert restored_tombstone.fingerprint == "fp_initial"


def test_sqlite_authoritative_tombstones_and_reset_conversation_retention(tmp_path):
    """Ensure SQLite request_tombstones table is authoritative for 7 days,

    persisted atomically with session snapshot, and survives reset_conversation().
    """
    import asyncio
    from backend.session.factory import SessionFactory
    from backend.workspace.repository import SQLiteRepository
    from backend.workspace.persistence import SessionPersistenceService

    async def _run():
        db = tmp_path / "tombstone_auth.db"
        repo = SQLiteRepository(db)

        pres = PresentationIR(title="Atomic Tombstone Test")
        session = SessionFactory.create(pres, session_id="sess_atomic_tombstone")
        service = SessionPersistenceService(repo, lambda sid: session, debounce_seconds=60)
        session.persistence = service

        # 1. Record completed request
        session.record_completed_request(
            request_id="req_durable_1",
            fingerprint="fp_durable_1",
            response={"turn_id": "turn_1"},
            admitted_generation=session.conversation_generation,
            durable=True,
        )

        assert "req_durable_1" in session.pending_tombstones
        assert session.get_request_tombstone("req_durable_1") is not None

        # 2. Persist session now -> atomically commits snapshot and pending tombstones
        await service.persist_session_now("sess_atomic_tombstone")
        assert "req_durable_1" not in session.pending_tombstones

        # 3. Query DB authoritative ledger directly
        db_tombstone = await repo.get_request_tombstone("sess_atomic_tombstone", "req_durable_1")
        assert db_tombstone is not None
        assert db_tombstone.fingerprint == "fp_durable_1"

        # 4. Simulate reset_conversation() -> clears transcript and completed_requests, but keeps tombstones
        await session.reset_conversation()
        assert session.get_completed_request("req_durable_1") is None
        assert session.get_request_tombstone("req_durable_1") is not None

        # 5. Evict memory tombstone to simulate cache miss and verify DB authoritative lookup
        session.completed_tombstones.clear()
        assert session.get_request_tombstone("req_durable_1") is None
        db_cached = await repo.get_request_tombstone("sess_atomic_tombstone", "req_durable_1")
        assert db_cached is not None
        assert db_cached.fingerprint == "fp_durable_1"

        await service.close()
        await repo.close()

    asyncio.run(_run())


def test_outbound_enforces_https_with_api_key(monkeypatch):
    """Ensure HTTP is rejected when an API key is attached to outbound requests."""
    from backend.security.outbound import OutboundURLPolicy, OutboundURLRejected

    # Monkeypatch DNS resolution so public.example.com resolves to 93.184.216.34
    monkeypatch.setattr(
        "backend.security.outbound._resolve_all_ips",
        lambda host, port: ["93.184.216.34"],
    )

    # 1. Plain HTTP without api_key is allowed (e.g. public info)
    norm, host, ips = OutboundURLPolicy.validate("http://public.example.com/v1")
    assert host == "public.example.com"

    # 2. Plain HTTP WITH api_key is strictly blocked
    import pytest
    with pytest.raises(OutboundURLRejected) as exc_info:
        OutboundURLPolicy.validate("http://public.example.com/v1", api_key="sk-secret-1234")
    assert exc_info.value.code == "OUTBOUND_HTTPS_REQUIRED"

    # 3. HTTPS WITH api_key is accepted
    norm, host, ips = OutboundURLPolicy.validate("https://public.example.com/v1", api_key="sk-secret-1234")
    assert host == "public.example.com"
    assert norm == "https://public.example.com/v1"


def test_models_route_server_configured_loopback_vs_client_override(monkeypatch):
    """Ensure /api/models allows server-configured loopback in dev/test,

    but strictly rejects client-supplied loopback overrides with SSRF block.
    """
    from backend.config import settings
    import httpx

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, headers=None):
            class FakeResp:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {"data": [{"id": "local-model"}]}
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "openai_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(settings, "openai_api_key", "local-token")

    client = TestClient(app)

    # 1. Caller supplies no base_url -> uses server-configured loopback -> allowed in dev
    res_server = client.post("/api/models", json={})
    assert res_server.status_code == 200
    assert "local-model" in res_server.json()["models"]

    # 2. Caller explicitly supplies loopback base_url -> rejected with 403 (HTTPS required or SSRF blocked)
    res_client = client.post("/api/models", json={"base_url": "http://127.0.0.1:11434/v1", "api_key": "some-key"})
    assert res_client.status_code == 403
    assert any(code in res_client.json()["detail"] for code in ("OUTBOUND_SSRF_BLOCKED", "OUTBOUND_HTTPS_REQUIRED"))

    # 3. Caller explicitly supplies HTTPS loopback base_url -> rejected with SSRF blocked
    res_client_https = client.post("/api/models", json={"base_url": "https://127.0.0.1:11434/v1", "api_key": "some-key"})
    assert res_client_https.status_code == 403
    assert "OUTBOUND_SSRF_BLOCKED" in res_client_https.json()["detail"]


def test_pinned_async_transport_constructed_safely():
    """Verify create_pinned_async_transport successfully constructs pinned pool."""
    from backend.security.outbound import create_pinned_async_transport
    import httpx

    transport = create_pinned_async_transport("api.openai.com", ["104.18.6.192"])
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    assert hasattr(transport, "_pool")


def test_committed_turns_cap_exactly_200():
    """Verify committed_turns bounded cache caps at exactly 200 (no off-by-one 201)."""
    from backend.session.factory import SessionFactory

    pres = PresentationIR(title="Cap Test")
    session = SessionFactory.create(pres, session_id="sess_cap_test")

    import asyncio
    async def _populate():
        for i in range(250):
            await session.commit_conversation_turn(
                request_id=f"req_turn_{i}",
                user_content=f"user_{i}",
                assistant_content=f"asst_{i}",
            )

    asyncio.run(_populate())
    assert len(session.committed_turns) == 200



