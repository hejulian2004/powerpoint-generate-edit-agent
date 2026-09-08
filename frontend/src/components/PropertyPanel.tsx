import React from 'react'
import {
  Trash2, Sliders, Type, Square,
  Sparkles, CornerUpRight
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import type { ShapeElementIR, TextElementIR, ConnectorElementIR } from '../types/ppt'

export const PropertyPanel: React.FC = () => {
  const {
    getActiveSlide,
    getSelectedElement,
    updateElementDirect,
    setSelectedElementId,
    sendChatMessage
  } = usePPTStore()

  const slide = getActiveSlide()
  const elem = getSelectedElement()

  // 1. If no element is selected, show Slide Level Properties
  if (!elem) {
    return (
      <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none text-slate-300">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sliders className="w-3.5 h-3.5 text-indigo-400" />
            <h4 className="text-xs font-semibold text-slate-100">幻灯片画布属性</h4>
          </div>
          <p className="text-[11px] text-slate-500">
            选中画布图元可进入精准属性调节；未选取时调节全页规范。
          </p>
        </div>

        {/* Slide Canvas Size Info */}
        <div className="bg-slate-900/80 rounded-xl p-3 border border-slate-800 space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">标准分辨率</span>
            <span className="font-mono text-slate-200">1280 × 720 px (16:9)</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">图元总数</span>
            <span className="font-mono text-slate-200">{slide?.elements.length || 0} 个</span>
          </div>
        </div>

        {/* Background Color Setting */}
        <div className="space-y-2">
          <label className="text-xs font-medium text-slate-300 block">页面底色 (Background)</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={slide?.background?.color || '#0B0F19'}
              onChange={(e) => {
                sendChatMessage(`将当前页背景色修改为 ${e.target.value}`)
              }}
              className="w-8 h-8 rounded-lg cursor-pointer bg-transparent border-0"
            />
            <span className="font-mono text-xs text-slate-300 bg-slate-900 px-2.5 py-1.5 rounded-lg border border-slate-800 flex-1">
              {slide?.background?.color || '#0B0F19'}
            </span>
          </div>
        </div>

        {/* Quick Style Palette Presets */}
        <div className="space-y-2.5 pt-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>一键风格调色板 (Theme Presets)</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[
              { id: 'tech_blue', name: '科技深蓝', bg: '#0B0F19', primary: '#2563EB' },
              { id: 'dark_minimal', name: '极简黑曜', bg: '#020617', primary: '#38BDF8' },
              { id: 'emerald_nature', name: '清新森绿', bg: '#F0FDF4', primary: '#059669' },
              { id: 'warm_corporate', name: '暖色商务', bg: '#FFFBEB', primary: '#D97706' }
            ].map((theme) => (
              <button
                key={theme.id}
                onClick={() => sendChatMessage(`应用全局主题风格: ${theme.id}`)}
                className="flex items-center gap-2 p-2 rounded-xl bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800 text-left transition"
              >
                <div
                  className="w-4 h-4 rounded-full border border-white/20 shrink-0"
                  style={{ backgroundColor: theme.primary }}
                />
                <span className="text-xs text-slate-300 truncate">{theme.name}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // 2. Element Selected -> Full Property Controls
  const isShape = elem.type === 'shape'
  const isText = elem.type === 'text'
  const isConn = elem.type === 'connector'

  const shapeElem = elem as ShapeElementIR
  const textElem = elem as TextElementIR
  const connElem = elem as ConnectorElementIR

  const plainText = isText
    ? textElem.text_content?.plain_text
    : isShape
    ? shapeElem.text_content?.plain_text
    : ''

  const handleUpdate = (updates: Record<string, any>) => {
    updateElementDirect(elem.id, updates)
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-5 select-none text-slate-300">
      {/* Element Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <Square className="w-4 h-4 text-blue-400" />
          <div>
            <span className="text-xs font-semibold text-slate-100 uppercase tracking-wider">
              {elem.type}
            </span>
            <span className="font-mono text-[11px] text-slate-500 ml-2">#{elem.id}</span>
          </div>
        </div>
        <button
          onClick={() => {
            sendChatMessage(`请帮我删除选中的元素 (ID: ${elem.id})`)
            setSelectedElementId(null)
          }}
          className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition"
          title="删除此元素"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Geometry: X, Y, W, H */}
      <div className="space-y-2">
        <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
          尺寸与坐标 (Geometry)
        </span>
        <div className="grid grid-cols-2 gap-2">
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5">
            <span className="text-[11px] text-slate-500 w-5 font-mono">X</span>
            <input
              type="number"
              value={Math.round(elem.x)}
              onChange={(e) => handleUpdate({ x: parseFloat(e.target.value) || 0 })}
              className="w-full bg-transparent text-xs text-slate-100 font-mono focus:outline-none"
            />
          </div>
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5">
            <span className="text-[11px] text-slate-500 w-5 font-mono">Y</span>
            <input
              type="number"
              value={Math.round(elem.y)}
              onChange={(e) => handleUpdate({ y: parseFloat(e.target.value) || 0 })}
              className="w-full bg-transparent text-xs text-slate-100 font-mono focus:outline-none"
            />
          </div>
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5">
            <span className="text-[11px] text-slate-500 w-5 font-mono">W</span>
            <input
              type="number"
              value={Math.round(elem.width)}
              onChange={(e) => handleUpdate({ width: parseFloat(e.target.value) || 10 })}
              className="w-full bg-transparent text-xs text-slate-100 font-mono focus:outline-none"
            />
          </div>
          <div className="flex items-center bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5">
            <span className="text-[11px] text-slate-500 w-5 font-mono">H</span>
            <input
              type="number"
              value={Math.round(elem.height)}
              onChange={(e) => handleUpdate({ height: parseFloat(e.target.value) || 10 })}
              className="w-full bg-transparent text-xs text-slate-100 font-mono focus:outline-none"
            />
          </div>
        </div>
      </div>

      {/* Fill Color */}
      {!isConn && (
        <div className="space-y-2">
          <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
            填充颜色 (Fill)
          </span>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={elem.style?.fill?.color || '#2563EB'}
              onChange={(e) => handleUpdate({ fill_color: e.target.value })}
              className="w-8 h-8 rounded-lg cursor-pointer bg-transparent border-0"
            />
            <input
              type="text"
              value={elem.style?.fill?.color || '#2563EB'}
              onChange={(e) => handleUpdate({ fill_color: e.target.value })}
              className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      )}

      {/* Border & Stroke */}
      <div className="space-y-2">
        <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block">
          边框与描边 (Stroke)
        </span>
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={elem.style?.border?.color || '#3B82F6'}
            onChange={(e) => handleUpdate({ border_color: e.target.value })}
            className="w-8 h-8 rounded-lg cursor-pointer bg-transparent border-0"
          />
          <div className="flex-1 flex items-center gap-1.5">
            <input
              type="text"
              value={elem.style?.border?.color || '#3B82F6'}
              onChange={(e) => handleUpdate({ border_color: e.target.value })}
              className="w-24 bg-slate-900 border border-slate-800 rounded-lg px-2 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-blue-500"
            />
            <input
              type="number"
              min="0"
              max="20"
              value={elem.style?.border?.width ?? 1}
              onChange={(e) => handleUpdate({ border_width: parseFloat(e.target.value) || 0 })}
              className="w-16 bg-slate-900 border border-slate-800 rounded-lg px-2 py-1.5 text-xs text-slate-200 font-mono text-center focus:outline-none"
            />
            <span className="text-[11px] text-slate-500">px</span>
          </div>
        </div>
      </div>

      {/* Text Content & Typography */}
      {(isText || (isShape && plainText !== undefined)) && (
        <div className="space-y-2.5 pt-1 border-t border-slate-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1">
              <Type className="w-3 h-3 text-slate-400" />
              <span>文本与排版 (Typography)</span>
            </span>
          </div>
          <textarea
            value={plainText || ''}
            onChange={(e) => handleUpdate({ text: e.target.value })}
            rows={3}
            placeholder="输入文本内容..."
            className="w-full bg-slate-900 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none font-sans"
          />

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">字号</span>
            <input
              type="number"
              min="10"
              max="72"
              value={18}
              onChange={(e) => handleUpdate({ font_size: parseFloat(e.target.value) || 16 })}
              className="w-16 bg-slate-900 border border-slate-800 rounded-lg px-2 py-1.5 text-xs text-slate-200 font-mono text-center focus:outline-none"
            />
            <span className="text-[11px] text-slate-500">px</span>
          </div>
        </div>
      )}

      {/* Connector Specifics */}
      {isConn && (
        <div className="space-y-2 pt-2 border-t border-slate-800/80">
          <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <CornerUpRight className="w-3 h-3 text-blue-400" />
            <span>连接线端点 (Endpoints)</span>
          </span>
          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
            <div className="bg-slate-900 p-2 rounded-lg border border-slate-800">
              <span className="text-slate-500 block text-[10px]">START</span>
              ({Math.round(connElem.start_x)}, {Math.round(connElem.start_y)})
            </div>
            <div className="bg-slate-900 p-2 rounded-lg border border-slate-800">
              <span className="text-slate-500 block text-[10px]">END</span>
              ({Math.round(connElem.end_x)}, {Math.round(connElem.end_y)})
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
