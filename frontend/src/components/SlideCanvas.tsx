import { ZoomIn, ZoomOut, Maximize2, Trash2 } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'

export const SlideCanvas: React.FC = () => {
  const {
    getActiveSlide,
    zoom,
    setZoom,
    selectedElementId,
    setSelectedElementId,
    sendChatMessage
  } = usePPTStore()

  const slide = getActiveSlide()

  if (!slide) {
    return (
      <div className="flex-1 bg-slate-950 flex items-center justify-center text-slate-500 text-sm">
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

  return (
    <main className="flex-1 bg-slate-950/95 relative flex flex-col items-center justify-center p-6 overflow-hidden select-none">
      {/* Background Dots */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(#ffffff 1px, transparent 1px)',
          backgroundSize: '24px 24px'
        }}
      />

      {/* Main Slide Canvas Container (16:9 aspect ratio) */}
      <div
        className="relative w-full max-w-[1080px] aspect-video rounded-xl shadow-2xl shadow-black/80 border border-slate-800/80 overflow-hidden bg-slate-900 transition-transform duration-150"
        style={{ transform: `scale(${zoom})` }}
      >
        <SVGRendererComponent slide={slide} />
      </div>

      {/* Bottom Floating Control Bar: Zoom & Element Inspector */}
      <div className="absolute bottom-6 flex items-center gap-3">
        {/* Zoom Controls */}
        <div className="flex items-center gap-1 bg-slate-900/90 backdrop-blur-md px-2.5 py-1.5 rounded-xl border border-slate-800/80 shadow-lg text-slate-300">
          <button
            onClick={() => setZoom(Math.max(zoom - 0.1, 0.5))}
            className="p-1 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
            title="缩小"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-mono px-1.5 w-12 text-center text-slate-300">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={() => setZoom(Math.min(zoom + 0.1, 2.0))}
            className="p-1 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
            title="放大"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <div className="w-[1px] h-3.5 bg-slate-800 mx-1" />
          <button
            onClick={() => setZoom(1.0)}
            className="p-1 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
            title="重置 100%"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Selected Element Quick Inspector Banner */}
        {selectedElement && (
          <div className="flex items-center gap-3 bg-blue-950/80 backdrop-blur-md px-3 py-1.5 rounded-xl border border-blue-500/40 shadow-lg text-xs text-blue-200 animate-in fade-in">
            <span className="font-mono text-blue-300">
              {selectedElement.type.toUpperCase()} #{selectedElement.id}
            </span>
            <span className="text-blue-400/80 font-mono text-[11px]">
              X:{Math.round(selectedElement.x)} Y:{Math.round(selectedElement.y)} ({Math.round(selectedElement.width)}×{Math.round(selectedElement.height)})
            </span>
            <button
              onClick={handleDeleteSelected}
              className="p-1 rounded hover:bg-rose-500/20 text-rose-400 transition"
              title="删除此元素"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </main>
  )
}
