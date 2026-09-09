import type { SnapGuide, SnapGuideKind } from './types'

export const GUIDE_COLOR = '#FF4D8D'
export const GUIDE_CENTER_WIDTH = 1.5
export const GUIDE_ELEMENT_WIDTH = 1.25

export interface GuideStrokeStyle {
  stroke: string
  strokeWidth: number
  strokeDasharray?: string
}

/**
 * Pure mapping from a snap guide to SVG stroke styling.
 * Slide-center guides render solid; element and spacing guides render dashed.
 */
export function guideStrokeStyle(kind: SnapGuideKind): GuideStrokeStyle {
  if (kind === 'slide-center') {
    return { stroke: GUIDE_COLOR, strokeWidth: GUIDE_CENTER_WIDTH }
  }
  return { stroke: GUIDE_COLOR, strokeWidth: GUIDE_ELEMENT_WIDTH, strokeDasharray: '6 4' }
}

export function isSlideGuide(guide: SnapGuide): boolean {
  return guide.kind === 'slide-center' || guide.kind === 'slide-edge'
}