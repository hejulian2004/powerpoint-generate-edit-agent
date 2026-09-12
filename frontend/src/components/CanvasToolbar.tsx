import React from 'react'
import {
  Type, Square, Circle as CircleIcon,
  ArrowUpRight, Grid, AlignCenterHorizontal, Magnet,
  RectangleHorizontal, Triangle, Diamond, GripVertical,
  Layers, Ungroup, AlignStartVertical, AlignEndVertical,
  AlignHorizontalDistributeCenter
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'

export const CanvasToolbar: React.FC = () => {
  const {
    addShapeQuick,
    addTextQuick,
    addConnectorQuick,
    optimizeLayoutDirect,
    showGrid,
    setShowGrid,
    snapEnabled,
    setSnapEnabled,
    showSmartGuides,
    setShowSmartGuides,
    selectedElementIds,
    getSelectedElement,
    groupSelectedElements,
    ungroupSelectedElement,
    alignSelectedElements,
    editLockState,
    sessionTakenOver,
    needsResync
  } = usePPTStore()

  const canAuthor = editLockState === 'editable' && !sessionTakenOver && !needsResync
  const authoringDisabled = !canAuthor

  const isMulti = selectedElementIds.length > 1
  const selectedElement = getSelectedElement()
  const isGroup = !isMulti && selectedElement?.type === 'group'

  const handleDragStart = (e: React.DragEvent, shapeType: string) => {
    e.dataTransfer.setData('application/ppt-shape', shapeType)
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div className="absolute top-4 z-10 flex items-center gap-1 bg-panel/95 backdrop-blur-xl px-2.5 py-1.5 rounded-xl border border-line-strong shadow-xl shadow-slate-200/60 select-none">
      {/* Drag Indicator Tooltip Note */}
      <div className="flex items-center text-line-focus pl-0.5 pr-1" title="支持拖拽至主舞台任意坐标放置">
        <GripVertical className="w-3.5 h-3.5" />
      </div>

      {/* 1. Text Tool (Click or Drag) */}
      <button
        draggable
        onDragStart={(e) => handleDragStart(e, 'text')}
        onClick={() => addTextQuick()}
        disabled={authoringDisabled}
        title="拖拽至画布或点击添加文本"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-elevated text-secondary hover:text-main text-xs font-medium transition-all cursor-grab active:cursor-grabbing"
      >
        <Type className="w-3.5 h-3.5 text-muted" />
        <span>文本</span>
      </button>

      {/* 2. Rounded Card (Click or Drag) */}
      <button
        draggable
        onDragStart={(e) => handleDragStart(e, 'roundRect')}
        onClick={() => addShapeQuick('roundRect')}
        disabled={authoringDisabled}
        title="拖拽至画布或点击添加圆角卡片"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-elevated text-secondary hover:text-main text-xs font-medium transition-all cursor-grab active:cursor-grabbing"
      >
        <RectangleHorizontal className="w-3.5 h-3.5 text-muted" />
        <span>卡片</span>
      </button>

      {/* 3. Rectangle */}
      <button
        draggable
        onDragStart={(e) => handleDragStart(e, 'rectangle')}
        onClick={() => addShapeQuick('rectangle')}
        disabled={authoringDisabled}
        title="拖拽或点击添加矩形"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors cursor-grab active:cursor-grabbing"
      >
        <Square className="w-3.5 h-3.5" />
      </button>

      {/* 4. Circle / Ellipse */}
      <button
        draggable
        onDragStart={(e) => handleDragStart(e, 'ellipse')}
        onClick={() => addShapeQuick('ellipse')}
        disabled={authoringDisabled}
        title="拖拽或点击添加圆形 / 椭圆"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors cursor-grab active:cursor-grabbing"
      >
        <CircleIcon className="w-3.5 h-3.5" />
      </button>

      {/* 5. Triangle */}
      <button
        draggable
        onDragStart={(e) => handleDragStart(e, 'triangle')}
        onClick={() => addShapeQuick('triangle')}
        disabled={authoringDisabled}
        title="拖拽或点击添加三角形"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors cursor-grab active:cursor-grabbing"
      >
        <Triangle className="w-3.5 h-3.5" />
      </button>

      {/* 6. Diamond */}
      <button
        draggable
        onDragStart={(e) => handleDragStart(e, 'diamond')}
        onClick={() => addShapeQuick('diamond')}
        disabled={authoringDisabled}
        title="拖拽或点击添加菱形决策节点"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors cursor-grab active:cursor-grabbing"
      >
        <Diamond className="w-3.5 h-3.5" />
      </button>

      {/* 7. Connector Line */}
      <button
        onClick={addConnectorQuick}
        disabled={authoringDisabled}
        title="添加流程连接线与箭头"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors"
      >
        <ArrowUpRight className="w-3.5 h-3.5" />
      </button>

      <div className="w-[1px] h-4 bg-line mx-1" />

      {/* 8. Smart Alignment */}
      <button
        onClick={optimizeLayoutDirect}
        disabled={authoringDisabled}
        title="智能规整当前页元素排版与对齐"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-elevated text-secondary hover:text-main text-xs font-medium transition-all"
      >
        <AlignCenterHorizontal className="w-3.5 h-3.5 text-muted" />
        <span>智能对齐</span>
      </button>

      {/* 8b. Contextual Multi-Selection: Align / Distribute / Group */}
      {isMulti && (
        <>
          <div className="w-[1px] h-4 bg-line mx-1" />
          <button
            onClick={() => alignSelectedElements('left')}
            disabled={authoringDisabled}
            title="左对齐选中图元"
            className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors"
          >
            <AlignStartVertical className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => alignSelectedElements('right')}
            disabled={authoringDisabled}
            title="右对齐选中图元"
            className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors"
          >
            <AlignEndVertical className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => alignSelectedElements('distribute_h')}
            disabled={authoringDisabled}
            title="水平等距分布"
            className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors"
          >
            <AlignHorizontalDistributeCenter className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => groupSelectedElements()}
            disabled={authoringDisabled}
            title={`组合选中的 ${selectedElementIds.length} 个图元 (Ctrl+G)`}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-inverted hover:bg-inverted-hover text-inverted-text text-xs font-medium transition-all shadow-xs"
          >
            <Layers className="w-3.5 h-3.5" />
            <span>组合</span>
          </button>
        </>
      )}

      {/* 8c. Contextual Single Group: Ungroup */}
      {isGroup && (
        <>
          <div className="w-[1px] h-4 bg-line mx-1" />
          <button
            onClick={() => ungroupSelectedElement()}
            disabled={authoringDisabled}
            title="解散当前组合 (Ctrl+Shift+G)"
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 text-xs font-medium transition-all"
          >
            <Ungroup className="w-3.5 h-3.5" />
            <span>解散组合</span>
          </button>
        </>
      )}

      <div className="w-[1px] h-4 bg-line mx-1" />

      {/* 9. Grid Overlay Toggle */}
      <button
        onClick={() => setShowGrid(!showGrid)}
        title={showGrid ? '隐藏对齐标尺网格' : '显示对齐标尺网格'}
        className={`p-1.5 rounded-lg transition-all ${
          showGrid
            ? 'bg-inverted text-inverted-text shadow-xs font-medium'
            : 'hover:bg-elevated text-muted hover:text-main'
        }`}
      >
        <Grid className="w-3.5 h-3.5" />
      </button>

      <div className="w-[1px] h-4 bg-line mx-1" />

      {/* 10. Snap Toggle (manual drag/resize geometry, independent from AI Smart Alignment) */}
      <button
        onClick={() => setSnapEnabled(!snapEnabled)}
        title={snapEnabled ? '关闭拖拽吸附 (按住 Alt 可临时关闭)' : '开启拖拽吸附'}
        className={`p-1.5 rounded-lg transition-all ${
          snapEnabled
            ? 'bg-inverted text-inverted-text shadow-xs font-medium'
            : 'hover:bg-elevated text-muted hover:text-main'
        }`}
      >
        <Magnet className="w-3.5 h-3.5" />
      </button>

      {/* 11. Smart Guides Toggle (show/hide alignment guide lines during drag) */}
      <button
        onClick={() => setShowSmartGuides(!showSmartGuides)}
        title={showSmartGuides ? '隐藏智能对齐辅助线' : '显示智能对齐辅助线'}
        className={`px-2 py-1.5 rounded-lg text-xs font-medium transition-all ${
          showSmartGuides
            ? 'bg-inverted text-inverted-text shadow-xs'
            : 'hover:bg-elevated text-muted hover:text-main'
        }`}
      >
        <span>辅助线</span>
      </button>
    </div>
  )
}
