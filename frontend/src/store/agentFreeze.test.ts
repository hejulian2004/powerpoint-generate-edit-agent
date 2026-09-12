import { beforeEach, describe, expect, it } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide } from '../test/factories'

const connect = () => {
  usePPTStore.getState().initWebSocket()
  const ws = FakeWebSocket.latest()
  ws.onopen?.({})
  return ws
}

describe('agent edit freeze', () => {
  beforeEach(() => {
    installFakeWebSocket()
    usePPTStore.setState({
      sessionId: 'sess_freeze',
      isBootstrapping: false,
      sessionTakenOver: false,
      editLockState: 'editable',
      needsResync: false,
      ws: null,
      wsConnected: false,
      hasServerRevision: true,
      confirmedRevision: 1,
      documentEpoch: 'epoch_1',
      mutationStatus: 'idle',
      pendingMutations: [],
      outbox: [],
      inFlightMutationId: null,
      inFlightMessage: null,
      isAgentThinking: false,
      messages: [],
      presentation: makePresentation([makeSlide([makeShape('s1', 0, 0)])])
    })
  })

  it('freezes locally on send, locks on broadcast, unlocks on snapshot', async () => {
    const ws = connect()
    await usePPTStore.getState().sendChatMessage('make it bold')
    expect(usePPTStore.getState().editLockState).toBe('agent_lock_pending')

    ws.emit('document_frozen', {
      session_id: 'sess_freeze',
      edit_lock: { locked: true, kind: 'agent', turn_id: 'turn_1' }
    })
    expect(usePPTStore.getState().editLockState).toBe('agent_locked')

    ws.emit('presentation_updated', {
      session_id: 'sess_freeze',
      presentation: makePresentation([makeSlide([makeShape('s1', 0, 0)])]),
      document_epoch: 'epoch_1',
      version: 2,
      edit_lock: { locked: false, kind: null, turn_id: null }
    })
    expect(usePPTStore.getState().editLockState).toBe('editable')
  })

  it('marks needsResync when frozen while local edits are queued', () => {
    const ws = connect()
    usePPTStore.setState({ pendingMutations: [{} as never] })
    ws.emit('document_frozen', {
      session_id: 'sess_freeze',
      edit_lock: { locked: true, kind: 'agent', turn_id: 'turn_2' }
    })
    expect(usePPTStore.getState().editLockState).toBe('agent_locked')
    expect(usePPTStore.getState().needsResync).toBe(true)
  })

  it('handles a backend document_frozen rejection', () => {
    const ws = connect()
    ws.emit('mutation_rejected', {
      session_id: 'sess_freeze',
      mutation_id: 'm1',
      error: 'document_frozen'
    })
    expect(usePPTStore.getState().editLockState).toBe('agent_locked')
  })
})
