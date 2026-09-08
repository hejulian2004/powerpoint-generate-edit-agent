import React from 'react'
import { Plus, Trash2, LayoutTemplate } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'

export const Sidebar: React.FC = () => {
  const { presentation, activeSlideId, setActiveSlideId, sendChatMessage } = usePPTStore()

  if (!presentation) {
    return (
      <aside className="w-56 bg-[#0E1117] border-r border-[#21262D] p-3 flex flex-col shrink-0">
        <div className="text-xs text-slate-500 text-center py-6">正在加载幻灯片...</div>
      </aside>
    )
  }

  const handleDeleteSlide = (e: React.MouseEvent, _slideId: string, slideNum: number) => {
    e.stopPropagation()
    if (presentation.slides.length <= 1) {
      alert('不能删除最后一页')
      return
    }
    if (confirm(`确定删除第 ${slideNum} 页幻灯片吗？`)) {
      sendChatMessage(`请帮我删除第 ${slideNum} 页幻灯片`)
    }
  }

  const handleAddSlide = () => {
    sendChatMessage('帮我新增一页幻灯片')
  }

  return (
    <aside className="w-60 bg-[#0B0D13] border-r border-[#21262D] flex flex-col shrink-0 overflow-hidden select-none">
      {/* Sidebar Header */}
      <div className="h-10 px-3.5 border-b border-[#21262D] flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
          <LayoutTemplate className="w-3.5 h-3.5 text-indigo-400" />
          <span>幻灯片大纲 ({presentation.slides.length})</span>
        </div>
        <button
          onClick={handleAddSlide}
          title="添加新页"
          className="p-1 rounded-md hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Thumbnails Filmstrip */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar">
        {presentation.slides.map((slide, idx) => {
          const isActive = slide.id === activeSlideId
          return (
            <div
              key={slide.id}
              onClick={() => setActiveSlideId(slide.id)}
              className={`group relative rounded-xl border transition-all cursor-pointer p-1.5 ${
                isActive
                  ? 'border-indigo-500 bg-indigo-500/10 shadow-md shadow-indigo-500/10'
                  : 'border-[#21262D] hover:border-[#383F52] bg-[#161B22]/50'
              }`}
            >
              {/* Slide Meta Label */}
              <div className="flex items-center justify-between mb-1.5 px-1">
                <span
                  className={`text-[11px] font-mono font-medium ${
                    isActive ? 'text-indigo-400' : 'text-slate-500'
                  }`}
                >
                  {String(idx + 1).padStart(2, '0')}
                </span>
                <span className="text-[11px] text-slate-400 truncate max-w-[120px]">
                  {slide.title || `页面 ${idx + 1}`}
                </span>

                {presentation.slides.length > 1 && (
                  <button
                    onClick={(e) => handleDeleteSlide(e, slide.id, idx + 1)}
                    title="删除此页"
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* 16:9 Mini Canvas Preview */}
              <div className="relative w-full aspect-video rounded-lg overflow-hidden border border-[#21262D] bg-[#0E1117]">
                <div className="w-full h-full pointer-events-none transform origin-top-left">
                  <SVGRendererComponent slide={slide} isThumbnail />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Bottom Add Action */}
      <div className="p-3 border-t border-[#21262D]">
        <button
          onClick={handleAddSlide}
          className="w-full py-2 px-3 rounded-lg border border-dashed border-[#30363D] hover:border-indigo-500/60 hover:bg-indigo-500/5 text-xs text-slate-400 hover:text-indigo-400 flex items-center justify-center gap-1.5 transition"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>添加新幻灯片</span>
        </button>
      </div>
    </aside>
  )
}
