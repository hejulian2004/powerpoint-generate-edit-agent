import { getBoundsAnchors, clampBoundsToSlide } from './geometry'
import type {
  Bounds,
  SlideBounds,
  SnapCandidate,
  SnapGuide,
  SnapResult,
  ResizeSnapResult,
  SnapAxis,
  SnapSession,
  ActiveSnap,
  ResizeHandle,
  SnapThresholds
} from './types'

export const SNAP_SCREEN_PX = 6
export const RELEASE_SCREEN_PX = 10

const GUIDE_PADDING = 12
/** Tolerance for floating-point when validating snapped bounds against the slide. */
const BOUNDS_EPS = 1e-6
/**
 * Max allowed deviation between a winning guide position and the final
 * dragged edge before the guide is considered misleading and dropped
 * (covers FP noise from clamp arithmetic; real minSize floors move by more).
 */
const GUIDE_EPS = 1e-6

type AnchorX = 'left' | 'centerX' | 'right'
type AnchorY = 'top' | 'centerY' | 'bottom'

// Ordering of anchor pairs controls which alignments are supported.
const X_PAIRS: ReadonlyArray<[AnchorX, AnchorX]> = [
  ['left', 'left'],
  ['left', 'right'],
  ['centerX', 'centerX'],
  ['right', 'right'],
  ['right', 'left']
]

const Y_PAIRS: ReadonlyArray<[AnchorY, AnchorY]> = [
  ['top', 'top'],
  ['top', 'bottom'],
  ['centerY', 'centerY'],
  ['bottom', 'bottom'],
  ['bottom', 'top']
]

/**
 * Deterministic priority for equal-distance ties (lower wins):
 * 0 slide-center, 1 element-center, 2 element-edge, 3 slide-edge.
 */
function kindPriority(kind: SnapGuide['kind']): number {
  switch (kind) {
    case 'slide-center':
      return 0
    case 'element-center':
      return 1
    case 'element-edge':
      return 2
    case 'slide-edge':
      return 3
    case 'spacing':
      return 4
  }
}

interface AxisOption {
  axis: SnapAxis
  key: string
  dist: number
  priority: number
  /** Position correction (in slide units) to apply to the moving bounds origin (or size for resize). */
  delta: number
  guide: SnapGuide
  candidate: SnapCandidate
}

function buildGuide(
  axis: SnapAxis,
  position: number,
  kind: SnapGuide['kind'],
  bounds: Bounds,
  candidate: SnapCandidate,
  slide: SlideBounds,
  isSlide: boolean
): SnapGuide {
  if (kind === 'slide-center' || kind === 'slide-edge') {
    return {
      axis,
      position,
      kind,
      start: 0,
      end: axis === 'x' ? slide.height : slide.width,
      targetElementId: isSlide ? undefined : candidate.id
    }
  }
  // Element guide extends across the moving + target bounding range with padding.
  if (axis === 'x') {
    const start = Math.min(bounds.y, candidate.bounds.y) - GUIDE_PADDING
    const end = Math.max(bounds.y + bounds.height, candidate.bounds.y + candidate.bounds.height) + GUIDE_PADDING
    return { axis, position, kind, start, end, targetElementId: candidate.id }
  }
  const start = Math.min(bounds.x, candidate.bounds.x) - GUIDE_PADDING
  const end = Math.max(bounds.x + bounds.width, candidate.bounds.x + candidate.bounds.width) + GUIDE_PADDING
  return { axis, position, kind, start, end, targetElementId: candidate.id }
}

function toAxisKind(targetAnchor: string, isSlide: boolean): SnapGuide['kind'] {
  const isCenter = targetAnchor === 'centerX' || targetAnchor === 'centerY'
  if (isSlide) return isCenter ? 'slide-center' : 'slide-edge'
  return isCenter ? 'element-center' : 'element-edge'
}

function compareOptions(a: AxisOption, b: AxisOption): number {
  if (a.dist !== b.dist) return a.dist - b.dist
  if (a.priority !== b.priority) return a.priority - b.priority
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0
}

/**
 * Rebuild a winning option's guide against the final snapped bounds so the
 * guide span tracks the element's rendered position (the pre-snap span can be
 * off by up to the snap delta). Guide position/kind are unchanged.
 */
function refreshGuide(option: AxisOption, snappedBounds: Bounds, slide: SlideBounds): SnapGuide {
  const isSlide = option.candidate.id === '__slide__'
  return buildGuide(
    option.axis,
    option.guide.position,
    option.guide.kind,
    snappedBounds,
    option.candidate,
    slide,
    isSlide
  )
}

/**
 * Resolve the best snap for one axis with hysteresis.
 * Mutates `session` per-axis to keep a snap engaged until release threshold.
 */
function resolveAxis(
  options: AxisOption[],
  axis: SnapAxis,
  session: SnapSession,
  thresholds: SnapThresholds
): { option?: AxisOption; engaged: boolean } {
  const { enter, release } = thresholds[axis]
  const active: ActiveSnap | undefined = session[axis === 'x' ? 'activeSnapX' : 'activeSnapY']

  if (active) {
    const activeOpt = options.find((o) => o.key === active.key)
    if (activeOpt && activeOpt.dist <= release) {
      return { option: activeOpt, engaged: true }
    }
    // Broke the hysteresis envelope; clear and re-evaluate below.
    session[axis === 'x' ? 'activeSnapX' : 'activeSnapY'] = undefined
  }

  const withinEnter = options.filter((o) => o.dist <= enter).sort(compareOptions)
  if (withinEnter.length > 0) {
    const best = withinEnter[0]
    session[axis === 'x' ? 'activeSnapX' : 'activeSnapY'] = { key: best.key, guide: best.guide }
    return { option: best, engaged: true }
  }
  return { engaged: false }
}

/** True when applying `delta` to the X origin keeps the bounds inside the slide. */
function moveXInBounds(bounds: Bounds, delta: number, slide: SlideBounds): boolean {
  const nx = bounds.x + delta
  return nx >= -BOUNDS_EPS && nx <= slide.width - bounds.width + BOUNDS_EPS
}

/** True when applying `delta` to the Y origin keeps the bounds inside the slide. */
function moveYInBounds(bounds: Bounds, delta: number, slide: SlideBounds): boolean {
  const ny = bounds.y + delta
  return ny >= -BOUNDS_EPS && ny <= slide.height - bounds.height + BOUNDS_EPS
}

/**
 * Drop any engaged per-axis hysteresis so a later snap re-enters from the
 * ENTER threshold rather than inheriting a stale release envelope.
 * Used when snapping is toggled off (e.g. Alt bypass) mid-drag.
 */
export function clearSnapSession(session: SnapSession): void {
  session.activeSnapX = undefined
  session.activeSnapY = undefined
}

/**
 * Pure function: snap the moving bounds toward slide + sibling candidates.
 * Returns snapped geometry plus the guides to render. Does not mutate the
 * presentation or any React/Zustand state.
 *
 * Snap options that would push the element outside the slide are ignored so
 * the returned geometry is always in-bounds and every guide is truthful.
 */
export function snapMove(
  bounds: Bounds,
  candidates: SnapCandidate[],
  slide: SlideBounds,
  session: SnapSession,
  thresholds: SnapThresholds,
  enabled: boolean
): SnapResult {
  const result: SnapResult = { x: bounds.x, y: bounds.y, guides: [], snappedX: false, snappedY: false }
  if (!enabled) {
    // Alt bypass: drop any engaged hysteresis so snapping resumes with a
    // fresh ENTER threshold instead of inheriting the release envelope.
    clearSnapSession(session)
    return result
  }

  const moving = getBoundsAnchors(bounds)

  const xOptions: AxisOption[] = []
  const yOptions: AxisOption[] = []

  for (const candidate of candidates) {
    const isSlide = candidate.id === '__slide__'
    const target = getBoundsAnchors(candidate.bounds)

    for (const [ma, ta] of X_PAIRS) {
      const pos = target[ta]
      const delta = pos - moving[ma]
      if (!moveXInBounds(bounds, delta, slide)) continue
      const kind = toAxisKind(ta, isSlide)
      xOptions.push({
        axis: 'x',
        key: `${candidate.id}:${ma}->${ta}`,
        dist: Math.abs(delta),
        priority: kindPriority(kind),
        delta,
        guide: buildGuide('x', pos, kind, bounds, candidate, slide, isSlide),
        candidate
      })
    }

    for (const [ma, ta] of Y_PAIRS) {
      const pos = target[ta]
      const delta = pos - moving[ma]
      if (!moveYInBounds(bounds, delta, slide)) continue
      const kind = toAxisKind(ta, isSlide)
      yOptions.push({
        axis: 'y',
        key: `${candidate.id}:${ma}->${ta}`,
        dist: Math.abs(delta),
        priority: kindPriority(kind),
        delta,
        guide: buildGuide('y', pos, kind, bounds, candidate, slide, isSlide),
        candidate
      })
    }
  }

  let winX: AxisOption | undefined
  let winY: AxisOption | undefined

  const rx = resolveAxis(xOptions, 'x', session, thresholds)
  if (rx.option) {
    result.x = bounds.x + rx.option.delta
    result.snappedX = true
    result.snapXKey = rx.option.key
    winX = rx.option
  }

  const ry = resolveAxis(yOptions, 'y', session, thresholds)
  if (ry.option) {
    result.y = bounds.y + ry.option.delta
    result.snappedY = true
    result.snapYKey = ry.option.key
    winY = ry.option
  }

  const snappedBounds: Bounds = { ...bounds, x: result.x, y: result.y }
  if (winX) result.guides.push(refreshGuide(winX, snappedBounds, slide))
  if (winY) result.guides.push(refreshGuide(winY, snappedBounds, slide))

  return result
}

interface ResizeEdges {
  /** Dragged X edge anchor ('left' for west, 'right' for east, undefined if not resizing horizontally). */
  xEdge?: 'left' | 'right'
  /** Dragged Y edge anchor ('top' for north, 'bottom' for south, undefined if not resizing vertically). */
  yEdge?: 'top' | 'bottom'
}

function edgesForHandle(handle: ResizeHandle): ResizeEdges {
  return {
    xEdge: handle.includes('e') ? 'right' : handle.includes('w') ? 'left' : undefined,
    yEdge: handle.includes('s') ? 'bottom' : handle.includes('n') ? 'top' : undefined
  }
}

/**
 * Clamp one resize axis while preserving the non-dragged (fixed) edge.
 * - `draggedEdge 'min'`: near edge (x/y) is dragged, far edge (right/bottom) is
 *   fixed — minSize flooring moves the dragged edge, never the fixed one.
 * - `draggedEdge 'max'` (or axis untouched): near edge is fixed; only the size
 *   is clamped to fit the slide.
 */
export function clampResizeAxis(
  pos: number,
  size: number,
  slideSize: number,
  minSize: number,
  draggedEdge: 'min' | 'max'
): { pos: number; size: number } {
  if (draggedEdge === 'min') {
    const far = Math.max(minSize, Math.min(pos + size, slideSize))
    const s = Math.max(minSize, Math.min(size, far))
    return { pos: far - s, size: s }
  }
  const p = Math.max(0, Math.min(pos, slideSize - minSize))
  const s = Math.max(minSize, Math.min(size, slideSize - p))
  return { pos: p, size: s }
}

/**
 * Pure function: snap the dragged edge(s) of a resizing element.
 * Each axis is independent; corner handles snap both axes. Enforces minSize
 * and slide-bounds clamping (never negative width/height) without moving the
 * non-dragged edge.
 */
export function snapResize(
  bounds: Bounds,
  handle: ResizeHandle,
  candidates: SnapCandidate[],
  slide: SlideBounds,
  session: SnapSession,
  thresholds: SnapThresholds,
  enabled: boolean,
  minSize = 24
): ResizeSnapResult {
  const edges = edgesForHandle(handle)

  let x: number = bounds.x
  let y: number = bounds.y
  let width: number = bounds.width
  let height: number = bounds.height

  let winX: AxisOption | undefined
  let winY: AxisOption | undefined

if (enabled) {
    const anchors = getBoundsAnchors(bounds)

    if (edges.xEdge) {
      const options: AxisOption[] = []
      const isLeft = edges.xEdge === 'left'
      const movingPos = isLeft ? anchors.left : anchors.right
      const X_TARGETS: ReadonlyArray<AnchorX> = ['left', 'centerX', 'right']

      for (const candidate of candidates) {
        const isSlide = candidate.id === '__slide__'
        const target = getBoundsAnchors(candidate.bounds)
        for (const ta of X_TARGETS) {
          const pos = target[ta]
          const delta = pos - movingPos
          const kind = toAxisKind(ta, isSlide)
          options.push({
            axis: 'x',
            key: `resize:${candidate.id}:${isLeft ? 'left' : 'right'}->${ta}`,
            dist: Math.abs(delta),
            priority: kindPriority(kind),
            delta,
            guide: buildGuide('x', pos, kind, bounds, candidate, slide, isSlide),
            candidate
          })
        }
      }

      const rx = resolveAxis(options, 'x', session, thresholds)
      if (rx.option) {
        const delta = rx.option.delta
        if (isLeft) {
          x = bounds.x + delta
          width = bounds.width - delta
        } else {
          width = bounds.width + delta
        }
        winX = rx.option
      }
    }

    if (edges.yEdge) {
      const options: AxisOption[] = []
      const isTop = edges.yEdge === 'top'
      const movingPos = isTop ? anchors.top : anchors.bottom
      const Y_TARGETS: ReadonlyArray<AnchorY> = ['top', 'centerY', 'bottom']

      for (const candidate of candidates) {
        const isSlide = candidate.id === '__slide__'
        const target = getBoundsAnchors(candidate.bounds)
        for (const ta of Y_TARGETS) {
          const pos = target[ta]
          const delta = pos - movingPos
          const kind = toAxisKind(ta, isSlide)
          options.push({
            axis: 'y',
            key: `resize:${candidate.id}:${isTop ? 'top' : 'bottom'}->${ta}`,
            dist: Math.abs(delta),
            priority: kindPriority(kind),
            delta,
            guide: buildGuide('y', pos, kind, bounds, candidate, slide, isSlide),
            candidate
          })
        }
      }

      const ry = resolveAxis(options, 'y', session, thresholds)
      if (ry.option) {
        const delta = ry.option.delta
        if (isTop) {
          y = bounds.y + delta
          height = bounds.height - delta
        } else {
          height = bounds.height + delta
        }
        winY = ry.option
      }
    }
  } else {
    // Alt bypass: drop any engaged hysteresis so snapping resumes fresh.
    clearSnapSession(session)
  }

  // Enforce minSize + slide bounds while preserving the fixed (non-dragged) edge.
  const cx = clampResizeAxis(x, width, slide.width, minSize, edges.xEdge === 'left' ? 'min' : 'max')
  const cy = clampResizeAxis(y, height, slide.height, minSize, edges.yEdge === 'top' ? 'min' : 'max')

  const result: ResizeSnapResult = {
    x: cx.pos,
    y: cy.pos,
    width: cx.size,
    height: cy.size,
    guides: []
  }

  const finalRect: Bounds = { x: result.x, y: result.y, width: result.width, height: result.height }

  // A minSize/slide clamp may have moved the dragged edge off the candidate
  // position (e.g. height floored to minSize). A guide would then lie about
  // where the edge actually is, so only emit it when the final edge matches.
  if (winX) {
    const edgePos = edges.xEdge === 'left' ? finalRect.x : finalRect.x + finalRect.width
    if (Math.abs(edgePos - winX.guide.position) <= GUIDE_EPS) {
      result.guides.push(refreshGuide(winX, finalRect, slide))
    }
  }
  if (winY) {
    const edgePos = edges.yEdge === 'top' ? finalRect.y : finalRect.y + finalRect.height
    if (Math.abs(edgePos - winY.guide.position) <= GUIDE_EPS) {
      result.guides.push(refreshGuide(winY, finalRect, slide))
    }
  }

  return result
}

export function clampMove(bounds: Bounds, slide: SlideBounds): Bounds {
  return clampBoundsToSlide(bounds, slide)
}