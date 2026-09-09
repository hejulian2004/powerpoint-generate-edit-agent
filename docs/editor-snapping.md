# Editor Snapping & Smart Guides

PowerPoint-style manual drag/resize snapping for the slide canvas. This is a
**frontend-only deterministic geometry system**. It is deliberately separate
from the Agent auto-layout path (`optimize_layout` / Smart Alignment button).

## Architecture

```
Mouse drag (mouseDown)
  -> screen delta
  -> screenDeltaToSlideDelta  (slide.width / canvasRect.width, zoom-safe)
  -> raw bounds
  -> clampBoundsToSlide       (pre-clamp)
  -> snapMove / snapResize    (pure geometry, no React/Zustand/DOM)
  -> snapped bounds + guides
  -> local target mutation + setTick re-render
  -> setAlignmentGuides       (SlideCanvas local state only)
  -> mouseup: single updateElementDirect()  (one backend mutation = one history record)
```

### Modules (`frontend/src/editor/snapping/`)

- `types.ts` — `Bounds`, `ElementAnchors`, `SnapGuide`, `SnapGuideKind`,
  `SnapResult`, `ResizeSnapResult`, `SnapCandidate`, `ActiveSnap`,
  `SnapSession`, `ResizeHandle`.
- `geometry.ts` — `getBoundsAnchors`, `clampBoundsToSlide`,
  `screenToSlidePoint`, `screenDeltaToSlideDelta`, `screenPxToSlideUnits`.
- `candidates.ts` — `collectSnapCandidates` (slide + top-level siblings,
  groups as one bounding box, moving element excluded).
- `snapEngine.ts` — `snapMove`, `snapResize`, hysteresis session, deterministic
  anchor-pair comparator. Exports `SNAP_SCREEN_PX = 6`, `RELEASE_SCREEN_PX = 10`.
- `guideStyle.ts` — pure `SnapGuide -> SVG stroke` mapping
  (slide-center solid, element guides `6 4` dashed, `#FF4D8D`).
- `snapEngine.test.ts` — 64 Vitest unit tests.

Rendering lives in `frontend/src/components/AlignmentGuides.tsx`, fed by an
optional `alignmentGuides` prop on `SVGRendererComponent` so guides share the
same SVG viewBox / slide coordinate space (aligned at 50%/100%/200% zoom).
`vectorEffect="non-scaling-stroke"` keeps the on-screen stroke width constant
across zoom levels.

## Coordinate model

The canvas uses `aspect-video` with CSS `transform: scale(zoom)`.
`getBoundingClientRect()` therefore returns the **post-transform** box, so the
slide mapping already includes zoom. Never multiply by `zoom` again or the
scale is applied twice. All slide dimensions come from
`slide.width / slide.height`; the old hardcoded `1280 x 720` values in
`SlideCanvas.tsx` were removed.

Because the stage SVG renders with `preserveAspectRatio="xMidYMid meet"`,
`geometry.ts` resolves a uniform meet viewport (`getSlideViewport`):
uniform fit scale plus centered letterbox offsets. Screen→slide conversion
subtracts the bar offsets before dividing by the uniform scale, so drop
placement, drag deltas, and thresholds stay exact even for non-16:9 slides:

```
viewport.scale   = min(rect.width / slide.width, rect.height / slide.height)
viewport.offsetX = (rect.width  - slide.width  * scale) / 2
viewport.offsetY = (rect.height - slide.height * scale) / 2
```

## Snap candidates

Collected **once at drag start** (`mouseDown`) and stored in `DragState`:

- Slide itself: left / centerX / right, top / centerY / bottom.
- Top-level sibling elements (whole axis-aligned bounds).
- Groups count as one whole bounding box; nested children are never separate
  candidates (no nested group editing mode).
- `candidate.id === movingElement.id` is always excluded.

`mousemove` then only compares against the pre-computed list (O(n) scan).

## Threshold & hysteresis

Thresholds are screen-space, converted per-frame via the uniform meet scale,
identical on both axes:

```
enterThreshold   = 6  screen px -> slide units
releaseThreshold = 10 screen px -> slide units
```

Per axis, a `SnapSession` (`activeSnapX` / `activeSnapY`, held in a `useRef`)
keeps a snap engaged while `distance <= release`, breaking only beyond it.
This prevents boundary oscillation (5.9 snap / 6.1 unsnap / 5.8 snap).

## Move vs resize

- `snapMove` compares the moving element's 3 X-anchors x 3 candidate anchors
  (left->left, left->right, center->center, right->right, right->left) and the
  matching Y set, resolving X and Y independently. Snap options that would
  push the element outside the slide are ignored, so returned geometry is
  always in-bounds and every guide is truthful.
- `snapResize` only snaps the dragged edge: East->right edge, West->left,
  North->top, South->bottom; corner handles resolve both axes. Enforces
  `minSize = 24` and slide bounds via an edge-aware clamp that preserves the
  non-dragged (fixed) edge — minSize flooring moves the dragged edge, never
  the opposite one. The clamp runs even when snapping is disabled
  (`Alt + Drag`), so geometry can never collapse to 0. If the clamp moves the
  dragged edge off the candidate position, that axis's guide is dropped rather
  than drawn at a position the edge does not reach.
- Clamp order: `pre-clamp -> snap -> final clamp (inside snapResize)`. Geometry
  stays fractional end-to-end so the committed IR coordinate equals the guide
  position exactly; rounding happens only in display formatting, never in
  geometry.

Deterministic tie-break for equal distances: nearest first, then priority
`slide-center < element-center < element-edge < slide-edge`, then candidate
key. No dependence on element array order.

## Move flow / resize flow / commit

- `drag start`: capture `initialElem`, screen start, collect candidates, reset
  `SnapSession`.
- `mousemove`: raw -> pre-clamp -> snap -> write `target.x/y(/w/h)` local
  object + `setTick` -> `setAlignmentGuides` (local state, never Zustand,
  never WebSocket, never LLM). `Alt` held -> snapping + guides off, boundary
  clamp still applies.
- `mouseup`: read final snapped geometry -> **one** `updateElementDirect()`
  -> clear guides, session, drag state.

Because `updateElementDirect` (`direct_update_element` -> `update_element` ->
`history.record`) fires exactly once per drag, one drag = one undo step, and
the committed coordinates are exactly the snapped coordinates that also flow
into PPTX export.

## Store & toolbar

- `snapEnabled` (default `true`) and `showSmartGuides` (default `true`) in
  `usePPTStore`; `showGrid` stays an independent visual-only toggle.
- Toolbar adds a Magnet snap toggle and a 辅助线 guides toggle. The existing
  智能对齐 (Agent auto-layout) button is untouched — the two paths coexist:
  manual geometry vs AI layout.

## Validation

```bash
cd frontend
npm run test    # vitest run — 64 engine tests
npm run lint    # oxlint
npm run build   # tsc -b && vite build
```

## Known limitations

- Rotated elements snap using their IR axis-aligned bounds (no OBB/SAT or
  rotation-aware snapping).
- Nested group editing is not implemented; groups participate as a single
  sibling bounding box.
- Connector endpoint magnetic attachment / connection-site engine is out of
  scope; connectors snap as ordinary whole bounds when they have x/y/w/h.
- Equal-spacing (gap-equality) smart guides are deferred; the `spacing` guide
  kind is already present in `SnapGuideKind` and styled, but no engine produces
  such guides yet.
- Keyboard arrow-nudge was deferred to keep this change minimal.
