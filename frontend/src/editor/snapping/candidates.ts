import type { SlideBounds, SnapCandidate } from './types'

/**
 * Collect static snapping candidates at drag-start time.
 *
 * - Slide itself contributes left/center/right and top/center/bottom anchors.
 * - Sibling top-level elements contribute their whole axis-aligned bounds.
 *   Groups are treated as a single bounding box (no nested group traversal).
 * - The moving element is always excluded to avoid self-snapping.
 */
export function collectSlideCandidates(slide: SlideBounds): SnapCandidate[] {
  return [
    { id: '__slide__', bounds: { x: 0, y: 0, width: slide.width, height: slide.height } }
  ]
}

export function collectElementCandidates(
  elements: ReadonlyArray<{ id: string; x: number; y: number; width: number; height: number }>,
  movingIds: string | ReadonlyArray<string>
): SnapCandidate[] {
  const excluded = new Set(typeof movingIds === 'string' ? [movingIds] : movingIds)
  const result: SnapCandidate[] = []
  for (const el of elements) {
    if (excluded.has(el.id)) continue
    result.push({
      id: el.id,
      bounds: { x: el.x, y: el.y, width: el.width, height: el.height }
    })
  }
  return result
}

export function collectSnapCandidates(
  slide: SlideBounds,
  siblingElements: ReadonlyArray<{ id: string; x: number; y: number; width: number; height: number }>,
  movingIds: string | ReadonlyArray<string>
): SnapCandidate[] {
  return [...collectSlideCandidates(slide), ...collectElementCandidates(siblingElements, movingIds)]
}