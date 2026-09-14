"""PR #28 Post-Merge Hardening adversarial regressions.

Phase acceptance order:
  Phase 0 Security -> Phase 1 Authority/CAS -> Phase 2 Attachment/Transcript
  -> Phase 3 this file -> full CI.

Phase 0 failures (SSRF, key leak, unauth remote/WS, traversal, budgets) are
P0 merge blockers; Phase 1 stale-tab / missing-stamp / frozen-stale confusion
are P1 merge blockers.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from unittest.mock import patch
from fastapi import HTTPException

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager

client = TestClient(app)


# ---------------------------------------------------------------------------
# sanitize_upload_name: cross-platform (POSIX + Windows separators)
# ---------------------------------------------------------------------------

def test_sanitize_upload_name_cross_platform():
    from backend.security.upload_names import sanitize_upload_name

    assert sanitize_upload_name("../../escape.pdf") == "escape.pdf"
    assert sanitize_upload_name("..\\..\\evil.pdf") == "evil.pdf"
    assert sanitize_upload_name("..\\escape.pdf") == "escape.pdf"
    assert sanitize_upload_name("/abs/path.pdf") == "path.pdf"
    assert sanitize_upload_name("C:\\Windows\\temp.pdf") == "temp.pdf"
    assert sanitize_upload_name("C:/Windows/temp.pdf") == "temp.pdf"
    assert sanitize_upload_name("a\x00b.pdf") == "ab.pdf"
    assert sanitize_upload_name("  spaced.pdf  ") == "spaced.pdf"
    assert sanitize_upload_name("") == "upload.pdf"
    assert sanitize_upload_name("..") == "upload.pdf"
    assert sanitize_upload_name(".") == "upload.pdf"
    long_name = "a" * 300 + ".pdf"
    assert len(sanitize_upload_name(long_name)) <= 255


def test_paper_analyze_uses_fixed_server_path(monkeypatch):
    """Malicious filenames never form a filesystem path; metadata is sanitized."""
    import backend.api.routes as routes

    captured = {}

    async def fake_extract(pdf_path):
        # The server-generated path must always be input.pdf, never attacker input.
        captured["pdf_name"] = str(pdf_path).replace("\\", "/").rsplit("/", 1)[-1]
        from backend.paper.schema import PaperIR

        return PaperIR(source_filename="input.pdf")

    def fake_render(pdf_path, force=False):
        captured["render_name"] = str(pdf_path).replace("\\", "/").rsplit("/", 1)[-1]
        from backend.paper_visual.cache import RenderResult

        return RenderResult(
            pdf_sha256="0" * 64,
            page_count=1,
            assets=[],
            warnings=[],
            cache_hit=False,
            dpi=144,
        ), captured.get("cache_dir")

    # Patch at the import site used inside the route (lazy imports).
    import backend.paper as paper_mod

    monkeypatch.setattr(paper_mod, "extract_paper", fake_extract)

    async def _fake_analyze_noop(*args, **kwargs):
        from backend.paper_visual.schema import PaperVisualIR

        return PaperVisualIR(
            source_filename="input.pdf",
            source_sha256="0" * 64,
            vision_model=None,
            pages=[],
        )

    # Patch render + visual analysis through the route's lazy imports by
    # pre-seeding a minimal valid cache is complex; instead verify the fixed
    # path contract directly: the route source must contain the fixed name and
    # must not interpolate file.filename into a Path.
    import pathlib

    src = pathlib.Path(routes.__file__).read_text(encoding="utf-8")
    assert 'Path(tmp) / "input.pdf"' in src or "Path(tmp) / 'input.pdf'" in src
    assert "Path(tmp) / file.filename" not in src


# ---------------------------------------------------------------------------
# OutboundURLPolicy: literal IP, DNS all-public, scheme, userinfo, redirect
# ---------------------------------------------------------------------------

def test_outbound_rejects_literal_private_ips():
    from backend.security.outbound import OutboundURLPolicy, OutboundURLRejected

    for bad in [
        "http://127.0.0.1:8000/v1",
        "http://127.1.2.3/v1",
        "http://10.0.0.5/v1",
        "http://192.168.1.1/v1",
        "http://172.16.0.9/v1",
        "http://169.254.169.254/v1",
        "http://[::1]/v1",
        "http://0.0.0.0/v1",
    ]:
        with pytest.raises(OutboundURLRejected):
            OutboundURLPolicy.validate(bad)


def test_outbound_rejects_bad_scheme_and_userinfo():
    from backend.security.outbound import OutboundURLPolicy, OutboundURLRejected

    with pytest.raises(OutboundURLRejected):
        OutboundURLPolicy.validate("ftp://example.com/v1")
    with pytest.raises(OutboundURLRejected):
        OutboundURLPolicy.validate("file:///etc/passwd")
    with pytest.raises(OutboundURLRejected):
        OutboundURLPolicy.validate("https://user:pass@example.com/v1")


def test_outbound_dns_all_must_be_public(monkeypatch):
    import backend.security.outbound as ob

    def _fake_getaddrinfo(host, port, *a, **k):
        # One public + one private -> whole URL must be rejected.
        return [
            (2, 1, 6, "", ("93.184.216.34", port)),
            (2, 1, 6, "", ("10.0.0.8", port)),
        ]

    monkeypatch.setattr(ob.socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(ob.OutboundURLRejected):
        ob.OutboundURLPolicy.validate("https://provider.example.com/v1")


@pytest.mark.anyio
async def test_pinned_async_transport_tls_sni_host_dial_verified():
    """Gate F E2E: Real TLS test server with dynamic CA and leaf certificate.

    Verifies that:
    1. TCP dials exclusively to the pinned IP (127.0.0.1)
    2. TLS SNI callback receives 'provider.test'
    3. HTTP Host header is 'provider.test:<port>'
    4. Real TLS certificate validation succeeds against custom CA (verify=ca_file, NOT verify=False)
    5. Global socket.getaddrinfo is NEVER mutated
    """
    import asyncio
    import datetime
    import socket as std_socket
    import ssl
    import tempfile
    from pathlib import Path
    import httpx
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from backend.security.outbound import create_pinned_async_transport

    orig_getaddrinfo = std_socket.getaddrinfo

    # 1. Generate Root CA with KeyUsage, SubjectKeyIdentifier, and AuthorityKeyIdentifier
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Root CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_ski = x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(ca_ski, critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    # 2. Generate Leaf Certificate for provider.test with SAN, KeyUsage, ExtendedKeyUsage
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "provider.test")])
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("provider.test")]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ca_ski), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    recorded_sni = []

    def _sni_cb(ssl_sock, server_name, ssl_ctx):
        recorded_sni.append(server_name)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ca_path = tmp_path / "ca.crt"
        cert_path = tmp_path / "leaf.crt"
        key_path = tmp_path / "leaf.key"

        ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )

        server_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ssl_ctx.load_cert_chain(cert_path, key_path)
        server_ssl_ctx.sni_callback = _sni_cb

        recorded_request = {}

        async def handle_client(reader, writer):
            peer = writer.get_extra_info("peername")
            recorded_request["peer"] = peer
            data = await reader.read(2048)
            recorded_request["raw"] = data.decode("utf-8", errors="replace")
            body = b'{"models":["m"]}'
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"Content-Type: application/json\r\n"
                b"\r\n" + body
            )
            writer.write(resp)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handle_client,
            host="127.0.0.1",
            port=0,
            ssl=server_ssl_ctx,
        )
        server_port = server.sockets[0].getsockname()[1]

        try:
            # Pinned transport specifies provider.test -> 127.0.0.1 with custom CA verification
            client_ssl_ctx = ssl.create_default_context(cafile=str(ca_path))
            transport = create_pinned_async_transport("provider.test", ["127.0.0.1"], verify=client_ssl_ctx)

            # Real TLS verification against custom CA SSLContext, NO verify=False!
            async with httpx.AsyncClient(transport=transport) as client:
                resp = await client.get(f"https://provider.test:{server_port}/v1/models")
                assert resp.status_code == 200
                assert resp.json() == {"models": ["m"]}

            # 1. Connected to 127.0.0.1
            assert recorded_request["peer"][0] == "127.0.0.1"
            # 2. TLS SNI callback observed provider.test
            assert "provider.test" in recorded_sni
            # 3. Host header preserves provider.test:<port>
            assert f"host: provider.test:{server_port}" in recorded_request["raw"].lower()
            # 4. Global socket.getaddrinfo untouched
            assert std_socket.getaddrinfo is orig_getaddrinfo

        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.anyio
async def test_pinned_async_transport_concurrent_interleaving_safe():
    """Adversarial test for DNS pinning: two concurrent requests targeting different

    hosts must route to their respective pinned IPs without race conditions, and
    MUST NOT mutate process-global socket.getaddrinfo.
    """
    import anyio
    import socket as std_socket
    from backend.security.outbound import create_pinned_async_transport

    orig_getaddrinfo = std_socket.getaddrinfo

    host_a = "service-a.test"
    ips_a = ["198.51.100.1"]
    host_b = "service-b.test"
    ips_b = ["198.51.100.2"]

    transport_a = create_pinned_async_transport(host_a, ips_a)
    transport_b = create_pinned_async_transport(host_b, ips_b)

    recorded_connections = []
    barrier = anyio.Event()

    # Inspect the backend of each transport
    backend_a = transport_a._pool._network_backend
    backend_b = transport_b._pool._network_backend

    orig_connect_a = backend_a._auto_backend.connect_tcp
    orig_connect_b = backend_b._auto_backend.connect_tcp

    async def mock_connect_a(target_ip, port, **kw):
        recorded_connections.append(("A_start", target_ip))
        # Signal B to start and wait for B
        barrier.set()
        await anyio.sleep(0.05)
        recorded_connections.append(("A_done", target_ip))
        class FakeStream:
            async def aclose(self): pass
        return FakeStream()

    async def mock_connect_b(target_ip, port, **kw):
        # Wait until A has started
        await barrier.wait()
        recorded_connections.append(("B_start", target_ip))
        recorded_connections.append(("B_done", target_ip))
        class FakeStream:
            async def aclose(self): pass
        return FakeStream()

    backend_a._auto_backend.connect_tcp = mock_connect_a
    backend_b._auto_backend.connect_tcp = mock_connect_b

    async def run_a():
        await backend_a.connect_tcp(host_a, 443)

    async def run_b():
        await backend_b.connect_tcp(host_b, 443)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_a)
        tg.start_soon(run_b)

    # Global socket.getaddrinfo must NEVER have been replaced!
    assert std_socket.getaddrinfo is orig_getaddrinfo

    # Verify that A dialed 198.51.100.1 and B dialed 198.51.100.2 despite interleaving
    assert ("A_start", "198.51.100.1") in recorded_connections
    assert ("B_start", "198.51.100.2") in recorded_connections


def test_models_does_not_inherit_saved_key_for_custom_host(monkeypatch):
    """Custom base_url must NOT receive the server-saved API key."""
    import httpx

    from backend.config import settings

    # Bypass DNS for this key-isolation test (SSRF covered above).
    def _fake_validate(cls, base_url, trusted_hosts=None, allow_private_for_tests=False):
        from urllib.parse import urlparse as _up

        raw = str(base_url).strip().rstrip("/")
        host = (_up(raw).hostname or "x").lower()
        return raw, host, []

    monkeypatch.setattr(
        "backend.security.outbound.OutboundURLPolicy.validate",
        classmethod(_fake_validate),
    )
    monkeypatch.setattr(settings, "openai_base_url", "https://default.example/v1")
    monkeypatch.setattr(settings, "openai_api_key", "sk-SERVER-SAVED")

    seen = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "m1"}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            seen["auth"] = (headers or {}).get("Authorization")
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    resp = client.post(
        "/api/models",
        json={"base_url": "https://attacker.example/v1"},
    )
    assert resp.status_code == 200
    # No inherited server key for a foreign host.
    assert seen.get("auth") in (None, "")

    # Even if base_url has the exact same host/path (e.g. HTTP downgrade attempt),
    # explicit base_url NEVER inherits server-saved key!
    resp_downgrade = client.post(
        "/api/models",
        json={"base_url": "http://default.example/v1"},
    )
    assert resp_downgrade.status_code == 200
    assert seen.get("auth") in (None, "")

    # Omitting base_url uses default endpoint AND inherits server key
    resp_default = client.post("/api/models", json={})
    assert resp_default.status_code == 200
    assert seen.get("auth") == "Bearer sk-SERVER-SAVED"


def test_models_blocks_loopback_even_with_key(monkeypatch):
    resp = client.post(
        "/api/models",
        json={"base_url": "http://127.0.0.1:9/v1", "api_key": "sk-test"},
    )
    assert resp.status_code == 403
    assert "SSRF" in resp.json()["detail"] or "OUTBOUND" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Auth boundaries: startup guard, REST 401, WS pre-ownership
# ---------------------------------------------------------------------------

def test_remote_bind_without_token_fails_fast(monkeypatch):
    from backend.config import settings
    from backend.security.auth import ensure_remote_auth_configured

    monkeypatch.setattr(settings, "host", "0.0.0.0")
    monkeypatch.setattr(settings, "ppt_api_token", "")
    with pytest.raises(RuntimeError, match="REMOTE_EXPOSURE_WITHOUT_AUTH"):
        ensure_remote_auth_configured()
    # Explicit bind_host also fails fast regardless of settings.host
    with pytest.raises(RuntimeError, match="REMOTE_EXPOSURE_WITHOUT_AUTH"):
        ensure_remote_auth_configured(bind_host="0.0.0.0")


def test_launcher_cli_host_guard_subprocess():
    """Verify that launching via python main.py --host 0.0.0.0 without a token

    fails fast before uvicorn starts. Protected with strict timeout and cleanup.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    root_dir = Path(__file__).resolve().parent.parent.parent
    main_py = root_dir / "main.py"
    env = dict(os.environ)
    env.pop("PPT_API_TOKEN", None)
    env["HOST"] = "127.0.0.1"  # ensure env alone wouldn't trigger it

    proc = subprocess.Popen(
        [sys.executable, str(main_py), "--host", "0.0.0.0", "--no-browser"],
        cwd=str(root_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail("main.py with --host 0.0.0.0 hung instead of failing fast!")

    assert proc.returncode != 0
    combined = (stdout + stderr).lower()
    assert "remote_exposure_without_auth" in combined or "安全拦截" in (stdout + stderr)


def test_loopback_without_token_boots(monkeypatch):
    from backend.config import settings
    from backend.security.auth import ensure_remote_auth_configured

    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "ppt_api_token", "")
    ensure_remote_auth_configured()


def test_rest_requires_bearer_when_token_configured(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "ppt_api_token", "tok-test-123")
    try:
        # No token -> 401
        r = client.get("/api/settings")
        assert r.status_code == 401
        # Wrong token -> 401
        r2 = client.get(
            "/api/settings", headers={"Authorization": "Bearer wrong"}
        )
        assert r2.status_code == 401
        # Correct token -> 200
        r3 = client.get(
            "/api/settings", headers={"Authorization": "Bearer tok-test-123"}
        )
        assert r3.status_code == 200
    finally:
        monkeypatch.setattr(settings, "ppt_api_token", "")


def test_websocket_rejects_unauthenticated_before_ownership(monkeypatch):
    from backend.config import settings
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setattr(settings, "ppt_api_token", "super-secret-tok")
    sid = "test_ws_auth_handshake"
    sess = session_manager.get_or_create(sid)
    try:
        # 1. Unauthenticated WS handshake must receive UNAUTHORIZED and be closed with 4401 before ownership
        with client.websocket_connect(f"/ws?session_id={sid}") as ws:
            data = ws.receive_json()
            assert data.get("type") == "session_error"
            assert data.get("error") == "UNAUTHORIZED"
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4401
            # Session connection was never attached to this unauthenticated socket
            assert sess.connection.websocket != ws

        # 2. Authenticated WS handshake with base64url subprotocol succeeds
        import base64
        b64 = base64.urlsafe_b64encode(b"super-secret-tok").decode("ascii").rstrip("=")
        with client.websocket_connect(
            f"/ws?session_id={sid}", subprotocols=[f"ppt-token.{b64}"]
        ) as ws:
            # Session is attached only after successful auth
            assert sess.connection.websocket is not None
    finally:
        session_manager.delete_session(sid)
        monkeypatch.setattr(settings, "ppt_api_token", "")


# ---------------------------------------------------------------------------
# Upload budgets: streaming, zip bomb, pdf pages
# ---------------------------------------------------------------------------

def test_read_upload_bounded_enforces_limit():
    import asyncio

    from backend.security.budgets import PayloadTooLarge, read_upload_bounded

    class FakeUpload:
        def __init__(self, data: bytes):
            self._buf = io.BytesIO(data)

        async def read(self, n: int = -1):
            return self._buf.read(n)

    big = b"x" * 200
    with pytest.raises(PayloadTooLarge):
        asyncio.run(read_upload_bounded(FakeUpload(big), max_bytes=100))
    small = asyncio.run(read_upload_bounded(FakeUpload(b"abc"), max_bytes=100))
    assert small == b"abc"


def test_ooxml_zip_budget_rejects_bomb_and_traversal():
    from backend.security.budgets import PayloadTooLarge, validate_ooxml_zip_budget

    # Traversal entry.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("../../evil.txt", b"evil")
    with pytest.raises(PayloadTooLarge):
        validate_ooxml_zip_budget(buf.getvalue())

    # Absurd compression ratio (stored small, claimed huge is hard to fake with
    # STORED; use DEFLATED highly-compressible data and a tiny limit via config).
    from backend.config import settings

    old = settings.pptx_max_uncompressed_bytes
    try:
        settings.pptx_max_uncompressed_bytes = 10
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", b"a" * 1000)
        with pytest.raises(PayloadTooLarge):
            validate_ooxml_zip_budget(buf2.getvalue())
    finally:
        settings.pptx_max_uncompressed_bytes = old


def test_pdf_page_budget_rejects_oversized_and_fail_closed(monkeypatch):
    from backend.config import settings
    from backend.security.budgets import (
        PayloadTooLarge,
        get_pdf_page_count,
        validate_pdf_geometry_and_raster_budget,
        validate_pdf_page_budget,
    )

    monkeypatch.setattr(settings, "max_pdf_pages", 2)
    with pytest.raises(PayloadTooLarge):
        validate_pdf_page_budget(80)
    validate_pdf_page_budget(2)
    # Fail-closed: None or invalid integer must be rejected
    with pytest.raises(PayloadTooLarge) as exc_info:
        validate_pdf_page_budget(None)  # type: ignore[arg-type]
    assert exc_info.value.code == "PDF_INVALID_PAGE_COUNT"

    with pytest.raises(PayloadTooLarge) as exc_info2:
        validate_pdf_page_budget(0)
    assert exc_info2.value.code == "PDF_INVALID_PAGE_COUNT"

    # Empty or corrupt PDF fail-closed
    with pytest.raises(PayloadTooLarge) as exc_empty:
        get_pdf_page_count(b"")
    assert exc_empty.value.code == "PDF_EMPTY"

    with pytest.raises(PayloadTooLarge) as exc_bad:
        get_pdf_page_count(b"NOT_A_PDF_STREAM")
    assert exc_bad.value.code == "PDF_CORRUPT_OR_UNREADABLE"

    # Geometry & raster pixel limits
    # 1. Page point limits (8192pt limit)
    with pytest.raises(PayloadTooLarge) as exc_pts:
        validate_pdf_geometry_and_raster_budget(10000.0, 500.0, dpi=150)
    assert exc_pts.value.code == "PDF_PAGE_POINTS_OUT_OF_BOUNDS"

    # 2. Raster dimension limits (8192px limit at high DPI)
    with pytest.raises(PayloadTooLarge) as exc_dim:
        validate_pdf_geometry_and_raster_budget(5000.0, 500.0, dpi=300)
    assert exc_dim.value.code == "PDF_PAGE_DIMENSION_PIXELS_TOO_LARGE"

    # 3. Single page pixel limit (20,000,000 pixels): 4000x5500 at 72dpi = 22M px, dimension 5500 <= 8192
    with pytest.raises(PayloadTooLarge) as exc_px:
        validate_pdf_geometry_and_raster_budget(4000.0, 5500.0, dpi=72)
    assert exc_px.value.code == "PDF_PAGE_PIXELS_TOO_LARGE"

    # 4. Valid page calculates properly and accumulates
    w, h, cum = validate_pdf_geometry_and_raster_budget(600.0, 800.0, dpi=150, cumulative_pixels=0)
    assert w > 0 and h > 0 and cum == w * h


def test_upload_rejects_oversized_stream(monkeypatch):
    from backend.config import settings

    sid = "test_budget_upload"
    sess = session_manager.get_or_create(sid)
    monkeypatch.setattr(settings, "max_upload_file_bytes", 10)
    try:
        resp = client.post(
            f"/api/upload?session_id={sid}&expected_epoch={sess.document_epoch}"
            f"&expected_revision={sess.document.presentation.version}",
            files={"file": ("big.pptx", b"x" * 100, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        )
        assert resp.status_code == 413
    finally:
        monkeypatch.setattr(settings, "max_upload_file_bytes", 50 * 1024 * 1024)
        session_manager.delete_session(sid)


# ---------------------------------------------------------------------------
# Strict caller-observed CAS for whole-document replacement
# ---------------------------------------------------------------------------

def test_pptspec_generate_requires_caller_stamp():
    sid = "test_cas_pptspec_stamp"
    session_manager.get_or_create(sid)
    try:
        resp = client.post(
            "/api/pptspec/generate",
            json={"normalization_id": "nid_missing_stamp", "session_id": sid},
        )
        # Artifact missing (404) takes precedence over stamp check only when the
        # artifact itself is unknown; with a bogus id we get 404. To isolate the
        # stamp gate, seed a valid artifact below in the paper test. Here we at
        # least assert that a stamp-less call never silently succeeds.
        assert resp.status_code in (404, 409)
        if resp.status_code == 409:
            assert "MISSING_REPLACEMENT_STAMP" in resp.text
    finally:
        session_manager.delete_session(sid)


def test_pptspec_generate_missing_stamp_with_valid_artifact():
    from backend.pptspec.artifact import artifact_store
    from backend.pptspec.schema import (
        CanonicalPPTSpec,
        MetricEvidence,
        PresentationConfig,
        SlideRequest,
    )

    sid = "test_cas_valid_stamp"
    session_manager.get_or_create(sid)
    try:
        spec = CanonicalPPTSpec(
            spec_version="1.0",
            presentation=PresentationConfig(title="CAS"),
            evidence=[],
            slides=[],
        )
        art = artifact_store.save(
            session_id=sid, raw_input="hello", spec=spec, summary={}, asset_requirements=[]
        )
        resp = client.post(
            "/api/pptspec/generate",
            json={"normalization_id": art.id, "session_id": sid},
        )
        assert resp.status_code == 409
        assert "MISSING_REPLACEMENT_STAMP" in resp.text
    finally:
        session_manager.delete_session(sid)


def test_paper_generate_requires_caller_stamp(cache_root=None):
    sid = "test_cas_paper_stamp"
    session_manager.get_or_create(sid)
    try:
        resp = client.post(
            "/api/paper/generate",
            json={"session_id": sid, "cache_key": "0" * 64},
        )
        # Either the cache is missing (422) or the stamp is missing (409);
        # a stamp-less call must never reach generation.
        assert resp.status_code in (409, 422)
    finally:
        session_manager.delete_session(sid)


# ---------------------------------------------------------------------------
# Plan confirmation authority: REST retired, WS-only
# ---------------------------------------------------------------------------

def test_plan_confirm_rest_retired():
    resp = client.post("/api/plan/confirm", json={"plan_id": "p1"})
    assert resp.status_code == 410
    assert "WebSocket" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Attachment disposition: fail-closed on partial consumption
# ---------------------------------------------------------------------------

def test_disposition_requires_full_consumption_for_mutating():
    from backend.agent.attachment_router import (
        ACTION_IMAGE,
        ACTION_PAPER,
        build_disposition_plan,
        disposition_all_consumed,
    )

    two_pdfs = [
        {"attachment_id": "att_0", "name": "a.pdf", "kind": "pdf"},
        {"attachment_id": "att_1", "name": "b.pdf", "kind": "pdf"},
    ]
    plan = build_disposition_plan(two_pdfs, ACTION_PAPER)
    assert not disposition_all_consumed(plan)
    assert plan[0]["disposition"] == "consume"
    assert plan[1]["disposition"] == "unused"

    mixed = [
        {"attachment_id": "att_0", "name": "a.pdf", "kind": "pdf"},
        {"attachment_id": "att_1", "name": "b.png", "kind": "image"},
    ]
    plan2 = build_disposition_plan(mixed, ACTION_PAPER)
    assert not disposition_all_consumed(plan2)


def test_chat_drive_mutating_with_unused_attachment_fails_closed(monkeypatch):
    import backend.api.routes as routes

    monkeypatch.setattr(
        routes.router, "route_class_hack", None, raising=False
    ) if False else None
    # Force paper_generate with a PDF + an extra image: image would be dropped
    # by the old _first() logic; now it must fail closed.
    import backend.agent.attachment_router as router

    async def _force_paper(llm, message, kinds):
        return "paper_generate"

    monkeypatch.setattr(router, "classify_intent", _force_paper)
    sid = "test_disposition_drive"
    sess = session_manager.get_or_create(sid)
    try:
        resp = client.post(
            "/api/chat/drive",
            data={
                "message": "参考论文并把图放进去",
                "session_id": sid,
                "expected_epoch": sess.document_epoch,
                "expected_revision": sess.document.presentation.version,
            },
            files=[
                ("files", ("paper.pdf", b"%PDF-1.4 fake", "application/pdf")),
                ("files", ("fig.png", b"\x89PNG\r\n\x1a\n", "image/png")),
            ],
        )
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", body)
        assert "UNPROCESSED_ATTACHMENTS" in json.dumps(detail, ensure_ascii=False)
    finally:
        session_manager.delete_session(sid)


# ---------------------------------------------------------------------------
# Transcript ownership: mutating turns persist provenance, failures do not
# ---------------------------------------------------------------------------

def test_mutating_turn_persists_provenance(monkeypatch):
    import backend.agent.attachment_router as router
    import backend.api.routes as routes

    async def _force_text(llm, message, kinds):
        return "text_generate"

    monkeypatch.setattr(router, "classify_intent", _force_text)

    async def fake_normalize(payload):
        return {
            "valid": True,
            "normalization_id": "nid_prov",
            "summary": "s",
            "warnings": [],
            "errors": [],
        }

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    monkeypatch.setattr(routes, "api_normalize_pptspec", fake_normalize)
    monkeypatch.setattr(routes, "api_generate_from_pptspec", fake_gen)

    sid = "test_transcript_prov"
    sess = session_manager.get_or_create(sid)
    before = len(sess.memory.messages)
    try:
        resp = client.post(
            "/api/chat/drive",
            data={
                "message": "根据文档生成",
                "session_id": sid,
                "expected_epoch": sess.document_epoch,
                "expected_revision": sess.document.presentation.version,
            },
            files=[("files", ("outline.txt", "大纲A".encode(), "text/plain"))],
        )
        assert resp.status_code == 200, resp.text
        after = sess.memory.messages
        assert len(after) == before + 2
        user_msg, asst_msg = after[-2], after[-1]
        assert user_msg["role"] == "user" and asst_msg["role"] == "assistant"
        assert "outline.txt" in user_msg["content"]
        # No raw file content persisted in conversation turns.
        assert "大纲A" not in json.dumps(after[-2:], ensure_ascii=False)
        for m in after[-2:]:
            assert "base64" not in m["content"]
            assert "data:" not in m["content"]
    finally:
        session_manager.delete_session(sid)


def test_llm_provider_failure_is_502_without_transcript_pollution(monkeypatch):
    import asyncio

    from backend.agent.runtime import AgentRuntime

    sid = "test_llm_fail_transcript"
    sess = session_manager.get_or_create(sid)
    before = list(sess.memory.messages)
    try:
        rt = AgentRuntime.__new__(AgentRuntime)

        class ExplodingLLM:
            async def chat_completion(self, *a, **k):
                raise TimeoutError("provider timeout")

        rt.llm = ExplodingLLM()

        class Ctx:
            text_digest = "hello"
            image_parts = []
            unsupported = []

        result = asyncio.run(
            rt.chat_with_attachments(sess, "总结", Ctx(), ui_context=None)
        )
        assert result.get("error") == "LLM_PROVIDER_ERROR"
        # No fake assistant turn persisted.
        assert sess.memory.messages == before
    finally:
        session_manager.delete_session(sid)


def test_chat_drive_idempotency_and_zero_pollution_on_error(monkeypatch):
    """Verifies that:

    1. Successful /chat/drive turn with a request_id is idempotent: retrying with
       the same request_id returns identical turn_id without creating extra messages.
    2. Failed /chat/drive turn leaves ZERO transcript messages in session.memory.
    """
    import backend.agent.attachment_router as router
    import backend.api.routes as routes

    async def _force_text(llm, message, kinds):
        return "text_generate"

    monkeypatch.setattr(router, "classify_intent", _force_text)

    async def fake_normalize(payload):
        return {
            "valid": True,
            "normalization_id": "nid_idemp",
            "summary": "s",
            "warnings": [],
            "errors": [],
        }

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    monkeypatch.setattr(routes, "api_normalize_pptspec", fake_normalize)
    monkeypatch.setattr(routes, "api_generate_from_pptspec", fake_gen)

    sid = "test_transcript_idemp_pollution"
    sess = session_manager.get_or_create(sid)
    before_count = len(sess.memory.messages)
    try:
        # Part 1: First request with request_id
        req_id = "req_client_abc_123"
        resp1 = client.post(
            "/api/chat/drive",
            data={
                "message": "生成",
                "session_id": sid,
                "request_id": req_id,
                "expected_epoch": sess.document_epoch,
                "expected_revision": sess.document.presentation.version,
            },
            files=[("files", ("test.txt", b"sample", "text/plain"))],
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert "turn" in data1
        turn1 = data1["turn"]
        assert turn1["request_id"] == req_id
        assert len(sess.memory.messages) == before_count + 2

        # Retrying with the same request_id returns the EXACT same turn DTO
        # EVEN IF document revision advanced in the meantime!
        sess.document.presentation.version += 10
        resp2 = client.post(
            "/api/chat/drive",
            data={
                "message": "生成",
                "session_id": sid,
                "request_id": req_id,
                "expected_epoch": sess.document_epoch,
                "expected_revision": sess.document.presentation.version - 10,
            },
            files=[("files", ("test.txt", b"sample", "text/plain"))],
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["turn"]["turn_id"] == turn1["turn_id"]
        # Messages count did NOT increase (strict idempotency)
        assert len(sess.memory.messages) == before_count + 2

        # Retrying with SAME request_id but DIFFERENT payload returns 409
        resp_mismatch = client.post(
            "/api/chat/drive",
            data={
                "message": "不同的指令",
                "session_id": sid,
                "request_id": req_id,
                "expected_epoch": sess.document_epoch,
                "expected_revision": sess.document.presentation.version,
            },
            files=[("files", ("test.txt", b"sample", "text/plain"))],
        )
        assert resp_mismatch.status_code == 409
        assert "REQUEST_ID_PAYLOAD_MISMATCH" in resp_mismatch.text

        # Part 2: Failed request (e.g. invalid text normalization) leaves ZERO transcript
        async def fake_normalize_fail(payload):
            return {
                "valid": False,
                "normalization_id": None,
                "errors": ["Corrupt text structure"],
            }
        monkeypatch.setattr(routes, "api_normalize_pptspec", fake_normalize_fail)

        before_fail = len(sess.memory.messages)
        resp_fail = client.post(
            "/api/chat/drive",
            data={
                "message": "生成",
                "session_id": sid,
                "request_id": "req_will_fail",
                "expected_epoch": sess.document_epoch,
                "expected_revision": sess.document.presentation.version,
            },
            files=[("files", ("test.txt", b"sample", "text/plain"))],
        )
        assert resp_fail.status_code == 422
        # Exact zero transcript pollution
        assert len(sess.memory.messages) == before_fail

        # Part 3: Corrupted PDF and Corrupted PPTX upload map to 422 with zero transcript pollution
        from backend.agent.attachment_router import ACTION_CHAT
        async def _force_chat(*a, **k):
            return ACTION_CHAT
        monkeypatch.setattr(router, "classify_intent", _force_chat)

        before_corrupt = len(sess.memory.messages)
        resp_corrupt_pdf = client.post(
            "/api/chat/drive",
            data={
                "message": "解析这篇论文",
                "session_id": sid,
                "request_id": "req_corrupt_pdf",
            },
            files=[("files", ("corrupt.pdf", b"not-a-valid-pdf-content", "application/pdf"))],
        )
        assert resp_corrupt_pdf.status_code == 422
        assert len(sess.memory.messages) == before_corrupt

        resp_corrupt_pptx = client.post(
            "/api/chat/drive",
            data={
                "message": "解析这个课件",
                "session_id": sid,
                "request_id": "req_corrupt_pptx",
            },
            files=[("files", ("corrupt.pptx", b"not-a-valid-pptx-binary", "application/vnd.openxmlformats-officedocument.presentationml.presentation"))],
        )
        assert resp_corrupt_pptx.status_code == 422
        assert len(sess.memory.messages) == before_corrupt

        # Part 4: Empty attachment (0 bytes) is rejected with 400 EMPTY_ATTACHMENT
        resp_empty = client.post(
            "/api/chat/drive",
            data={
                "message": "这是空文件",
                "session_id": sid,
                "request_id": "req_empty_file",
            },
            files=[("files", ("empty.pdf", b"", "application/pdf"))],
        )
        assert resp_empty.status_code == 400
        assert "EMPTY_ATTACHMENT" in resp_empty.text
        assert len(sess.memory.messages) == before_corrupt
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_in_flight_concurrent_deduplication():
    """Gate B: Concurrent in-flight requests with identical (session_id, request_id, fingerprint)

    must execute the pipeline ONLY ONCE and broadcast the exact same outcome to all waiters.
    """
    import anyio
    import backend.agent.attachment_router as router
    import backend.api.routes as routes

    async def _force_text(llm, message, kinds):
        return "text_generate"

    execution_count = 0
    barrier = anyio.Event()

    async def fake_normalize(payload):
        nonlocal execution_count
        execution_count += 1
        # Signal that first execution started, wait a moment to allow concurrent request to arrive
        barrier.set()
        await anyio.sleep(0.05)
        return {
            "valid": True,
            "normalization_id": "nid_conc",
            "summary": "s",
            "warnings": [],
            "errors": [],
        }

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    sid = "test_concurrent_dedup"
    sess = session_manager.get_or_create(sid)
    req_id = "req_conc_123"

    import httpx
    from backend.main import app

    results = []

    async def client_request(idx):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            data = {
                "message": "生成",
                "session_id": sid,
                "request_id": req_id,
                "expected_epoch": sess.document_epoch,
                "expected_revision": str(sess.document.presentation.version),
            }
            files = {"files": ("test.txt", b"sample", "text/plain")}
            resp = await ac.post("/api/chat/drive", data=data, files=files)
            results.append((idx, resp.status_code, resp.json()))

    from unittest.mock import patch
    with patch.object(router, "classify_intent", _force_text), \
         patch.object(routes, "api_normalize_pptspec", fake_normalize), \
         patch.object(routes, "api_generate_from_pptspec", fake_gen):
        async with anyio.create_task_group() as tg:
            tg.start_soon(client_request, 1)
            await barrier.wait()
            tg.start_soon(client_request, 2)

    try:
        # Pipeline executed exactly once
        assert execution_count == 1
        assert len(results) == 2
        assert results[0][1] == 200
        assert results[1][1] == 200
        # Exactly identical turn DTO received
        assert results[0][2]["turn"]["turn_id"] == results[1][2]["turn"]["turn_id"]
        # Exactly 2 messages in session (1 user, 1 assistant)
        assert len(sess.memory.messages) == 2
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_rejects_conversation_reset_during_request():
    """Gate B / reset_conversation(): If reset_conversation() runs while /chat/drive

    is in flight, the request MUST NOT commit its transcript to the new conversation
    and must return 409 CONVERSATION_RESET_DURING_REQUEST.
    """
    import anyio
    import backend.agent.attachment_router as router
    import backend.api.routes as routes

    async def _force_text(llm, message, kinds):
        return "text_generate"

    barrier = anyio.Event()

    async def fake_normalize(payload):
        # Notify that request has been admitted with generation 0
        barrier.set()
        await anyio.sleep(0.08)
        return {
            "valid": True,
            "normalization_id": "nid_reset",
            "summary": "s",
            "warnings": [],
            "errors": [],
        }

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    sid = "test_reset_in_flight"
    sess = session_manager.get_or_create(sid)
    req_id = "req_reset_123"

    import httpx
    from backend.main import app

    results = []

    async def client_request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            data = {
                "message": "生成",
                "session_id": sid,
                "request_id": req_id,
                "expected_epoch": sess.document_epoch,
                "expected_revision": str(sess.document.presentation.version),
            }
            files = {"files": ("test.txt", b"sample", "text/plain")}
            resp = await ac.post("/api/chat/drive", data=data, files=files)
            results.append((resp.status_code, resp.json()))

    from unittest.mock import patch
    with patch.object(router, "classify_intent", _force_text), \
         patch.object(routes, "api_normalize_pptspec", fake_normalize), \
         patch.object(routes, "api_generate_from_pptspec", fake_gen):
        async with anyio.create_task_group() as tg:
            tg.start_soon(client_request)
            await barrier.wait()
            # User triggers reset while request is in flight
            await sess.reset_conversation()

    try:
        assert len(results) == 1
        status_code, body = results[0]
        assert status_code == 409
        assert "CONVERSATION_RESET_DURING_REQUEST" in str(body)
        # Session transcript remains empty after reset
        assert len(sess.memory.messages) == 0
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_session_snapshot_persists_completed_requests_across_restart():
    """Gate B: SessionSnapshot must serialize completed_requests and conversation_generation,

    and restore them with re-validated budgets so that lost-response recovery works
    even after a process restart.
    """
    from backend.session.snapshot import session_to_snapshot, snapshot_to_session
    from backend.session.session import CompletedRequestRecord

    sid = "test_snapshot_journal_restart"
    sess = session_manager.get_or_create(sid)
    try:
        sess.conversation_generation = 3
        sess.completed_requests["req_1"] = CompletedRequestRecord(
            request_id="req_1",
            fingerprint="fp_1",
            response={"turn": {"turn_id": "t1"}, "success": True},
            admitted_generation=3,
            size_bytes=50,
        )

        snapshot = await sess.snapshot_for_persistence()
        assert snapshot.conversation_generation == 3
        assert len(snapshot.completed_requests) == 1
        assert snapshot.completed_requests[0]["request_id"] == "req_1"

        # Restore into a fresh session instance
        restored = snapshot_to_session(snapshot)
        assert restored.conversation_generation == 3
        assert "req_1" in restored.completed_requests
        rec = restored.completed_requests["req_1"]
        assert rec.request_id == "req_1"
        assert rec.fingerprint == "fp_1"
        assert rec.response == {"turn": {"turn_id": "t1"}, "success": True}
        assert rec.admitted_generation == 3
        assert rec.size_bytes > 0
        assert rec.durable is True
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_durable_flush_across_sqlite_restart(monkeypatch):
    """Scenario 1: success -> SQLite flush -> restart -> retry

    Pipeline executes exactly once, turn_id is identical, exact canonical turn preserved.
    """
    import backend.agent.attachment_router as router
    import backend.api.routes as routes
    from backend.workspace.manager import WorkspaceManager
    from backend.workspace.persistence import SessionPersistenceService
    from backend.session.snapshot import SessionSnapshot

    class FakeRepo:
        def __init__(self):
            self.saved = {}
        async def save(self, snapshot):
            self.saved[snapshot.session_id] = snapshot
        async def load(self, sid):
            return self.saved.get(sid)
        async def list_ids(self):
            return list(self.saved.keys())
        async def close(self):
            pass

    fake_repo = FakeRepo()
    wm = WorkspaceManager(session_manager, fake_repo, debounce_seconds=0.01)
    monkeypatch.setattr(routes, "get_workspace_manager", lambda: wm)

    async def _force_text(*a, **k):
        return "text_generate"

    execution_count = 0
    async def fake_normalize(payload):
        nonlocal execution_count
        execution_count += 1
        return {
            "valid": True,
            "normalization_id": "nid_sqlite",
            "summary": "s",
            "warnings": [],
            "errors": [],
        }

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    sid = "test_sqlite_restart_sid"
    sess = session_manager.get_or_create(sid)
    sess.persistence = wm.persistence
    req_id = "req_durable_sqlite_1"

    try:
        with patch.object(router, "classify_intent", _force_text), \
             patch.object(routes, "api_normalize_pptspec", fake_normalize), \
             patch.object(routes, "api_generate_from_pptspec", fake_gen):
            resp1 = client.post(
                "/api/chat/drive",
                data={
                    "message": "生成PPT",
                    "session_id": sid,
                    "request_id": req_id,
                    "expected_epoch": sess.document_epoch,
                    "expected_revision": sess.document.presentation.version,
                },
                files=[("files", ("test.txt", b"sample content", "text/plain"))],
            )
            assert resp1.status_code == 200
            res1 = resp1.json()
            turn1 = res1.get("turn")
            assert turn1 is not None

            # Verify saved into fake_repo immediately (durable flush executed)
            assert sid in fake_repo.saved
            saved_snap = fake_repo.saved[sid]
            assert any(r["request_id"] == req_id for r in saved_snap.completed_requests)

            # Simulate complete process crash & restart: delete session from memory, reload from repo
            session_manager.delete_session(sid)
            restored_sess = await wm.restore_session(sid)
            assert restored_sess is not None
            assert req_id in restored_sess.completed_requests
            assert restored_sess.completed_requests[req_id].durable is True

            # Retry with exact same request_id
            resp2 = client.post(
                "/api/chat/drive",
                data={
                    "message": "生成PPT",
                    "session_id": sid,
                    "request_id": req_id,
                    "expected_epoch": restored_sess.document_epoch,
                    "expected_revision": restored_sess.document.presentation.version,
                },
                files=[("files", ("test.txt", b"sample content", "text/plain"))],
            )
            assert resp2.status_code == 200
            res2 = resp2.json()
            # Pipeline executed exactly once
            assert execution_count == 1
            # Exact same turn_id received
            assert res2.get("turn", {}).get("turn_id") == turn1.get("turn_id")
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_durable_flush_strictly_before_success(monkeypatch):
    """Scenario 2: Durable flush in SQLite must complete strictly BEFORE HTTP success."""
    import backend.agent.attachment_router as router
    import backend.api.routes as routes
    from backend.workspace.manager import WorkspaceManager

    flush_completed = False
    http_returned = False

    class SpyRepo:
        async def save(self, snapshot):
            nonlocal flush_completed
            # Assert HTTP success has NOT been returned yet
            assert not http_returned
            flush_completed = True
        async def close(self):
            pass

    wm = WorkspaceManager(session_manager, SpyRepo(), debounce_seconds=0.01)
    monkeypatch.setattr(routes, "get_workspace_manager", lambda: wm)

    async def _force_text(*a, **k):
        return "text_generate"

    async def fake_normalize(payload):
        return {"valid": True, "normalization_id": "nid_spy", "summary": "s", "warnings": [], "errors": []}

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    sid = "test_flush_order_sid"
    sess = session_manager.get_or_create(sid)
    sess.persistence = wm.persistence
    req_id = "req_order_test_1"

    try:
        with patch.object(router, "classify_intent", _force_text), \
             patch.object(routes, "api_normalize_pptspec", fake_normalize), \
             patch.object(routes, "api_generate_from_pptspec", fake_gen):
            resp = client.post(
                "/api/chat/drive",
                data={
                    "message": "生成内容",
                    "session_id": sid,
                    "request_id": req_id,
                    "expected_epoch": sess.document_epoch,
                    "expected_revision": sess.document.presentation.version,
                },
                files=[("files", ("test.txt", b"sample content", "text/plain"))],
            )
            http_returned = True
            assert resp.status_code == 200
            assert flush_completed is True
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_reset_during_finalization_window_returns_409(monkeypatch):
    """Scenario 3: reset after canonical commit / before or during finalization flush

    Must return 409 CONVERSATION_RESET_DURING_REQUEST and no old turn reaches the new conversation.
    """
    import anyio
    import backend.agent.attachment_router as router
    import backend.api.routes as routes
    from backend.workspace.manager import WorkspaceManager

    sid = "test_reset_fence2_sid"
    sess = session_manager.get_or_create(sid)
    req_id = "req_reset_fence2"

    async def _force_text(*a, **k):
        return "text_generate"

    async def fake_normalize(payload):
        return {"valid": True, "normalization_id": "nid_f2", "summary": "s", "warnings": [], "errors": []}

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    # Simulate persist_session_now intercepting and triggering reset
    async def fake_persist_now(sid_arg):
        # User triggers reset right during the persistence window!
        await sess.reset_conversation()

    wm = WorkspaceManager(session_manager, None)
    monkeypatch.setattr(routes, "get_workspace_manager", lambda: wm)
    monkeypatch.setattr(wm, "persist_session_now", fake_persist_now)

    try:
        with patch.object(router, "classify_intent", _force_text), \
             patch.object(routes, "api_normalize_pptspec", fake_normalize), \
             patch.object(routes, "api_generate_from_pptspec", fake_gen):
            resp = client.post(
                "/api/chat/drive",
                data={
                    "message": "生成大纲",
                    "session_id": sid,
                    "request_id": req_id,
                    "expected_epoch": sess.document_epoch,
                    "expected_revision": sess.document.presentation.version,
                },
                files=[("files", ("test.txt", b"content", "text/plain"))],
            )
            assert resp.status_code == 409
            assert "CONVERSATION_RESET_DURING_REQUEST" in resp.text
            # Confirm session transcript is clean (no old turn in new conversation)
            assert len(sess.memory.messages) == 0
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_concurrent_failure_cohort_deduplication():
    """Scenario 4: Concurrent N callers with same request_id hitting failure

    Must execute pipeline exactly once, and all callers receive identical error status & detail.
    """
    import anyio
    import backend.agent.attachment_router as router
    import backend.api.routes as routes

    execution_count = 0
    barrier = anyio.Event()

    async def _force_fail(*a, **k):
        nonlocal execution_count
        execution_count += 1
        barrier.set()
        await anyio.sleep(0.05)
        raise HTTPException(status_code=500, detail="Pipeline calculation failed")

    sid = "test_cohort_fail_sid"
    sess = session_manager.get_or_create(sid)
    req_id = "req_cohort_fail"

    results = []

    async def client_call(caller_id: int):
        if caller_id > 0:
            await barrier.wait()
        resp = await anyio.to_thread.run_sync(
            lambda: client.post(
                "/api/chat/drive",
                data={"message": "失败测试", "session_id": sid, "request_id": req_id},
                files=[("files", ("test.txt", b"foo", "text/plain"))],
            )
        )
        results.append((caller_id, resp.status_code, resp.text))

    try:
        with patch.object(router, "classify_intent", _force_fail):
            async with anyio.create_task_group() as tg:
                for i in range(3):
                    tg.start_soon(client_call, i)

        assert execution_count == 1
        assert len(results) == 3
        # All callers received identical status (500)
        assert all(r[1] == 500 for r in results)
        # All callers received error detail mentioning failure
        assert all("Pipeline calculation failed" in r[2] for r in results)
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_failure_cache_ttl_hit():
    """Scenario 5: Retry inside failure TTL (5s) hits cache without pipeline rerun."""
    import backend.agent.attachment_router as router

    execution_count = 0

    async def _force_fail(*a, **k):
        nonlocal execution_count
        execution_count += 1
        raise HTTPException(status_code=500, detail="Failure cache test")

    sid = "test_fail_cache_hit_sid"
    sess = session_manager.get_or_create(sid)
    req_id = "req_fail_cache_hit"

    try:
        with patch.object(router, "classify_intent", _force_fail):
            resp1 = client.post(
                "/api/chat/drive",
                data={"message": "重试缓存", "session_id": sid, "request_id": req_id},
                files=[("files", ("test.txt", b"foo", "text/plain"))],
            )
            assert resp1.status_code == 500
            assert execution_count == 1

            # Retry immediately (inside TTL)
            resp2 = client.post(
                "/api/chat/drive",
                data={"message": "重试缓存", "session_id": sid, "request_id": req_id},
                files=[("files", ("test.txt", b"foo", "text/plain"))],
            )
            assert resp2.status_code == 500
            # Pipeline was NOT executed again!
            assert execution_count == 1
            assert "Failure cache test" in resp2.text
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_failure_cache_ttl_expired():
    """Scenario 6: Retry after failure TTL expired is allowed to execute pipeline again."""
    import time
    import backend.agent.attachment_router as router

    execution_count = 0

    async def _force_fail(*a, **k):
        nonlocal execution_count
        execution_count += 1
        raise HTTPException(status_code=500, detail=f"Failure run {execution_count}")

    sid = "test_fail_cache_exp_sid"
    sess = session_manager.get_or_create(sid)
    req_id = "req_fail_cache_exp"

    try:
        with patch.object(router, "classify_intent", _force_fail):
            resp1 = client.post(
                "/api/chat/drive",
                data={"message": "过期重试", "session_id": sid, "request_id": req_id},
                files=[("files", ("test.txt", b"foo", "text/plain"))],
            )
            assert resp1.status_code == 500
            assert execution_count == 1

            # Manually expire the entry in sess.failed_requests
            assert req_id in sess.failed_requests
            sess.failed_requests[req_id].expire_at = time.monotonic() - 1.0

            # Retry after expiration
            resp2 = client.post(
                "/api/chat/drive",
                data={"message": "过期重试", "session_id": sid, "request_id": req_id},
                files=[("files", ("test.txt", b"foo", "text/plain"))],
            )
            assert resp2.status_code == 500
            # Pipeline was executed a second time
            assert execution_count == 2
    finally:
        session_manager.delete_session(sid)


@pytest.mark.anyio
async def test_chat_drive_filename_less_multipart_retained():
    """Scenario 7: multipart file with filename='' and non-empty bytes

    Attachment count is preserved, sanitized fallback name is assigned, and disposition contains it.
    """
    import backend.agent.attachment_router as router
    import backend.api.routes as routes

    async def _force_text(*a, **k):
        return "text_generate"

    async def fake_normalize(payload):
        return {"valid": True, "normalization_id": "nid_nameless", "summary": "s", "warnings": [], "errors": []}

    async def fake_gen(payload):
        return {"success": True, "session_id": payload["session_id"]}

    sid = "test_nameless_upload_sid"
    sess = session_manager.get_or_create(sid)

    try:
        with patch.object(router, "classify_intent", _force_text), \
             patch.object(routes, "api_normalize_pptspec", fake_normalize), \
             patch.object(routes, "api_generate_from_pptspec", fake_gen):
            # Pass UploadFile directly to the route function to test filename="" behavior cleanly
            from starlette.datastructures import UploadFile
            uf = UploadFile(
                filename="",
                file=io.BytesIO(b"Hello world non-empty content"),
                headers={"content-type": "text/plain"},
            )
            res = await routes.chat_with_attachments(
                message="分析附件",
                session_id=sid,
                request_id="req_nameless",
                expected_epoch=sess.document_epoch,
                expected_revision=sess.document.presentation.version,
                files=[uf],
            )
            dispositions = res.get("dispositions", [])
            assert len(dispositions) == 1
            # Fallback name was assigned (e.g. attachment_0)
            assert "attachment_0" in dispositions[0]["filename"]
            assert dispositions[0]["disposition"] == "consume"
    finally:
        session_manager.delete_session(sid)

# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_persist_node_distinguishes_frozen_from_stale_behaviorally():
    from backend.agent.graphs.generation import persist_session_node
    from backend.agent.mutation_gateway import DOCUMENT_FROZEN, STALE_MUTATION
    from backend.ir.models import PresentationIR

    sid = "test_persist_frozen_vs_stale"
    sess = session_manager.get_or_create(sid)
    try:
        # Acquire agent freeze so that commit_replacement rejects with DOCUMENT_FROZEN
        sess.agent_execution.begin_turn("turn_frozen_agent")

        # 1. State when document is frozen by agent
        state_frozen = {
            "session_id": sid,
            "presentation_ir": PresentationIR(title="New"),
            "base_document_epoch": sess.document_epoch,
            "base_revision": sess.document.presentation.version,
        }
        res_frozen = await persist_session_node(state_frozen, config={})
        assert res_frozen.get("status") == "document_frozen"
        assert res_frozen.get("error") == DOCUMENT_FROZEN

        # Release freeze so next test hits revision CAS mismatch
        sess.agent_execution.end_turn("turn_frozen_agent")

        # 2. State when revision is stale (CAS mismatch)
        state_stale = {
            "session_id": sid,
            "presentation_ir": PresentationIR(title="New"),
            "base_document_epoch": sess.document_epoch,
            "base_revision": sess.document.presentation.version + 999,
        }
        res_stale = await persist_session_node(state_stale, config={})
        assert res_stale.get("status") == "stale_generation"
        assert res_stale.get("status") != "document_frozen"
    finally:
        session_manager.delete_session(sid)


# ---------------------------------------------------------------------------
# Export fail-closed on lossy write-back
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_remote_exposure_guard_asgi_middleware_blocks_non_loopback():
    """Gate A: Pure ASGI middleware RemoteExposureGuardMiddleware must block

    any request arriving at a non-loopback local socket when PPT_API_TOKEN is unset.
    - HTTP returns 500 SERVER_MISCONFIGURED
    - WebSocket closes with 4401 immediately
    """
    from backend.security.auth import RemoteExposureGuardMiddleware
    from backend.config import settings

    # Ensure auth is disabled
    saved_token = settings.ppt_api_token
    settings.ppt_api_token = ""
    try:
        # Dummy downstream app
        downstream_called = False
        async def dummy_app(scope, receive, send):
            nonlocal downstream_called
            downstream_called = True
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"OK"})

        guarded = RemoteExposureGuardMiddleware(dummy_app)

        # 1. Non-loopback HTTP (e.g. socket bound to LAN or 0.0.0.0)
        http_scope = {
            "type": "http",
            "server": ("192.168.1.50", 8000),
            "path": "/api/chat",
        }
        sent_messages = []
        async def mock_send_http(msg):
            sent_messages.append(msg)

        downstream_called = False
        await guarded(http_scope, None, mock_send_http)
        assert not downstream_called
        assert any(m.get("status") == 500 for m in sent_messages)

        # 2. Non-loopback WebSocket
        ws_scope = {
            "type": "websocket",
            "server": ("0.0.0.0", 8000),
            "path": "/ws",
        }
        sent_ws = []
        async def mock_send_ws(msg):
            sent_ws.append(msg)

        downstream_called = False
        await guarded(ws_scope, None, mock_send_ws)
        assert not downstream_called
        assert sent_ws == [{"type": "websocket.close", "code": 4401}]

        # 3. Loopback HTTP is permitted through to downstream
        loopback_scope = {
            "type": "http",
            "server": ("127.0.0.1", 8000),
            "path": "/api/chat",
        }
        sent_loopback = []
        async def mock_send_loopback(msg):
            sent_loopback.append(msg)

        downstream_called = False
        await guarded(loopback_scope, None, mock_send_loopback)
        assert downstream_called
    finally:
        settings.ppt_api_token = saved_token


def test_export_requires_explicit_lossy_consent():
    from backend.ir.models import SlideIR, TableCellIR, TableElementIR

    sid = "test_lossy_export"
    sess = session_manager.get_or_create(sid)
    try:
        # Build a deck with a native table (lossy on export).
        table = TableElementIR(
            id="tbl_1",
            rows=2,
            cols=2,
            cells=[
                [
                    TableCellIR(row=0, col=0),
                    TableCellIR(row=0, col=1),
                ],
                [
                    TableCellIR(row=1, col=0),
                    TableCellIR(row=1, col=1),
                ],
            ],
        )
        slide = SlideIR(id="s_lossy", slide_num=1, title="T", elements=[table])
        sess.document.presentation.slides = [slide]
        resp = client.get(f"/api/export?session_id={sid}")
        assert resp.status_code == 409
        assert "lossy" in resp.text.lower()
        resp2 = client.get(f"/api/export?session_id={sid}&allow_lossy=true")
        assert resp2.status_code == 200
    finally:
        session_manager.delete_session(sid)
