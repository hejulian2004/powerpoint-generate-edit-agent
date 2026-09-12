import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'
import { makeGroup, makePresentation, makeShape, makeSlide } from '../test/factories'
import type { TextElementIR } from '../types/ppt'

const resetStore = () => {
  usePPTStore.setState({
    sessionId: 'sess_test',
    presentation: null,
    confirmedPresentation: null,
    activeSlideId: null,
    selectedElementId: null,
    selectedElementIds: [],
    selectionScope: [],
    editingElementId: null,
    ws: null,
    wsConnected: false,
    previewSvg: null,
    previewScore: null,
    previewSlideId: null,
    qualityScore: null,
    pendingMutations: [],
    outbox: [],
    inFlightMutationId: null,
    inFlightMessage: null,
    documentEpoch: null,
    confirmedRevision: 0,
    hasServerRevision: false,
    clientId: 'client_test',
    uiContextRevision: 0,
    clientSequence: 0,
    mutationStatus: 'idle'
  })
}

const connect = () => {
  usePPTStore.getState().initWebSocket()
  const ws = FakeWebSocket.latest()
  ws.onopen?.({})
  return ws
}

const makeText = (id: string): TextElementIR => ({
  id,
  type: 'text',
  x: 0,
  y: 0,
  width: 120,
  height: 40,
  rotation: 0,
  z_index: 0,
  style: { opacity: 1, radius: 0, padding: 8 },
  text_content: {
    paragraphs: [{ align: 'left', line_spacing: 1.25, runs: [{ text: 'hello' }] }]
  },
  children: []
})

describe('usePPTStore mutation pipeline', () => {
  beforeEach(() => {
    installFakeWebSocket()
    resetStore()
  })

  it('optimistically applies geometry and clears it on server ack', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide])
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40, y: 25 })

    const sent = ws.sentMessages().find((m) => m.type === 'direct_update_element')!
    expect(sent).toBeTruthy()
    expect(sent.mutation_id).toBeTruthy()
    expect(usePPTStore.getState().getActiveSlide()?.elements[0].x).toBe(40)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(1)

    const serverPres = makePresentation([makeSlide([makeShape('s1', 40, 25)])], 2)
    ws.emit('presentation_updated', {
      presentation: serverPres,
      active_slide_id: slide.id,
      last_mutation_id: sent.mutation_id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().presentation).toStrictEqual(serverPres)
    expect(usePPTStore.getState().mutationStatus).toBe('committed')
  })

  it('single-flight: only sends the head until acked, then stamps the real server revision', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 3)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 3,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    usePPTStore.getState().updateElementDirect('s1', { x: 80 })

    let messages = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(messages).toHaveLength(1)
    expect(messages[0].expected_revision).toBe(3)
    expect(usePPTStore.getState().getActiveSlide()?.elements[0].x).toBe(80)
    expect(usePPTStore.getState().inFlightMutationId).toBe(messages[0].mutation_id)

    const serverPres = makePresentation([makeSlide([makeShape('s1', 40, 0)])], 4)
    ws.emit('presentation_updated', {
      presentation: serverPres,
      active_slide_id: slide.id,
      last_mutation_id: messages[0].mutation_id,
      version: 4
    })

    messages = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(messages).toHaveLength(2)
    expect(messages[1].expected_revision).toBe(4)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(1)
    expect(usePPTStore.getState().getActiveSlide()?.elements[0].x).toBe(80)
  })

  it('queues mutations in the outbox when the socket is closed and flushes on reconnect', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([slide]),
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_A'
    })
    ws.readyState = FakeWebSocket.CLOSED

    usePPTStore.getState().updateElementDirect('s1', { x: 12 })

    expect(usePPTStore.getState().outbox).toHaveLength(1)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(1)
    expect(usePPTStore.getState().mutationStatus).toBe('offline')
    expect(ws.sentMessages()).toHaveLength(0)

    ws.readyState = FakeWebSocket.OPEN
    usePPTStore.getState().flushOutbox()

    expect(ws.sentMessages()).toHaveLength(1)
    expect(ws.sentMessages()[0].type).toBe('direct_update_element')
    expect(usePPTStore.getState().outbox).toHaveLength(0)
  })

  it('rolls back to the confirmed presentation when a mutation is rejected', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide])
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 99 })
    const sent = ws.sentMessages().find((m) => m.type === 'direct_update_element')!

    ws.emit('mutation_rejected', { mutation_id: sent.mutation_id, error: 'boom' })

    expect(usePPTStore.getState().presentation).toStrictEqual(pres)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('rolled_back')
  })

  it('stale rejection resyncs to the authoritative snapshot and never sends the queued tail', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
    const pres = makePresentation([slide], 10)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 10,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    usePPTStore.getState().updateElementDirect('s2', { x: 260 })
    usePPTStore.getState().enterGroup('g1')

    const sent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(sent).toHaveLength(1)

    const authoritative = makePresentation(
      [makeSlide([makeShape('s1', 999, 0), makeShape('s2', 260, 0)])],
      11
    )
    ws.emit('mutation_rejected', {
      mutation_id: sent[0].mutation_id,
      error: 'stale_mutation',
      version: 11,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    // The queued tail is discarded and never dispatched against the new revision.
    expect(ws.sentMessages().filter((m) => m.type === 'direct_update_element')).toHaveLength(1)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().inFlightMutationId).toBeNull()
    expect(usePPTStore.getState().presentation).toStrictEqual(authoritative)
    expect(usePPTStore.getState().confirmedPresentation).toStrictEqual(authoritative)
    expect(usePPTStore.getState().confirmedRevision).toBe(11)
    expect(usePPTStore.getState().selectionScope).toEqual([])
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('replays an in-flight mutation with its original CAS stamp after reconnect', () => {
    vi.useFakeTimers()
    try {
      const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
      const pres = makePresentation([slide], 10)
      usePPTStore.getState().setPresentation(pres)
      const ws = connect()
      ws.emit('presentation_loaded', {
        presentation: pres,
        active_slide_id: slide.id,
        version: 10,
        document_epoch: 'epoch_A'
      })

      usePPTStore.getState().updateElementDirect('s1', { x: 40 })
      usePPTStore.getState().updateElementDirect('s2', { x: 260 })

      const firstSent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
      expect(firstSent).toHaveLength(1)
      expect(firstSent[0].expected_revision).toBe(10)

      // The ACK is lost: the socket drops while A is still in-flight.
      ws.close()

      // Reconnect and reload the same document at a newer revision.
      const ws2 = connect()
      const pres11 = makePresentation(
        [makeSlide([makeShape('s1', 900, 0), makeShape('s2', 900, 0)])],
        11
      )
      ws2.emit('presentation_loaded', {
        presentation: pres11,
        active_slide_id: slide.id,
        version: 11,
        document_epoch: 'epoch_A'
      })

      const replayed = ws2.sentMessages().filter((m) => m.type === 'direct_update_element')
      expect(replayed).toHaveLength(1)
      expect(replayed[0].mutation_id).toBe(firstSent[0].mutation_id)
      // Retry must reuse the ORIGINAL stamp (10), not the freshly loaded revision.
      expect(replayed[0].expected_revision).toBe(10)
      expect(replayed[0].document_epoch).toBe('epoch_A')
      // The queued tail stays behind the unacknowledged head.
      expect(ws2.sentMessages().filter((m) => m.type === 'direct_update_element')).toHaveLength(1)

      // Server rejects A as stale: the tail is dropped, never dispatched.
      const authoritative = makePresentation(
        [makeSlide([makeShape('s1', 999, 0), makeShape('s2', 999, 0)])],
        11
      )
      ws2.emit('mutation_rejected', {
        mutation_id: firstSent[0].mutation_id,
        error: 'stale_mutation',
        version: 11,
        document_epoch: 'epoch_A',
        presentation: authoritative,
        active_slide_id: slide.id
      })

      expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
      expect(usePPTStore.getState().outbox).toHaveLength(0)
      expect(usePPTStore.getState().presentation).toStrictEqual(authoritative)
      expect(usePPTStore.getState().mutationStatus).toBe('resynced')
      expect(ws2.sentMessages().filter((m) => m.type === 'direct_update_element')).toHaveLength(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('sends one atomic batch when deleting a multi-selection', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([slide]),
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().setSelectedElementIds(['s1', 's2'])
    usePPTStore.getState().deleteSelectedElements()

    const batch = ws.sentMessages().find((m) => m.type === 'batch_mutation')!
    expect(batch).toBeTruthy()
    expect(batch.mutations).toHaveLength(2)
    expect(usePPTStore.getState().getActiveSlide()?.elements).toHaveLength(0)
  })

  it('single-flight: a multi-op batch ack advances the revision for the next edit', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
    const pres = makePresentation([slide], 3)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 3,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().setSelectedElementIds(['s1', 's2'])
    usePPTStore.getState().deleteSelectedElements()
    usePPTStore.getState().updateElementDirect('s1', { x: 50 })

    const batch = ws.sentMessages().find((m) => m.type === 'batch_mutation')!
    expect(batch.expected_revision).toBe(3)
    expect(ws.sentMessages().filter((m) => m.type === 'direct_update_element')).toHaveLength(0)

    // The backend bumps the version once per update_element: 3 -> 5.
    const serverPres = makePresentation([makeSlide([makeShape('s1', 50, 0)])], 5)
    ws.emit('presentation_updated', {
      presentation: serverPres,
      active_slide_id: slide.id,
      last_mutation_id: batch.mutation_id,
      version: 5
    })

    const next = ws.sentMessages().find((m) => m.type === 'direct_update_element')!
    expect(next.expected_revision).toBe(5)
  })

  it('routes undo/redo through the single-flight queue with CAS', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 7)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 7,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().triggerUndo()
    const undo = ws.sentMessages().find((m) => m.type === 'undo')!
    expect(undo.mutation_id).toBeTruthy()
    expect(undo.expected_revision).toBe(7)
    expect(undo.document_epoch).toBe('epoch_A')

    usePPTStore.getState().triggerRedo()
    expect(ws.sentMessages().filter((m) => m.type === 'redo')).toHaveLength(0)

    ws.emit('presentation_updated', {
      presentation: pres,
      active_slide_id: slide.id,
      last_mutation_id: undo.mutation_id,
      version: 8
    })

    const redo = ws.sentMessages().find((m) => m.type === 'redo')!
    expect(redo.expected_revision).toBe(8)
  })

  it('never opens inline editing from a last_target_id server echo', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeText('t1')])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    usePPTStore.getState().setSelectedElementId('s1')

    const serverPres = makePresentation([makeSlide([makeShape('s1', 10, 0), makeText('t1')])], 2)
    ws.emit('presentation_updated', {
      presentation: serverPres,
      active_slide_id: slide.id,
      last_target_id: 't1'
    })

    expect(usePPTStore.getState().editingElementId).toBeNull()
    expect(usePPTStore.getState().selectedElementIds).toEqual(['s1'])
  })

  it('keeps single-click selection of an already selected element intact for multi-drag', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0), makeShape('s3', 400, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    usePPTStore.getState().setSelectedElementIds(['s1', 's2', 's3'])

    usePPTStore.getState().setSelectedElementId('s2')

    expect(usePPTStore.getState().selectedElementIds).toEqual(['s1', 's2', 's3'])
    expect(usePPTStore.getState().selectedElementId).toBe('s2')
  })

  it('keeps nested selections on a server update and drops deleted ones', () => {
    const group = makeGroup('g1', 0, 0, 200, 100, [makeShape('s1', 0, 0), makeShape('s2', 120, 0)])
    const slide = makeSlide([group])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    usePPTStore.getState().setSelectedElementIds(['s2'])

    const samePres = makePresentation(
      [makeSlide([makeGroup('g1', 0, 0, 200, 100, [makeShape('s1', 0, 0), makeShape('s2', 120, 0)])])],
      2
    )
    ws.emit('presentation_updated', { presentation: samePres, active_slide_id: slide.id })
    expect(usePPTStore.getState().selectedElementIds).toEqual(['s2'])

    const removedPres = makePresentation(
      [makeSlide([makeGroup('g1', 0, 0, 100, 100, [makeShape('s1', 0, 0)])])],
      3
    )
    ws.emit('presentation_updated', { presentation: removedPres, active_slide_id: slide.id })
    expect(usePPTStore.getState().selectedElementIds).toEqual([])
  })

  it('recomputes ancestor group bounds when a nested child moves', () => {
    const group = makeGroup('g1', 100, 100, 300, 200, [
      makeShape('s1', 120, 120),
      makeShape('s2', 260, 120)
    ])
    usePPTStore.getState().setPresentation(makePresentation([makeSlide([group])]))
    connect()

    usePPTStore.getState().updateElementDirect('s1', { x: 150, y: 140 })

    const stored = usePPTStore.getState().getActiveSlide()?.elements[0]
    expect(stored?.type).toBe('group')
    if (stored?.type !== 'group') return
    expect(stored.children[0].x).toBe(150)
    expect(stored.children[0].y).toBe(140)
    expect(stored.x).toBe(150)
    expect(stored.y).toBe(120)
    expect(stored.width).toBe(210)
    expect(stored.height).toBe(70)
  })

  it('selects the created element when its local direct-action ack arrives', () => {
    const slide = makeSlide([makeText('t0')])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([slide]),
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().addShapeQuick('roundRect', 10, 20)
    const sent = ws.sentMessages().find((m) => m.type === 'direct_action')!
    expect(sent.action).toBe('add_shape')

    const serverPres = makePresentation(
      [makeSlide([makeText('t0'), makeShape('created1', 10, 20)])],
      2
    )
    ws.emit('presentation_updated', {
      presentation: serverPres,
      active_slide_id: slide.id,
      last_mutation_id: sent.mutation_id,
      last_target_id: 'created1'
    })

    expect(usePPTStore.getState().selectedElementIds).toEqual(['created1'])
    expect(usePPTStore.getState().selectedElementId).toBe('created1')
  })

  it('stamps the live document epoch and revision onto outgoing mutations', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()

    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 10 })

    const sent = ws.sentMessages().find((m) => m.type === 'direct_update_element')!
    expect(sent.document_epoch).toBe('epoch_A')
    expect(sent.expected_revision).toBe(5)
    expect(usePPTStore.getState().documentEpoch).toBe('epoch_A')
    expect(usePPTStore.getState().confirmedRevision).toBe(5)
  })

  it('drops outbox mutations bound to a previous document epoch after reload', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const presA = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(presA)
    const ws = connect()

    ws.emit('presentation_loaded', {
      presentation: presA,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    ws.readyState = FakeWebSocket.CLOSED
    usePPTStore.getState().updateElementDirect('s1', { x: 10 })
    expect(usePPTStore.getState().outbox).toHaveLength(1)

    // Server restored a checkpoint while we were offline: new document epoch.
    ws.readyState = FakeWebSocket.OPEN
    const presB = makePresentation([makeSlide([makeShape('s1', 0, 0)])], 1)
    ws.emit('presentation_loaded', {
      presentation: presB,
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_B'
    })

    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(ws.sentMessages().filter((m) => m.type === 'direct_update_element')).toHaveLength(0)
    expect(usePPTStore.getState().documentEpoch).toBe('epoch_B')
  })

  it('replays same-epoch outbox mutations after reload', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()

    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    ws.readyState = FakeWebSocket.CLOSED
    usePPTStore.getState().updateElementDirect('s1', { x: 10 })
    expect(usePPTStore.getState().outbox).toHaveLength(1)

    ws.readyState = FakeWebSocket.OPEN
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(1)
    expect(ws.sentMessages().filter((m) => m.type === 'direct_update_element')).toHaveLength(1)
  })

  it('generates session-unique mutation ids via crypto.randomUUID', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    connect()

    const randomUUID = vi.fn()
      .mockReturnValueOnce('uuid-1')
      .mockReturnValueOnce('uuid-2')
    vi.stubGlobal('crypto', { randomUUID })
    try {
      usePPTStore.getState().updateElementDirect('s1', { x: 1 })
      usePPTStore.getState().updateElementDirect('s1', { x: 2 })
      const ids = usePPTStore.getState().pendingMutations.map((m) => m.mutationId)
      expect(randomUUID).toHaveBeenCalledTimes(2)
      expect(ids).toEqual(['mut_uuid-1', 'mut_uuid-2'])
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('falls back to distinct monotonic ids when crypto.randomUUID is unavailable', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    connect()

    vi.stubGlobal('crypto', {})
    try {
      usePPTStore.getState().updateElementDirect('s1', { x: 1 })
      usePPTStore.getState().updateElementDirect('s1', { x: 2 })
      const ids = usePPTStore.getState().pendingMutations.map((m) => m.mutationId)
      expect(ids).toHaveLength(2)
      expect(ids[0]).toMatch(/^mut_/)
      expect(ids[0]).not.toBe(ids[1])
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('adoptCanonicalSnapshot installs epoch/version and drops the old-epoch queue', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const presA = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(presA)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: presA,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    // A mutation is authored while offline against epoch_A.
    ws.readyState = FakeWebSocket.CLOSED
    usePPTStore.getState().updateElementDirect('s1', { x: 10 })
    expect(usePPTStore.getState().outbox).toHaveLength(1)
    ws.readyState = FakeWebSocket.OPEN

    const newSlide = makeSlide([makeShape('s2', 0, 0)])
    const presB = makePresentation([newSlide], 1)
    usePPTStore.getState().adoptCanonicalSnapshot({
      session_id: 'sess',
      presentation: presB,
      document_epoch: 'epoch_B',
      version: 1,
      active_slide_id: newSlide.id,
      can_undo: false,
      can_redo: false
    })

    expect(usePPTStore.getState().documentEpoch).toBe('epoch_B')
    expect(usePPTStore.getState().confirmedRevision).toBe(1)
    expect(usePPTStore.getState().confirmedPresentation).toStrictEqual(presB)
    expect(usePPTStore.getState().presentation).toStrictEqual(presB)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
  })

  it('chat carries UIContext and the confirmed base revision', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 9)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 9,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().setSelectedElementId('s1')
    await usePPTStore.getState().sendChatMessage('把这个改红')

    const chat = ws.sentMessages().find((m) => m.type === 'chat')!
    expect(chat).toBeTruthy()
    expect(chat.base_revision).toBe(9)
    expect(chat.document_epoch).toBe('epoch_A')
    expect(chat.ui_context.selected_element_ids).toEqual(['s1'])
    expect(chat.ui_context.primary_selected_element_id).toBe('s1')
    expect(chat.ui_context.active_slide_id).toBe(slide.id)
    expect(chat.ui_context.ui_context_revision).toBeGreaterThan(0)
    expect(typeof chat.ui_context.client_id).toBe('string')
  })

  it('isolates a remote client active-slide change from the local view and chat targeting', async () => {
    const s2 = makeSlide([makeShape('b1', 0, 0)], 'slide_2')
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const pres = makePresentation([s2, s7], 5)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })
    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')

    // Client A switched slides: the session-global broadcast must be ignored.
    ws.emit('active_slide_changed', { active_slide_id: 'slide_2' })
    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')

    // Client A mutated the document; the server template carries their active
    // slide, but client B must keep viewing slide_7.
    ws.emit('presentation_updated', {
      presentation: makePresentation([s2, s7], 6),
      active_slide_id: 'slide_2',
      version: 6
    })
    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')

    // Client B edits slide_7; the shared document still carries A's active
    // slide_2. Even on B's OWN ack the canonical active_slide_id must not move
    // B's view — navigation is client-local.
    usePPTStore.getState().updateElementDirect('b2', { x: 10 })
    const bAck = usePPTStore.getState().pendingMutations[0].mutationId
    ws.emit('presentation_updated', {
      presentation: makePresentation([s2, s7], 7),
      active_slide_id: 'slide_2',
      version: 7,
      last_mutation_id: bAck
    })
    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')

    await usePPTStore.getState().sendChatMessage('把这个改红')
    const chat = ws.sentMessages().find((m) => m.type === 'chat')!
    expect(chat.ui_context.active_slide_id).toBe('slide_7')
  })

  it('rebase replay preserves pending edits when the remote changed a different field', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 0, 0)])
    const pres = makePresentation([slide], 10)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 10,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    usePPTStore.getState().updateElementDirect('s2', { y: 50 })

    const first = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(first).toHaveLength(1)
    const headId = first[0].mutation_id

    // The remote edited s2.x (a different field than our pending s2.y), so both
    // pending operations survive the rebase.
    const authoritative = makePresentation(
      [makeSlide([makeShape('s1', 0, 0), { ...makeShape('s2', 999, 0), y: 0 }])],
      11
    )
    ws.emit('mutation_rejected', {
      mutation_id: headId,
      error: 'stale_mutation',
      version: 11,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    const replayed = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(replayed).toHaveLength(2)
    expect(replayed[1].mutation_id).toBe(headId)
    expect(replayed[1].expected_revision).toBe(11)
    expect(replayed[1].document_epoch).toBe('epoch_A')
    expect(usePPTStore.getState().confirmedRevision).toBe(11)
    // Optimistic view keeps our edits on top of the authoritative base.
    const active = usePPTStore.getState().getActiveSlide()
    const elements = active ? active.elements : []
    expect((elements.find((e) => e.id === 's1') as any).x).toBe(40)
    expect((elements.find((e) => e.id === 's2') as any).x).toBe(999)
    expect((elements.find((e) => e.id === 's2') as any).y).toBe(50)
  })

  it('rebase drops a pending edit when the same field changed remotely', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 10)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 10,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    const headId = ws.sentMessages().find((m) => m.type === 'direct_update_element')!.mutation_id

    const authoritative = makePresentation([makeSlide([makeShape('s1', 700, 0)])], 11)
    ws.emit('mutation_rejected', {
      mutation_id: headId,
      error: 'stale_mutation',
      version: 11,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
    const conflicted = usePPTStore.getState().getActiveSlide()
    expect((conflicted ? conflicted.elements[0] : null) as any as { x: number }).toMatchObject({ x: 700 })
    expect(usePPTStore.getState().messages.some((m) => m.content.includes('字段冲突'))).toBe(true)
  })

  it('rebases an ordered queue with serial CAS attempts (M1@10 -> ACK11 -> M2@11)', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
    const pres = makePresentation([slide], 10)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 10,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    usePPTStore.getState().updateElementDirect('s2', { x: 260 })

    const firstSent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(firstSent).toHaveLength(1)
    const m1 = firstSent[0]
    expect(m1.expected_revision).toBe(10)

    // A stale rejection with an unchanged authoritative deck: both pending
    // operations survive, but only the head gets a fresh CAS attempt.
    const authoritative = makePresentation(
      [makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])],
      10
    )
    ws.emit('mutation_rejected', {
      mutation_id: m1.mutation_id,
      error: 'stale_mutation',
      version: 10,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    let sent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(sent).toHaveLength(2)
    expect(sent[1].mutation_id).toBe(m1.mutation_id)
    expect(sent[1].expected_revision).toBe(10)
    // The tail must NOT have been sent against the stale revision.
    expect(sent.filter((m) => m.mutation_id !== m1.mutation_id)).toHaveLength(0)

    // M1 ACK raises the server revision; only now does the tail establish rev 11.
    ws.emit('presentation_updated', {
      presentation: makePresentation(
        [makeSlide([makeShape('s1', 40, 0), makeShape('s2', 200, 0)])],
        11
      ),
      active_slide_id: slide.id,
      last_mutation_id: m1.mutation_id,
      version: 11
    })

    sent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(sent).toHaveLength(3)
    const m2 = sent[2]
    expect(m2.mutation_id).not.toBe(m1.mutation_id)
    expect(m2.expected_revision).toBe(11)
    expect(m2.expected_revision).not.toBe(10)
  })

  it('rebase keeps a same-client sequential queue alive (x=100 then x=120)', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 10)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 10,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 100 })
    usePPTStore.getState().updateElementDirect('s1', { x: 120 })

    const firstSent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(firstSent).toHaveLength(1)
    const m1 = firstSent[0]

    const authoritative = makePresentation([makeSlide([makeShape('s1', 0, 0)])], 10)
    ws.emit('mutation_rejected', {
      mutation_id: m1.mutation_id,
      error: 'stale_mutation',
      version: 10,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    // Neither pending edit is dropped: the second is not a foreign conflict.
    expect(usePPTStore.getState().pendingMutations).toHaveLength(2)

    // M1 commits at rev 11, then the tail must be dispatched at rev 11 (not 10).
    ws.emit('presentation_updated', {
      presentation: makePresentation([makeSlide([makeShape('s1', 100, 0)])], 11),
      active_slide_id: slide.id,
      last_mutation_id: m1.mutation_id,
      version: 11
    })

    const sent = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    const m2 = sent[sent.length - 1]
    expect(m2.mutation_id).not.toBe(m1.mutation_id)
    expect(m2.expected_revision).toBe(11)
    expect((usePPTStore.getState().getActiveSlide()?.elements[0] as any).x).toBe(120)
  })

  it('structural rebase drops an ungroup whose group children changed remotely', () => {
    const group = makeGroup('g1', 0, 0, 300, 200, [makeShape('s1', 0, 0), makeShape('s2', 150, 0)])
    const slide = makeSlide([group])
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().setSelectedElementId('g1')
    usePPTStore.getState().ungroupSelectedElement()
    const sent = ws.sentMessages().find((m) => m.action === 'ungroup_elements')!
    expect(sent).toBeTruthy()

    // Remote regrouped the same group: children no longer match the fingerprint.
    const authoritative = makePresentation(
      [makeSlide([makeGroup('g1', 0, 0, 200, 100, [makeShape('s1', 0, 0)])])],
      6
    )
    ws.emit('mutation_rejected', {
      mutation_id: sent.mutation_id,
      error: 'stale_mutation',
      version: 6,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().presentation).toStrictEqual(authoritative)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('structural rebase drops a delete whose target was removed remotely', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().setSelectedElementId('s1')
    usePPTStore.getState().deleteSelectedElement()
    const sent = ws.sentMessages().find((m) => m.action === 'delete_element')!
    expect(sent).toBeTruthy()

    // The target no longer exists on the server.
    const authoritative = makePresentation([makeSlide([makeShape('s2', 200, 0)])], 6)
    ws.emit('mutation_rejected', {
      mutation_id: sent.mutation_id,
      error: 'stale_mutation',
      version: 6,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().presentation).toStrictEqual(authoritative)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('sequencing barrier resolves immediately when already synced', async () => {
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([makeSlide([makeShape('s1', 0, 0)])], 1),
      active_slide_id: 's1',
      version: 1,
      document_epoch: 'epoch_A'
    })

    await expect(
      usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 200 })
    ).resolves.toBeUndefined()
  })

  it('sequencing barrier waits for the in-flight mutation to be acked', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 3)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 3,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    const sent = ws.sentMessages().find((m) => m.type === 'direct_update_element')!
    const barrier = usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 1000 })

    ws.emit('presentation_updated', {
      presentation: makePresentation([makeSlide([makeShape('s1', 40, 0)])], 4),
      active_slide_id: slide.id,
      last_mutation_id: sent.mutation_id,
      version: 4
    })

    await expect(barrier).resolves.toBeUndefined()
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
  })

  it('sequencing barrier rejects immediately when offline with unsynced edits', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    ws.readyState = FakeWebSocket.CLOSED
    usePPTStore.getState().updateElementDirect('s1', { x: 12 })

    await expect(
      usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 1000 })
    ).rejects.toMatchObject({ code: 'LOCAL_CHANGES_NOT_SYNCED' })
  })

  it('sequencing barrier hard-fails when offline even with NO pending edits', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide], 3))
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([slide], 3),
      active_slide_id: slide.id,
      version: 3,
      document_epoch: 'epoch_A'
    })
    // Clean local state, but the transport is down: a gated action must not
    // believe it is safely synced.
    ws.readyState = FakeWebSocket.CLOSED

    await expect(
      usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 1000 })
    ).rejects.toMatchObject({ code: 'LOCAL_CHANGES_NOT_SYNCED' })
  })

  it('sequencing barrier times out when the ack never arrives', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 3)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 3,
      document_epoch: 'epoch_A'
    })
    usePPTStore.getState().updateElementDirect('s1', { x: 40 })

    await expect(
      usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 40 })
    ).rejects.toMatchObject({ code: 'LOCAL_CHANGES_NOT_SYNCED' })
  })

  it('sendChatMessage aborts and notifies when local edits are unsynced', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
    ws.readyState = FakeWebSocket.CLOSED
    usePPTStore.getState().updateElementDirect('s1', { x: 12 })

    await usePPTStore.getState().sendChatMessage('把这个改红')

    expect(ws.sentMessages().some((m) => m.type === 'chat')).toBe(false)
    expect(usePPTStore.getState().messages.some((m) => m.content.includes('尚未同步完成'))).toBe(true)
  })

  it('deleteSlide resolves a slide number to its stable id before sending', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)], 'slide_1')
    const pres = makePresentation([slide], 4)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 4,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().deleteSlide(1)

    const sent = ws.sentMessages().find((m) => m.action === 'delete_slide')!
    expect(sent).toBeTruthy()
    expect(sent.payload.slide_id_or_num).toBe('slide_1')
  })

  it('rebase drops a clear_slide_elements when the slide content changed remotely', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)], 'slide_1')
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().clearSlideElements('slide_1', false)
    const sent = ws.sentMessages().find((m) => m.action === 'clear_slide_elements')!
    expect(sent).toBeTruthy()

    // A remote element was added after we captured the fingerprint.
    const authoritative = makePresentation(
      [makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0), makeShape('s3', 40, 40)], 'slide_1')],
      6
    )
    ws.emit('mutation_rejected', {
      mutation_id: sent.mutation_id,
      error: 'stale_mutation',
      version: 6,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().presentation).toStrictEqual(authoritative)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('rebase drops a never-policy delete_slide even when content is unchanged', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)], 'slide_1')
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().deleteSlide('slide_1')
    const sent = ws.sentMessages().find((m) => m.action === 'delete_slide')!
    expect(sent).toBeTruthy()

    // Identical authoritative content: a destructive op still must not replay.
    const authoritative = makePresentation([makeSlide([makeShape('s1', 0, 0)], 'slide_1')], 6)
    ws.emit('mutation_rejected', {
      mutation_id: sent.mutation_id,
      error: 'stale_mutation',
      version: 6,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('rebase drops a never-policy optimize_layout even with no preconditions', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)], 'slide_1')
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().optimizeLayoutDirect()
    const sent = ws.sentMessages().find((m) => m.action === 'optimize_layout')!
    expect(sent).toBeTruthy()

    const authoritative = makePresentation(
      [makeSlide([makeShape('s1', 30, 30)], 'slide_1')],
      6
    )
    ws.emit('mutation_rejected', {
      mutation_id: sent.mutation_id,
      error: 'stale_mutation',
      version: 6,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('rebase drops an align whose element geometry changed remotely', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)], 'slide_1')
    const pres = makePresentation([slide], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().setSelectedElementIds(['s1', 's2'])
    usePPTStore.getState().alignSelectedElements('top')
    const sent = ws.sentMessages().find((m) => m.action === 'align_elements')!
    expect(sent).toBeTruthy()

    // Remote moved s2 vertically: the captured x/y fingerprint no longer matches.
    const authoritative = makePresentation(
      [makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 90)], 'slide_1')],
      6
    )
    ws.emit('mutation_rejected', {
      mutation_id: sent.mutation_id,
      error: 'stale_mutation',
      version: 6,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('a foreign field change conflicts with a pending same-field edit', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)], 'slide_1')
    const pres = makePresentation([slide], 10)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 10,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    const headId = ws.sentMessages().find((m) => m.type === 'direct_update_element')!.mutation_id

    // The authoritative deck moved `s1.x` to 700 by a foreign write while our
    // x=40 edit was in flight. There is no local-effect ledger to excuse that:
    // it must fail safe as a conflict and resync.
    const authoritative = makePresentation([makeSlide([makeShape('s1', 700, 0)], 'slide_1')], 11)
    ws.emit('mutation_rejected', {
      mutation_id: headId,
      error: 'stale_mutation',
      version: 11,
      document_epoch: 'epoch_A',
      presentation: authoritative,
      active_slide_id: slide.id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('resynced')
  })

  it('direct mutations stay queued until a canonical server revision exists', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)], 'slide_1')
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()

    usePPTStore.getState().updateElementDirect('s1', { x: 12 })

    expect(ws.sentMessages()).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(1)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(1)

    ws.emit('presentation_loaded', {
      presentation: makePresentation([slide], 1),
      active_slide_id: slide.id,
      version: 1,
      document_epoch: 'epoch_A'
    })

    const sent = ws.sentMessages().find((m) => m.type === 'direct_update_element')!
    expect(sent).toBeTruthy()
    expect(sent.expected_revision).toBe(1)
    expect(sent.document_epoch).toBe('epoch_A')
  })
})
