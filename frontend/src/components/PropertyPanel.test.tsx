import { beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PropertyPanel } from './PropertyPanel'
import { usePPTStore } from '../store/usePPTStore'
import { installFakeWebSocket } from '../test/wsMock'
import { makePresentation, makeShape, makeSlide, makeText } from '../test/factories'

const resetStore = (elements: ReturnType<typeof makeShape>[] | ReturnType<typeof makeText>[]) => {
  installFakeWebSocket()
  usePPTStore.setState({
    sessionId: 'sess_test',
    presentation: makePresentation([makeSlide(elements)]),
    confirmedPresentation: null,
    activeSlideId: 'slide_1',
    selectedElementId: elements[0]?.id ?? null,
    selectedElementIds: elements[0]?.id ? [elements[0].id] : [],
    selectionScope: [],
    editingElementId: null,
    ws: null,
    wsConnected: false,
    pendingMutations: [],
    outbox: [],
    mutationStatus: 'idle'
  })
}

describe('PropertyPanel editing transactions', () => {
  beforeEach(() => {
    resetStore([makeShape('s1', 0, 0)])
  })

  it('commits panel text once on blur instead of per keystroke', () => {
    resetStore([makeText('t1', 'hello')])
    render(<PropertyPanel />)

    const textarea = screen.getByPlaceholderText('输入卡片或段落文本内容...')
    fireEvent.change(textarea, { target: { value: 'A' } })
    fireEvent.change(textarea, { target: { value: 'An' } })
    fireEvent.change(textarea, { target: { value: 'Anomaly' } })

    expect(usePPTStore.getState().outbox).toHaveLength(0)

    fireEvent.blur(textarea)

    const outbox = usePPTStore.getState().outbox
    expect(outbox).toHaveLength(1)
    expect(outbox[0].message.payload.text).toBe('Anomaly')
  })

  it('commits a numeric field once on blur', () => {
    render(<PropertyPanel />)

    const inputs = screen.getAllByRole('spinbutton')
    const widthInput = inputs[2]
    fireEvent.focus(widthInput)
    fireEvent.change(widthInput, { target: { value: '2' } })
    fireEvent.change(widthInput, { target: { value: '20' } })
    fireEvent.change(widthInput, { target: { value: '200' } })

    expect(usePPTStore.getState().outbox).toHaveLength(0)

    fireEvent.blur(widthInput)

    const outbox = usePPTStore.getState().outbox
    expect(outbox).toHaveLength(1)
    expect(outbox[0].message.payload.width).toBe(200)
  })

  it('commits a slider only after the pointer is released', () => {
    const { container } = render(<PropertyPanel />)

    const sliders = container.querySelectorAll('input[type="range"]')
    expect(sliders.length).toBeGreaterThan(0)
    const radiusSlider = sliders[0]

    fireEvent.change(radiusSlider, { target: { value: '24' } })
    expect(usePPTStore.getState().outbox).toHaveLength(0)

    fireEvent.pointerUp(radiusSlider)

    const outbox = usePPTStore.getState().outbox
    expect(outbox).toHaveLength(1)
    expect(outbox[0].message.payload.radius).toBe(24)
  })

  it('does not emit a mutation when a blurred numeric field is unchanged', () => {
    render(<PropertyPanel />)

    const inputs = screen.getAllByRole('spinbutton')
    const widthInput = inputs[2]
    fireEvent.focus(widthInput)
    fireEvent.blur(widthInput)

    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().pendingMutations).toHaveLength(0)
  })
})
