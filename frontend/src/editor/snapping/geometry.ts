import type { Bounds, ElementAnchors, SlideBounds } from './types'

export function getBoundsAnchors(bounds: Bounds): ElementAnchors {
  return {
    left: bounds.x,
    centerX: bounds.x + bounds.width / 2,
    right: bounds.x + bounds.width,
    top: bounds.y,
    centerY: bounds.y + bounds.height / 2,
    bottom: bounds.y + bounds.height
  }
}

/**
 * Clamp a raw bounds rect so it always stays fully inside the slide.
 * Guarantees: 0 <= x, 0 <= y, x + width <= slide.width, y + height <= slide.height,
 * and non-negative width/height.
 */
export function clampBoundsToSlide(bounds: Bounds, slide: SlideBounds): Bounds {
  const width = Math.min(slide.width, Math.max(0, bounds.width))
  const height = Math.min(slide.height, Math.max(0, bounds.height))
  const maxX = Math.max(0, slide.width - width)
  const maxY = Math.max(0, slide.height - height)
  const x = Math.max(0, Math.min(bounds.x, maxX))
  const y = Math.max(0, Math.min(bounds.y, maxY))
  return { x, y, width, height }
}

export interface SlideViewport {
  /** Uniform screen->slide scale (slide units per screen px). */
  scale: number
  /** Horizontal letterbox bar width in screen px (0 when aspects match). */
  offsetX: number
  /** Vertical letterbox bar height in screen px (0 when aspects match). */
  offsetY: number
}

/**
 * Resolve how the slide maps into the canvas box under SVG
 * `preserveAspectRatio="xMidYMid meet"` semantics: uniform scale fit,
 * centered, with letterbox bars when the aspects differ.
 *
 * Because getBoundingClientRect() already includes the CSS transform
 * scale(zoom), the resulting scale absorbs zoom — never multiply by zoom
 * again or it gets applied twice.
 */
export function getSlideViewport(
  canvasRect: { width: number; height: number },
  slide: SlideBounds
): SlideViewport {
  const scale = Math.min(canvasRect.width / slide.width, canvasRect.height / slide.height)
  return {
    scale,
    offsetX: (canvasRect.width - slide.width * scale) / 2,
    offsetY: (canvasRect.height - slide.height * scale) / 2
  }
}

/**
 * Convert a point in screen (client) coordinates into slide coordinates,
 * accounting for CSS zoom and meet-letterboxing.
 */
export function screenToSlidePoint(
  clientX: number,
  clientY: number,
  canvasRect: { left: number; top: number; width: number; height: number },
  slide: SlideBounds
): { x: number; y: number } {
  const vp = getSlideViewport(canvasRect, slide)
  return {
    x: (clientX - canvasRect.left - vp.offsetX) / vp.scale,
    y: (clientY - canvasRect.top - vp.offsetY) / vp.scale
  }
}

/**
 * Convert a screen-space pixel delta into slide units, using the scaled
 * canvas rect so that zoom is accounted for automatically.
 */
export function screenDeltaToSlideDelta(
  dx: number,
  dy: number,
  canvasRect: { width: number; height: number },
  slide: SlideBounds
): { dx: number; dy: number } {
  const vp = getSlideViewport(canvasRect, slide)
  return { dx: dx / vp.scale, dy: dy / vp.scale }
}

/**
 * Convert a screen-space pixel distance (px) into slide units.
 * Uses the uniform meet scale, so thresholds behave consistently across
 * 50% / 100% / 200% zoom on both axes and for any slide aspect.
 */
export function screenPxToSlideUnits(
  screenPx: number,
  canvasRect: { width: number; height: number },
  slide: SlideBounds
): number {
  return screenPx / getSlideViewport(canvasRect, slide).scale
}

/** The slide-units distance between an element anchor position and a candidate anchor position. */
export function absDelta(a: number, b: number): number {
  return Math.abs(a - b)
}