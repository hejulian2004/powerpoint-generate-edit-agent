/**
 * Mirror of backend/design/tokens.py.
 * Radius is pixels. 0 is a sharp corner.
 */
export const MAX_CARD_RADIUS = 3

export const SHADOW_DX = 2
export const SHADOW_DY = 4
export const SHADOW_STD_DEVIATION = 4
export const SHADOW_FLOOD_OPACITY = 0.15

export function clampRadius(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0
  return Math.min(MAX_CARD_RADIUS, value)
}
