# Concurrency Hardening Plan

Baseline: `main` @ `8931257` (PR #22 merged). Branch: `hardening/concurrency-interlock`.

This document is the contract for the GUI / Agent / Generation concurrency interlock. It fixes the invariants, the replacement transaction API, the canonical snapshot envelope, the retry-vs-rebase state machine, and the grounding policy. Each phase below is a commit on the same branch and must land green before the next begins.

---

## 1. Core Principle

> GUI and Agent may hold different interaction state, but they may only modify the same `PresentationIR` through one CAS-guarded Document Mutation Kernel.

```
                        ┌── GUI Direct Editor
                        │
                        │       UIContext
                        │          │
                        │          ↓
User ───────────────────┤       Agent
                        │          │
                        │          │ explicit operations
                        ↓          ↓
                    Mutation Kernel
                          │
                   CAS / preconditions
                          │
                          ↓
                    PresentationIR
                          │
              canonical snapshot broadcast
                          │
              ┌───────────┴───────────┐
              ↓                       ↓
           Client A                 Client B
```

Deterministic user edits never route through the Agent. The Agent is one caller of the kernel, not its owner.

---

## 2. Invariants

### Invariant A — PresentationIR is the document state

```
DocumentState:
  PresentationIR
  document_epoch
  document_revision
```

`(document_epoch, document_revision)` is the document identity. A replacement may reset `version` to 1; identity is carried by the pair, never by `version` alone.

### Invariant B — UIContext is not document state

```
UIContext:
  client_id
  ui_context_revision
  active_slide_id
  selected_element_ids
  primary_selected_element_id
  selection_scope
  editing_element_id
```

`UIContext` is request-scoped and never enters `PresentationIR`.

### Invariant C — GUI and Agent share the Mutation Kernel, not an entry point

GUI deterministic edits (drag, resize, property change, align, group, undo/redo) go straight to the kernel. The Agent emits explicit operations into the same kernel. Neither bypasses CAS.

### Invariant D — retry and rebase are different state transitions

```
Retry  (network drop / lost ACK, NO explicit stale):
  same mutation_id
  same document_epoch
  same expected_revision      # frozen at first send, never restamped

Rebase (explicit stale_mutation + authoritative snapshot):
  install snapshot
  validate original operation against field/structure preconditions
  establish a NEW CAS attempt
```

`dispatchNextMutation` must never be changed back to restamping the latest revision on every send. That was the PR #22 HIGH fix.

`turn_base_revision` (Chat request start) is not `plan_base_revision` (each Executor plan attempt start). Stale replan must re-capture both.

### Invariant E — epoch mismatch never auto-rebases

Same epoch + stale revision may attempt rebase. Different `document_epoch` must never be replayed: the deck may be entirely different. Report the conflict and drop.

---

## 3. Replacement Transaction

All whole-document replacement (Upload, Generate, Import, Restore) uses one API. It owns the lock and the CAS; callers do not.

```python
async def commit_replacement(
    self,
    pres: PresentationIR,
    *,
    expected_epoch: str,
    expected_revision: int,
    clear_history: bool = True,
    clear_checkpoints: bool = True,
    checkpoint_description: str | None = None,
) -> ReplacementResult: ...

ReplacementResult(
    committed: bool,
    error: None | "stale_generation" | "document_epoch_mismatch",
    old_epoch: str,
    old_revision: int,
    document_epoch: str,
    version: int,
)
```

Inside: acquire `mutation_lock` → check epoch → check revision → replace → rotate epoch → clear stale state → return the new canonical stamp.

`replace_presentation()` is demoted to a private primitive. Expensive compute (PPTX parse, generation) runs **outside** the lock; only the commit is locked.

Generation commits compare the **live session revision** against the captured `base_revision` (the generated IR always carries `version=1`, so its own version is not comparable).

---

## 4. Canonical Snapshot

One transport-neutral builder, used by WS success, `presentation_loaded`, REST upload, generate, chat fallback, checkpoint restore, and `GET /presentation/snapshot`.

```json
{
  "session_id": "sess_x",
  "presentation": {},
  "document_epoch": "epoch_x",
  "version": 42,
  "active_slide_id": "slide_1",
  "can_undo": true,
  "can_redo": false,
  "last_target_id": "el_1",
  "last_mutation_id": null
}
```

`event_type` (`presentation_loaded` / `presentation_updated`) is transport metadata, not part of the snapshot. The frontend has exactly one server-document entry point: `adoptCanonicalSnapshot(snapshot)`. The legacy `GET /presentation` stays raw IR for compatibility but must not be used to correct canonical state.

---

## 5. UIContext and Agent Targeting

`active_slide_id` is not a shared document field for targeting. The Agent receives `ui_context.active_slide_id` per request. The planner works on a request-local deep snapshot with `snapshot.active_slide_id = ui_context.active_slide_id`, leaving the live IR untouched.

Deictic references (`这个 / 这个框 / 它 / 当前这个 / 选中的 / 这些 / 它们 / 这几个`) are fail-closed:

- valid selection in `ui_context` → bind to explicit element id(s);
- no valid selection → **clarification / no-op**, never `last_target_id`.

`last_target_id` remains valid only for continuation edits (`再往右一点`, `再大一点`).

`ui_context_revision` increments on selection change, slide change, enter/exit group, and editing-target change. A request freezes it; later changes do not affect the in-flight request.

---

## 6. Rebase Preconditions

Every rebaseable mutation records the minimal necessary precondition at authoring time, not just structural operations.

- Field update (`update_element`, style, geometry): precondition stores the target property values read at authoring time. On rebase, if the same element + same property was changed remotely → **conflict**; different element or property with unchanged parent/group → safe replay.
- Structural operations (`group`, `ungroup`, `delete`, `duplicate`, slide delete): use a structure fingerprint (existence, parent/group relationship, element type).

Conflict classes that must not silently overwrite:

```
target element deleted
target parent/group changed
same property changed remotely
slide deleted
element type changed
```

Optimistic UI is rebuilt locally from `canonical snapshot + pending operations` before network replay, so the user does not see their edits vanish and reappear.

Mutation idempotency is extended with a logical payload hash:

```
cache key = (document_epoch, mutation_id)
logical_payload_hash = hash(operations, client identity, client_sequence)
```

`expected_revision` / `document_epoch` are **not** part of the logical hash (rebase changes the CAS attempt, not the logical operation). Same id with a different payload → `mutation_id_payload_mismatch`, not a cache hit. This ships in Phase 4.

---

## 7. Sequencing Barrier

`awaitDirectSyncBarrier({ timeoutMs })` resolves only when:

```
pendingMutations == 0
outbox == 0
inFlightMutationId == null
hasServerRevision == true
mutationStatus ∉ { failed, rolled_back }
```

Offline → fail immediately. Timeout → `LOCAL_CHANGES_NOT_SYNCED` and the follow-up action (Chat / Export / Upload / Generate / Restore) must not run.

Backend Export uses an immutable revision snapshot: capture a deep copy plus epoch/revision under the lock, release, then render. The file corresponds to one deterministic revision.

---

## 8. Grounding Policy (ALLOW / PLACEHOLDER / BLOCK)

Grounding returns a structured verdict, never a bare bool:

```
GroundingVerdict:
  decision:    ALLOW | PLACEHOLDER | BLOCK
  claim:       str
  category:    numeric | performance | compatibility | attribution | qualitative
  reason:      str
  evidence:    str | None
  replacement: str | None
```

Tiers:

- **BLOCK** (hard, no evidence allowed): numbers, percentages, multipliers, latency, throughput, accuracy, SOTA, specific experimental comparisons, explicit platform-compatibility ranges, explicit source attribution. These may not be written without evidence.
- **PLACEHOLDER / clarification**: qualitative claims that imply a factual commitment but are semantically fuzzy, e.g. `毫秒级`, `无损`, `全平台`, `业界领先`, `企业级可靠性`. Without a source, degrade to `[待验证性能描述]`, `[待补充兼容性依据]`, or ask the user. `企业级` alone is PLACEHOLDER; a specific commitment such as `企业级 SLA 99.99%` or `满足企业级高并发要求` escalates to BLOCK.
- **ALLOW**: design, subjective, and non-factual copy, e.g. `简洁视觉风格`, `突出核心结论`, `提升信息层级感`.

The policy is data-driven so tuning false positives changes only the policy table, never the Generation / Mutation main path.

Grounding applies to **all** generation tools (`generate_presentation`, `generate_slide_layout`, `batch_add_cards`), not only the `generate_presentation` intent. Ambiguous `modify` requests produce clarification, never a generic `add_shape`.

---

## 9. Phase Plan

| Phase | Scope | Key acceptance |
| --- | --- | --- |
| 0 | This document + invariants + state matrix | Reviewed contract, no code |
| 1 | Document concurrency correctness: `commit_replacement`, `state/store.py`, generation base stamps, per-plan executor freeze, remediation binding | Generation/Agent can never overwrite revisions created after start |
| 2 | Canonical protocol module + `adoptCanonicalSnapshot` + `/presentation/snapshot` + REST chat fallback | Every path broadcasts/consumes one envelope; no stale CAS token |
| 3 | UIContext (`client_id`, `ui_context_revision`), request-local active slide, deictic fail-closed | "把这个改红" hits the selected element; two clients are isolated |
| 4 | Direct rebase: retry vs rebase state machine, `authoredBaseRevision`, `clientSequence`, payload hash, field/structure preconditions, optimistic replay | Stale never silently drops or overwrites; PR #22 frozen retry preserved |
| 5 | Sequencing barrier (Chat/Export/Upload/Generate/Restore), backend export snapshot, atomic center batch | Agent/export always see committed edits |
| 6 | Grounding & ambiguity hardening with ALLOW/PLACEHOLDER/BLOCK | No fabricated metrics; ambiguous modify clarifies |
| 7 | Schema/architectural consolidation: generated IR types, protocol/editor split, drift + lint CI, renderer ownership docs | Backend and frontend IR cannot drift silently |

Commits are per phase, no squash. Each phase lands with the full suite green.

---

## 10. Interleave Test Matrix

| Test | Acceptance |
| --- | --- |
| GUI edits while LLM planning | stale Agent plan rejected / replanned |
| GUI edits during PPT generation | generation cannot overwrite GUI edit |
| GUI edit immediately followed by Chat | Agent sees the committed edit |
| Agent mutation makes GUI queue stale | pending op is rebased, not lost |
| stale + different-field remote edit | auto rebase succeeds |
| stale + same-field remote edit | explicit conflict, no silent overwrite |
| offline edit + remote update + reconnect | rebase or conflict; authored revision never upgraded |
| ACK lost without stale rejection | reconnect reuses original CAS stamp (PR #22 regression) |
| selected element + "把这个改红" | exact selected element modified |
| selection changes during planning | frozen UIContext used |
| selected element deleted while planning | clarification, no guessing |
| Client A changes slide, Client B chats | B uses its own UIContext active slide |
| export while another client edits | export matches one deterministic revision |
| upload with local mutations pending | barrier, then replacement; no silent local loss |
| two clients same session | Client A selection does not pollute Client B |
| generate/upload/restore epoch rotation | frontend gets correct epoch/version immediately |
| same mutation id + different payload | `mutation_id_payload_mismatch` |
| visual remediation on a stale screenshot | repair does not act on the newer deck |

---

## 11. Verification

```
Backend:  D:\PPT\.venv\Scripts\python.exe -m pytest -q
Frontend: npm run test && npm run build && npm run lint   (cwd frontend)
```

CI is updated (Phase 7) to run frontend lint in addition to build/test so the merge gate matches the local gate.
