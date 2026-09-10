import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { SlideCanvas } from './SlideCanvas'
import { usePPTStore } from '../store/usePPTStore'
import { installFakeWebSocket } from '../test/wsMock'
import { makeConnector, makeGroup, makePresentation, makeShape, makeSlide } from '../test/factories'
import { getBounds } from '../editor/geometry/adapter'
import type { ConnectorElementIR } from '../types/ppt'

const mockCanvasRect = (width: number, height: number) => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    width,
    height,
    top: 0,
    left: 0,
    right: width,
    bottom: height,
    toJSON: () => ({})
  } as DOMRect)
}

const resetStore = () => {
  usePPTStore.setState({
    sessionId: 'sess_test',
    presentation: null,
    confirmedPresentation: null,
    activeSlideId: null,
    selectedElementId: null,
    selectedElementIds: [],
    selectionScope: [],
    editingElementId: null,
    ws: null,
    wsConnected: false,
    pendingMutations: [],
    outbox: [],
    mutationStatus: 'idle',
    zoom: 1
  })
}

describe('SlideCanvas interaction kernel', () => {
  beforeEach(() => {
    installFakeWebSocket()
    resetStore()
  })

  it('moves every element of a multi-selection as one atomic batch', () => {
    mockCanvasRect(1280, 720)
    const slide = makeSlide([
      makeShape('s1', 100, 100),
      makeShape('s2', 300, 100),
      makeShape('s3', 500, 100)
    ])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const { container } = render(<SlideCanvas />)

    const s1 = container.querySelector('#s1') as Element
    const s2 = container.querySelector('#s2') as Element
    const s3 = container.querySelector('#s3') as Element

    fireEvent.mouseDown(s1, { clientX: 150, clientY: 120 })
    fireEvent.mouseUp(window)
    fireEvent.mouseDown(s2, { clientX: 350, clientY: 120, shiftKey: true })
    fireEvent.mouseDown(s3, { clientX: 550, clientY: 120, shiftKey: true })

    expect(usePPTStore.getState().selectedElementIds).toEqual(['s1', 's2', 's3'])

    fireEvent.mouseDown(s1, { clientX: 150, clientY: 120 })
    fireEvent.mouseMove(window, { clientX: 200, clientY: 150 })
    fireEvent.mouseUp(window)

    const elements = usePPTStore.getState().getActiveSlide()?.elements ?? []
    expect(elements[0].x).toBeCloseTo(150)
    expect(elements[0].y).toBeCloseTo(130)
    expect(elements[1].x).toBeCloseTo(350)
    expect(elements[1].y).toBeCloseTo(130)
    expect(elements[2].x).toBeCloseTo(550)
    expect(elements[2].y).toBeCloseTo(130)

    const outbox = usePPTStore.getState().outbox
    expect(outbox).toHaveLength(1)
    expect(outbox[0].message.type).toBe('batch_mutation')
    expect(outbox[0].message.mutations).toHaveLength(3)
  })

  it('keeps connector endpoints and bbox in sync while dragging at 200% zoom', () => {
    mockCanvasRect(2560, 1440)
    const connector = makeConnector('c1', 100, 100, 300, 200)
    usePPTStore.getState().setPresentation(makePresentation([makeSlide([connector])]))
    const { container } = render(<SlideCanvas />)

    const c1 = container.querySelector('#c1') as Element
    fireEvent.mouseDown(c1, { clientX: 200, clientY: 200 })
    fireEvent.mouseMove(window, { clientX: 300, clientY: 240 })
    fireEvent.mouseUp(window)

    const updated = usePPTStore.getState().getActiveSlide()?.elements[0] as ConnectorElementIR
    expect(updated.start_x).toBeCloseTo(150)
    expect(updated.start_y).toBeCloseTo(120)
    expect(updated.end_x).toBeCloseTo(350)
    expect(updated.end_y).toBeCloseTo(220)
    expect(getBounds(updated)).toEqual({ x: 150, y: 120, width: 200, height: 100 })

    const payload = usePPTStore.getState().outbox[0].message.payload
    expect(payload).toMatchObject({
      start_x: 150,
      start_y: 120,
      end_x: 350,
      end_y: 220
    })
  })

  it('selects the group first and only exposes children after entering the scope', () => {
    mockCanvasRect(1280, 720)
    const group = makeGroup('g1', 100, 100, 300, 200, [
      makeShape('s1', 120, 120),
      makeShape('s2', 260, 120)
    ])
    usePPTStore.getState().setPresentation(makePresentation([makeSlide([group])]))
    const { container } = render(<SlideCanvas />)

    const groupNode = container.querySelector('#g1') as Element
    fireEvent.mouseDown(groupNode, { clientX: 150, clientY: 150 })
    fireEvent.mouseUp(window)
    expect(usePPTStore.getState().selectedElementIds).toEqual(['g1'])

    const childBefore = container.querySelector('#s1') as Element
    fireEvent.mouseDown(childBefore, { clientX: 150, clientY: 150 })
    fireEvent.mouseUp(window)
    expect(usePPTStore.getState().selectedElementIds).toEqual(['g1'])

    fireEvent.doubleClick(groupNode)
    expect(usePPTStore.getState().selectionScope).toEqual(['g1'])

    const childAfter = container.querySelector('#s1') as Element
    fireEvent.mouseDown(childAfter, { clientX: 150, clientY: 150 })
    fireEvent.mouseUp(window)
    expect(usePPTStore.getState().selectedElementIds).toEqual(['s1'])
  })

  it('drags a group child inside the entered scope and recomputes ancestor bounds', () => {
    mockCanvasRect(1280, 720)
    const group = makeGroup('g1', 100, 100, 300, 200, [
      makeShape('s1', 120, 120),
      makeShape('s2', 260, 120)
    ])
    usePPTStore.getState().setPresentation(makePresentation([makeSlide([group])]))
    const { container } = render(<SlideCanvas />)

    const groupNode = container.querySelector('#g1') as Element
    fireEvent.mouseDown(groupNode, { clientX: 150, clientY: 150 })
    fireEvent.mouseUp(window)
    fireEvent.doubleClick(groupNode)

    const child = container.querySelector('#s1') as Element
    fireEvent.mouseDown(child, { clientX: 150, clientY: 150 })
    fireEvent.mouseMove(window, { clientX: 180, clientY: 170 })
    fireEvent.mouseUp(window)

    const storedGroup = usePPTStore.getState().getActiveSlide()?.elements[0]
    const storedChild = storedGroup?.type === 'group' ? storedGroup.children[0] : null
    expect(storedChild?.x).toBeCloseTo(150)
    expect(storedChild?.y).toBeCloseTo(140)

    expect(storedGroup?.x).toBe(150)
    expect(storedGroup?.y).toBe(120)
    expect(storedGroup?.width).toBe(210)
    expect(storedGroup?.height).toBe(70)

    const payload = usePPTStore.getState().outbox[0].message.payload
    expect(payload.element_id).toBe('s1')
    expect(payload).toMatchObject({ x: 150, y: 140 })
  })

  it('makes entered group children interactive without pointer-events passthrough', () => {
    mockCanvasRect(1280, 720)
    const group = makeGroup('g1', 100, 100, 300, 200, [
      makeShape('s1', 120, 120),
      makeShape('s2', 260, 120)
    ])
    usePPTStore.getState().setPresentation(makePresentation([makeSlide([group])]))
    const { container } = render(<SlideCanvas />)

    const groupNode = container.querySelector('#g1') as Element
    expect(container.querySelector('#group-content-g1')?.getAttribute('style')).toContain('pointer-events: none')

    fireEvent.doubleClick(groupNode)

    const content = container.querySelector('#group-content-g1') as Element
    expect(content.getAttribute('style') ?? '').not.toContain('pointer-events')
    expect(container.querySelector('#s1')?.getAttribute('class')).toContain('cursor-move')
  })

  it('does not commit group geometry until the resize gesture ends', () => {
    mockCanvasRect(1280, 720)
    const group = makeGroup('g1', 100, 100, 200, 100, [
      makeShape('s1', 120, 120),
      makeShape('s2', 220, 120)
    ])
    const slide = makeSlide([group])
    usePPTStore.getState().setPresentation(makePresentation([slide]))
    const { container } = render(<SlideCanvas />)

    const groupNode = container.querySelector('#g1') as Element
    fireEvent.mouseDown(groupNode, { clientX: 150, clientY: 150 })
    fireEvent.mouseUp(window)

    const handles = container.querySelectorAll('rect[width="9"]')
    expect(handles.length).toBe(8)
    const seHandle = handles[4]

    fireEvent.mouseDown(seHandle, { clientX: 300, clientY: 200 })
    fireEvent.mouseMove(window, { clientX: 500, clientY: 300 })

    expect(usePPTStore.getState().outbox).toHaveLength(0)
    expect(usePPTStore.getState().getActiveSlide()?.elements[0].width).toBe(200)

    fireEvent.mouseUp(window)

    const outbox = usePPTStore.getState().outbox
    expect(outbox).toHaveLength(1)
    const stored = usePPTStore.getState().getActiveSlide()?.elements[0]
    expect(stored?.width).toBeCloseTo(400)
    expect(stored?.height).toBeCloseTo(200)
  })
})
