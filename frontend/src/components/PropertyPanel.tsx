import React from 'react'
import {
  Trash2, Sliders, Type, Square,
  Palette, CornerUpRight, Move, Bold, Italic,
  AlignLeft, AlignCenter, AlignRight, Copy
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import type { ShapeElementIR, TextElementIR, ConnectorElementIR, GroupElementIR } from '../types/ppt'
import { themeColors, DEFAULT_COLOR_SWATCHES, SLIDE_THEME_PRESETS } from '../theme/tokens'

const FONT_FAMILIES = [
  { label: '现代无衬线 (Inter / Segoe UI)', value: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' },
  { label: '思源黑体 (Noto Sans SC)', value: '"Noto Sans SC", -apple-system, sans-serif' },
  { label: '微软雅黑 (Microsoft YaHei)', value: '"Microsoft YaHei", "PingFang SC", sans-serif' },
  { label: '苹方黑体 (PingFang SC)', value: '"PingFang SC", -apple-system, sans-serif' },
  { label: '人文衬线 (Songti / SimSun)', value: '"Songti SC", SimSun, "Noto Serif SC", serif' },
  { label: '极客等宽 (JetBrains Mono)', value: '"JetBrains Mono", Consolas, monospace' }
]

const QUICK_FONT_SIZES = [14, 16, 18, 24, 32, 40, 48, 64]

const LAYOUT_PRESETS = [
  { name: '标题横幅', w: 1040, h: 80 },
  { name: '标准卡片', w: 360, h: 260 },
  { name: '指标卡片', w: 260, h: 160 },
  { name: '宽幅展板', w: 540, h: 320 },
  { name: '全屏容器', w: 1120, h: 560 }
]

const COLOR_SWATCHES = DEFAULT_COLOR_SWATCHES

export const PropertyPanel: React.FC = () => {
  const {
    getActiveSlide,
    getSelectedElement,
    setSlideBackgroundDirect,
    applyThemeDirect,
    duplicateSelectedElement,
    deleteSelectedElement,
    updateElementDirect
  } = usePPTStore()

  const slide = getActiveSlide()
  const elem = getSelectedElement()

  // 1. If no element is selected, show Slide Level Properties & Archetypes
  if (!elem) {
    return (
      <div className="flex-1 overflow-y-auto p-4 space-y-6 select-none text-secondary bg-panel custom-scrollbar">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Sliders className="w-3.5 h-3.5 text-muted" />
            <h4 className="text-xs font-semibold text-main">幻灯片画布规范</h4>
          </div>
          <p className="text-[11px] text-muted leading-relaxed">
            在主舞台选取图元可调控矢量几何与字号排版；当前显示页面级全局样式。
          </p>
        </div>

        {/* Slide Canvas Size Info */}
        <div className="bg-subtle rounded-xl p-3 border border-line space-y-2.5 shadow-xs">
          <div className="flex justify-between items-center text-xs">
            <span className="text-muted font-medium">标准分辨率</span>
            <span className="font-tabular text-main font-semibold">1280 × 720 (16:9)</span>
          </div>
          <div className="flex justify-between items-center text-xs">
            <span className="text-muted font-medium">图元总数</span>
            <span className="font-tabular text-main font-semibold">{slide?.elements.length || 0} 个对象</span>
          </div>
        </div>

        {/* Background Color Setting */}
        <div className="space-y-2">
          <label className="text-xs font-semibold text-secondary block">页面背景色</label>
          <div className="flex items-center gap-2.5">
            <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-line-strong shrink-0 shadow-xs">
              <input
                type="color"
                value={slide?.background?.color || themeColors.surface.panel}
                onChange={(e) => {
                  setSlideBackgroundDirect(e.target.value)
                }}
                className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
              />
            </div>
            <span className="font-tabular text-xs text-main font-medium bg-subtle px-3 py-1.5 rounded-lg border border-line flex-1">
              {slide?.background?.color || themeColors.surface.panel}
            </span>
          </div>
        </div>

        {/* Quick Style Palette Presets */}
        <div className="space-y-2.5 pt-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <Palette className="w-3.5 h-3.5 text-muted" />
            <span>钛金与单色调色预设</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {SLIDE_THEME_PRESETS.map((theme) => (
              <button
                key={theme.id}
                onClick={() => applyThemeDirect(theme.id)}
                className="flex items-center gap-2 p-2 rounded-xl bg-panel hover:bg-subtle border border-line hover:border-line-strong text-left transition-all shadow-xs"
              >
                <div
                  className="w-3.5 h-3.5 rounded-full border border-slate-300 shrink-0 shadow-xs"
                  style={{ backgroundColor: theme.primary }}
                />
                <span className="text-xs text-secondary truncate font-medium">{theme.name}</span>
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
  const isGroup = elem.type === 'group'

  const shapeElem = elem as ShapeElementIR
  const textElem = elem as TextElementIR
  const connElem = elem as ConnectorElementIR
  const groupElem = elem as GroupElementIR

  const textContent = isText ? textElem.text_content : isShape ? shapeElem.text_content : null
  const plainText = textContent?.plain_text ?? ''

  // Typography state extraction
  const firstPara = textContent?.paragraphs?.[0]
  const firstRun = firstPara?.runs?.[0]
  const currentFontFamily = firstRun?.font?.name || 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  const currentFontSize = firstRun?.font?.size || (isText ? 28 : 18)
  const currentFontColor = firstRun?.font?.color || themeColors.content.primary
  const isBold = firstRun?.font?.bold ?? false
  const isItalic = firstRun?.font?.italic ?? false
  const currentAlign = firstPara?.align || 'left'
  const currentRadius = elem.style?.radius ?? 12
  const currentOpacity = Math.round((elem.style?.opacity ?? 1.0) * 100)

  const handleUpdate = (updates: Record<string, any>) => {
    updateElementDirect(elem.id, updates)
  }

  // Quick Layout Alignment Helpers
  const alignElement = (type: 'center-x' | 'center-y' | 'left' | 'right' | 'top' | 'bottom') => {
    if (type === 'center-x') {
      handleUpdate({ x: Math.round((1280 - elem.width) / 2) })
    } else if (type === 'center-y') {
      handleUpdate({ y: Math.round((720 - elem.height) / 2) })
    } else if (type === 'left') {
      handleUpdate({ x: 80 })
    } else if (type === 'right') {
      handleUpdate({ x: Math.round(1280 - 80 - elem.width) })
    } else if (type === 'top') {
      handleUpdate({ y: 80 })
    } else if (type === 'bottom') {
      handleUpdate({ y: Math.round(720 - 80 - elem.height) })
    }
  }

  const applySizePreset = (w: number, h: number) => {
    handleUpdate({
      width: w,
      height: h,
      x: Math.min(elem.x, 1280 - w),
      y: Math.min(elem.y, 720 - h)
    })
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-5 select-none text-secondary bg-panel custom-scrollbar">
      {/* Element Header & Quick Actions */}
      <div className="flex items-center justify-between border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-elevated border border-line-strong flex items-center justify-center text-main">
            {isText ? <Type className="w-3 h-3" /> : isGroup ? <Sliders className="w-3 h-3" /> : <Square className="w-3 h-3" />}
          </div>
          <div>
            <span className="text-xs font-semibold text-main">
              {elem.type === 'shape' ? '几何卡片' : elem.type === 'text' ? '文本段落' : elem.type === 'group' ? `组合容器 (${groupElem.children?.length || 0}项)` : '连接导线'}
            </span>
            <span className="font-tabular text-[11px] text-muted ml-2 font-medium">#{elem.id}</span>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={duplicateSelectedElement}
            className="p-1.5 rounded-lg text-muted hover:text-main hover:bg-elevated transition-colors"
            title="复制图元"
          >
            <Copy className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={deleteSelectedElement}
            className="p-1.5 rounded-lg text-muted hover:text-rose-600 hover:bg-rose-50 transition-colors"
            title="删除此图元"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Geometry: X, Y, Width, Height */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-semibold text-secondary">
          <div className="flex items-center gap-1.5">
            <Move className="w-3.5 h-3.5 text-muted" />
            <span>尺寸与坐标 (像素)</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">X</span>
            <input
              type="number"
              value={Math.round(elem.x)}
              onChange={(e) => handleUpdate({ x: parseFloat(e.target.value) || 0 })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">Y</span>
            <input
              type="number"
              value={Math.round(elem.y)}
              onChange={(e) => handleUpdate({ y: parseFloat(e.target.value) || 0 })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">宽</span>
            <input
              type="number"
              value={Math.round(elem.width)}
              onChange={(e) => handleUpdate({ width: parseFloat(e.target.value) || 10 })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">高</span>
            <input
              type="number"
              value={Math.round(elem.height)}
              onChange={(e) => handleUpdate({ height: parseFloat(e.target.value) || 10 })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
        </div>

        {/* Quick Alignment Actions */}
        <div className="pt-1">
          <span className="text-[10px] text-muted block mb-1.5 font-medium">快速画布定位对齐</span>
          <div className="grid grid-cols-3 gap-1.5">
            <button
              onClick={() => alignElement('center-x')}
              className="py-1 px-1.5 bg-elevated hover:bg-line text-secondary hover:text-main rounded border border-line text-[10px] font-medium transition-colors"
            >
              水平居中
            </button>
            <button
              onClick={() => alignElement('center-y')}
              className="py-1 px-1.5 bg-elevated hover:bg-line text-secondary hover:text-main rounded border border-line text-[10px] font-medium transition-colors"
            >
              垂直居中
            </button>
            <button
              onClick={() => {
                alignElement('center-x')
                alignElement('center-y')
              }}
              className="py-1 px-1.5 bg-elevated hover:bg-line text-secondary hover:text-main rounded border border-line text-[10px] font-medium transition-colors"
            >
              画布正中
            </button>
            <button
              onClick={() => alignElement('left')}
              className="py-1 px-1.5 bg-elevated hover:bg-line text-secondary hover:text-main rounded border border-line text-[10px] font-medium transition-colors"
            >
              靠左边距
            </button>
            <button
              onClick={() => alignElement('right')}
              className="py-1 px-1.5 bg-elevated hover:bg-line text-secondary hover:text-main rounded border border-line text-[10px] font-medium transition-colors"
            >
              靠右边距
            </button>
            <button
              onClick={() => alignElement('top')}
              className="py-1 px-1.5 bg-elevated hover:bg-line text-secondary hover:text-main rounded border border-line text-[10px] font-medium transition-colors"
            >
              靠顶边距
            </button>
          </div>
        </div>

        {/* Size Archetype Presets */}
        <div className="pt-1">
          <span className="text-[10px] text-muted block mb-1.5 font-medium">标准布局卡片尺寸</span>
          <div className="flex flex-wrap gap-1.5">
            {LAYOUT_PRESETS.map((p) => (
              <button
                key={p.name}
                onClick={() => applySizePreset(p.w, p.h)}
                className="py-1 px-2 bg-subtle hover:bg-elevated text-secondary hover:text-main rounded-md border border-line-strong text-[10px] font-tabular font-medium transition-colors"
              >
                {p.name} ({p.w}×{p.h})
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Typography: Font Family, Size, Styling, Alignment */}
      {(isText || (isShape && textContent !== null)) && (
        <div className="space-y-3 pt-3 border-t border-line">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <Type className="w-3.5 h-3.5 text-muted" />
            <span>字体型号与文本排版</span>
          </div>

          {/* 1. Font Family Selector */}
          <div className="space-y-1">
            <span className="text-[11px] text-muted font-medium">字体型号 (Font Family)</span>
            <select
              value={currentFontFamily}
              onChange={(e) => handleUpdate({ font_family: e.target.value })}
              className="w-full bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 text-xs text-main font-medium focus:outline-none focus:border-blue-500"
            >
              {FONT_FAMILIES.map((f) => (
                <option key={f.label} value={f.value} className="bg-panel text-main">
                  {f.label}
                </option>
              ))}
            </select>
          </div>

          {/* 2. Font Size Stepper & Quick Pills */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted font-medium">字号大小 (Font Size)</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleUpdate({ font_size: Math.max(10, currentFontSize - 2) })}
                  className="w-6 h-6 bg-elevated hover:bg-line text-secondary rounded border border-line-strong flex items-center justify-center text-xs font-semibold"
                  title="减小字号"
                >
                  -
                </button>
                <input
                  type="number"
                  min="10"
                  max="120"
                  value={Math.round(currentFontSize)}
                  onChange={(e) => handleUpdate({ font_size: parseFloat(e.target.value) || 16 })}
                  className="w-14 bg-subtle border border-line-strong rounded px-1.5 py-1 text-xs text-main font-tabular font-medium text-center focus:outline-none focus:border-blue-500"
                />
                <button
                  onClick={() => handleUpdate({ font_size: Math.min(120, currentFontSize + 2) })}
                  className="w-6 h-6 bg-elevated hover:bg-line text-secondary rounded border border-line-strong flex items-center justify-center text-xs font-semibold"
                  title="增大字号"
                >
                  +
                </button>
                <span className="text-[10px] text-muted ml-1 font-medium">px</span>
              </div>
            </div>

            <div className="flex flex-wrap gap-1">
              {QUICK_FONT_SIZES.map((sz) => (
                <button
                  key={sz}
                  onClick={() => handleUpdate({ font_size: sz })}
                  className={`py-0.5 px-2 rounded text-[10px] font-tabular border transition-colors ${
                    Math.round(currentFontSize) === sz
                      ? 'bg-inverted text-inverted-text border-inverted font-semibold'
                      : 'bg-subtle text-secondary border-line-strong hover:text-main'
                  }`}
                >
                  {sz}
                </button>
              ))}
            </div>
          </div>

          {/* 3. Text Styles: Bold, Italic & Alignment */}
          <div className="flex items-center justify-between pt-1">
            {/* Bold / Italic Toggles */}
            <div className="flex items-center gap-1 bg-elevated p-1 rounded-lg border border-line">
              <button
                onClick={() => handleUpdate({ bold: !isBold })}
                className={`p-1.5 rounded transition-colors ${
                  isBold ? 'bg-panel text-main shadow-xs' : 'text-muted hover:text-main'
                }`}
                title="加粗"
              >
                <Bold className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => handleUpdate({ italic: !isItalic })}
                className={`p-1.5 rounded transition-colors ${
                  isItalic ? 'bg-panel text-main shadow-xs' : 'text-muted hover:text-main'
                }`}
                title="斜体"
              >
                <Italic className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Alignments */}
            <div className="flex items-center gap-1 bg-elevated p-1 rounded-lg border border-line">
              <button
                onClick={() => handleUpdate({ align: 'left' })}
                className={`p-1.5 rounded transition-colors ${
                  currentAlign === 'left' ? 'bg-panel text-main shadow-xs' : 'text-muted hover:text-main'
                }`}
                title="靠左对齐"
              >
                <AlignLeft className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => handleUpdate({ align: 'center' })}
                className={`p-1.5 rounded transition-colors ${
                  currentAlign === 'center' ? 'bg-panel text-main shadow-xs' : 'text-muted hover:text-main'
                }`}
                title="居中对齐"
              >
                <AlignCenter className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => handleUpdate({ align: 'right' })}
                className={`p-1.5 rounded transition-colors ${
                  currentAlign === 'right' ? 'bg-panel text-main shadow-xs' : 'text-muted hover:text-main'
                }`}
                title="靠右对齐"
              >
                <AlignRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* 4. Font Color */}
          <div className="space-y-1.5">
            <span className="text-[11px] text-muted font-medium">文字颜色 (Font Color)</span>
            <div className="flex items-center gap-2">
              <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-line-strong shrink-0 shadow-xs">
                <input
                  type="color"
                  value={currentFontColor}
                  onChange={(e) => handleUpdate({ font_color: e.target.value })}
                  className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
                />
              </div>
              <input
                type="text"
                value={currentFontColor}
                onChange={(e) => handleUpdate({ font_color: e.target.value })}
                className="flex-1 bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
              />
            </div>
            {/* Swatches */}
            <div className="flex items-center gap-1.5 pt-0.5">
              {COLOR_SWATCHES.map((col) => (
                <button
                  key={col}
                  onClick={() => handleUpdate({ font_color: col })}
                  className="w-5 h-5 rounded-full border border-slate-300 hover:scale-110 transition-transform shadow-xs"
                  style={{ backgroundColor: col }}
                  title={col}
                />
              ))}
            </div>
          </div>

          {/* 5. Text Content Editor */}
          <div className="space-y-1">
            <span className="text-[11px] text-muted font-medium">文本内容编辑</span>
            <textarea
              value={plainText}
              onChange={(e) => handleUpdate({ text: e.target.value })}
              rows={3}
              placeholder="输入图元文本内容..."
              className="w-full bg-subtle border border-line-strong rounded-lg p-2.5 text-xs text-main placeholder-line-focus focus:outline-none focus:border-blue-500 resize-none leading-relaxed"
            />
          </div>
        </div>
      )}

      {/* Visual Styling: Fill, Border, Radius, Opacity */}
      {!isConn && (
        <div className="space-y-3 pt-3 border-t border-line">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <Palette className="w-3.5 h-3.5 text-muted" />
            <span>填充、边框与圆角</span>
          </div>

          {/* Fill Color */}
          <div className="space-y-1.5">
            <span className="text-[11px] text-muted block font-medium">图元填充色</span>
            <div className="flex items-center gap-2">
              <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-line-strong shrink-0 shadow-xs">
                <input
                  type="color"
                  value={elem.style?.fill?.color || themeColors.surface.subtle}
                  onChange={(e) => handleUpdate({ fill_color: e.target.value })}
                  className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
                />
              </div>
              <input
                type="text"
                value={elem.style?.fill?.color || themeColors.surface.subtle}
                onChange={(e) => handleUpdate({ fill_color: e.target.value })}
                className="flex-1 bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          {/* Border Stroke */}
          <div className="space-y-1.5">
            <span className="text-[11px] text-muted block font-medium">边框描边与宽度</span>
            <div className="flex items-center gap-2">
              <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-line-strong shrink-0 shadow-xs">
                <input
                  type="color"
                  value={elem.style?.border?.color || themeColors.border.strong}
                  onChange={(e) => handleUpdate({ border_color: e.target.value })}
                  className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
                />
              </div>
              <input
                type="text"
                value={elem.style?.border?.color || themeColors.border.strong}
                onChange={(e) => handleUpdate({ border_color: e.target.value })}
                className="flex-1 bg-subtle border border-line-strong rounded-lg px-2 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
              />
              <input
                type="number"
                min="0"
                max="16"
                value={elem.style?.border?.width ?? 1}
                onChange={(e) => handleUpdate({ border_width: parseFloat(e.target.value) || 0 })}
                className="w-14 bg-subtle border border-line-strong rounded-lg px-2 py-1.5 text-xs text-main font-tabular font-medium text-center focus:outline-none focus:border-blue-500"
              />
              <span className="text-[10px] text-muted font-medium">px</span>
            </div>
          </div>

          {/* Corner Radius (for shapes) */}
          {isShape && (
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-[11px] text-muted font-medium">
                <span>圆角弧度 (Corner Radius)</span>
                <span className="font-tabular text-main font-semibold">{currentRadius}px</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="0"
                  max="48"
                  value={currentRadius}
                  onChange={(e) => handleUpdate({ radius: parseFloat(e.target.value) || 0 })}
                  className="w-full accent-inverted bg-line h-1.5 rounded-lg cursor-pointer"
                />
                <input
                  type="number"
                  min="0"
                  max="48"
                  value={currentRadius}
                  onChange={(e) => handleUpdate({ radius: parseFloat(e.target.value) || 0 })}
                  className="w-12 bg-subtle border border-line-strong rounded px-1.5 py-0.5 text-xs text-main font-tabular font-medium text-center focus:outline-none"
                />
              </div>
            </div>
          )}

          {/* Opacity */}
          <div className="space-y-1.5">
            <div className="flex justify-between items-center text-[11px] text-muted font-medium">
              <span>图元不透明度 (Opacity)</span>
              <span className="font-tabular text-main font-semibold">{currentOpacity}%</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min="10"
                max="100"
                value={currentOpacity}
                onChange={(e) => handleUpdate({ opacity: (parseFloat(e.target.value) || 100) / 100.0 })}
                className="w-full accent-inverted bg-line h-1.5 rounded-lg cursor-pointer"
              />
              <span className="text-xs font-tabular text-muted font-semibold w-12 text-right">{currentOpacity}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Connector Specifics */}
      {isConn && (
        <div className="space-y-2 pt-3 border-t border-line">
          <span className="text-xs font-semibold text-secondary flex items-center gap-1.5">
            <CornerUpRight className="w-3.5 h-3.5 text-muted" />
            <span>导线连接端点</span>
          </span>
          <div className="grid grid-cols-2 gap-2 text-xs font-tabular">
            <div className="bg-subtle p-2.5 rounded-lg border border-line-strong">
              <span className="text-muted block text-[10px] mb-0.5 font-medium">起始坐标</span>
              ({Math.round(connElem.start_x)}, {Math.round(connElem.start_y)})
            </div>
            <div className="bg-subtle p-2.5 rounded-lg border border-line-strong">
              <span className="text-muted block text-[10px] mb-0.5 font-medium">终止坐标</span>
              ({Math.round(connElem.end_x)}, {Math.round(connElem.end_y)})
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
