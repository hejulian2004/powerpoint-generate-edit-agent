import React, { useState, useRef, useEffect, useCallback } from 'react'
import { ZoomIn, ZoomOut, Maximize2, Trash2, Move } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'
import { CanvasToolbar } from './CanvasToolbar'

type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'

interface DragState {
  mode: 'move' | 'resize'
  elemId: string
  startX: number
  startY: number
  initialElem: {
    x: number
    y: number
    width: number
    height: number
  }
  handle?: ResizeHandle
}

export const SlideCanvas: React.FC = () => {
  const {
    getActiveSlide,
    zoom,
    setZoom,
    selectedElementId,
    setSelectedElementId,
    sendChatMessage,
    showGrid,
    updateElementDirect
  } = usePPTStore()

  const slide = getActiveSlide()
  const canvasRef = useRef<HTMLDivElement>(null)
  const [dragState, setDragState] = useState<DragState | null>(null)
  const [, setTick] = useState(0) // Force local re-render during smooth drag

  const selectedElement = slide?.elements.find((e) => e.id === selectedElementId) || null

  const handleDeleteSelected = () => {
    if (!selectedElement) return
    sendChatMessage(`请帮我删除选中的图元 (ID: ${selectedElement.id})`)
    setSelectedElementId(null)
  }

  // 1. Mouse down on any element -> Select & Start Dragging Move
  const handleElementMouseDown = useCallback((elemId: string, e: React.MouseEvent) => {
    if (!slide) return
    const elem = slide.elements.find((el) => el.id === elemId)
    if (!elem) return

    setSelectedElementId(elemId)
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
      }
    })
  }, [slide, setSelectedElementId])

  // 2. Mouse down on 8-direction resize handle
  const handleResizeHandleMouseDown = useCallback((handle: ResizeHandle, e: React.MouseEvent) => {
    if (!selectedElement) return
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
      handle
    })
  }, [selectedElement])

  // 3. Global Window MouseMove & MouseUp during active Drag or Resize
  useEffect(() => {
    if (!dragState) return

    const onMouseMove = (e: MouseEvent) => {
      if (!canvasRef.current || !slide) return
      const rect = canvasRef.current.getBoundingClientRect()
      const scale = rect.width / 1280.0
      if (scale <= 0) return

      const deltaX = (e.clientX - dragState.startX) / scale
      const deltaY = (e.clientY - dragState.startY) / scale

      const target = slide.elements.find((el) => el.id === dragState.elemId)
      if (!target) return

      if (dragState.mode === 'move') {
        const newX = Math.max(0, Math.min(1280 - target.width, dragState.initialElem.x + deltaX))
        const newY = Math.max(0, Math.min(720 - target.height, dragState.initialElem.y + deltaY))
        target.x = Math.round(newX)
        target.y = Math.round(newY)
        setTick((t) => t + 1)
      } else if (dragState.mode === 'resize') {
        const { initialElem, handle } = dragState
        const minSize = 24.0

        let newX = initialElem.x
        let newY = initialElem.y
        let newW = initialElem.width
        let newH = initialElem.height

        if (handle?.includes('e')) {
          newW = Math.max(minSize, initialElem.width + deltaX)
        }
        if (handle?.includes('s')) {
          newH = Math.max(minSize, initialElem.height + deltaY)
        }
        if (handle?.includes('w')) {
          const clampedDeltaX = Math.min(initialElem.width - minSize, deltaX)
          newW = initialElem.width - clampedDeltaX
          newX = initialElem.x + clampedDeltaX
        }
        if (handle?.includes('n')) {
          const clampedDeltaY = Math.min(initialElem.height - minSize, deltaY)
          newH = initialElem.height - clampedDeltaY
          newY = initialElem.y + clampedDeltaY
        }

        // Clamp to canvas borders
        target.x = Math.round(Math.max(0, newX))
        target.y = Math.round(Math.max(0, newY))
        target.width = Math.round(Math.min(1280 - target.x, newW))
        target.height = Math.round(Math.min(720 - target.y, newH))
        setTick((t) => t + 1)
      }
    }

    const onMouseUp = () => {
      if (slide) {
        const target = slide.elements.find((el) => el.id === dragState.elemId)
        if (target) {
          updateElementDirect(dragState.elemId, {
            x: target.x,
            y: target.y,
            width: target.width,
            height: target.height
          })
        }
      }
      setDragState(null)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)

    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [dragState, slide, updateElementDirect])

  // 4. Drag and Drop from Toolbar onto Canvas
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    if (!canvasRef.current) return
    const shapeType = e.dataTransfer.getData('application/ppt-shape')
    if (!shapeType) return

    const rect = canvasRef.current.getBoundingClientRect()
    const scale = rect.width / 1280.0
    const dropX = Math.round(Math.max(40, Math.min(1080, (e.clientX - rect.left) / scale)))
    const dropY = Math.round(Math.max(40, Math.min(600, (e.clientY - rect.top) / scale)))

    if (shapeType === 'text') {
      sendChatMessage(`在当前页坐标 x=${dropX}, y=${dropY} 添加一个文本标题`)
    } else {
      sendChatMessage(`在当前页坐标 x=${dropX}, y=${dropY} 添加一个 ${shapeType} 卡片`)
    }
  }

  if (!slide) {
    return (
      <div className="flex-1 bg-[#08090B] flex items-center justify-center text-[#55586A] text-sm font-tabular">
        暂无选中的幻灯片
      </div>
    )
  }

  return (
    <main
      className="flex-1 bg-[#08090B] relative flex flex-col items-center justify-center p-8 overflow-hidden select-none"
      onClick={() => setSelectedElementId(null)}
    >
      {/* Floating Canvas Top Toolbar (Supports Drag to Canvas) */}
      <CanvasToolbar />

      {/* Grid Canvas Overlay (Alignment Grid) */}
      {showGrid && (
        <div
          className="absolute inset-0 pointer-events-none opacity-40"
          style={{
            backgroundImage:
              'linear-gradient(to right, #1B1D27 1px, transparent 1px), linear-gradient(to bottom, #1B1D27 1px, transparent 1px)',
            backgroundSize: '32px 32px'
          }}
        />
      )}

      {/* Subtle Studio Backdrop Dot Pattern */}
      <div
        className="absolute inset-0 opacity-[0.04] pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(#F1F2F6 1px, transparent 1px)',
          backgroundSize: '28px 28px'
        }}
      />

      {/* Main Slide Stage (Standard 16:9 Viewport) */}
      <div
        ref={canvasRef}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className="relative w-full max-w-[1120px] aspect-video rounded-xl shadow-[0_24px_54px_-12px_rgba(0,0,0,0.85)] border border-[#222533] overflow-hidden bg-[#0D0E13] transition-transform duration-150"
        style={{
          transform: `scale(${zoom})`,
          cursor: dragState ? (dragState.mode === 'resize' ? 'crosshair' : 'grabbing') : 'default'
        }}
        onClick={(e) => {
          // Deselect if clicked on empty canvas background
          if (e.target === canvasRef.current) {
            setSelectedElementId(null)
          }
        }}
      >
        <SVGRendererComponent
          slide={slide}
          onElementMouseDown={handleElementMouseDown}
          onResizeHandleMouseDown={handleResizeHandleMouseDown}
        />
      </div>

      {/* Bottom Floating Control Bar: Zoom & Quick Info */}
      <div className="absolute bottom-6 flex items-center gap-3 z-10">
        <div className="flex items-center gap-1 bg-[#12131B]/95 backdrop-blur-xl px-2.5 py-1.5 rounded-xl border border-[#242735] shadow-2xl shadow-black/60 text-[#C2C6D6]">
          <button
            onClick={() => setZoom(Math.max(zoom - 0.1, 0.5))}
            className="p-1 rounded-md hover:bg-[#1C1E2A] text-[#888C9E] hover:text-[#F1F2F6] transition-colors"
            title="缩小视图"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-tabular px-2 w-14 text-center text-[#C8CBD8]">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={() => setZoom(Math.min(zoom + 0.1, 2.0))}
            className="p-1 rounded-md hover:bg-[#1C1E2A] text-[#888C9E] hover:text-[#F1F2F6] transition-colors"
            title="放大视图"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div className="w-[1px] h-3.5 bg-[#242735] mx-1" />
          <button
            onClick={() => setZoom(1.0)}
            className="p-1 rounded-md hover:bg-[#1C1E2A] text-[#888C9E] hover:text-[#F1F2F6] transition-colors"
            title="重置缩放 100%"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Selected Element Floating Info & Quick Transform */}
        {selectedElement && (
          <div className="flex items-center gap-3 bg-[#12131B]/95 backdrop-blur-xl px-3 py-1.5 rounded-xl border border-[#383C4F] shadow-2xl shadow-black/60 text-xs text-[#E2E5F0] animate-in fade-in duration-150">
            <span className="font-tabular text-[#F1F2F6] font-medium bg-[#1B1D27] px-2 py-0.5 rounded border border-[#2B2E3C] flex items-center gap-1">
              <Move className="w-3 h-3 text-[#888C9E]" />
              <span>{selectedElement.type} #{selectedElement.id}</span>
            </span>
            <span className="text-[#888C9E] font-tabular text-[11px]">
              X: {Math.round(selectedElement.x)} Y: {Math.round(selectedElement.y)} · {Math.round(selectedElement.width)} × {Math.round(selectedElement.height)} px
            </span>
            <button
              onClick={handleDeleteSelected}
              className="p-1 rounded hover:bg-[#252838] text-[#888C9E] hover:text-rose-300 transition-colors ml-0.5"
              title="删除此图元"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </main>
  )
}
