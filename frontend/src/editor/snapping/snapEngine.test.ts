import { describe, it, expect } from 'vitest'
import { snapMove, snapResize, clampMove, clampResizeAxis, clearSnapSession, SNAP_SCREEN_PX, RELEASE_SCREEN_PX } from './snapEngine'
import { screenPxToSlideUnits, screenDeltaToSlideDelta, screenToSlidePoint, getSlideViewport, clampBoundsToSlide, getBoundsAnchors } from './geometry'
import { collectSnapCandidates, collectElementCandidates, collectSlideCandidates } from './candidates'
import { guideStrokeStyle, isSlideGuide } from './guideStyle'
import type { Bounds, SlideBounds, SnapCandidate, SnapSession, SnapThresholds } from './types'

const SLIDE: SlideBounds = { width: 1280, height: 720 }

// Helper: build slide-unit thresholds from a screen-space pixel distance and a
// scaled canvas box, matching the runtime computation.
function thresholdFor(screenPx: number, canvasWidth: number, canvasHeight: number, slide = SLIDE) {
  return screenPxToSlideUnits(screenPx, { width: canvasWidth, height: canvasHeight }, slide)
}

function newSession(): SnapSession {
  return {}
}

function cand(id: string, x: number, y: number, width: number, height: number): SnapCandidate {
  return { id, bounds: { x, y, width, height } }
}

// At 50% zoom: canvasRect 640x360 for a 1280x720 slide => 2 slide units per screen px.
const ENTER_50 = thresholdFor(SNAP_SCREEN_PX, 640, 360)
const RELEASE_50 = thresholdFor(RELEASE_SCREEN_PX, 640, 360)
const T50: SnapThresholds = {
  x: { enter: ENTER_50, release: RELEASE_50 },
  y: { enter: ENTER_50, release: RELEASE_50 }
}

describe('X snapping (move)', () => {
  const target = cand('B', 200, 100, 100, 80)
  const candidates = [target]

  it('left-left', () => {
    const b: Bounds = { x: 205, y: 0, width: 60, height: 40 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(200)
    expect(r.snappedX).toBe(true)
    expect(r.snapXKey).toContain('left->left')
  })

  it('center-center', () => {
    const near = { x: 240, y: 0, width: 20, height: 40 } // centerX = 250 exactly
    const r = snapMove(near, candidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
    // center-center wins by distance 0.
    expect(r.snapXKey).toContain('centerX->centerX')
    expect(r.x).toBe(240)
  })

  it('right-right', () => {
    // target.right = 300. moving right = x+60. Want |x+60-300| <= 12 => x in [228, 252]
    const b: Bounds = { x: 235, y: 0, width: 60, height: 40 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
    expect(r.x + 60).toBe(300)
    expect(r.snapXKey).toContain('right->right')
  })

  it('right-left', () => {
    // moving.right snaps to target.left=200. x+60 -> 200 => x=140
    const b: Bounds = { x: 145, y: 0, width: 60, height: 40 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
    expect(r.x + 60).toBe(200)
    expect(r.snapXKey).toContain('right->left')
  })

  it('left-right', () => {
    // moving.left snaps to target.right=300 => x=300
    const b: Bounds = { x: 305, y: 0, width: 60, height: 40 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
    expect(r.x).toBe(300)
    expect(r.snapXKey).toContain('left->right')
  })
})

describe('Y snapping (move)', () => {
  const target = cand('B', 0, 200, 100, 80)
  const candidates = [target]

  it('top-top', () => {
    const b: Bounds = { x: 0, y: 205, width: 40, height: 30 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.y).toBe(200)
    expect(r.snapYKey).toContain('top->top')
  })

  it('middle-middle', () => {
    // target centerY = 240. moving centerY = y+15. want y+15=240 => y=225
    const b: Bounds = { x: 0, y: 230, width: 40, height: 30 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.y + 15).toBe(240)
    expect(r.snapYKey).toContain('centerY->centerY')
  })

  it('bottom-bottom', () => {
    // target.bottom = 280. moving bottom = y+30. y+30=280 => y=250
    const b: Bounds = { x: 0, y: 255, width: 40, height: 30 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.y + 30).toBe(280)
    expect(r.snapYKey).toContain('bottom->bottom')
  })

  it('bottom-top', () => {
    // moving.bottom snaps to target.top=200. y+30=200 => y=170
    const b: Bounds = { x: 0, y: 175, width: 40, height: 30 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.y + 30).toBe(200)
    expect(r.snapYKey).toContain('bottom->top')
  })

  it('top-bottom', () => {
    // moving.top snaps to target.bottom=280 => y=280
    const b: Bounds = { x: 0, y: 285, width: 40, height: 30 }
    const r = snapMove(b, candidates, SLIDE, newSession(), T50, true)
    expect(r.y).toBe(280)
    expect(r.snapYKey).toContain('top->bottom')
  })
})

describe('Slide snapping', () => {
  const slideCandidates = collectSlideCandidates(SLIDE)
  const b: Bounds = { x: 0, y: 0, width: 80, height: 50 }

  it('slide left', () => {
    const r = snapMove({ ...b, x: 5 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(0)
  })

  it('slide horizontal center', () => {
    const r = snapMove({ ...b, y: 300, x: 595 }, slideCandidates, SLIDE, newSession(), T50, true)
    // centerX=595+40=635, slide center=640, delta=5 < 12
    expect(r.x).toBe(600)
    const xGuide = r.guides.find((g) => g.axis === 'x')
    expect(xGuide?.kind).toBe('slide-center')
  })

  it('slide right', () => {
    const r = snapMove({ ...b, x: 1195 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(1200)
  })

  it('slide top', () => {
    const r = snapMove({ ...b, y: 6 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.y).toBe(0)
  })

  it('slide vertical center', () => {
    const r = snapMove({ ...b, x: 300, y: 330 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.y).toBe(335)
    const yGuide = r.guides.find((g) => g.axis === 'y')
    expect(yGuide?.kind).toBe('slide-center')
  })

  it('slide bottom', () => {
    const r = snapMove({ ...b, y: 665 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.y).toBe(670)
  })
})

describe('Threshold (enter / no-snap)', () => {
  const slideCandidates = collectSlideCandidates(SLIDE)

  it('inside threshold -> snap', () => {
    const r = snapMove({ x: 5, y: 0, width: 80, height: 50 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
  })

  it('outside threshold -> no snap', () => {
    // x=40 => delta 40 > 12
    const r = snapMove({ x: 40, y: 0, width: 80, height: 50 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(false)
    expect(r.x).toBe(40)
  })

  it('snap that would push the element out of slide is ignored', () => {
    // Wide moving element (w=300) at the right edge: aligning left->sibling
    // left (985, dist 5, within enter) would put right at 1285, outside the
    // 1280 slide. The option is ignored; geometry and guides stay put.
    // (Element-only candidates isolate the filter from the slide-right anchor.)
    const sibling = cand('EDGE', 985, 100, 50, 60)
    const r = snapMove(
      { x: 980, y: 100, width: 300, height: 60 },
      [sibling],
      SLIDE,
      newSession(),
      T50,
      true
    )
    expect(r.snappedX).toBe(false)
    expect(r.x).toBe(980)
    expect(r.guides.filter((g) => g.axis === 'x')).toHaveLength(0)
  })
})

describe('Hysteresis', () => {
  const slideCandidates = collectSlideCandidates(SLIDE)
  // enter=12, release=20 (50% zoom)

  it('enter at 6 screen px, hold until 10, release > 10', () => {
    // At 50%, 6 screen px = 12 slide units. Simulate moving from far to near.
    const session = newSession()
    // First frame just inside enter threshold (delta 10 slide units => 5 screen px).
    let r = snapMove({ x: 10, y: 0, width: 80, height: 50 }, slideCandidates, SLIDE, session, T50, true)
    expect(r.snappedX).toBe(true)
    // Now grow delta beyond enter (15 slide units = 7.5 screen px) but below release (20).
    // Same frame position to reuse session state: delta 15.
    r = snapMove({ x: 15, y: 0, width: 80, height: 50 }, slideCandidates, SLIDE, session, T50, true)
    expect(r.snappedX).toBe(true) // still engaged via hysteresis
    // Grow to just under release (19) still snapped.
    r = snapMove({ x: 19, y: 0, width: 80, height: 50 }, slideCandidates, SLIDE, session, T50, true)
    expect(r.snappedX).toBe(true)
    // Exceed release (21) => releases.
    r = snapMove({ x: 21, y: 0, width: 80, height: 50 }, slideCandidates, SLIDE, session, T50, true)
    expect(r.snappedX).toBe(false)
    expect(r.x).toBe(21)
  })
})

describe('Independent axis', () => {
  const slideCandidates = collectSlideCandidates(SLIDE)

  it('X snap only', () => {
    const r = snapMove({ x: 5, y: 300, width: 80, height: 50 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
    expect(r.snappedY).toBe(false)
    expect(r.y).toBe(300)
  })

  it('Y snap only', () => {
    const r = snapMove({ x: 300, y: 5, width: 80, height: 50 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(false)
    expect(r.snappedY).toBe(true)
    expect(r.x).toBe(300)
  })

  it('X + Y simultaneous', () => {
    const r = snapMove({ x: 5, y: 5, width: 80, height: 50 }, slideCandidates, SLIDE, newSession(), T50, true)
    expect(r.snappedX).toBe(true)
    expect(r.snappedY).toBe(true)
    expect(r.guides.length).toBe(2)
  })

  it('element guide span tracks the snapped bounds, not pre-snap bounds', () => {
    // X snaps left 306->300 and Y snaps bottom 120->130 (bottom->bottom wins
    // the dist-10 tie by key order). The X guide span must use snapped y
    // (100..130): start = 100-12 = 88 (pre-snap would give 90-12 = 78).
    const target = cand('B', 300, 100, 200, 30)
    const r = snapMove(
      { x: 306, y: 90, width: 30, height: 30 },
      [...slideCandidates, target],
      SLIDE,
      newSession(),
      T50,
      true
    )
    expect(r.x).toBe(300)
    expect(r.y).toBe(100)
    const xGuide = r.guides.find((g) => g.axis === 'x')
    expect(xGuide?.position).toBe(300)
    expect(xGuide?.start).toBe(88)
    expect(xGuide?.end).toBe(142)
  })
})

describe('Candidate collection', () => {
  const sibling = { id: 'A', x: 0, y: 0, width: 100, height: 60 }
  const group = { id: 'G', x: 300, y: 100, width: 200, height: 120 }
  const moving = { id: 'M', x: 50, y: 50, width: 40, height: 40 }

  it('moving element excluded', () => {
    const c = collectElementCandidates([sibling, moving], 'M')
    expect(c.map((x) => x.id)).toEqual(['A'])
  })

  it('slide candidates built', () => {
    const c = collectSlideCandidates(SLIDE)
    expect(c).toHaveLength(1)
    expect(c[0].bounds.width).toBe(1280)
    expect(c[0].bounds.height).toBe(720)
  })

  it('group treated as one sibling bounding box', () => {
    const c = collectElementCandidates([sibling, group], 'M')
    expect(c.map((x) => x.id)).toEqual(['A', 'G'])
    const g = c.find((x) => x.id === 'G')
    expect(g?.bounds.width).toBe(200)
    expect(g?.bounds.height).toBe(120)
  })

  it('snap to group bbox left', () => {
    const candidates = collectSnapCandidates(SLIDE, [group], 'M')
    const r = snapMove({ x: 306, y: 120, width: 30, height: 30 }, candidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(300)
    expect(r.snapXKey).toContain('G:left->left')
  })
})

describe('Resize snapping', () => {
  const slideCandidates = collectSlideCandidates(SLIDE)
  const target = cand('B', 400, 300, 100, 80)
  const candidates = [...slideCandidates, target]

  it('east: right edge snaps to target.left', () => {
    // base right = 320. target.left = 400. want right -> 400. delta = 80 (too far).
    // Instead start base such that right is near 400.
    const near: Bounds = { x: 290, y: 200, width: 120, height: 90 } // right=410, delta 10 < 12
    const r = snapResize(near, 'e', candidates, SLIDE, newSession(), T50, true)
    expect(r.width).toBe(400 - near.x) // right snapped to 400
    expect(r.x).toBe(near.x)
  })

  it('west: left edge snaps to target.left, width shrinks', () => {
    const near: Bounds = { x: 405, y: 200, width: 120, height: 90 } // left=405 near target.left 400, delta 5
    const r = snapResize(near, 'w', candidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(400)
    expect(r.width).toBe(near.x + near.width - 400)
  })

  it('north: top snaps to target.top', () => {
    const near: Bounds = { x: 200, y: 305, width: 120, height: 90 } // top=305 near 300
    const r = snapResize(near, 'n', candidates, SLIDE, newSession(), T50, true)
    expect(r.y).toBe(300)
    expect(r.height).toBe(near.y + near.height - 300)
  })

  it('south: bottom snaps to target.bottom', () => {
    // target.bottom = 380. near.bottom = y+90 near 380 => y ~ 285
    const near: Bounds = { x: 200, y: 285, width: 120, height: 90 } // bottom=375, delta 5
    const r = snapResize(near, 's', candidates, SLIDE, newSession(), T50, true)
    expect(r.height).toBe(380 - near.y)
    expect(r.y).toBe(near.y)
  })

  it('corner ne: right + top snap', () => {
    const near: Bounds = { x: 290, y: 305, width: 120, height: 90 } // right=410 near 400, top=305 near 300
    const r = snapResize(near, 'ne', candidates, SLIDE, newSession(), T50, true)
    expect(r.width).toBe(400 - r.x)
    expect(r.height).toBe(near.y + near.height - 300)
    expect(r.y).toBe(300)
  })

  it('corner sw: left + bottom snap', () => {
    const near: Bounds = { x: 405, y: 285, width: 120, height: 90 } // left=405 near 400, bottom=375 near 380
    const r = snapResize(near, 'sw', candidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(400)
    expect(r.height).toBe(380 - near.y)
  })

  it('corner nw: left + top snap', () => {
    const near: Bounds = { x: 405, y: 305, width: 120, height: 90 }
    const r = snapResize(near, 'nw', candidates, SLIDE, newSession(), T50, true)
    expect(r.x).toBe(400)
    expect(r.y).toBe(300)
  })

  it('corner se: right + bottom snap', () => {
    const near: Bounds = { x: 290, y: 285, width: 120, height: 90 }
    const r = snapResize(near, 'se', candidates, SLIDE, newSession(), T50, true)
    expect(r.width).toBe(400 - near.x)
    expect(r.height).toBe(380 - near.y)
  })

  it('east respects minSize', () => {
    const tiny: Bounds = { x: 200, y: 200, width: 20, height: 90 } // right=220
    // Even if it tried to snap near 400, width stays >= minSize.
    const r = snapResize(tiny, 'e', candidates, SLIDE, newSession(), T50, true, 24)
    expect(r.width).toBeGreaterThanOrEqual(24)
  })

  it('north keeps height >= minSize and preserves the fixed bottom edge', () => {
    // Target top (110) sits 10 below the moving top (100), within the enter
    // threshold, so height would collapse to 20 -> minSize floors it at 24
    // while the fixed bottom edge (130) stays put: y = 130 - 24 = 106.
    const anchor = cand('C', 500, 110, 100, 32) // top = 110
    const r = snapResize({ x: 200, y: 100, width: 120, height: 30 }, 'n', [...candidates, anchor], SLIDE, newSession(), T50, true, 24)
    expect(r.y).toBe(106)
    expect(r.height).toBe(24)
    expect(r.y + r.height).toBe(130)
  })

  it('drops the guide when minSize flooring moves the dragged edge off target', () => {
    // Same setup as above: top snaps 100 -> 110 but minSize floors the edge
    // back to 106. The guide at 110 would lie, so no Y guide is emitted.
    const anchor = cand('C', 500, 110, 100, 32) // top = 110
    const r = snapResize({ x: 200, y: 100, width: 120, height: 30 }, 'n', [...candidates, anchor], SLIDE, newSession(), T50, true, 24)
    expect(r.guides.filter((g) => g.axis === 'y')).toHaveLength(0)
  })

  it('keeps the guide when the snapped edge lands exactly on target', () => {
    // North snap top 305 -> 300 with room to spare: edge matches, guide stays.
    const r = snapResize({ x: 200, y: 305, width: 120, height: 90 }, 'n', candidates, SLIDE, newSession(), T50, true, 24)
    expect(r.y).toBe(300)
    expect(r.guides.filter((g) => g.axis === 'y')).toHaveLength(1)
  })

  it('west minSize flooring preserves the fixed right edge', () => {
    // Moving left (100) snaps 10 right to target left (110); width would
    // collapse 30 -> 20, floored at 24 with the right edge (130) fixed.
    const anchor = cand('C', 110, 200, 60, 60) // left = 110
    const r = snapResize({ x: 100, y: 200, width: 30, height: 60 }, 'w', [...candidates, anchor], SLIDE, newSession(), T50, true, 24)
    expect(r.x).toBe(106)
    expect(r.width).toBe(24)
    expect(r.x + r.width).toBe(130)
  })

  it('east clamp keeps x fixed and shrinks width to fit the slide', () => {
    // Right edge dragged far past the slide: x stays, width fits the slide.
    const r = snapResize({ x: 1200, y: 100, width: 500, height: 60 }, 'e', candidates, SLIDE, newSession(), T50, true, 24)
    expect(r.x).toBe(1200)
    expect(r.width).toBe(80)
  })

  it('snapResize with enabled=false preserves minSize and clamps without snapping', () => {
    // Alt + Drag: snapping is disabled (enabled=false), but minSize and slide
    // bounds must still be strictly enforced without collapsing to 0 or shifting fixed edge.
    const rEast = snapResize({ x: 100, y: 100, width: 5, height: 50 }, 'e', candidates, SLIDE, newSession(), T50, false, 24)
    expect(rEast.x).toBe(100)
    expect(rEast.width).toBe(24)
    expect(rEast.guides).toHaveLength(0)

    const rSouth = snapResize({ x: 100, y: 100, width: 50, height: -10 }, 's', candidates, SLIDE, newSession(), T50, false, 24)
    expect(rSouth.y).toBe(100)
    expect(rSouth.height).toBe(24)
    expect(rSouth.guides).toHaveLength(0)

    const rWest = snapResize({ x: 100, y: 100, width: 10, height: 50 }, 'w', candidates, SLIDE, newSession(), T50, false, 24)
    // Fixed right edge is 100 + 10 = 110. Min size 24 => x = 110 - 24 = 86.
    expect(rWest.x).toBe(86)
    expect(rWest.width).toBe(24)
    expect(rWest.x + rWest.width).toBe(110)
    expect(rWest.guides).toHaveLength(0)
  })

  it('clampResizeAxis preserves fixed edges correctly', () => {
    // Min edge (west/north): far edge is 100 + 10 = 110. Clamped size 24 => pos = 110 - 24 = 86.
    const cMin = clampResizeAxis(100, 10, 1280, 24, 'min')
    expect(cMin.pos).toBe(86)
    expect(cMin.size).toBe(24)

    // Max edge (east/south): near edge is fixed at 100. Clamped size 24 => pos stays 100.
    const cMax = clampResizeAxis(100, 10, 1280, 24, 'max')
    expect(cMax.pos).toBe(100)
    expect(cMax.size).toBe(24)
  })
})

describe('Geometry clamps', () => {
  it('clampBoundsToSlide keeps in-bounds', () => {
    const r = clampBoundsToSlide({ x: -50, y: -30, width: 100, height: 50 }, SLIDE)
    expect(r.x).toBe(0)
    expect(r.y).toBe(0)
  })

  it('clampBoundsToSlide limits far right/bottom', () => {
    const r = clampBoundsToSlide({ x: 1300, y: 800, width: 100, height: 50 }, SLIDE)
    expect(r.x).toBe(1180)
    expect(r.y).toBe(670)
  })

  it('clampMove wraps clampBoundsToSlide', () => {
    const r = clampMove({ x: -10, y: 0, width: 50, height: 50 }, SLIDE)
    expect(r.x).toBe(0)
  })

  it('no negative width/height after clamp', () => {
    const r = clampBoundsToSlide({ x: 10, y: 10, width: -30, height: -20 }, SLIDE)
    expect(r.width).toBe(0)
    expect(r.height).toBe(0)
  })
})

describe('Scale (screen-space threshold consistency)', () => {
  // Same 6 screen-px threshold at 50%, 100%, 200% zoom.
  it('computes equivalent slide-unit thresholds', () => {
    expect(thresholdFor(SNAP_SCREEN_PX, 640, 360)).toBe(12)
    expect(thresholdFor(SNAP_SCREEN_PX, 1280, 720)).toBe(6)
    expect(thresholdFor(SNAP_SCREEN_PX, 2560, 1440)).toBe(3)
  })

  it('uses the uniform meet scale for non-16:9 canvas boxes', () => {
    // A tall canvas box (640x720) letterboxes a 16:9 slide: the fit is driven
    // by width (scale 0.5), so 6 screen px map to 12 slide units on both axes.
    expect(thresholdFor(SNAP_SCREEN_PX, 640, 720)).toBe(12)
  })

  it('getSlideViewport centers letterboxed content with side bars', () => {
    const vp = getSlideViewport({ width: 640, height: 720 }, SLIDE)
    expect(vp.scale).toBe(0.5)
    expect(vp.offsetX).toBe(0)
    expect(vp.offsetY).toBe((720 - 720 * 0.5) / 2)
  })

  it('screenToSlidePoint subtracts letterbox bars', () => {
    // 640x720 box, 16:9 slide: 180px bars top/bottom, slide spans y 180..540.
    const p = screenToSlidePoint(320, 360, { left: 0, top: 0, width: 640, height: 720 }, SLIDE)
    expect(p.x).toBe(640)
    expect(p.y).toBe(360)
  })

  it('screenDeltaToSlideDelta scales correctly', () => {
    // 10 screen px at 50% zoom => 20 slide units
    const d50 = screenDeltaToSlideDelta(10, 10, { width: 640, height: 360 }, SLIDE)
    expect(d50.dx).toBe(20)
    const d100 = screenDeltaToSlideDelta(10, 10, { width: 1280, height: 720 }, SLIDE)
    expect(d100.dx).toBe(10)
    const d200 = screenDeltaToSlideDelta(10, 10, { width: 2560, height: 1440 }, SLIDE)
    expect(d200.dx).toBe(5)
  })
})

describe('Guide style mapping', () => {
  it('slide-center is solid', () => {
    const s = guideStrokeStyle('slide-center')
    expect(s.strokeDasharray).toBeUndefined()
  })

  it('element guide is dashed', () => {
    const s = guideStrokeStyle('element-edge')
    expect(s.strokeDasharray).toBe('6 4')
  })

  it('isSlideGuide', () => {
    expect(isSlideGuide({ axis: 'x', kind: 'slide-center', position: 0, start: 0, end: 10 })).toBe(true)
    expect(isSlideGuide({ axis: 'x', kind: 'element-edge', position: 0, start: 0, end: 10 })).toBe(false)
  })
})

describe('getBoundsAnchors', () => {
  it('computes all anchors', () => {
    const a = getBoundsAnchors({ x: 10, y: 20, width: 100, height: 50 })
    expect(a.left).toBe(10)
    expect(a.centerX).toBe(60)
    expect(a.right).toBe(110)
    expect(a.top).toBe(20)
    expect(a.centerY).toBe(45)
    expect(a.bottom).toBe(70)
  })
})

describe('Fractional-coordinate fidelity (float geometry must not be rounded)', () => {
  // IR allows fractional coordinates; snapping must preserve them so the guide
  // position equals the committed IR coordinate equals the exported coordinate.
  it('snapMove keeps fractional snapped.x and guide.position', () => {
    const target = cand('B', 312.5, 100, 100, 80)
    const b: Bounds = { x: 314.5, y: 0, width: 60, height: 40 }
    const r = snapMove(b, [target], SLIDE, newSession(), T50, true)
    expect(r.x).toBe(312.5)
    expect(r.guides).toHaveLength(1)
    expect(r.guides[0].position).toBe(312.5)
  })

  it('clampMove preserves fractional snapped coordinate', () => {
    const r = clampMove({ x: 312.5, y: 120.25, width: 60, height: 40 }, SLIDE)
    expect(r.x).toBe(312.5)
    expect(r.y).toBe(120.25)
  })

  it('snapResize east keeps fractional dragged right edge + guide', () => {
    // Target right edge at 500.25; moving element's right sits near it.
    const target = cand('B', 400.25, 100, 100, 80) // right = 500.25
    const b: Bounds = { x: 300, y: 50, width: 198.25, height: 60 } // right = 498.25
    const r = snapResize(b, 'e', [target], SLIDE, newSession(), T50, true)
    expect(r.x).toBe(300)
    expect(r.width).toBe(200.25)
    expect(r.x + r.width).toBe(500.25)
    expect(r.guides.some((g) => g.position === 500.25)).toBe(true)
  })

  it('snapResize west keeps fractional dragged left edge', () => {
    const target = cand('B', 100.5, 100, 100, 80)
    const b: Bounds = { x: 102.5, y: 50, width: 198, height: 60 }
    const r = snapResize(b, 'w', [target], SLIDE, newSession(), T50, true)
    expect(r.x).toBe(100.5)
    expect(r.width).toBe(200)
  })
})

describe('Oversized element clamp', () => {
  it('clampBoundsToSlide caps an oversized element to slide dimensions', () => {
    const r = clampBoundsToSlide({ x: -40, y: 100, width: 1500, height: 800 }, SLIDE)
    expect(r.x).toBe(0)
    expect(r.width).toBe(SLIDE.width)
    expect(r.height).toBe(SLIDE.height)
    expect(r.x + r.width).toBe(SLIDE.width)
    expect(r.y + r.height).toBe(SLIDE.height)
  })
})

describe('Alt bypass resets hysteresis before snapping resumes', () => {
  const target = cand('B', 100, 100, 100, 80)
  const candidates = [target]

  it('clears an engaged snap so re-entry uses ENTER not a stale RELEASE envelope', () => {
    const session = newSession()

    // Enter snap: moving left (95) within enter(12) of target.left(100).
    let r = snapMove({ x: 95, y: 200, width: 40, height: 50 }, candidates, SLIDE, session, T50, true)
    expect(r.snappedX).toBe(true)
    expect(r.x).toBe(100)

    // Alt bypass: enabled=false must drop the engaged activeSnapX.
    r = snapMove({ x: 116, y: 200, width: 40, height: 50 }, candidates, SLIDE, session, T50, false)
    expect(r.snappedX).toBe(false)

    // Alt released: moving.left is 16 away from 100 — within release(20) but
    // NOT within enter(12). Without a reset it would inherit the release
    // envelope and snap back; after reset it must stay unsnapped.
    r = snapMove({ x: 116, y: 200, width: 40, height: 50 }, candidates, SLIDE, session, T50, true)
    expect(r.snappedX).toBe(false)
  })

  it('clearSnapSession drops both axes', () => {
    const session: SnapSession = { activeSnapX: { key: 'a', guide: { axis: 'x', kind: 'element-edge', position: 0, start: 0, end: 1 } }, activeSnapY: { key: 'b', guide: { axis: 'y', kind: 'element-edge', position: 0, start: 0, end: 1 } } }
    clearSnapSession(session)
    expect(session.activeSnapX).toBeUndefined()
    expect(session.activeSnapY).toBeUndefined()
  })

  it('snapResize clears an engaged snap on bypass', () => {
    const session = newSession()
    snapMove({ x: 95, y: 200, width: 80, height: 50 }, candidates, SLIDE, session, T50, true)
    expect(session.activeSnapX).toBeDefined()

    const r = snapResize({ x: 95, y: 200, width: 80, height: 50 }, 'e', candidates, SLIDE, session, T50, false)
    expect(r.guides).toHaveLength(0)
    expect(session.activeSnapX).toBeUndefined()
    expect(session.activeSnapY).toBeUndefined()
  })
})

describe('Spacing guide kind', () => {
  it('maps the reserved spacing kind to a dashed style', () => {
    const s = guideStrokeStyle('spacing')
    expect(s.strokeDasharray).toBe('6 4')
  })

  it('isSlideGuide excludes spacing', () => {
    expect(isSlideGuide({ axis: 'x', kind: 'spacing', position: 0, start: 0, end: 10 })).toBe(false)
  })
})