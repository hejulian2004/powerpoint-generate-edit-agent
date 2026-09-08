import React from 'react'
import {
  Type, Square, Circle as CircleIcon,
  ArrowUpRight, Grid, AlignCenterHorizontal,
  RectangleHorizontal
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'

export const CanvasToolbar: React.FC = () => {
  const {
    addShapeQuick,
    addTextQuick,
    addConnectorQuick,
    sendChatMessage,
    showGrid,
    setShowGrid
  } = usePPTStore()

  return (
    <div className="absolute top-4 z-10 flex items-center gap-1 bg-slate-900/90 backdrop-blur-md px-2 py-1.5 rounded-xl border border-slate-800 shadow-xl select-none">
      <button
        onClick={addTextQuick}
        title="添加文本框"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-300 hover:text-white text-xs font-medium transition"
      >
        <Type className="w-3.5 h-3.5 text-blue-400" />
        <span>文本</span>
      </button>

      <button
        onClick={() => addShapeQuick('roundRect')}
        title="添加圆角卡片"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-300 hover:text-white text-xs font-medium transition"
      >
        <RectangleHorizontal className="w-3.5 h-3.5 text-indigo-400" />
        <span>卡片</span>
      </button>

      <button
        onClick={() => addShapeQuick('rectangle')}
        title="添加直角矩形"
        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
      >
        <Square className="w-3.5 h-3.5" />
      </button>

      <button
        onClick={() => addShapeQuick('ellipse')}
        title="添加圆/椭圆"
        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
      >
        <CircleIcon className="w-3.5 h-3.5" />
      </button>

      <button
        onClick={addConnectorQuick}
        title="添加连接箭头"
        className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
      >
        <ArrowUpRight className="w-3.5 h-3.5 text-emerald-400" />
      </button>

      <div className="w-[1px] h-4 bg-slate-800 mx-1" />

      <button
        onClick={() => sendChatMessage('帮我自动规整当前页所有卡片的对齐与水平等距排版')}
        title="智能自动排版对齐"
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-slate-800 text-slate-300 hover:text-white text-xs font-medium transition"
      >
        <AlignCenterHorizontal className="w-3.5 h-3.5 text-amber-400" />
        <span>自动规整</span>
      </button>

      <div className="w-[1px] h-4 bg-slate-800 mx-1" />

      <button
        onClick={() => setShowGrid(!showGrid)}
        title={showGrid ? '隐藏网格' : '显示对齐网格'}
        className={`p-1.5 rounded-lg transition ${
          showGrid
            ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
            : 'hover:bg-slate-800 text-slate-400 hover:text-white'
        }`}
      >
        <Grid className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
