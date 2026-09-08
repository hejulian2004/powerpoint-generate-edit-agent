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
    <header className="h-13 bg-[#0B0D13] border-b border-[#21262D] flex items-center justify-between px-4 select-none shrink-0 z-20">
      {/* Brand & Presentation Metadata */}
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center shadow-sm">
          <Presentation className="w-3.5 h-3.5 text-indigo-400" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-100 text-xs tracking-tight">PPT-Agent-Studio</span>
            <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              IR v1.0
            </span>
          </div>
          <p className="text-[11px] text-slate-400 truncate max-w-[260px]">
            {presentation?.title || '未命名演示文稿'}
          </p>
        </div>
      </div>

      {/* Center Action Toolbar: History & New Slide */}
      <div className="flex items-center gap-1 bg-[#161B22] p-1 rounded-xl border border-[#30363D]">
        <button
          onClick={triggerUndo}
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          className="p-1.5 rounded-lg hover:bg-slate-800 disabled:opacity-30 disabled:hover:bg-transparent text-slate-300 transition"
        >
          <Undo2 className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={triggerRedo}
          disabled={!canRedo}
          title="重做 (Ctrl+Y)"
          className="p-1.5 rounded-lg hover:bg-slate-800 disabled:opacity-30 disabled:hover:bg-transparent text-slate-300 transition"
        >
          <Redo2 className="w-3.5 h-3.5" />
        </button>

        <div className="w-[1px] h-3.5 bg-slate-700 mx-1" />

        <button
          onClick={handleNewSlide}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-[#21262D] hover:bg-[#30363D] text-slate-200 transition"
        >
          <Plus className="w-3.5 h-3.5 text-indigo-400" />
          <span>新建页</span>
        </button>
      </div>

      {/* Right Controls: Import, Export, Settings, Live Status */}
      <div className="flex items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx"
          className="hidden"
          onChange={handleUpload}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          title="导入本地 PPTX 演示文稿"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#161B22] hover:bg-[#21262D] text-slate-200 border border-[#30363D] transition"
        >
          <Upload className="w-3.5 h-3.5 text-slate-400" />
          <span>导入 PPTX</span>
        </button>

        <button
          onClick={handleExport}
          title="无损重建并导出原生 PPTX 文件"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white shadow-sm shadow-blue-600/30 transition"
        >
          <Download className="w-3.5 h-3.5" />
          <span>导出 PPTX</span>
        </button>

        <button
          onClick={() => setSettingsOpen(true)}
          title="模型与服务设置"
          className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-[#161B22] transition"
        >
          <Settings className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-1.5 pl-2.5 border-l border-[#21262D]">
          <Circle
            className={`w-2 h-2 fill-current ${
              wsConnected ? 'text-emerald-400 animate-pulse' : 'text-amber-400'
            }`}
          />
          <span className="text-[10px] text-slate-400 font-mono tracking-wider">
            {wsConnected ? 'SYNCED' : 'OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  )
}
