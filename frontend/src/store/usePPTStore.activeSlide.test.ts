import { beforeEach, describe, expect, it } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide } from '../test/factories'

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
    mutationStatus: 'idle'
  })
}

const connect = () => {
  usePPTStore.getState().initWebSocket()
  const ws = FakeWebSocket.latest()
  ws.onopen?.({})
  return ws
}

describe('usePPTStore client-local active slide', () => {
  beforeEach(() => {
    installFakeWebSocket()
    resetStore()
  })

  it('follows a mutation-scoped local_view_hint on the local create-slide ack', () => {
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const pres = makePresentation([s7], 5)
    usePPTStore.getState().setPresentation(pres)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })
    ws.emit('preview_update', { slide_id: 'slide_7', svg: '<svg>7</svg>', score: 90 })
    expect(usePPTStore.getState().previewSlideId).toBe('slide_7')

    usePPTStore.getState().addNewSlide()
    const ackId = usePPTStore.getState().pendingMutations[0].mutationId
    const s8 = makeSlide([], 'slide_8')

    ws.emit('presentation_updated', {
      presentation: makePresentation([s7, s8], 6),
      active_slide_id: 'slide_8',
      version: 6,
      last_mutation_id: ackId,
      local_view_hint: { active_slide_id: 'slide_8' }
    })

    expect(usePPTStore.getState().activeSlideId).toBe('slide_8')
    // The slide_7 preview must not survive as slide_8's preview.
    expect(usePPTStore.getState().previewSvg).toBeNull()
    expect(usePPTStore.getState().previewSlideId).toBeNull()
    // The initiator asks for the new slide's preview instead.
    const requested = ws
      .sentMessages()
      .filter((m) => m.type === 'preview_request')
      .map((m) => m.slide_id)
    expect(requested).toContain('slide_8')
  })

  it('ignores a local_view_hint that is not scoped to this client ack', () => {
    const s2 = makeSlide([makeShape('b1', 0, 0)], 'slide_2')
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([s2, s7], 5),
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })
    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')

    // A remote mutation happens to carry a hint, but it is not our ack.
    ws.emit('presentation_updated', {
      presentation: makePresentation([s2, s7], 6),
      active_slide_id: 'slide_2',
      version: 6,
      last_mutation_id: 'mut_remote_other_client',
      local_view_hint: { active_slide_id: 'slide_2' }
    })

    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')
  })

  it('never adopts the shared active_slide_id on this client own ack', () => {
    const s2 = makeSlide([makeShape('b1', 0, 0)], 'slide_2')
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([s2, s7], 5),
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })

    usePPTStore.getState().updateElementDirect('b2', { x: 10 })
    const ackId = usePPTStore.getState().pendingMutations[0].mutationId
    ws.emit('presentation_updated', {
      presentation: makePresentation([s2, s7], 6),
      active_slide_id: 'slide_2',
      version: 6,
      last_mutation_id: ackId
    })

    expect(usePPTStore.getState().activeSlideId).toBe('slide_7')
  })

  it('ignores a preview_update for a slide this client is not viewing', () => {
    const s2 = makeSlide([makeShape('b1', 0, 0)], 'slide_2')
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([s2, s7], 5),
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })

    ws.emit('preview_update', { slide_id: 'slide_7', svg: '<svg>7</svg>', score: 90 })
    expect(usePPTStore.getState().previewSvg).toBe('<svg>7</svg>')
    expect(usePPTStore.getState().previewSlideId).toBe('slide_7')

    // Another client's mutation broadcasts slide_2's preview: drop it entirely.
    ws.emit('preview_update', { slide_id: 'slide_2', svg: '<svg>2</svg>', score: 10 })
    expect(usePPTStore.getState().previewSvg).toBe('<svg>7</svg>')
    expect(usePPTStore.getState().previewSlideId).toBe('slide_7')
  })

  it('labels the editor preview with its real provenance, never activeSlideId', () => {
    const s2 = makeSlide([makeShape('b1', 0, 0)], 'slide_2')
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([s2, s7], 5),
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })

    ws.emit('preview_update', { slide_id: 'slide_7', svg: '<svg>7</svg>', score: 90 })
    expect(usePPTStore.getState().getEditorState().preview?.slide_id).toBe('slide_7')

    // A foreign preview must never relabel the (still slide_7) cached SVG.
    ws.emit('preview_update', { slide_id: 'slide_2', svg: '<svg>2</svg>', score: 10 })
    expect(usePPTStore.getState().getEditorState().preview?.slide_id).toBe('slide_7')
    expect(usePPTStore.getState().getEditorState().preview?.svg).toBe('<svg>7</svg>')
  })

  it('clears a mismatched preview when navigating to another slide', () => {
    const s2 = makeSlide([makeShape('b1', 0, 0)], 'slide_2')
    const s7 = makeSlide([makeShape('b2', 0, 0)], 'slide_7')
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: makePresentation([s2, s7], 5),
      active_slide_id: 'slide_7',
      version: 5,
      document_epoch: 'epoch_A'
    })
    ws.emit('preview_update', { slide_id: 'slide_7', svg: '<svg>7</svg>', score: 90 })

    usePPTStore.getState().setActiveSlideId('slide_2')

    expect(usePPTStore.getState().previewSvg).toBeNull()
    expect(usePPTStore.getState().previewSlideId).toBeNull()
    const requested = ws
      .sentMessages()
      .filter((m) => m.type === 'preview_request')
      .map((m) => m.slide_id)
    expect(requested).toContain('slide_2')
  })
})
