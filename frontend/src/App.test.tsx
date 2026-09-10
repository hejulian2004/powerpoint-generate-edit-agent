import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import App from './App'
import { usePPTStore } from './store/usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from './test/wsMock'
import { makePresentation, makeShape, makeSlide } from './test/factories'

const renderApp = () => {
  render(<App />)
  FakeWebSocket.latest().onopen?.({})
}

describe('App keyboard shortcut scoping', () => {
  beforeEach(() => {
    installFakeWebSocket()
    usePPTStore.setState({
      ws: null,
      wsConnected: false,
      pendingMutations: [],
      outbox: [],
      editingElementId: null,
      selectionScope: [],
      presentation: makePresentation([makeSlide([makeShape('s1', 0, 0)])])
    })
  })

  it('leaves undo to the browser while an editable field has focus', () => {
    renderApp()
    const undoSpy = vi.spyOn(usePPTStore.getState(), 'triggerUndo')

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    fireEvent.keyDown(input, { key: 'z', ctrlKey: true })

    expect(undoSpy).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('routes canvas undo when focus is outside editable fields', () => {
    renderApp()
    const undoSpy = vi.spyOn(usePPTStore.getState(), 'triggerUndo')

    fireEvent.keyDown(window, { key: 'z', ctrlKey: true })

    expect(undoSpy).toHaveBeenCalledTimes(1)
  })

  it('deletes the selection only outside editable fields', () => {
    renderApp()
    const deleteSpy = vi.spyOn(usePPTStore.getState(), 'deleteSelectedElements')

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    fireEvent.keyDown(input, { key: 'Delete' })
    expect(deleteSpy).not.toHaveBeenCalled()
    document.body.removeChild(input)

    fireEvent.keyDown(window, { key: 'Delete' })
    expect(deleteSpy).toHaveBeenCalledTimes(1)
  })
})
