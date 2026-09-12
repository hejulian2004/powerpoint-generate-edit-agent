import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'

describe('session takeover', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installFakeWebSocket()
    usePPTStore.setState({
      sessionId: 'sess_takeover',
      isBootstrapping: false,
      sessionTakenOver: false,
      ws: null,
      wsConnected: false,
      inFlightMutationId: null,
      inFlightMessage: null,
      pendingMutations: [],
      outbox: [],
      mutationStatus: 'idle',
      messages: []
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('marks the tab taken over and never auto-reconnects', () => {
    usePPTStore.getState().initWebSocket()
    const ws = FakeWebSocket.latest()
    ws.onopen?.({})

    ws.emit('session_taken_over', { session_id: 'sess_takeover' })
    expect(usePPTStore.getState().sessionTakenOver).toBe(true)

    ws.onclose?.({ code: 4001 })
    expect(usePPTStore.getState().wsConnected).toBe(false)

    vi.advanceTimersByTime(10000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('still auto-reconnects on an ordinary disconnect', () => {
    usePPTStore.getState().initWebSocket()
    const ws = FakeWebSocket.latest()
    ws.onopen?.({})

    ws.onclose?.({ code: 1006 })
    vi.advanceTimersByTime(3500)
    expect(FakeWebSocket.instances.length).toBeGreaterThan(1)
  })
})
