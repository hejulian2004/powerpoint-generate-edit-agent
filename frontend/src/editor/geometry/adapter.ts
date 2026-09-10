import type { ConnectorElementIR, ElementIR, GroupElementIR } from '../../types/ppt'
import type { Bounds, ResizeHandle } from '../snapping/types'

const round2 = (value: number) => Math.round(value * 100) / 100

export function isGroup(el: ElementIR): el is GroupElementIR {
  return el.type === 'group'
}

export function isConnector(el: ElementIR): el is ConnectorElementIR {
  return el.type === 'connector'
}

export function cloneElement<T extends ElementIR>(el: T): T {
  return JSON.parse(JSON.stringify(el)) as T
}

export function syncTransform(el: ElementIR): void {
  const transform = el.transform
  if (!transform) {
    el.transform = {
      x: el.x,
      y: el.y,
      width: el.width,
      height: el.height,
      rotation: el.rotation
    }
    return
  }
  transform.x = el.x
  transform.y = el.y
  transform.width = el.width
  transform.height = el.height
  transform.rotation = el.rotation
}

export function syncConnectorBounds(el: ConnectorElementIR): void {
  el.x = round2(Math.min(el.start_x, el.end_x))
  el.y = round2(Math.min(el.start_y, el.end_y))
  el.width = round2(Math.max(Math.abs(el.end_x - el.start_x), 1))
  el.height = round2(Math.max(Math.abs(el.end_y - el.start_y), 1))
  syncTransform(el)
}

export function getBounds(el: ElementIR): Bounds {
  if (isConnector(el)) {
    return {
      x: Math.min(el.start_x, el.end_x),
      y: Math.min(el.start_y, el.end_y),
      width: Math.max(Math.abs(el.end_x - el.start_x), 1),
      height: Math.max(Math.abs(el.end_y - el.start_y), 1)
    }
  }
  return { x: el.x, y: el.y, width: el.width, height: el.height }
}

export function unionBounds(elements: ReadonlyArray<ElementIR>): Bounds | null {
  if (elements.length === 0) return null
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const el of elements) {
    const bounds = getBounds(el)
    minX = Math.min(minX, bounds.x)
    minY = Math.min(minY, bounds.y)
    maxX = Math.max(maxX, bounds.x + bounds.width)
    maxY = Math.max(maxY, bounds.y + bounds.height)
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY }
}

export function recomputeGroupBounds(group: GroupElementIR): void {
  const bounds = unionBounds(group.children)
  if (!bounds) return
  group.x = round2(bounds.x)
  group.y = round2(bounds.y)
  group.width = round2(Math.max(bounds.width, 1))
  group.height = round2(Math.max(bounds.height, 1))
  syncTransform(group)
}

export function translateElement(el: ElementIR, dx: number, dy: number): void {
  if (isGroup(el)) {
    el.x = round2(el.x + dx)
    el.y = round2(el.y + dy)
    for (const child of el.children) {
      translateElement(child, dx, dy)
    }
    syncTransform(el)
    return
  }
  if (isConnector(el)) {
    el.start_x = round2(el.start_x + dx)
    el.start_y = round2(el.start_y + dy)
    el.end_x = round2(el.end_x + dx)
    el.end_y = round2(el.end_y + dy)
    syncConnectorBounds(el)
    return
  }
  el.x = round2(el.x + dx)
  el.y = round2(el.y + dy)
  syncTransform(el)
}

export function scaleElement(
  el: ElementIR,
  sx: number,
  sy: number,
  originX?: number,
  originY?: number
): void {
  const ox = originX ?? el.x
  const oy = originY ?? el.y

  if (isGroup(el)) {
    el.x = round2(ox + (el.x - ox) * sx)
    el.y = round2(oy + (el.y - oy) * sy)
    el.width = round2(el.width * sx)
    el.height = round2(el.height * sy)
    for (const child of el.children) {
      scaleElement(child, sx, sy, ox, oy)
    }
    syncTransform(el)
    return
  }
  if (isConnector(el)) {
    el.start_x = round2(ox + (el.start_x - ox) * sx)
    el.start_y = round2(oy + (el.start_y - oy) * sy)
    el.end_x = round2(ox + (el.end_x - ox) * sx)
    el.end_y = round2(oy + (el.end_y - oy) * sy)
    syncConnectorBounds(el)
    return
  }
  el.x = round2(ox + (el.x - ox) * sx)
  el.y = round2(oy + (el.y - oy) * sy)
  el.width = round2(el.width * sx)
  el.height = round2(el.height * sy)
  syncTransform(el)
}

export function resizeElement(
  el: ElementIR,
  next: Bounds,
  _handle: ResizeHandle,
  minSize: number
): void {
  if (isGroup(el) || isConnector(el)) {
    const sx = el.width > 0 ? next.width / el.width : 1
    const sy = el.height > 0 ? next.height / el.height : 1
    const dx = next.x - el.x
    const dy = next.y - el.y
    if (sx !== 1 || sy !== 1) {
      scaleElement(el, sx, sy)
    }
    if (dx !== 0 || dy !== 0) {
      translateElement(el, dx, dy)
    }
    return
  }

  el.x = next.x
  el.y = next.y
  el.width = Math.max(minSize, next.width)
  el.height = Math.max(minSize, next.height)
  syncTransform(el)
}

export function canResize(el: ElementIR): boolean {
  return !el.locked
}

export function canTranslate(el: ElementIR): boolean {
  return !el.locked
}

export interface ElementPath {
  element: ElementIR
  parent: GroupElementIR | null
  index: number
  ancestors: string[]
}

export function findElementPath(
  elements: ReadonlyArray<ElementIR>,
  id: string,
  ancestors: string[] = []
): ElementPath | null {
  for (let index = 0; index < elements.length; index += 1) {
    const element = elements[index]
    if (element.id === id) {
      return {
        element,
        parent: null,
        index,
        ancestors
      }
    }
    if (isGroup(element)) {
      const found = findElementPath(element.children, id, [...ancestors, element.id])
      if (found) {
        return found.parent ? found : { ...found, parent: element }
      }
    }
  }
  return null
}
