import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide } from '../test/factories'

const bootstrapPayload = (sessionId: string) => {
  const presentation = makePresentation([makeSlide([makeShape('s1', 0, 0)])])
  return {
    session_id: sessionId,
    is_new: false,
    snapshot: {
      session_id: sessionId,
      presentation,
      document_epoch: 'epoch_1',
      version: presentation.version,
      active_slide_id: presentation.active_slide_id,
      can_undo: false,
      can_redo: false
    }
  }
}

describe('workspace bootstrap', () => {
  beforeEach(() => {
    installFakeWebSocket()
    localStorage.clear()
    usePPTStore.setState({
      sessionId: '',
      isBootstrapping: false,
      ws: null,
      wsConnected: false,
      presentation: null,
      confirmedPresentation: null,
      activeSlideId: null,
      pendingMutations: [],
      outbox: [],
      inFlightMutationId: null,
      inFlightMessage: null
    })
  })

  it('adopts the backend session and opens exactly one socket', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => bootstrapPayload('sess_backend')
    })
    vi.stubGlobal('fetch', fetchMock)

    await usePPTStore.getState().bootstrapWorkspace()

    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/bootstrap')
    expect(usePPTStore.getState().sessionId).toBe('sess_backend')
    expect(usePPTStore.getState().presentation?.title).toBe('Test Deck')
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.latest().url).toContain('session_id=sess_backend')
    expect(localStorage.getItem('ppt_session_hint')).toBe('sess_backend')
  })

  it('sends the cached session hint on reload', async () => {
    localStorage.setItem('ppt_session_hint', 'sess_prev')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => bootstrapPayload('sess_prev')
    })
    vi.stubGlobal('fetch', fetchMock)

    await usePPTStore.getState().bootstrapWorkspace()

    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/bootstrap?hint=sess_prev')
  })

  it('stays disconnected and surfaces an error when bootstrap is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    usePPTStore.setState({ sessionId: 'sess_local' })

    await usePPTStore.getState().bootstrapWorkspace()

    expect(FakeWebSocket.instances).toHaveLength(0)
    expect(usePPTStore.getState().bootstrapError).toBeTruthy()
  })

  it('does not adopt a session when the backend returns none', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: null })
    }))
    await usePPTStore.getState().bootstrapWorkspace()
    expect(FakeWebSocket.instances).toHaveLength(0)
    expect(usePPTStore.getState().bootstrapError).toBeTruthy()
  })
})
