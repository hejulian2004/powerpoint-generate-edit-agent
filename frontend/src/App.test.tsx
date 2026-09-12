import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import App from './App'
import { usePPTStore } from './store/usePPTStore'
import { FakeWebSocket, installFakeWebSocket } from './test/wsMock'
import { makePresentation, makeShape, makeSlide } from './test/factories'

const renderApp = async () => {
  render(<App />)
  await vi.waitFor(() => {
    FakeWebSocket.latest().onopen?.({})
  })
}

describe('App keyboard shortcut scoping', () => {
  beforeEach(() => {
    installFakeWebSocket()
    // App bootstraps the workspace over HTTP first; return a session so the
    // socket opens against the backend-owned session id.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 'sess_test', is_new: false, snapshot: null })
    }))
    usePPTStore.setState({
      sessionId: 'sess_test',
      ws: null,
      wsConnected: false,
      pendingMutations: [],
      outbox: [],
      editingElementId: null,
      selectionScope: [],
      presentation: makePresentation([makeSlide([makeShape('s1', 0, 0)])])
    })
  })

  it('leaves undo to the browser while an editable field has focus', async () => {
    await renderApp()
    const undoSpy = vi.spyOn(usePPTStore.getState(), 'triggerUndo')

    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    fireEvent.keyDown(input, { key: 'z', ctrlKey: true })

    expect(undoSpy).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('routes canvas undo when focus is outside editable fields', async () => {
    await renderApp()
    const undoSpy = vi.spyOn(usePPTStore.getState(), 'triggerUndo')

    fireEvent.keyDown(window, { key: 'z', ctrlKey: true })

    expect(undoSpy).toHaveBeenCalledTimes(1)
  })

  it('deletes the selection only outside editable fields', async () => {
    await renderApp()
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
