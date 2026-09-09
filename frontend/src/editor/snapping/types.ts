export interface Bounds {
  x: number
  y: number
  width: number
  height: number
}

export interface SlideBounds {
  width: number
  height: number
}

export interface ElementAnchors {
  left: number
  centerX: number
  right: number
  top: number
  centerY: number
  bottom: number
}

export type SnapAxis = 'x' | 'y'

export type SnapGuideKind =
  | 'slide-center'
  | 'slide-edge'
  | 'element-edge'
  | 'element-center'
  | 'spacing'

export interface SnapGuide {
  axis: SnapAxis
  position: number
  start: number
  end: number
  kind: SnapGuideKind
  sourceElementId?: string
  targetElementId?: string
  label?: string
}

export interface SnapResult {
  x: number
  y: number
  guides: SnapGuide[]
  snappedX: boolean
  snappedY: boolean
  snapXKey?: string
  snapYKey?: string
}

export interface ResizeSnapResult {
  x: number
  y: number
  width: number
  height: number
  guides: SnapGuide[]
}

export type AnchorX = 'left' | 'centerX' | 'right'
export type AnchorY = 'top' | 'centerY' | 'bottom'

export interface SnapCandidate {
  id: string
  bounds: Bounds
}

/**
 * Per-axis active snap identity used for hysteresis.
 * While a snap is engaged we allow the delta to grow up to the
 * release threshold before breaking the snap.
 */
export interface ActiveSnap {
  key: string
  guide: SnapGuide
}

export interface SnapSession {
  activeSnapX?: ActiveSnap
  activeSnapY?: ActiveSnap
}

export interface SnapOptions {
  enabled: boolean
  enterThreshold: number
  releaseThreshold: number
  session?: SnapSession
}

export interface AxisThreshold {
  enter: number
  release: number
}

export interface SnapThresholds {
  x: AxisThreshold
  y: AxisThreshold
}

export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'