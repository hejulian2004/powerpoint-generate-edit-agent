import { beforeEach, describe, expect, it } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide } from '../test/factories'

const resetStore = () => {
  usePPTStore.setState({
    sessionId: 'sess_cmd',
    presentation: null,
    confirmedPresentation: null,
    activeSlideId: null,
    messages: [{ id: 'm1', role: 'user', content: 'hi', timestamp: 1 }],
    interactionMode: 'auto',
    pendingPlan: null,
    pendingConfirmation: null,
    contextUsage: null,
    generationStage: null,
    isAgentThinking: false,
    thinkingStatus: '',
    ws: null,
    wsConnected: false,
    pendingMutations: [],
    outbox: [],
    inFlightMutationId: null,
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

describe('slash-command store control plane', () => {
  beforeEach(() => {
    installFakeWebSocket()
    resetStore()
  })

  it('new conversation sends the control message and clears chat locally', () => {
    const ws = connect()
    usePPTStore.getState().resetConversation()
    expect(ws.sentMessages().some((m) => m.type === 'new_conversation')).toBe(true)
    expect(usePPTStore.getState().messages).toHaveLength(0)
  })

  it('setInteractionMode sends set_plan_mode and updates local state', () => {
    const ws = connect()
    usePPTStore.getState().setInteractionMode('plan')
    const sent = ws.sentMessages().find((m) => m.type === 'set_plan_mode')
    expect(sent?.mode).toBe('plan')
    expect(usePPTStore.getState().interactionMode).toBe('plan')
  })

  it('plan_ready opens a plan card and confirm_plan approves it', () => {
    const ws = connect()
    ws.emit('plan_ready', {
      plan_id: 'p1',
      plan: '封面 + 三页内容',
      plan_review: { approved: true },
      expected_revision: 3
    })
    const plan = usePPTStore.getState().pendingPlan
    expect(plan?.planId).toBe('p1')
    expect(plan?.plan).toContain('封面')

    usePPTStore.getState().confirmPlan()
    expect(ws.sentMessages().some((m) => m.type === 'confirm_plan' && m.plan_id === 'p1')).toBe(true)
    expect(usePPTStore.getState().pendingPlan).toBeNull()
  })

  it('cancel_plan discards the plan card', () => {
    const ws = connect()
    ws.emit('plan_ready', { plan_id: 'p2', plan: 'x', plan_review: {} })
    usePPTStore.getState().cancelPlan()
    expect(ws.sentMessages().some((m) => m.type === 'cancel_plan' && m.plan_id === 'p2')).toBe(true)
    expect(usePPTStore.getState().pendingPlan).toBeNull()
  })

  it('confirmation_required opens a confirmation card', () => {
    const ws = connect()
    ws.emit('confirmation_required', {
      call_id: 'c1',
      tool: 'delete_element',
      arguments: { element_id: 'e1' },
      resolution_confidence: 0.4
    })
    expect(usePPTStore.getState().pendingConfirmation?.callId).toBe('c1')

    usePPTStore.getState().confirmConfirmation()
    expect(ws.sentMessages().some((m) => m.type === 'confirm_tool_call' && m.call_id === 'c1')).toBe(true)
    expect(usePPTStore.getState().pendingConfirmation).toBeNull()
  })

  it('vision_review_result adds an assistant report message', () => {
    const ws = connect()
    ws.emit('vision_review_result', {
      success: true,
      targets: ['s1', 's2'],
      overall: { score: 88.5, defects_count: 2, needs_auto_correction: false, critique_summary: 'ok' }
    })
    const last = usePPTStore.getState().messages.at(-1)
    expect(last?.role).toBe('assistant')
    expect(last?.visualReview?.score).toBe(88.5)
  })

  it('conversation_reset clears messages from the server event', () => {
    const ws = connect()
    expect(usePPTStore.getState().messages.length).toBeGreaterThan(0)
    ws.emit('conversation_reset', {})
    expect(usePPTStore.getState().messages).toHaveLength(0)
  })

  it('sendChatMessage carries the current interaction mode', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 4)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 4,
      document_epoch: 'epoch_A'
    })
    usePPTStore.setState({ interactionMode: 'plan' })

    await usePPTStore.getState().sendChatMessage('做一个新页面')

    const chat = ws.sentMessages().find((m) => m.type === 'chat')
    expect(chat?.mode).toBe('plan')
  })
})
