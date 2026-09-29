import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatPanel } from './ChatPanel'
import { usePPTStore } from '../store/usePPTStore'
import { installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide } from '../test/factories'

describe('ChatPanel conversation and inspector', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = () => {}
    installFakeWebSocket()
    usePPTStore.setState({
      sessionId: 'sess_test',
      presentation: makePresentation([makeSlide([makeShape('s1', 40, 40)])]),
      confirmedPresentation: null,
      activeSlideId: 'slide_1',
      selectedElementId: 's1',
      selectedElementIds: ['s1'],
      selectionScope: [],
      editingElementId: null,
      activeRightTab: 'inspector',
      messages: [{
        id: 'm1',
        role: 'assistant',
        content: '对话仍然可见',
        timestamp: 1
      }],
      ws: null,
      wsConnected: false,
      pendingMutations: [],
      outbox: [],
      mutationStatus: 'idle'
    })
  })

  it('keeps the message list mounted while the selected element inspector is open', () => {
    render(<ChatPanel />)

    expect(screen.getByTestId('chat-messages')).toBeTruthy()
    expect(screen.getByText('对话仍然可见')).toBeTruthy()
    expect(screen.getByTestId('inspector-dock')).toBeTruthy()
    expect(screen.getByText(/几何卡片/)).toBeTruthy()
  })
})
