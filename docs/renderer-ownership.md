# Renderer & IR Ownership

This document records which layer owns each concern so future changes land in
the right place and the two worlds never diverge silently.

## Ownership map

| Concern | Owner | Entry point |
| --- | --- | --- |
| IR data model / schema | Backend | `backend/ir/models.py` |
| Mutation kernel (CAS, history, idempotency) | Backend | `backend/agent/mutation_gateway.py` |
| Agent generation & grounding | Backend | `backend/agent/graph.py`, `backend/agent/grounding.py` |
| Session document identity (epoch/revision) | Backend | `backend/session/session.py` |
| Native `.pptx` write-back (export render) | Backend | `backend/state/store.py::export_pptx_bytes` |
| SVG slide preview (editor render) | Frontend | `frontend/src/components/SVGRendererComponent.tsx` |
| Editor interaction state (selection, drag) | Frontend | `frontend/src/store/usePPTStore.ts` |
| Optimistic UI + outbox/single-flight | Frontend | `frontend/src/store/usePPTStore.ts` |

Rules:

- The frontend **never** renders the exported file. Export is produced by the
  backend from an immutable epoch/revision-pinned copy (`snapshot_for_export`).
- The backend **never** trusts a local prediction. Every write goes through the
  Mutation Kernel and is CAS-checked against `(document_epoch, revision)`.
- Visual layout lives in the frontend renderer; the IR only carries data.

## Sync boundary

The canonical snapshot is the *only* document shape crossing the boundary:

```
{ session_id, presentation, document_epoch, version,
  active_slide_id, can_undo, can_redo, last_target_id, last_mutation_id }
```

`adoptCanonicalSnapshot` is the single frontend entry point. `event_type`
(`presentation_loaded` / `presentation_updated`) is transport metadata and is
not part of the document snapshot.

## Protocol vs editor types

- `frontend/src/types/protocol.ts` — WebSocket/REST envelopes
  (`CanonicalSnapshot`, `UIContextWire`, `MutationRejectionWire`,
  `ChatEnvelope`). Changes here are transport changes.
- `frontend/src/types/ppt.ts` — editor/IR types used by the renderer and store.
  These mirror the backend models.

Keeping them separate means a transport change never forces an editor-model
change, and vice versa.

## Drift guard

`frontend/src/types/ppt.ts` mirrors the Pydantic models by hand, so the backend
exports a checked-in JSON Schema:

```
python -m backend.ir.schema_export          # regenerate
python -m backend.ir.schema_export --check  # verify (runs in CI + pytest)
```

`tests/test_ir_schema_drift.py` fails when a model changes without regenerating
`frontend/src/types/ir.schema.json`. Always commit the regenerated schema in the
same change as the model edit.
