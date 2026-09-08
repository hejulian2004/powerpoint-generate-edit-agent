import React, { useRef } from 'react'
import {
  Undo2, Redo2, Plus, Upload, Download, Settings,
  Presentation, Circle
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'

export const Header: React.FC = () => {
  const {
    presentation,
    canUndo,
    canRedo,
    wsConnected,
    triggerUndo,
    triggerRedo,
    setSettingsOpen,
    sendChatMessage
  } = usePPTStore()

  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      })
      if (!res.ok) throw new Error('Upload failed')
      // Reload presentation
      const presRes = await fetch('/api/presentation')
      const presData = await presRes.json()
      usePPTStore.getState().setPresentation(presData)
    } catch (err) {
      alert(`上传失败: ${err}`)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleExport = () => {
    window.location.href = '/api/export'
  }

  const handleNewSlide = () => {
    sendChatMessage('帮我新增一页幻灯片，采用与当前风格一致的背景。')
  }

  return (
    <header className="h-14 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 select-none shrink-0 z-20">
      {/* Brand & Document title */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-blue-500/20">
          <Presentation className="w-4 h-4 text-white" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-100 text-sm tracking-wide">PPT-Agent-Studio</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
              IR v1.0
            </span>
          </div>
          <p className="text-xs text-slate-400 truncate max-w-[240px]">
            {presentation?.title || '未命名演示文稿'}
          </p>
        </div>
      </div>

      {/* Center Actions: Undo, Redo, Add Slide */}
      <div className="flex items-center gap-1.5 bg-slate-950/60 p-1 rounded-lg border border-slate-800/80">
        <button
          onClick={triggerUndo}
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          className="p-1.5 rounded-md hover:bg-slate-800 disabled:opacity-30 disabled:hover:bg-transparent text-slate-300 transition"
        >
          <Undo2 className="w-4 h-4" />
        </button>
        <button
          onClick={triggerRedo}
          disabled={!canRedo}
          title="重做 (Ctrl+Y)"
          className="p-1.5 rounded-md hover:bg-slate-800 disabled:opacity-30 disabled:hover:bg-transparent text-slate-300 transition"
        >
          <Redo2 className="w-4 h-4" />
        </button>

        <div className="w-[1px] h-4 bg-slate-800 mx-1" />

        <button
          onClick={handleNewSlide}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 transition"
        >
          <Plus className="w-3.5 h-3.5 text-blue-400" />
          <span>新建页</span>
        </button>
      </div>

      {/* Right Controls: Upload, Export, Settings, WS status */}
      <div className="flex items-center gap-2.5">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx"
          className="hidden"
          onChange={handleUpload}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          title="导入 PPTX 文件"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-800/80 hover:bg-slate-700 text-slate-200 border border-slate-700/60 transition"
        >
          <Upload className="w-3.5 h-3.5 text-slate-400" />
          <span>导入 PPTX</span>
        </button>

        <button
          onClick={handleExport}
          title="导出原生 PPTX 文件"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white shadow-sm shadow-blue-600/30 transition"
        >
          <Download className="w-3.5 h-3.5" />
          <span>导出 PPTX</span>
        </button>

        <button
          onClick={() => setSettingsOpen(true)}
          title="模型与服务设置"
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
        >
          <Settings className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-1.5 pl-2 border-l border-slate-800">
          <Circle
            className={`w-2.5 h-2.5 fill-current ${
              wsConnected ? 'text-emerald-500 animate-pulse' : 'text-amber-500'
            }`}
          />
          <span className="text-[11px] text-slate-400 font-mono">
            {wsConnected ? 'LIVE' : 'SYNC'}
          </span>
        </div>
      </div>
    </header>
  )
}
