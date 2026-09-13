# PR #28 Post-Merge Hardening — Security & Authority Invariants

Base: `9399044b8b1a0655bdd7f009895cbbccd4bde631` (single hardening branch,
Phase 0–3 internally gated, no parallel hardening branches).

Acceptance order (hard gates):

```text
Phase 0 Security
        ↓ must all pass
Phase 1 Authority / CAS
        ↓ must all pass
Phase 2 Attachment / Transcript
        ↓ must all pass
Phase 3 Adversarial Regression
        ↓
Full backend + frontend + schema CI
        ↓
Merge review
```

Phase 0 any SSRF / key-leakage / unauthenticated remote-or-WebSocket /
traversal / budget bypass = P0, blocks merge. Phase 1 any stale-tab
confirmation / replacement-without-caller-stamp / frozen-stale confusion =
P1, blocks merge. Phase 2 any silent attachment drop or UI-transcript vs
Agent-memory divergence blocks merge.

## Phase 0 — Upload isolation, outbound policy, auth, budgets

### Upload filenames never form paths

- `UploadFile.filename` is client-controlled. All PDF/PPTX ingestion writes to
  a server-generated fixed name (`tmp/input.pdf`, `NamedTemporaryFile`).
- `sanitize_upload_name()` (`backend/security/upload_names.py`) is the only
  allowed derivation for display metadata: it normalizes `\` → `/`, keeps the
  final segment, strips NULs, truncates to 255 chars, falls back on empty/`.`/
  `..`. `Path(name).name` alone is banned (Windows separators survive on Linux).

### Outbound provider probing (`OutboundURLPolicy`)

- Custom `base_url` NEVER inherits `settings.openai_api_key`. The saved key is
  attached only when probing the configured default host (or when no base_url
  override is given).
- Scheme must be http/https; userinfo is rejected; redirects are disabled
  (`follow_redirects=False`, 3xx → 403).
- Literal IPs are judged with `ipaddress` (private/loopback/link-local/
  multicast/reserved/unspecified all blocked, incl. 169.254.169.254).
- DNS hosts: EVERY A/AAAA result must be globally routable public; one private
  result rejects the whole URL.
- DNS-rebinding TOCTOU is closed with `pinned_dns()`: the validated IP set is
  enforced during connect by constraining `socket.getaddrinfo(host)` to those
  IPs. Host/SNI still use the original hostname, so TLS keeps validating.
- If pinning cannot be applied, v1 must restrict custom providers to an
  explicit `TRUSTED_PROVIDER_HOSTS` allowlist instead of claiming generic-URL
  safety.

### Authenticated remote mode

```text
local mode:    127.0.0.1 by default, auth optional
remote mode:   non-loopback bind + no PPT_API_TOKEN => startup failure
secure mode:   PPT_API_TOKEN set => REST + WebSocket both enforce auth
```

- Default `HOST` is `127.0.0.1` (was `0.0.0.0`).
- REST: `Authorization: Bearer <PPT_API_TOKEN>` on every `/api/*` (docs/health
  stay public). Missing/invalid → 401.
- WebSocket: verified BEFORE `session.connection.attach()` (no ownership for
  unauthenticated sockets) → close 4401. Browser path uses
  `Sec-WebSocket-Protocol: ppt-token.<TOKEN>`; permanent tokens are never
  accepted via URL query string.

### Resource budgets (before expensive work)

- `read_upload_bounded()` streams in 64 KiB chunks; `Content-Length` is only a
  pre-reject hint.
- `validate_ooxml_zip_budget()` inspects the ZIP central directory BEFORE the
  OOXML parser: entry count, total/single uncompressed size, compression ratio,
  encrypted entries, `..` traversal.
- PDF page count (`get_pdf_page_count()` fast header read) is checked BEFORE
  full parse/raster/vision; vision fan-out is bounded by `VisionWorkLimiter`
  semaphore.
- `wait_for(to_thread(parse))` is NOT a CPU-cancellation boundary; hard CPU
  isolation requires a worker process (documented limitation, not claimed as
  fixed).

## Phase 1 — Plan authority, strict CAS, terminal semantics, export consent

- `POST /plan/confirm` REST is retired (410, WebSocket-only). The sole path is
  `{"type":"confirm_plan"/"cancel_plan","plan_id"}` over the owning `/ws`
  connection with server-bound `connection_generation`
  (`session.connection.assert_current`). `GET /plan/pending` (read-only list)
  is retained.
- Whole-document replacement (`/upload`, `/pptspec/generate`,
  `/paper/generate`, `/chat/drive` mutating branches) requires
  caller-observed `expected_epoch + expected_revision`; missing either →
  `409 MISSING_REPLACEMENT_STAMP`. No server-current fallback.
- `persist_session_node()` distinguishes terminals: `DOCUMENT_FROZEN` →
  `status="document_frozen"`; epoch/revision mismatch → `stale_generation`;
  the real `error` code is preserved (never coerced to `None`).
- Export defaults to `allow_lossy=False` on the route AND
  `PresentationStore.export_pptx_bytes()` AND `ir.converter.export_pptx()`.
  Lossy decks (e.g. native Table) → `409 lossy_export_requires_confirmation`;
  callers retry explicitly with `allow_lossy=true`. Internal batch pipelines
  opt in explicitly.

## Phase 2 — Attachment disposition & durable turn ownership

### Explicit disposition (fail-closed)

```python
AttachmentDisposition(
    attachment_id, filename, kind,
    disposition="consume" | "unsupported" | "unused",
    action, reason,
)
```

- `ACTION_CHAT`: supported → consume (read-only), unknown → unsupported
  (model receives an explicit not-read notice; all-unsupported → 415).
- Mutating actions: FIRST required-kind attachment → consume; every other file
  (extra same-kind, other kinds, unknown) → unused/unsupported.
- Gate: `∀ d: d.disposition == "consume"` else `400 UNPROCESSED_ATTACHMENTS`
  with full `dispositions[]` + `unprocessed[]`. No silent `_first()` drops.

### `/chat/drive` transactional turn owner

```text
UserTurn (text + provenance) → execute action → success: AssistantTurn(metadata)
                                              → failure: no fake assistant write
```

- Provenance only (never binary/digest/data-URI):
  `{name, kind, sha256, size_bytes, action, cache_key?, status}`.
- `conversation_lock` guards transcript admission/commit only, never the
  minutes-long paper/vision pipeline; document concurrency stays with
  CAS/Agent-lease. Commits are atomic User+Assistant pairs after success.
- Parse failure (422/415) vs inference failure (502 `LLM_PROVIDER_ERROR`) are
  separated; provider errors never become `success:true` transcript turns.

## Phase 3 — Regression gates

`tests/security/test_hardening_pr28.py` (26 tests) covers: cross-platform
sanitization, fixed-path contract, literal-IP/SSRF/DNS/pinning, key isolation,
startup guard, REST 401, WS pre-ownership ordering, streaming/zip/pdf budgets,
strict CAS stamps, REST plan retirement, full-consumption disposition,
drive fail-closed, provenance persistence, LLM 502 without pollution,
frozen-vs-stale distinction, lossy-export consent.

## Repository governance (recommended, non-code)

```text
main:
- require PR (no direct push, no force push)
- require Backend pytest
- require Frontend build & tests
- require schema/TS drift checks
```

## Commit map (PR #28)

```text
Phase 0 (consolidated: uploads + outbound + auth + budgets landed together)
fix(security): isolate uploads and secure outbound provider probing
  (includes authenticated remote mode + bounded upload budgets: default
  127.0.0.1, PPT_API_TOKEN for REST+WS, streaming/zip/pdf/vision budgets)
Phase 1
fix(authority): align plan confirmation and replacement CAS boundaries
  (includes frozen/stale terminals + allow_lossy=False per doc fix)
Phase 2
refactor(attachments): introduce explicit attachment disposition plans
fix(chat): make chat/drive the durable turn owner
fix(chat): separate parse and provider failure semantics
Phase 3
test(hardening): add adversarial security and authority regressions
docs(hardening): document security/authority invariants
```
