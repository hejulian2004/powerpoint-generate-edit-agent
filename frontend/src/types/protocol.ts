// Wire protocol types: the backend/frontend transport contract.
//
// These describe envelopes exchanged over WebSocket/REST. They are intentionally
// separate from the editor state types in `ppt.ts` so a transport change never
// forces an editor-model change (and vice versa).
//
// The authoritative document type is the canonical snapshot below. It is the
// ONLY shape `adoptCanonicalSnapshot` accepts; `event_type` is transport
// metadata and is deliberately not part of the document snapshot.

import type { PresentationIR } from './presentation-ir.generated'

export interface UIContextWire {
  client_id: string
  ui_context_revision: number
  active_slide_id: string | null
  selected_element_ids: string[]
  primary_selected_element_id: string | null
  selection_scope: string[]
  editing_element_id: string | null
}

export interface LocalViewHintWire {
  active_slide_id: string | null
}

export interface CanonicalSnapshot {
  session_id: string
  presentation: PresentationIR
  document_epoch: string
  version: number
  active_slide_id: string | null
  can_undo: boolean
  can_redo: boolean
  last_target_id?: string | null
  last_mutation_id?: string | null
  // Navigation is client-local; this mutation-scoped hint travels ONLY on the
  // ack of the client that triggered a slide-creating mutation.
  local_view_hint?: LocalViewHintWire | null
}

export interface MutationRejectionWire {
  type: 'mutation_rejected'
  mutation_id: string
  error: string
  version: number
  document_epoch?: string | null
  presentation?: PresentationIR
  active_slide_id?: string | null
}

export interface ChatEnvelope {
  type: 'chat'
  message: string
  session_id: string
  document_epoch: string | null
  base_revision: number
  ui_context: UIContextWire
}
