import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePPTStore } from './usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide } from '../test/factories'

const resetStore = () => {
  usePPTStore.setState({
    sessionId: 'sess_test',
    presentation: null,
    confirmedPresentation: null,
    activeSlideId: null,
    messages: [],
    isAgentThinking: false,
    thinkingStatus: '',
    ws: null,
    wsConnected: false,
    pendingMutations: [],
    outbox: [],
    inFlightMutationId: null,
    inFlightMessage: null,
    documentEpoch: null,
    confirmedRevision: 0,
    hasServerRevision: false,
    clientId: 'client_test',
    uiContextRevision: 0,
    mutationStatus: 'idle'
  })
}

const connect = () => {
  usePPTStore.getState().initWebSocket()
  const ws = FakeWebSocket.latest()
  ws.onopen?.({})
  return ws
}

const makeFile = (name: string, type: string) =>
  new File([new Uint8Array([1, 2, 3])], name, { type })

describe('sendChatWithAttachments', () => {
  beforeEach(() => {
    installFakeWebSocket()
    resetStore()
  })

  it('fails closed without a live transport and never posts', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await usePPTStore.getState().sendChatWithAttachments('放进去', [makeFile('a.png', 'image/png')])

    expect(fetchMock).not.toHaveBeenCalled()
    const state = usePPTStore.getState()
    expect(state.isAgentThinking).toBe(false)
    expect(state.messages.at(-1)?.content).toContain('已取消本次发送')
  })

  it('posts attachments to /api/chat/drive and adopts the returned snapshot', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 9)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 9,
      document_epoch: 'epoch_A'
    })

    const snapshot = {
      success: true,
      action: 'image_insert',
      session_id: 'sess_test',
      presentation: pres,
      document_epoch: 'epoch_B',
      version: 10,
      active_slide_id: slide.id,
      can_undo: true,
      can_redo: false
    }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => snapshot })
    vi.stubGlobal('fetch', fetchMock)

    await usePPTStore.getState().sendChatWithAttachments('把这张图放到当前页', [
      makeFile('figure.png', 'image/png')
    ])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/chat/drive')
    expect(init.method).toBe('POST')
    const body = init.body as FormData
    expect(body.get('message')).toBe('把这张图放到当前页')
    expect(body.get('session_id')).toBe('sess_test')
    expect(body.get('expected_epoch')).toBe('epoch_A')
    expect(body.get('expected_revision')).toBe('9')
    expect(body.getAll('files')).toHaveLength(1)

    const state = usePPTStore.getState()
    expect(state.documentEpoch).toBe('epoch_B')
    expect(state.isAgentThinking).toBe(false)
    expect(state.messages.at(-1)?.content).toContain('图片')
  })

  it('falls back to a normal chat turn without duplicating the user message', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 9)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 9,
      document_epoch: 'epoch_A'
    })

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, action: 'chat', session_id: 'sess_test' })
    })
    vi.stubGlobal('fetch', fetchMock)

    await usePPTStore.getState().sendChatWithAttachments('这是什么文件', [
      makeFile('a.png', 'image/png')
    ])

    const userMessages = usePPTStore.getState().messages.filter((m) => m.role === 'user')
    expect(userMessages).toHaveLength(1)
    expect(ws.sentMessages().some((m) => m.type === 'chat')).toBe(true)
  })

  it('shows the server attachment-chat answer without a second WS turn', async () => {
    const slide = makeSlide([makeShape('s1', 0, 0)])
    const pres = makePresentation([slide], 9)
    const ws = connect()
    ws.emit('presentation_loaded', {
      presentation: pres,
      active_slide_id: slide.id,
      version: 9,
      document_epoch: 'epoch_A'
    })

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        action: 'chat',
        session_id: 'sess_test',
        message: '这篇论文讲的是……'
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    await usePPTStore.getState().sendChatWithAttachments('这篇论文讲什么', [
      makeFile('paper.pdf', 'application/pdf')
    ])

    const messages = usePPTStore.getState().messages
    expect(messages.at(-1)?.role).toBe('assistant')
    expect(messages.at(-1)?.content).toBe('这篇论文讲的是……')
    // The attachment content already reached the LLM server-side; no second,
    // attachment-less chat turn is sent.
    expect(ws.sentMessages().some((m) => m.type === 'chat')).toBe(false)
  })
})
