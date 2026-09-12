import { beforeEach, describe, expect, it, vi } from 'vitest'
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

  it('blocks direct action authoring while the lock is pending', () => {
    const ws = connect()
    usePPTStore.setState({ editLockState: 'agent_lock_pending' })
    usePPTStore.getState().executeDirectAction('delete_element', { element_id: 's1' })
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(ws.sentMessages()).toHaveLength(0)
  })

  it('blocks optimistic element edits while locked', () => {
    connect()
    const pres = makePresentation([makeSlide([makeShape('s1', 10, 10)])])
    usePPTStore.setState({
      editLockState: 'agent_locked',
      presentation: pres,
      confirmedPresentation: pres
    })
    usePPTStore.getState().updateElementDirect('s1', { x: 999 })
    expect(usePPTStore.getState().presentation).toStrictEqual(pres)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
  })

  it('retires the obsolete chain on a frozen rejection and resumes at the agent revision', () => {
    const ws = connect()
    usePPTStore.setState({
      pendingMutations: [{ mutationId: 'm1', operations: [] } as never],
      outbox: [{ message: {}, mutation: { mutationId: 'm1' } } as never],
      inFlightMutationId: 'm1',
      inFlightMessage: {}
    })
    ws.emit('mutation_rejected', {
      session_id: 'sess_freeze',
      mutation_id: 'm1',
      error: 'document_frozen'
    })
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().inFlightMutationId).toBeNull()
    expect(usePPTStore.getState().needsResync).toBe(true)

    // Terminal Agent snapshot unlocks and advances the revision to 9.
    ws.emit('presentation_updated', {
      session_id: 'sess_freeze',
      presentation: makePresentation([makeSlide([makeShape('s1', 40, 40)])]),
      document_epoch: 'epoch_1',
      version: 9,
      edit_lock: { locked: false, kind: null, turn_id: null }
    })
    expect(usePPTStore.getState().editLockState).toBe('editable')
    expect(usePPTStore.getState().needsResync).toBe(false)
    expect(usePPTStore.getState().confirmedRevision).toBe(9)

    // The next GUI mutation is stamped with the Agent's final revision.
    usePPTStore.getState().executeDirectAction('delete_element', { element_id: 's1' })
    const sent = ws.sentMessages().find((m) => m.action === 'delete_element')
    expect(sent).toBeTruthy()
    expect(sent?.expected_revision).toBe(9)
  })

  it('drops the queued chain when frozen mid-flight', () => {
    const ws = connect()
    usePPTStore.setState({
      pendingMutations: [{ mutationId: 'm2', operations: [] } as never],
      outbox: [{ message: {}, mutation: { mutationId: 'm2' } } as never],
      inFlightMutationId: 'm2'
    })
    ws.emit('document_frozen', {
      session_id: 'sess_freeze',
      edit_lock: { locked: true, kind: 'agent', turn_id: 'turn_9' }
    })
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().inFlightMutationId).toBeNull()
    expect(usePPTStore.getState().needsResync).toBe(true)
    expect(usePPTStore.getState().mutationStatus).toBe('resyncing')
  })

  it('never falls back to REST when the socket is unusable after the barrier', async () => {
    const ws = connect()
    usePPTStore.setState({ sessionTakenOver: true })
    const fetchSpy = vi.fn()
    const originalFetch = globalThis.fetch
    globalThis.fetch = fetchSpy as never
    try {
      await usePPTStore.getState().sendChatMessage('hello')
    } finally {
      globalThis.fetch = originalFetch
    }
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(ws.sentMessages().find((m) => m.type === 'chat')).toBeFalsy()
    expect(usePPTStore.getState().editLockState).toBe('editable')
    expect(usePPTStore.getState().isAgentThinking).toBe(false)
  })

  it('barrier fails fast while the Agent owns the document (no timeout wait)', async () => {
    connect()
    usePPTStore.setState({ editLockState: 'agent_locked', needsResync: true })
    await expect(
      // A 60s timeout proves this is an immediate block, not a timeout.
      usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 60000 })
    ).rejects.toMatchObject({ code: 'LOCAL_CHANGES_NOT_SYNCED' })
  })

  it('barrier fails fast when the session was taken over', async () => {
    connect()
    usePPTStore.setState({ sessionTakenOver: true })
    await expect(
      usePPTStore.getState().awaitDirectSyncBarrier({ timeoutMs: 60000 })
    ).rejects.toMatchObject({ code: 'LOCAL_CHANGES_NOT_SYNCED' })
  })

  it('clears thinking on turn_rejected without force-unlocking the edit lock', () => {
    const ws = connect()
    usePPTStore.setState({
      editLockState: 'agent_locked',
      isAgentThinking: true,
      thinkingStatus: '规划中'
    })
    ws.emit('turn_rejected', {
      session_id: 'sess_freeze',
      error: 'agent_turn_in_progress',
      message: '演示文稿正被另一个 Agent 任务编辑，请稍后重试。'
    })
    const s = usePPTStore.getState()
    expect(s.isAgentThinking).toBe(false)
    expect(s.thinkingStatus).toBe('')
    // The snapshot's edit_lock is authoritative; a rejection never unlocks.
    expect(s.editLockState).toBe('agent_locked')
    expect(s.messages.at(-1)?.content).toContain('另一个 Agent')
  })

  it('requests a resync on a stale turn rejection without unlocking', () => {
    const ws = connect()
    usePPTStore.setState({ editLockState: 'agent_locked' })
    ws.emit('turn_rejected', {
      session_id: 'sess_freeze',
      error: 'request_stale',
      message: '演示文稿已在您发送后更新，本次指令未执行，已同步到最新版本，请重试。',
      version: 5,
      document_epoch: 'epoch_1'
    })
    const s = usePPTStore.getState()
    expect(s.needsResync).toBe(true)
    expect(s.mutationStatus).toBe('resyncing')
    expect(s.editLockState).toBe('agent_locked')
  })

  it('recovers from a missing_request_stamp rejection via the canonical snapshot', async () => {
    const ws = connect()
    await usePPTStore.getState().sendChatMessage('first')
    expect(usePPTStore.getState().editLockState).toBe('agent_lock_pending')
    expect(usePPTStore.getState().isAgentThinking).toBe(true)

    ws.emit('turn_rejected', {
      session_id: 'sess_freeze',
      error: 'missing_request_stamp',
      message: '本次指令缺少文档版本信息，未执行，请同步当前版本后重试。'
    })
    const rejected = usePPTStore.getState()
    expect(rejected.isAgentThinking).toBe(false)
    expect(rejected.thinkingStatus).toBe('')
    // The frontend must NOT self-unlock: the canonical edit_lock is authoritative.
    expect(rejected.editLockState).toBe('agent_lock_pending')

    ws.emit('presentation_updated', {
      session_id: 'sess_freeze',
      presentation: makePresentation([makeSlide([makeShape('s1', 0, 0)])]),
      document_epoch: 'epoch_1',
      version: 2,
      edit_lock: { locked: false, kind: null, turn_id: null }
    })
    expect(usePPTStore.getState().editLockState).toBe('editable')
    expect(usePPTStore.getState().needsResync).toBe(false)

    // The next chat passes the barrier and actually reaches the wire.
    await usePPTStore.getState().sendChatMessage('second')
    const chats = ws.sentMessages().filter((m) => m.type === 'chat')
    expect(chats).toHaveLength(2)
    expect(chats[1]?.message).toBe('second')
  })
})
