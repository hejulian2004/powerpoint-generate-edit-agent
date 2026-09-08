import React, { useState, useRef } from 'react'
import { ZoomIn, ZoomOut, Maximize2, Trash2 } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'
import { CanvasToolbar } from './CanvasToolbar'

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
  const [dragState, setDragState] = useState<{
    isDragging: boolean
    elemId: string
    startX: number
    startY: number
    initialElemX: number
    initialElemY: number
  } | null>(null)

  if (!slide) {
    return (
      <div className="flex-1 bg-[#050505] flex items-center justify-center text-neutral-500 text-sm">
        暂无选中的幻灯片
      </div>
    )
  }

  const selectedElement = selectedElementId
    ? slide.elements.find((e) => e.id === selectedElementId)
    : null

  const handleDeleteSelected = () => {
    if (!selectedElement) return
    sendChatMessage(`请帮我删除当前选中的元素 (ID: ${selectedElement.id})`)
    setSelectedElementId(null)
  }

  // Handle Drag Move on Canvas
  const handleMouseDown = (e: React.MouseEvent) => {
    if (!selectedElement || !canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    // Check if clicked near/on selected element
    const scale = rect.width / 1280.0
    const clickCanvasX = (e.clientX - rect.left) / scale
    const clickCanvasY = (e.clientY - rect.top) / scale

    if (
      clickCanvasX >= selectedElement.x &&
      clickCanvasX <= selectedElement.x + selectedElement.width &&
      clickCanvasY >= selectedElement.y &&
      clickCanvasY <= selectedElement.y + selectedElement.height
    ) {
      setDragState({
        isDragging: true,
        elemId: selectedElement.id,
        startX: e.clientX,
        startY: e.clientY,
        initialElemX: selectedElement.x,
        initialElemY: selectedElement.y
      })
    }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragState || !dragState.isDragging || !canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    const scale = rect.width / 1280.0

    const deltaX = (e.clientX - dragState.startX) / scale
    const deltaY = (e.clientY - dragState.startY) / scale

    const newX = Math.max(0, Math.min(1280 - (selectedElement?.width || 0), dragState.initialElemX + deltaX))
    const newY = Math.max(0, Math.min(720 - (selectedElement?.height || 0), dragState.initialElemY + deltaY))

    // Real-time optimistic update
    if (selectedElement) {
      selectedElement.x = Math.round(newX)
      selectedElement.y = Math.round(newY)
    }
  }

  const handleMouseUp = () => {
    if (dragState && dragState.isDragging && selectedElement) {
      updateElementDirect(dragState.elemId, {
        x: selectedElement.x,
        y: selectedElement.y
      })
    }
    setDragState(null)
  }

  return (
    <main
      className="flex-1 bg-[#050505] relative flex flex-col items-center justify-center p-8 overflow-hidden select-none"
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      {/* Floating Canvas Top Toolbar */}
      <CanvasToolbar />

      {/* Grid Canvas Overlay (Optional alignment grid) */}
      {showGrid && (
        <div
          className="absolute inset-0 pointer-events-none opacity-25"
          style={{
            backgroundImage:
              'linear-gradient(to right, #222222 1px, transparent 1px), linear-gradient(to bottom, #222222 1px, transparent 1px)',
            backgroundSize: '40px 40px'
          }}
        />
      )}

      {/* Subtle Studio Backdrop Pattern */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(#ffffff 1px, transparent 1px)',
          backgroundSize: '32px 32px'
        }}
      />

      {/* Main Slide Stage (Standard 16:9) */}
      <div
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        className="relative w-full max-w-[1120px] aspect-video rounded-xl shadow-2xl shadow-black border border-[#222222] overflow-hidden bg-[#0A0A0A] transition-transform duration-150 cursor-default"
        style={{
          transform: `scale(${zoom})`,
          cursor: dragState?.isDragging ? 'grabbing' : 'default'
        }}
      >
        <SVGRendererComponent slide={slide} />
      </div>

      {/* Bottom Floating Control Bar: Zoom & Quick Info */}
      <div className="absolute bottom-6 flex items-center gap-3 z-10">
        <div className="flex items-center gap-1 bg-[#121212]/95 backdrop-blur-md px-2.5 py-1.5 rounded-xl border border-[#222222] shadow-2xl text-neutral-300">
          <button
            onClick={() => setZoom(Math.max(zoom - 0.1, 0.5))}
            className="p-1 rounded-lg hover:bg-[#1E1E1E] text-neutral-400 hover:text-white transition"
            title="缩小"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-mono px-2 w-14 text-center text-neutral-300">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={() => setZoom(Math.min(zoom + 0.1, 2.0))}
            className="p-1 rounded-lg hover:bg-[#1E1E1E] text-neutral-400 hover:text-white transition"
            title="放大"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div className="w-[1px] h-3.5 bg-[#222222] mx-1" />
          <button
            onClick={() => setZoom(1.0)}
            className="p-1 rounded-lg hover:bg-[#1E1E1E] text-neutral-400 hover:text-white transition"
            title="重置 100%"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Selected Element Pill */}
        {selectedElement && (
          <div className="flex items-center gap-3 bg-[#121212]/95 backdrop-blur-md px-3.5 py-1.5 rounded-xl border border-white/40 shadow-2xl text-xs text-neutral-200 animate-in fade-in">
            <span className="font-mono text-white font-medium bg-[#1C1C1C] px-1.5 py-0.5 rounded border border-[#2A2A2A]">
              {selectedElement.type.toUpperCase()} #{selectedElement.id}
            </span>
            <span className="text-neutral-400 font-mono text-[11px]">
              {Math.round(selectedElement.x)}, {Math.round(selectedElement.y)} · {Math.round(selectedElement.width)}×{Math.round(selectedElement.height)}px
            </span>
            <button
              onClick={handleDeleteSelected}
              className="p-1 rounded hover:bg-neutral-800 text-neutral-400 hover:text-white transition ml-1"
              title="删除元素"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </main>
  )
}
