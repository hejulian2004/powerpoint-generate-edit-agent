import { beforeEach, describe, expect, it } from 'vitest'
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
    pendingMutations: [],
    outbox: [],
    documentEpoch: null,
    confirmedRevision: 0,
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

  it('keeps optimistic state while later mutations are still pending', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide])
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()

    usePPTStore.getState().updateElementDirect('s1', { x: 40 })
    usePPTStore.getState().updateElementDirect('s1', { x: 80 })
    const messages = ws.sentMessages().filter((m) => m.type === 'direct_update_element')
    expect(messages).toHaveLength(2)

    const serverPres = makePresentation([makeSlide([makeShape('s1', 40, 0)])], 2)
    ws.emit('presentation_updated', {
      presentation: serverPres,
      active_slide_id: slide.id,
      last_mutation_id: messages[0].mutation_id
    })

    expect(usePPTStore.getState().pendingMutations).toHaveLength(1)
    expect(usePPTStore.getState().presentation).not.toBe(serverPres)
    expect(usePPTStore.getState().getActiveSlide()?.elements[0].x).toBe(80)
  })

  it('queues mutations in the outbox when the socket is closed and flushes on reconnect', () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()
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

    usePPTStore.getState().updateElementDirect('s1', { x: 99 })
    const sent = ws.sentMessages().find((m) => m.type === 'direct_update_element')!

    ws.emit('mutation_rejected', { mutation_id: sent.mutation_id, error: 'boom' })

    expect(usePPTStore.getState().presentation).toBe(pres)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().mutationStatus).toBe('rolled_back')
  })

  it('sends one atomic batch when deleting a multi-selection', () => {
    const slide = makeSlide([makeShape('s1', 0, 0), makeShape('s2', 200, 0)])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const ws = connect()

    usePPTStore.getState().setSelectedElementIds(['s1', 's2'])
    usePPTStore.getState().deleteSelectedElements()

    const batch = ws.sentMessages().find((m) => m.type === 'batch_mutation')!
    expect(batch).toBeTruthy()
    expect(batch.mutations).toHaveLength(2)
    expect(usePPTStore.getState().getActiveSlide()?.elements).toHaveLength(0)
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
})
