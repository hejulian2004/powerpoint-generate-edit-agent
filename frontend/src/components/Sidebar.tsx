import React from 'react'
import { Plus, Trash2, LayoutTemplate } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'

export const Sidebar: React.FC = () => {
  const { presentation, activeSlideId, setActiveSlideId, sendChatMessage } = usePPTStore()

  if (!presentation) {
    return (
      <aside className="w-56 bg-[#0A0A0A] border-r border-[#222222] p-3 flex flex-col shrink-0">
        <div className="text-xs text-neutral-500 text-center py-6 font-mono">加载中...</div>
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
    sendChatMessage('帮我新增一页黑白灰极简幻灯片')
  }

  return (
    <aside className="w-60 bg-[#0A0A0A] border-r border-[#222222] flex flex-col shrink-0 overflow-hidden select-none">
      {/* Sidebar Header */}
      <div className="h-10 px-3.5 border-b border-[#222222] flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium text-neutral-300">
          <LayoutTemplate className="w-3.5 h-3.5 text-neutral-400" />
          <span>幻灯片大纲 ({presentation.slides.length})</span>
        </div>
        <button
          onClick={handleAddSlide}
          title="添加新页"
          className="p-1 rounded-md hover:bg-[#1C1C1C] text-neutral-400 hover:text-white transition"
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
                  ? 'border-white bg-[#141414] shadow-lg shadow-black'
                  : 'border-[#222222] hover:border-[#383838] bg-[#0E0E0E]'
              }`}
            >
              {/* Slide Meta Label */}
              <div className="flex items-center justify-between mb-1.5 px-1">
                <span
                  className={`text-[11px] font-mono font-medium ${
                    isActive ? 'text-white' : 'text-neutral-500'
                  }`}
                >
                  {String(idx + 1).padStart(2, '0')}
                </span>
                <span className="text-[11px] text-neutral-400 truncate max-w-[120px]">
                  {slide.title || `页面 ${idx + 1}`}
                </span>

                {presentation.slides.length > 1 && (
                  <button
                    onClick={(e) => handleDeleteSlide(e, slide.id, idx + 1)}
                    title="删除此页"
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-neutral-500 hover:text-white hover:bg-[#2A2A2A] transition"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* 16:9 Mini Canvas Preview */}
              <div className="relative w-full aspect-video rounded-lg overflow-hidden border border-[#1E1E1E] bg-[#050505]">
                <div className="w-full h-full pointer-events-none transform origin-top-left">
                  <SVGRendererComponent slide={slide} isThumbnail />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Bottom Add Action */}
      <div className="p-3 border-t border-[#222222]">
        <button
          onClick={handleAddSlide}
          className="w-full py-2 px-3 rounded-lg border border-dashed border-[#282828] hover:border-neutral-400 hover:bg-[#141414] text-xs text-neutral-400 hover:text-white flex items-center justify-center gap-1.5 transition"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>添加新幻灯片</span>
        </button>
      </div>
    </aside>
  )
}
