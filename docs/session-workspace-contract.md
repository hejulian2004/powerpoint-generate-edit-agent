# Session & Workspace Contract (Single-User Persistent Workspace)

Baseline: PR #23 @ `9c0598ba2259526d3d1e7b42f9ee4884d1e22b73`. Branch: `refactor/persistent-session-workspace` (PR #24).

This document is the product and architecture contract for the **single-user persistent workspace** model. It supersedes the multi-client assumptions of [`concurrency-hardening-plan.md`](./concurrency-hardening-plan.md): PR #23 hardened concurrency for a collaborative, multi-frontend-per-session world; PR #24 narrows the product to **one user, one frontend per session, strict session isolation, and an Agent-exclusive edit window**, then builds durable workspace persistence on top.

No squash: one commit per phase, additive history.

---

## 1. Target architecture

```
Single User
    │
    ▼
WorkspaceManager
    │
    ├── last_active_session_id
    │
    └── SessionManager
            │
            ├── Session A
            │     ├── DocumentService
            │     ├── HistoryService
            │     ├── CheckpointService
            │     ├── MemoryService
            │     ├── ConfirmationService
            │     ├── AgentExecutionService
            │     ├── ConnectionService
            │     └── Persistence
            │
            └── Session B
                  └── 完全独立的一套状态
```

`AgentRuntime` is a **shared, stateless execution engine**. It owns no cross-session mutable memory: every session's conversation, agent memory, and subagent memories live in that session's `MemoryService`.

---

## 2. Core invariants

| ID | Invariant |
| --- | --- |
| **S1** | A `PPTSession` has at most **one online frontend** at any time. |
| **S2** | A `PresentationIR` object belongs to **exactly one** `PPTSession`. |
| **S3** | Different sessions have **fully isolated** presentation / memory / history / checkpoint / confirmation state. |
| **S4** | Production API never implicitly falls back to a `default` session. |
| **S5** | Reopening the app restores the workspace's `last_active_session`. |
| **S6** | A page refresh reconnects the **same** session; it never creates a new one. |
| **S7** | While an Agent turn is active, that session's frontend is **read-only**. |
| **S8** | The backend mutation boundary also rejects frontend writes while the session is frozen. |
| **S9** | `AgentRuntime` is a shared stateless engine; it holds no cross-session mutable memory. |
| **S10** | On backend restart, the last **committed** session state is restored; a half-executed Agent coroutine is never resumed. |

### 2.1 Ownership rules derived from S1–S10

- **Replacement writes** (import / PPTSpec generation / checkpoint restore) are the only sources of a new document identity (`document_epoch`), and they reset `version`.
- **Direct GUI writes** are `user_direct`; they must carry CAS stamps (`document_epoch`, `expected_revision`).
- **Agent writes** are `agent` / `remediation` and are only legal while holding the active Agent turn lease.
- **No silent fallback**: a missing `session_id` on a production path is an error, never `active_session`.

---

## 3. Three classes of state

### 3.1 Persistent State (survives restart)

- `PresentationIR`
- `document_epoch` (identity anchor; restored as persisted)
- `messages` (conversation transcript)
- `AgentMemory`
- `SubagentMemory` (per subagent)
- `checkpoints` (including the actual `PresentationIR` snapshot)
- workspace metadata (`last_active_session_id`, session ids)

### 3.2 Session Runtime State (never persisted)

- `mutation_lock`
- `active_agent_turn`
- live service objects
- idempotency cache (`completed_mutations`)

### 3.3 Connection State (never persisted)

- websocket
- `frontend_instance_id`
- `connection_generation`

---

## 4. Persistence invariants

### Invariant P1 — Idempotency cache is process-runtime state

`completed_mutations` is **not** persisted. Across a backend restart:

- exact cached-success replay is **not** guaranteed;
- a lost-ACK mutation may be rejected as `stale`/`document_epoch_mismatch` after restore;
- the canonical snapshot is authoritative;
- **the same mutation is never applied twice**.

Guarantee across restart: **no duplicate mutation**, not "same `mutation_id` always returns the original cached success forever". If that stronger guarantee is ever required, persist the most recent 256 idempotency entries — out of scope for PR24.

### Invariant P2 — Ephemeral security / execution state is never restored

After a backend restart:

```
pending confirmations = empty
active_agent_turn    = None
connection           = detached
in-flight transport mutations = dropped
```

A pending confirmation is bound to `document_epoch`, `expected_revision`, and tool arguments; letting it survive a process lifetime only extends the lifetime of a dangerous call. The user re-issues the Agent instruction instead.

### Invariant P3 — Debounced persistence with an explicit flush

`SessionPersistenceService` exposes:

```python
async def schedule_persist(...)   # mark dirty, coalesce
async def flush(...)              # durably write dirty state NOW
async def close(...)              # flush + close repository
```

Persistence is scheduled after: successful mutation commit, replacement, checkpoint restore, conversation-turn completion, meaningful memory update, session switch, and graceful shutdown.

Durability contract (locked):

```
Normal close / refresh / graceful restart : zero committed-state loss
Hard process crash                       : <= one debounce window may be lost
```

Session switch that both dirties the previous session and moves `last_active_session_id` is executed as **one repository transaction**:

```
flush previous dirty session
persist target session if required
update last_active_session_id
COMMIT
```

---

## 5. Product assumptions deprecated by this contract

Superseded from PR #23 (kept only as historical implementation):

- multiple frontends editing the same session;
- cross-client collaborative rebase;
- foreign-client causal-effect reconciliation (`localEffectLedger`).

## 6. Hardening preserved from PR #23

- CAS (`document_epoch` + `expected_revision`) on every mutation;
- `mutation_id` idempotency;
- single-flight mutation ordering;
- lost-ACK retry with the original attempt stamp;
- offline outbox;
- Agent / GUI serialization through the single writer (`MutationGateway`).

---

## 7. Exclusive frontend & Agent edit window

- **Newest tab wins.** On attach, the server issues a `connection_generation` bound to that WebSocket handler, sends `SESSION_TAKEN_OVER` to the previous socket, and closes it with a dedicated close code. The previous frontend sets `suppressReconnect = true` and never auto-reconnects.
- **Server-bound generation.** Every mutation / chat / confirm dispatch calls `session.connection.assert_current(websocket, bound_generation)`; a client-reported generation is never trusted.
- **Agent freeze authorizes by source + turn.** While `active_agent_turn` is set:
  - a mutation whose `agent_turn_id != active_agent_turn.turn_id` is rejected with `DOCUMENT_FROZEN`;
  - a mutation whose `source not in {"agent", "remediation"}` is rejected with `DOCUMENT_FROZEN`.
  The `agent_turn_id` is threaded end-to-end through `auto_correct_node` → `RemediationRunner.apply_plan` → `MutationGateway`.
- **Freeze is reflected in the canonical snapshot** as `edit_lock: {locked, kind, turn_id}` so a refreshed page immediately knows the deck is frozen.
- **No frozen-outbox replay.** If `document_frozen` arrives while local pending mutations exist (a race), they are marked `needs_resync`, never dispatched, and discarded when the final canonical snapshot arrives. Lost-ACK is resolved by `awaitDirectSyncBarrier()` before the turn starts.

## 8. Rebase policy (single-client)

Because S1 removes concurrent writers, stale mutations can only come from reconnect, REST, replacement, Agent turns, or backend restart. Therefore:

- `create_slide` → `safe` (purely additive);
- `update_element` (local field mutation) → field precondition;
- destructive / global operations (`delete_slide`, `clear_slide_elements`, `duplicate_slide`, `optimize_layout`, `apply_theme`) → `never` rebase: on stale, adopt the authoritative snapshot, roll back optimistic state, and let the user re-execute.

No weak "existence-only" fingerprint is permitted as a substitute for correctness.
