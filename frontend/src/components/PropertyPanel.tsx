import React, { useState, useEffect, useRef } from 'react'
import {
  Trash2, Sliders, Type, Square,
  Palette, CornerUpRight, Move, Bold, Italic,
  AlignLeft, AlignCenter, AlignRight, Copy, Image as ImageIcon,
  AlignStartVertical, AlignCenterVertical, AlignEndVertical,
  AlignStartHorizontal, AlignCenterHorizontal, AlignEndHorizontal,
  AlignHorizontalDistributeCenter, AlignVerticalDistributeCenter,
  Layers, Ungroup
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import type { ShapeElementIR, TextElementIR, ConnectorElementIR, GroupElementIR, ImageElementIR } from '../types/ppt'
import { themeColors, DEFAULT_COLOR_SWATCHES, SLIDE_THEME_PRESETS } from '../theme/tokens'

const safeHexColor = (col?: string, fallback = '#0F172A') => {
  if (!col) return fallback
  if (/^#[0-9A-Fa-f]{6}$/.test(col)) return col
  if (/^#[0-9A-Fa-f]{3}$/.test(col)) {
    return `#${col[1]}${col[1]}${col[2]}${col[2]}${col[3]}${col[3]}`
  }
  return fallback
}

export const getPlainText = (tc: any): string => {
  if (!tc) return ''
  if (typeof tc.plain_text === 'string' && tc.plain_text) return tc.plain_text
  if (Array.isArray(tc.paragraphs)) {
    return tc.paragraphs
      .map((p: any) =>
        Array.isArray(p.runs)
          ? p.runs.map((r: any) => (r && typeof r.text === 'string' ? r.text : '')).join('')
          : ''
      )
      .join('\n')
  }
  return ''
}

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

interface CommitNumberInputProps {
  value: number
  onCommit: (value: number) => void
  min?: number
  max?: number
  fallback?: number
  className: string
}

const CommitNumberInput: React.FC<CommitNumberInputProps> = ({
  value,
  onCommit,
  min,
  max,
  fallback,
  className
}) => {
  const [draft, setDraft] = useState(String(Math.round(value)))
  const focusedRef = useRef(false)
  const draftRef = useRef(String(Math.round(value)))

  useEffect(() => {
    if (!focusedRef.current) {
      const next = String(Math.round(value))
      draftRef.current = next
      setDraft(next)
    }
  }, [value])

  const commit = () => {
    focusedRef.current = false
    const parsed = parseFloat(draftRef.current)
    const next = Number.isFinite(parsed) ? parsed : fallback ?? value
    if (next === value) return
    onCommit(next)
  }

  return (
    <input
      type="number"
      min={min}
      max={max}
      value={draft}
      onFocus={() => {
        focusedRef.current = true
      }}
      onChange={(e) => {
        focusedRef.current = true
        draftRef.current = e.target.value
        setDraft(e.target.value)
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          ;(e.target as HTMLInputElement).blur()
        }
      }}
      className={className}
    />
  )
}

interface CommitTextInputProps {
  value: string
  onCommit: (value: string) => void
  className: string
}

const CommitTextInput: React.FC<CommitTextInputProps> = ({ value, onCommit, className }) => {
  const [draft, setDraft] = useState(value)
  const focusedRef = useRef(false)
  const draftRef = useRef(value)

  useEffect(() => {
    if (!focusedRef.current) {
      draftRef.current = value
      setDraft(value)
    }
  }, [value])

  const commit = () => {
    focusedRef.current = false
    if (draftRef.current === value) return
    onCommit(draftRef.current)
  }

  return (
    <input
      type="text"
      value={draft}
      onFocus={() => {
        focusedRef.current = true
      }}
      onChange={(e) => {
        focusedRef.current = true
        draftRef.current = e.target.value
        setDraft(e.target.value)
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          ;(e.target as HTMLInputElement).blur()
        }
      }}
      className={className}
    />
  )
}

interface CommitColorInputProps {
  value: string
  onCommit: (value: string) => void
  className: string
}

const CommitColorInput: React.FC<CommitColorInputProps> = ({ value, onCommit, className }) => {
  const [draft, setDraft] = useState(value)
  const focusedRef = useRef(false)
  const draftRef = useRef(value)

  useEffect(() => {
    if (!focusedRef.current) {
      draftRef.current = value
      setDraft(value)
    }
  }, [value])

  return (
    <input
      type="color"
      value={safeHexColor(draft, '#000000')}
      onFocus={() => {
        focusedRef.current = true
      }}
      onChange={(e) => {
        focusedRef.current = true
        draftRef.current = e.target.value
        setDraft(e.target.value)
      }}
      onBlur={() => {
        focusedRef.current = false
        if (safeHexColor(draftRef.current, '#000000') === safeHexColor(value, '#000000')) return
        onCommit(draftRef.current)
      }}
      className={className}
    />
  )
}

interface CommitSliderProps {
  value: number
  min: number
  max: number
  onCommit: (value: number) => void
  className: string
}

const CommitSlider: React.FC<CommitSliderProps> = ({ value, min, max, onCommit, className }) => {
  const [draft, setDraft] = useState(value)
  const draftRef = useRef(value)
  const draggingRef = useRef(false)

  useEffect(() => {
    if (!draggingRef.current) {
      draftRef.current = value
      setDraft(value)
    }
  }, [value])

  const commit = () => {
    if (!draggingRef.current) return
    draggingRef.current = false
    if (draftRef.current === value) return
    onCommit(draftRef.current)
  }

  return (
    <input
      type="range"
      min={min}
      max={max}
      value={draft}
      onPointerDown={() => {
        draggingRef.current = true
      }}
      onChange={(e) => {
        draggingRef.current = true
        const next = parseFloat(e.target.value) || 0
        draftRef.current = next
        setDraft(next)
      }}
      onPointerUp={commit}
      onKeyUp={(e) => {
        if (e.key.startsWith('Arrow')) {
          commit()
        }
      }}
      onBlur={commit}
      className={className}
    />
  )
}

export const PropertyPanel: React.FC = () => {
  const {
    getActiveSlide,
    getSelectedElement,
    selectedElementIds,
    setSlideBackgroundDirect,
    applyThemeDirect,
    duplicateSelectedElement,
    duplicateSelectedElements,
    deleteSelectedElement,
    deleteSelectedElements,
    groupSelectedElements,
    ungroupSelectedElement,
    alignSelectedElements,
    updateElementDirect,
    setEditingElementId
  } = usePPTStore()

  const slide = getActiveSlide()
  const elem = getSelectedElement()

  const isShape = elem?.type === 'shape'
  const isText = elem?.type === 'text'
  const isConn = elem?.type === 'connector'
  const isGroup = elem?.type === 'group'
  const isImage = elem?.type === 'image'

  const shapeElem = elem as ShapeElementIR
  const textElem = elem as TextElementIR
  const connElem = elem as ConnectorElementIR
  const groupElem = elem as GroupElementIR
  const imageElem = elem as ImageElementIR

  const textContent = isText ? textElem.text_content : isShape ? shapeElem.text_content : null
  const plainText = getPlainText(textContent)

  // Top-level unconditional React hooks (preserves hook call order on every render)
  const panelTextareaRef = useRef<HTMLTextAreaElement>(null)
  const [localText, setLocalText] = useState(plainText)
  useEffect(() => {
    if (document.activeElement !== panelTextareaRef.current) {
      setLocalText(plainText)
    }
  }, [elem?.id, plainText])

  // Multi-selection: alignment, distribution and grouping controls
  if (selectedElementIds.length > 1) {
    const alignActions = [
      { mode: 'left' as const, label: '左对齐', icon: <AlignStartVertical className="w-3.5 h-3.5" /> },
      { mode: 'center' as const, label: '水平居中', icon: <AlignCenterVertical className="w-3.5 h-3.5" /> },
      { mode: 'right' as const, label: '右对齐', icon: <AlignEndVertical className="w-3.5 h-3.5" /> },
      { mode: 'top' as const, label: '顶部对齐', icon: <AlignStartHorizontal className="w-3.5 h-3.5" /> },
      { mode: 'middle' as const, label: '垂直居中', icon: <AlignCenterHorizontal className="w-3.5 h-3.5" /> },
      { mode: 'bottom' as const, label: '底部对齐', icon: <AlignEndHorizontal className="w-3.5 h-3.5" /> }
    ]
    const distributeActions = [
      { mode: 'distribute_h' as const, label: '水平等距分布', icon: <AlignHorizontalDistributeCenter className="w-3.5 h-3.5" /> },
      { mode: 'distribute_v' as const, label: '垂直等距分布', icon: <AlignVerticalDistributeCenter className="w-3.5 h-3.5" /> }
    ]

    return (
      <div className="flex-1 overflow-y-auto p-4 space-y-5 text-secondary bg-panel custom-scrollbar">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-blue-50 border border-blue-200 flex items-center justify-center text-blue-600">
              <Layers className="w-3.5 h-3.5" />
            </div>
            <div>
              <span className="text-xs font-semibold text-main">多选编排</span>
              <span className="font-tabular text-[11px] text-muted ml-2 font-medium">
                已选中 {selectedElementIds.length} 个图元
              </span>
            </div>
          </div>
        </div>

        {/* Alignment */}
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <AlignCenterHorizontal className="w-3.5 h-3.5 text-muted" />
            <span>对齐方式</span>
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {alignActions.map((a) => (
              <button
                key={a.mode}
                onClick={() => alignSelectedElements(a.mode)}
                className="flex flex-col items-center justify-center gap-1 py-2 bg-subtle hover:bg-elevated text-secondary hover:text-main rounded-lg border border-line hover:border-line-strong text-[10px] font-medium transition-all"
                title={a.label}
              >
                <span className="text-muted">{a.icon}</span>
                <span>{a.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Distribution */}
        <div className="space-y-2 pt-2 border-t border-line">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <AlignHorizontalDistributeCenter className="w-3.5 h-3.5 text-muted" />
            <span>等距分布</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {distributeActions.map((a) => (
              <button
                key={a.mode}
                onClick={() => alignSelectedElements(a.mode)}
                className="flex items-center justify-center gap-1.5 py-2 bg-subtle hover:bg-elevated text-secondary hover:text-main rounded-lg border border-line hover:border-line-strong text-[10px] font-medium transition-all"
                title={a.label}
              >
                <span className="text-muted">{a.icon}</span>
                <span>{a.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Grouping & Actions */}
        <div className="space-y-2 pt-2 border-t border-line">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <Layers className="w-3.5 h-3.5 text-muted" />
            <span>组合与批量操作</span>
          </div>
          <button
            onClick={() => groupSelectedElements()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg bg-inverted hover:bg-inverted-hover text-inverted-text text-xs font-medium transition-all shadow-xs"
            title="组合选中图元 (Ctrl+G)"
          >
            <Layers className="w-3.5 h-3.5" />
            <span>组合 (Ctrl+G)</span>
          </button>
          <button
            onClick={() => duplicateSelectedElements()}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-subtle hover:bg-elevated text-secondary hover:text-main border border-line-strong text-xs font-medium transition-all"
            title="复制选中图元 (Ctrl+D)"
          >
            <Copy className="w-3.5 h-3.5" />
            <span>复制图元</span>
          </button>
          <button
            onClick={deleteSelectedElements}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 rounded-lg bg-subtle hover:bg-rose-50 text-muted hover:text-rose-600 border border-line-strong hover:border-rose-200 text-xs font-medium transition-all"
            title="删除选中图元 (Delete)"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>删除图元</span>
          </button>
        </div>
      </div>
    )
  }

  // 1. If no element is selected, show Slide Level Properties & Archetypes
  if (!elem) {
    return (
      <div className="flex-1 overflow-y-auto p-4 space-y-6 text-secondary bg-panel custom-scrollbar">
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

  // Typography state extraction
  const firstPara = textContent?.paragraphs?.[0]
  const firstRun = firstPara?.runs?.[0]
  const currentFontFamily = firstRun?.font?.name || 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  const currentFontSize = firstRun?.font?.size || (isText ? 28 : 18)
  const currentFontColor = firstRun?.font?.color || themeColors.content.primary
  const isBold = firstRun?.font?.bold ?? false
  const isItalic = firstRun?.font?.italic ?? false
  const currentAlign = firstPara?.align || 'left'
  const currentRadius = elem.style?.radius ?? 0
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
    <div className="flex-1 overflow-y-auto p-4 space-y-5 text-secondary bg-panel custom-scrollbar">
      {/* Element Header & Quick Actions */}
      <div className="flex items-center justify-between border-b border-line pb-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-elevated border border-line-strong flex items-center justify-center text-main">
            {isText ? (
              <Type className="w-3 h-3" />
            ) : isImage ? (
              <ImageIcon className="w-3.5 h-3.5 text-blue-600" />
            ) : isGroup ? (
              <Sliders className="w-3 h-3" />
            ) : (
              <Square className="w-3 h-3" />
            )}
          </div>
          <div>
            <span className="text-xs font-semibold text-main">
              {elem.type === 'shape'
                ? '几何卡片'
                : elem.type === 'text'
                ? '文本段落'
                : elem.type === 'image'
                ? '图像素材'
                : elem.type === 'group'
                ? `组合容器 (${groupElem.children?.length || 0}项)`
                : '连接导线'}
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

      {/* Group Specific Actions */}
      {isGroup && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-secondary">
            <Layers className="w-3.5 h-3.5 text-muted" />
            <span>组合容器</span>
            <span className="font-tabular text-[11px] text-muted font-medium">
              {groupElem.children?.length || 0} 个成员图元
            </span>
          </div>
          <button
            onClick={ungroupSelectedElement}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 text-xs font-medium transition-all shadow-xs"
            title="解散当前组合，恢复成员图元 (Ctrl+Shift+G)"
          >
            <Ungroup className="w-3.5 h-3.5" />
            <span>解散组合 (Ctrl+Shift+G)</span>
          </button>
        </div>
      )}

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
            <CommitNumberInput
              value={Math.round(elem.x)}
              fallback={0}
              onCommit={(v) => handleUpdate({ x: v })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">Y</span>
            <CommitNumberInput
              value={Math.round(elem.y)}
              fallback={0}
              onCommit={(v) => handleUpdate({ y: v })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">宽</span>
            <CommitNumberInput
              value={Math.round(elem.width)}
              fallback={10}
              onCommit={(v) => handleUpdate({ width: v })}
              className="w-full bg-transparent text-xs text-main font-tabular focus:outline-none font-medium"
            />
          </div>
          <div className="flex items-center bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 focus-within:border-blue-500 transition-colors">
            <span className="text-[11px] text-muted w-5 font-tabular font-medium">高</span>
            <CommitNumberInput
              value={Math.round(elem.height)}
              fallback={10}
              onCommit={(v) => handleUpdate({ height: v })}
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
      {(isText || isShape) && (
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
                <CommitNumberInput
                  value={Math.round(currentFontSize)}
                  min={10}
                  max={120}
                  fallback={16}
                  onCommit={(v) => handleUpdate({ font_size: v })}
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
                <CommitColorInput
                  value={currentFontColor}
                  onCommit={(v) => handleUpdate({ font_color: v })}
                  className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
                />
              </div>
              <CommitTextInput
                value={currentFontColor}
                onCommit={(v) => handleUpdate({ font_color: v })}
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
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted font-medium">文本内容编辑</span>
              <button
                type="button"
                onClick={() => setEditingElementId(elem.id)}
                className="text-[10px] text-blue-600 hover:text-blue-700 font-medium hover:underline flex items-center gap-1 cursor-pointer"
              >
                <span>在画布就地打字 ✏️</span>
              </button>
            </div>
            <textarea
              ref={panelTextareaRef}
              value={localText}
              onChange={(e) => {
                setLocalText(e.target.value)
              }}
              onBlur={() => {
                if (localText !== plainText) {
                  handleUpdate({ text: localText })
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.stopPropagation()
                  setLocalText(plainText)
                  ;(e.target as HTMLTextAreaElement).blur()
                }
              }}
              rows={3}
              placeholder="输入卡片或段落文本内容..."
              className="w-full bg-subtle border border-line-strong rounded-lg p-2.5 text-xs text-main placeholder-line-focus focus:outline-none focus:border-blue-500 resize-none leading-relaxed select-text"
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

          {/* Fill Color (Shapes and Textboxes only) */}
          {!isImage && (
            <div className="space-y-1.5">
              <span className="text-[11px] text-muted block font-medium">图元填充色</span>
              <div className="flex items-center gap-2">
                <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-line-strong shrink-0 shadow-xs">
                  <CommitColorInput
                    value={elem.style?.fill?.color || themeColors.surface.subtle}
                    onCommit={(v) => handleUpdate({ fill_color: v })}
                    className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
                  />
                </div>
                <CommitTextInput
                  value={elem.style?.fill?.color || themeColors.surface.subtle}
                  onCommit={(v) => handleUpdate({ fill_color: v })}
                  className="flex-1 bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          )}

          {/* Border Stroke */}
          <div className="space-y-1.5">
            <span className="text-[11px] text-muted block font-medium">边框描边与宽度</span>
            <div className="flex items-center gap-2">
              <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-line-strong shrink-0 shadow-xs">
                <CommitColorInput
                  value={elem.style?.border?.color || themeColors.border.strong}
                  onCommit={(v) => handleUpdate({ border_color: v })}
                  className="absolute -inset-2 w-12 h-12 cursor-pointer bg-transparent border-0"
                />
              </div>
              <CommitTextInput
                value={elem.style?.border?.color || themeColors.border.strong}
                onCommit={(v) => handleUpdate({ border_color: v })}
                className="flex-1 bg-subtle border border-line-strong rounded-lg px-2 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
              />
              <CommitNumberInput
                value={elem.style?.border?.width ?? 1}
                min={0}
                max={16}
                fallback={0}
                onCommit={(v) => handleUpdate({ border_width: v })}
                className="w-14 bg-subtle border border-line-strong rounded-lg px-2 py-1.5 text-xs text-main font-tabular font-medium text-center focus:outline-none focus:border-blue-500"
              />
              <span className="text-[10px] text-muted font-medium">px</span>
            </div>
          </div>

          {/* Corner Radius (for shapes and images) */}
          {(isShape || isImage) && (
            <div className="space-y-1.5">
              <div className="flex justify-between items-center text-[11px] text-muted font-medium">
                <span>圆角弧度 (Corner Radius)</span>
                <span className="font-tabular text-main font-semibold">{currentRadius}px</span>
              </div>
              <div className="flex items-center gap-2">
                <CommitSlider
                  value={currentRadius}
                  min={0}
                  max={48}
                  onCommit={(v) => handleUpdate({ radius: v })}
                  className="w-full accent-inverted bg-line h-1.5 rounded-lg cursor-pointer"
                />
                <CommitNumberInput
                  value={currentRadius}
                  min={0}
                  max={48}
                  fallback={0}
                  onCommit={(v) => handleUpdate({ radius: v })}
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
              <CommitSlider
                value={currentOpacity}
                min={10}
                max={100}
                onCommit={(v) => handleUpdate({ opacity: v / 100.0 })}
                className="w-full accent-inverted bg-line h-1.5 rounded-lg cursor-pointer"
              />
              <span className="text-xs font-tabular text-muted font-semibold w-12 text-right">{currentOpacity}%</span>
            </div>
          </div>
        </div>
      )}

      {/* Image Specific Details */}
      {isImage && (
        <div className="space-y-2 pt-3 border-t border-line">
          <span className="text-xs font-semibold text-secondary flex items-center gap-1.5">
            <ImageIcon className="w-3.5 h-3.5 text-blue-600" />
            <span>图像素材参数</span>
          </span>
          <div className="bg-subtle p-2.5 rounded-lg border border-line-strong space-y-1.5 text-xs font-tabular">
            <div className="flex justify-between text-muted">
              <span>原始尺寸</span>
              <span>{Math.round(imageElem.width)} × {Math.round(imageElem.height)} px</span>
            </div>
            <div className="flex justify-between text-muted">
              <span>圆角裁剪</span>
              <span className="text-main font-medium">{imageElem.style?.radius || 0} px</span>
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
