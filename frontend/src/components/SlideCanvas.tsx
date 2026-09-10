import React, { useState, useRef, useEffect, useCallback } from 'react'
import {
  ZoomIn, ZoomOut, Maximize2, Trash2, Move,
  Edit3, Bold, Image as ImageIcon
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'
import { CanvasToolbar } from './CanvasToolbar'
import {
  screenDeltaToSlideDelta,
  screenPxToSlideUnits,
  screenToSlidePoint,
  clampBoundsToSlide
} from '../editor/snapping/geometry'
import { snapMove, snapResize, clampResizeAxis, SNAP_SCREEN_PX, RELEASE_SCREEN_PX } from '../editor/snapping/snapEngine'
import { collectSnapCandidates } from '../editor/snapping/candidates'
import type { Bounds, SnapCandidate, SnapGuide, SnapSession, SnapThresholds, ResizeHandle } from '../editor/snapping/types'

const MIN_SIZE = 24

interface DragState {
  mode: 'move' | 'resize'
  elemId: string
  startX: number
  startY: number
  initialElem: Bounds
  handle?: ResizeHandle
  snapCandidates: SnapCandidate[]
}

const safeHexColor = (col?: string, fallback = '#0F172A') => {
  if (!col) return fallback
  if (/^#[0-9A-Fa-f]{6}$/.test(col)) return col
  if (/^#[0-9A-Fa-f]{3}$/.test(col)) {
    return `#${col[1]}${col[1]}${col[2]}${col[2]}${col[3]}${col[3]}`
  }
  return fallback
}

export const SlideCanvas: React.FC = () => {
  const {
    getActiveSlide,
    zoom,
    setZoom,
    selectedElementId,
    setSelectedElementId,
    deleteSelectedElement,
    addShapeQuick,
    addTextQuick,
    showGrid,
    snapEnabled,
    showSmartGuides,
    updateElementDirect,
    editingElementId,
    setEditingElementId
  } = usePPTStore()

  const slide = getActiveSlide()
  const canvasRef = useRef<HTMLDivElement>(null)
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [alignmentGuides, setAlignmentGuides] = useState<SnapGuide[]>([])
  const snapSessionRef = useRef<SnapSession>({})
  const [, setTick] = useState(0) // Force local re-render during smooth drag

  const selectedElement = slide?.elements.find((e) => e.id === selectedElementId) || null

  const handleDeleteSelected = () => {
    deleteSelectedElement()
    setEditingElementId(null)
  }

  // Double click to trigger inline canvas editing
  const handleElementDoubleClick = useCallback((elemId: string) => {
    if (!slide) return
    const elem = slide.elements.find((el) => el.id === elemId)
    if (!elem) return
    setSelectedElementId(elemId)
    if (elem.type === 'text' || elem.type === 'shape') {
      setEditingElementId(elemId)
    }
  }, [slide, setSelectedElementId, setEditingElementId])

  const handleCommitInlineEdit = useCallback((elemId: string, text: string) => {
    updateElementDirect(elemId, { text })
    setEditingElementId(null)
  }, [updateElementDirect, setEditingElementId])

  const handleCancelInlineEdit = useCallback(() => {
    setEditingElementId(null)
  }, [setEditingElementId])

  // 1. Mouse down on any element -> Select & Start Dragging Move
  const handleElementMouseDown = useCallback((elemId: string, e: React.MouseEvent) => {
    if (!slide) return
    const elem = slide.elements.find((el) => el.id === elemId)
    if (!elem) return

    const siblings = slide.elements
    const snapCandidates = collectSnapCandidates(slide, siblings, elemId)

    setSelectedElementId(elemId)
    snapSessionRef.current = {}
    setDragState({
      mode: 'move',
      elemId,
      startX: e.clientX,
      startY: e.clientY,
      initialElem: {
        x: elem.x,
        y: elem.y,
        width: elem.width,
        height: elem.height
      },
      snapCandidates
    })
  }, [slide, setSelectedElementId, setDragState])

  // 2. Mouse down on 8-direction resize handle
  const handleResizeHandleMouseDown = useCallback((handle: ResizeHandle, e: React.MouseEvent) => {
    if (!selectedElement) return
    const snapCandidates = slide ? collectSnapCandidates(slide, slide.elements, selectedElement.id) : []
    snapSessionRef.current = {}
    setDragState({
      mode: 'resize',
      elemId: selectedElement.id,
      startX: e.clientX,
      startY: e.clientY,
      initialElem: {
        x: selectedElement.x,
        y: selectedElement.y,
        width: selectedElement.width,
        height: selectedElement.height
      },
      handle,
      snapCandidates
    })
  }, [selectedElement, slide, setDragState])

  // 3. Global Window MouseMove & MouseUp during active Drag or Resize
  useEffect(() => {
    if (!dragState) return

    const onMouseMove = (e: MouseEvent) => {
      if (!canvasRef.current || !slide) return
      const rect = canvasRef.current.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return

      // Slide-units-per-screen-px already accounts for CSS scale(zoom) because
      // getBoundingClientRect() returns the post-transform box. The uniform
      // meet scale keeps thresholds identical on both axes at any zoom.
      const enter = screenPxToSlideUnits(SNAP_SCREEN_PX, rect, slide)
      const release = screenPxToSlideUnits(RELEASE_SCREEN_PX, rect, slide)
      const thresholds: SnapThresholds = {
        x: { enter, release },
        y: { enter, release }
      }
      const snappingEnabled = snapEnabled && !e.altKey

      const delta = screenDeltaToSlideDelta(
        e.clientX - dragState.startX,
        e.clientY - dragState.startY,
        rect,
        slide
      )

      const target = slide.elements.find((el) => el.id === dragState.elemId)
      if (!target) return

      if (dragState.mode === 'move') {
        const rawBounds: Bounds = {
          x: dragState.initialElem.x + delta.dx,
          y: dragState.initialElem.y + delta.dy,
          width: dragState.initialElem.width,
          height: dragState.initialElem.height
        }
        // pre-clamp -> snap -> (snapMove only returns in-bounds geometry;
        // out-of-bounds snap options are ignored so guides stay truthful)
        const preClamped = clampBoundsToSlide(rawBounds, slide)
        const snapped = snapMove(
          preClamped,
          dragState.snapCandidates,
          slide,
          snapSessionRef.current,
          thresholds,
          snappingEnabled
        )

        // Clamp after snapping. Geometry stays fractional so the committed
        // IR coordinate matches the guide position exactly (rounding happens
        // only in display formatting, never in geometry).
        const finalMove = clampBoundsToSlide(
          { x: snapped.x, y: snapped.y, width: target.width, height: target.height },
          slide
        )
        target.x = finalMove.x
        target.y = finalMove.y
        setAlignmentGuides(snappingEnabled && showSmartGuides ? snapped.guides : [])
      } else if (dragState.mode === 'resize' && dragState.handle) {
        const { initialElem, handle } = dragState

        let rawX = initialElem.x
        let rawY = initialElem.y
        let rawW = initialElem.width
        let rawH = initialElem.height

        if (handle.includes('e')) {
          rawW = Math.max(MIN_SIZE, initialElem.width + delta.dx)
        }
        if (handle.includes('s')) {
          rawH = Math.max(MIN_SIZE, initialElem.height + delta.dy)
        }
        if (handle.includes('w')) {
          const clamped = Math.min(initialElem.width - MIN_SIZE, delta.dx)
          rawW = initialElem.width - clamped
          rawX = initialElem.x + clamped
        }
        if (handle.includes('n')) {
          const clamped = Math.min(initialElem.height - MIN_SIZE, delta.dy)
          rawH = initialElem.height - clamped
          rawY = initialElem.y + clamped
        }

        const snapped = snapResize(
          { x: rawX, y: rawY, width: rawW, height: rawH },
          handle,
          dragState.snapCandidates,
          slide,
          snapSessionRef.current,
          thresholds,
          snappingEnabled,
          MIN_SIZE
        )

        // Clamp snapped geometry using edge-aware clamping so the element
        // never overflows the slide or shifts its fixed edge. Geometry stays
        // fractional to match the guide position exactly.
        const isLeft = handle.includes('w')
        const isTop = handle.includes('n')
        const cx = clampResizeAxis(
          snapped.x,
          snapped.width,
          slide.width,
          MIN_SIZE,
          isLeft ? 'min' : 'max'
        )
        const cy = clampResizeAxis(
          snapped.y,
          snapped.height,
          slide.height,
          MIN_SIZE,
          isTop ? 'min' : 'max'
        )
        target.x = cx.pos
        target.y = cy.pos
        target.width = cx.size
        target.height = cy.size
        setAlignmentGuides(snappingEnabled && showSmartGuides ? snapped.guides : [])
      }
      setTick((t) => t + 1)
    }

    const onMouseUp = () => {
      if (slide) {
        const target = slide.elements.find((el) => el.id === dragState.elemId)
        if (target) {
          const hasMoved =
            Math.abs(target.x - dragState.initialElem.x) > 0.5 ||
            Math.abs(target.y - dragState.initialElem.y) > 0.5 ||
            Math.abs(target.width - dragState.initialElem.width) > 0.5 ||
            Math.abs(target.height - dragState.initialElem.height) > 0.5

          if (hasMoved) {
            // Single backend mutation per actual drag/resize; pure clicks never commit to history.
            updateElementDirect(dragState.elemId, {
              x: target.x,
              y: target.y,
              width: target.width,
              height: target.height
            })
          }
        }
      }
      snapSessionRef.current = {}
      setAlignmentGuides([])
      setDragState(null)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [dragState, slide, updateElementDirect, snapEnabled, showSmartGuides])

  // 4. Drag and Drop from Toolbar onto Canvas
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (!canvasRef.current || !slide) return
    const shapeType = e.dataTransfer.getData('application/ppt-shape')
    if (!shapeType) return

    const rect = canvasRef.current.getBoundingClientRect()
    const point = screenToSlidePoint(e.clientX, e.clientY, rect, slide)
    const margin = 40
    const dropX = Math.round(Math.max(margin, Math.min(slide.width - margin, point.x)))
    const dropY = Math.round(Math.max(margin, Math.min(slide.height - margin, point.y)))

    if (shapeType === 'text') {
      addTextQuick(dropX, dropY)
    } else {
      addShapeQuick(shapeType, dropX, dropY)
    }
  }

  if (!slide) {
    return (
      <div className="flex-1 bg-canvas flex items-center justify-center text-muted text-sm font-tabular">
        暂无选中的幻灯片
      </div>
    )
  }

  return (
    <main
      className="flex-1 bg-canvas relative flex flex-col items-center justify-center p-8 overflow-hidden select-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          setSelectedElementId(null)
          setEditingElementId(null)
        }
      }}
    >
      {/* Floating Canvas Top Toolbar (Supports Drag to Canvas) */}
      <CanvasToolbar />

      {/* Grid Canvas Overlay (Alignment Grid) */}
      {showGrid && (
        <div
          className="absolute inset-0 pointer-events-none opacity-40"
          style={{
            backgroundImage:
              'linear-gradient(to right, var(--border-strong) 1px, transparent 1px), linear-gradient(to bottom, var(--border-strong) 1px, transparent 1px)',
            backgroundSize: '32px 32px'
          }}
        />
      )}

      {/* Subtle Studio Backdrop Dot Pattern */}
      <div
        className="absolute inset-0 opacity-[0.12] pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(var(--border-focus) 1px, transparent 1px)',
          backgroundSize: '24px 24px'
        }}
      />

      {/* Main Slide Stage */}
      <div
        ref={canvasRef}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="relative w-full max-w-[1120px] aspect-video rounded-xl shadow-[0_20px_50px_-12px_rgba(0,0,0,0.12),0_0_0_1px_rgba(0,0,0,0.05)] border border-line overflow-hidden bg-panel transition-transform duration-150"
        style={{
          transform: `scale(${zoom})`,
          cursor: dragState ? (dragState.mode === 'resize' ? 'crosshair' : 'grabbing') : 'default'
        }}
        onClick={(e) => {
          // Deselect if clicked on empty canvas background
          if (e.target === canvasRef.current) {
            setSelectedElementId(null)
            setEditingElementId(null)
          }
        }}
      >
        <SVGRendererComponent
          slide={slide}
          onElementMouseDown={handleElementMouseDown}
          onElementDoubleClick={handleElementDoubleClick}
          onResizeHandleMouseDown={handleResizeHandleMouseDown}
          alignmentGuides={alignmentGuides}
          editingElementId={editingElementId}
          onCommitInlineEdit={handleCommitInlineEdit}
          onCancelInlineEdit={handleCancelInlineEdit}
        />
      </div>

      {/* Bottom Floating Control Bar: Zoom & Quick Info & Instant Formatter */}
      <div className="absolute bottom-6 flex flex-wrap items-center justify-center gap-3 z-10 max-w-[95%]">
        <div className="flex items-center gap-1 bg-panel/95 backdrop-blur-xl px-2.5 py-1.5 rounded-xl border border-line-strong shadow-xl shadow-slate-200/60 text-secondary">
          <button
            onClick={() => setZoom(Math.max(zoom - 0.1, 0.5))}
            className="p-1 rounded-md hover:bg-elevated text-muted hover:text-main transition-colors"
            title="缩小视图"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-tabular font-medium px-2 w-14 text-center text-secondary">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={() => setZoom(Math.min(zoom + 0.1, 2.0))}
            className="p-1 rounded-md hover:bg-elevated text-muted hover:text-main transition-colors"
            title="放大视图"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div className="w-[1px] h-3.5 bg-line mx-1" />
          <button
            onClick={() => setZoom(1.0)}
            className="p-1 rounded-md hover:bg-elevated text-muted hover:text-main transition-colors"
            title="重置缩放 100%"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Selected Element Floating Info & Instant Formatter */}
        {selectedElement && (() => {
          const isTextOrShape = selectedElement.type === 'text' || selectedElement.type === 'shape'
          const isImageOrShape = selectedElement.type === 'image' || selectedElement.type === 'shape'
          const textContent = (selectedElement as any)?.text_content
          const firstPara = textContent?.paragraphs?.[0]
          const firstRun = firstPara?.runs?.[0]
          const currentFontSize = firstRun?.font?.size ?? (selectedElement.type === 'text' ? 24 : 16)
          const currentFontColor = firstRun?.font?.color ?? '#0F172A'
          const isBold = firstRun?.font?.bold ?? false
          const currentRadius = selectedElement.style?.radius ?? 0

          return (
            <div className="flex items-center gap-2.5 bg-panel/95 backdrop-blur-xl px-3 py-1.5 rounded-xl border border-line-strong shadow-xl shadow-slate-200/60 text-xs text-main animate-in fade-in duration-150">
              <span className="font-tabular text-main font-semibold bg-elevated px-2 py-0.5 rounded border border-line flex items-center gap-1">
                {selectedElement.type === 'image' ? (
                  <ImageIcon className="w-3.5 h-3.5 text-blue-600" />
                ) : (
                  <Move className="w-3.5 h-3.5 text-muted" />
                )}
                <span>{selectedElement.type} #{selectedElement.id}</span>
              </span>

              <span className="text-muted font-tabular text-[11px] font-medium hidden sm:inline">
                {Math.round(selectedElement.width)} × {Math.round(selectedElement.height)} px
              </span>

              <div className="w-[1px] h-3.5 bg-line" />

              {/* Instant Inline Text Edit Button */}
              {isTextOrShape && (
                <button
                  onClick={() => setEditingElementId(selectedElement.id)}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 font-medium transition-colors text-[11px]"
                  title="就地双击或点击此按钮输入文本"
                >
                  <Edit3 className="w-3 h-3" />
                  <span>编辑文字</span>
                </button>
              )}

              {/* Font Size Quick Stepper */}
              {isTextOrShape && (
                <div className="flex items-center gap-1 bg-subtle px-1.5 py-0.5 rounded border border-line">
                  <span className="text-[10px] text-muted font-medium">字号</span>
                  <button
                    onClick={() => updateElementDirect(selectedElement.id, { font_size: Math.max(10, currentFontSize - 2) })}
                    className="w-4 h-4 rounded flex items-center justify-center hover:bg-line text-muted hover:text-main text-[10px] font-bold"
                  >
                    -
                  </button>
                  <span className="font-tabular text-[11px] font-semibold w-5 text-center">
                    {Math.round(currentFontSize)}
                  </span>
                  <button
                    onClick={() => updateElementDirect(selectedElement.id, { font_size: Math.min(96, currentFontSize + 2) })}
                    className="w-4 h-4 rounded flex items-center justify-center hover:bg-line text-muted hover:text-main text-[10px] font-bold"
                  >
                    +
                  </button>
                </div>
              )}

              {/* Bold Quick Toggle */}
              {isTextOrShape && (
                <button
                  onClick={() => updateElementDirect(selectedElement.id, { bold: !isBold })}
                  className={`p-1 rounded transition-colors ${
                    isBold ? 'bg-inverted text-inverted-text shadow-xs' : 'hover:bg-elevated text-secondary'
                  }`}
                  title="文字加粗"
                >
                  <Bold className="w-3 h-3" />
                </button>
              )}

              {/* Font Color Picker */}
              {isTextOrShape && (
                <div className="flex items-center gap-1" title="设置字体颜色">
                  <div className="relative w-5 h-5 rounded overflow-hidden border border-line-strong cursor-pointer shrink-0 shadow-xs">
                    <input
                      type="color"
                      value={safeHexColor(currentFontColor, '#0F172A')}
                      onChange={(e) => updateElementDirect(selectedElement.id, { font_color: e.target.value })}
                      className="absolute -inset-2 w-10 h-10 cursor-pointer opacity-0"
                    />
                    <div className="w-full h-full" style={{ backgroundColor: currentFontColor }} />
                  </div>
                </div>
              )}

              {/* Corner Radius Quick Selector (for Cards & Images) */}
              {isImageOrShape && (
                <div className="flex items-center gap-1 bg-subtle px-1.5 py-0.5 rounded border border-line">
                  <span className="text-[10px] text-muted font-medium">圆角</span>
                  {[0, 4, 8, 16].map((r) => (
                    <button
                      key={r}
                      onClick={() => updateElementDirect(selectedElement.id, { radius: r })}
                      className={`px-1.5 py-0.2 rounded text-[10px] font-tabular transition-colors ${
                        currentRadius === r
                          ? 'bg-inverted text-inverted-text font-bold shadow-xs'
                          : 'hover:bg-line text-muted hover:text-main'
                      }`}
                    >
                      {r}px
                    </button>
                  ))}
                </div>
              )}

              <div className="w-[1px] h-3.5 bg-line" />

              <button
                onClick={handleDeleteSelected}
                className="p-1 rounded hover:bg-rose-50 text-muted hover:text-rose-600 transition-colors ml-0.5"
                title="删除此图元"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          )
        })()}
      </div>
    </main>
  )
}