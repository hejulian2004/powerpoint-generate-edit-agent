import { describe, expect, it } from 'vitest'
import type { ConnectorElementIR, GroupElementIR, ShapeElementIR } from '../../types/ppt'
import {
  canResize,
  cloneElement,
  findElementPath,
  getBounds,
  resizeElement,
  scaleElement,
  syncConnectorBounds,
  translateElement,
  unionBounds
} from './adapter'

const makeShape = (id: string, x: number, y: number, width = 100, height = 50): ShapeElementIR => ({
  id,
  type: 'shape',
  shape_type: 'roundRect',
  x,
  y,
  width,
  height,
  rotation: 0,
  z_index: 0,
  style: { opacity: 1, radius: 2, padding: 8 },
  children: []
})

const makeConnector = (id: string, startX: number, startY: number, endX: number, endY: number): ConnectorElementIR => {
  const connector: ConnectorElementIR = {
    id,
    type: 'connector',
    x: Math.min(startX, endX),
    y: Math.min(startY, endY),
    width: Math.max(Math.abs(endX - startX), 1),
    height: Math.max(Math.abs(endY - startY), 1),
    rotation: 0,
    z_index: 0,
    start_x: startX,
    start_y: startY,
    end_x: endX,
    end_y: endY,
    arrow_start: 'none',
    arrow_end: 'triangle',
    line_type: 'straight',
    style: { opacity: 1, radius: 0, padding: 8 },
    children: []
  }
  syncConnectorBounds(connector)
  return connector
}

const makeGroup = (id: string, x: number, y: number, width: number, height: number, children: GroupElementIR['children']): GroupElementIR => ({
  id,
  type: 'group',
  x,
  y,
  width,
  height,
  rotation: 0,
  z_index: 0,
  style: { opacity: 1, radius: 0, padding: 8 },
  children
})

describe('geometry adapter', () => {
  it('derives connector bounds from endpoints instead of stale x/y', () => {
    const connector = makeConnector('c1', 300, 200, 100, 100)
    connector.x = 999
    connector.y = 999

    expect(getBounds(connector)).toEqual({ x: 100, y: 100, width: 200, height: 100 })
  })

  it('translates a connector by moving both endpoints and resyncing bounds', () => {
    const connector = makeConnector('c1', 100, 100, 300, 200)

    translateElement(connector, 40, -20)

    expect(connector.start_x).toBe(140)
    expect(connector.start_y).toBe(80)
    expect(connector.end_x).toBe(340)
    expect(connector.end_y).toBe(180)
    expect(connector.x).toBe(140)
    expect(connector.y).toBe(80)
    expect(connector.transform?.x).toBe(140)
  })

  it('translates group children and nested connectors recursively', () => {
    const shape = makeShape('s1', 100, 100)
    const connector = makeConnector('c1', 100, 150, 200, 150)
    const inner = makeGroup('g2', 100, 100, 100, 60, [connector])
    const group = makeGroup('g1', 100, 100, 200, 100, [shape, inner])

    translateElement(group, 30, 10)

    expect(group.x).toBe(130)
    expect(shape.x).toBe(130)
    expect(shape.y).toBe(110)
    expect(inner.x).toBe(130)
    expect(connector.start_x).toBe(130)
    expect(connector.end_x).toBe(230)
    expect(connector.y).toBe(160)
  })

  it('scales group children and connector endpoints around a fixed origin', () => {
    const shape = makeShape('s1', 100, 100, 100, 50)
    const connector = makeConnector('c1', 100, 150, 200, 150)
    const group = makeGroup('g1', 100, 100, 200, 100, [shape, connector])

    scaleElement(group, 2, 2, 100, 100)

    expect(group.width).toBe(400)
    expect(shape.x).toBe(100)
    expect(shape.width).toBe(200)
    expect(connector.start_x).toBe(100)
    expect(connector.start_y).toBe(200)
    expect(connector.end_x).toBe(300)
    expect(connector.end_y).toBe(200)
  })

  it('resizes a group with the same scale-then-translate semantics as the backend', () => {
    const shape = makeShape('s1', 120, 140, 80, 40)
    const connector = makeConnector('c1', 120, 200, 260, 240)
    const group = makeGroup('g1', 100, 100, 200, 150, [shape, connector])
    const clone = cloneElement(group)

    resizeElement(group, { x: 150, y: 130, width: 400, height: 300 }, 'se', 24)

    scaleElement(clone, 2, 2, 100, 100)
    translateElement(clone, 50, 30)

    expect(group.x).toBe(clone.x)
    expect(group.width).toBe(clone.width)
    expect(shape.x).toBe(clone.children[0].x)
    expect(shape.width).toBe(clone.children[0].width)
    expect(connector.start_x).toBe((clone.children[1] as ConnectorElementIR).start_x)
    expect(connector.end_y).toBe((clone.children[1] as ConnectorElementIR).end_y)
  })

  it('resizes a connector by scaling its endpoints', () => {
    const connector = makeConnector('c1', 100, 100, 300, 200)

    resizeElement(connector, { x: 100, y: 100, width: 400, height: 100 }, 'e', 24)

    expect(connector.start_x).toBe(100)
    expect(connector.end_x).toBe(500)
    expect(connector.start_y).toBe(100)
    expect(connector.end_y).toBe(200)
    expect(getBounds(connector)).toEqual({ x: 100, y: 100, width: 400, height: 100 })
  })

  it('computes union bounds across mixed element types', () => {
    const shape = makeShape('s1', 100, 100, 100, 50)
    const connector = makeConnector('c1', 300, 200, 400, 400)

    expect(unionBounds([shape, connector])).toEqual({ x: 100, y: 100, width: 300, height: 300 })
  })

  it('finds nested elements with their ancestor path', () => {
    const shape = makeShape('s1', 100, 100)
    const inner = makeGroup('g2', 100, 100, 100, 50, [shape])
    const group = makeGroup('g1', 100, 100, 100, 50, [inner])

    const path = findElementPath([group], 's1')

    expect(path?.element.id).toBe('s1')
    expect(path?.ancestors).toEqual(['g1', 'g2'])
    expect(path?.parent?.id).toBe('g2')
  })

  it('respects locked elements for resize capability', () => {
    const shape = makeShape('s1', 0, 0)
    expect(canResize(shape)).toBe(true)
    shape.locked = true
    expect(canResize(shape)).toBe(false)
  })
})
