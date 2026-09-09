import React from 'react'
import { Plus, Trash2, LayoutGrid } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { SVGRendererComponent } from './SVGRendererComponent'

export const Sidebar: React.FC = () => {
  const { presentation, activeSlideId, setActiveSlideId, addNewSlide, deleteSlide } = usePPTStore()

  if (!presentation) {
    return (
      <aside className="w-60 bg-[#0D0E12] border-r border-[#1F212B] p-4 flex flex-col shrink-0">
        <div className="text-xs text-[#5D6173] text-center py-8 font-tabular">载入演示结构...</div>
      </aside>
    )
  }

  const handleDeleteSlide = (e: React.MouseEvent, slideId: string, slideNum: number) => {
    e.stopPropagation()
    if (presentation.slides.length <= 1) {
      alert('演示文稿至少需保留一页幻灯片')
      return
    }
    if (confirm(`确定删除第 ${slideNum} 页幻灯片吗？`)) {
      deleteSlide(slideId)
    }
  }

  const handleAddSlide = () => {
    addNewSlide()
  }

  return (
    <aside className="w-60 bg-[#0D0E12] border-r border-[#1F212B] flex flex-col shrink-0 overflow-hidden select-none">
      {/* Sidebar Header */}
      <div className="h-11 px-3.5 border-b border-[#1F212B] flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-[#C8CBD8]">
          <LayoutGrid className="w-3.5 h-3.5 text-[#73778A]" />
          <span>页面索引</span>
          <span className="font-tabular text-[10px] text-[#7A7E90] bg-[#161720] px-1.5 py-0.2 rounded border border-[#232634]">
            {presentation.slides.length}
          </span>
        </div>
        <button
          onClick={handleAddSlide}
          title="新建页面"
          className="p-1 rounded-md hover:bg-[#1A1C25] text-[#868A9D] hover:text-[#F1F2F6] transition-colors"
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
              className={`group relative rounded-xl border transition-all cursor-pointer p-2 ${
                isActive
                  ? 'border-[#525668] bg-[#161821] shadow-md shadow-black/40'
                  : 'border-[#1E202A] hover:border-[#2F3242] bg-[#101117] hover:bg-[#13151D]'
              }`}
            >
              {/* Slide Header Info */}
              <div className="flex items-center justify-between mb-1.5 px-0.5">
                <div className="flex items-center gap-1.5 overflow-hidden">
                  <span
                    className={`text-[11px] font-tabular font-medium ${
                      isActive ? 'text-[#F1F2F6]' : 'text-[#616578]'
                    }`}
                  >
                    {String(idx + 1).padStart(2, '0')}
                  </span>
                  <span className="text-[11px] text-[#9A9EB0] truncate max-w-[130px]">
                    {slide.title || `页面 ${idx + 1}`}
                  </span>
                </div>

                {presentation.slides.length > 1 && (
                  <button
                    onClick={(e) => handleDeleteSlide(e, slide.id, idx + 1)}
                    title="删除页面"
                    className="opacity-0 group-hover:opacity-100 p-1 rounded text-[#73778A] hover:text-rose-300 hover:bg-[#252838] transition-all"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                )}
              </div>

              {/* 16:9 Mini Canvas Preview */}
              <div className="relative w-full aspect-video rounded-lg overflow-hidden border border-[#20222E] bg-[#08090B]">
                <div className="w-full h-full pointer-events-none transform origin-top-left">
                  <SVGRendererComponent slide={slide} isThumbnail />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Bottom Add Action */}
      <div className="p-3 border-t border-[#1F212B]">
        <button
          onClick={handleAddSlide}
          className="w-full py-2 px-3 rounded-lg border border-dashed border-[#272A38] hover:border-[#4B4F64] hover:bg-[#14161F] text-xs text-[#82869A] hover:text-[#F1F2F6] flex items-center justify-center gap-1.5 transition-all"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>添加新幻灯片</span>
        </button>
      </div>
    </aside>
  )
}
