import React from 'react'
import {
  Type, Square, Circle as CircleIcon,
  ArrowUpRight, Grid, AlignCenterHorizontal,
  RectangleHorizontal, Triangle, Diamond, GripVertical
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'

export const CanvasToolbar: React.FC = () => {
  const {
    addShapeQuick,
    addTextQuick,
    addConnectorQuick,
    optimizeLayoutDirect,
    showGrid,
    setShowGrid
  } = usePPTStore()

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
        title="拖拽或点击添加菱形决策节点"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors cursor-grab active:cursor-grabbing"
      >
        <Diamond className="w-3.5 h-3.5" />
      </button>

      {/* 7. Connector Line */}
      <button
        onClick={addConnectorQuick}
        title="添加流程连接线与箭头"
        className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-main transition-colors"
      >
        <ArrowUpRight className="w-3.5 h-3.5" />
      </button>

      <div className="w-[1px] h-4 bg-line mx-1" />

      {/* 8. Smart Alignment */}
      <button
        onClick={optimizeLayoutDirect}
        title="智能规整当前页元素排版与对齐"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-elevated text-secondary hover:text-main text-xs font-medium transition-all"
      >
        <AlignCenterHorizontal className="w-3.5 h-3.5 text-muted" />
        <span>智能对齐</span>
      </button>

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
    </div>
  )
}
