import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ChatPanel } from './ChatPanel'
import { usePPTStore } from '../store/usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from '../test/wsMock'

const resetStore = () => {
  usePPTStore.setState({
    sessionId: 'sess_ui',
    presentation: null,
    confirmedPresentation: null,
    activeSlideId: null,
    selectedElementId: null,
    messages: [],
    isAgentThinking: false,
    thinkingStatus: '',
    contextUsage: null,
    generationStage: null,
    visualRemediation: null,
    interactionMode: 'auto',
    pendingPlan: null,
    pendingConfirmation: null,
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

describe('ChatPanel slash-command palette', () => {
  beforeEach(() => {
    installFakeWebSocket()
    resetStore()
    // jsdom does not implement scrollIntoView.
    if (!Element.prototype.scrollIntoView) {
      Element.prototype.scrollIntoView = vi.fn()
    }
  })

  it('opens the palette when typing "/" and executes a command', () => {
    const ws = connect()
    render(<ChatPanel />)

    const textarea = screen.getByPlaceholderText(/输入需求/)
    fireEvent.change(textarea, { target: { value: '/' } })

    expect(screen.getByText('/review')).toBeInTheDocument()
    expect(screen.getByText('/compress')).toBeInTheDocument()

    fireEvent.click(screen.getByText('/compress'))
    expect(ws.sentMessages().some((m) => m.type === 'compress_context')).toBe(true)
    expect((textarea as HTMLTextAreaElement).value).toBe('')
  })

  it('renders the plan confirmation card when a plan is pending', () => {
    resetStore()
    usePPTStore.setState({
      pendingPlan: {
        planId: 'p_ui',
        plan: '封面 + 三页内容',
        planReview: { approved: true },
        createdAt: Date.now()
      }
    })
    render(<ChatPanel />)

    expect(screen.getByText('待确认计划')).toBeInTheDocument()
    expect(screen.getByText('确认执行')).toBeInTheDocument()
  })

  it('rejects unsupported files instead of silently attaching them', () => {
    resetStore()
    render(<ChatPanel />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const bad = new File(['x'], 'old.ppt', { type: 'application/vnd.ms-powerpoint' })
    Object.defineProperty(input, 'files', { value: [bad], configurable: true })

    fireEvent.change(input)

    expect(screen.queryByLabelText('移除 old.ppt')).toBeNull()
    const messages = usePPTStore.getState().messages
    expect(
      messages.some((m) => m.content.includes('不支持该文件格式') && m.content.includes('old.ppt'))
    ).toBe(true)
  })

  it('accepts a .pptx attachment', () => {
    resetStore()
    render(<ChatPanel />)
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const good = new File(['x'], 'deck.pptx', {
      type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    })
    Object.defineProperty(input, 'files', { value: [good], configurable: true })

    fireEvent.change(input)

    expect(screen.getByLabelText('移除 deck.pptx')).toBeInTheDocument()
  })
})
