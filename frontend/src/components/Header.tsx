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
    sendChatMessage('帮我新增一页幻灯片，采用黑白灰极简背景。')
  }

  return (
    <header className="h-13 bg-[#0A0A0A] border-b border-[#222222] flex items-center justify-between px-4 select-none shrink-0 z-20">
      {/* Brand & Document Name */}
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-[#181818] border border-[#333333] flex items-center justify-center shadow-sm">
          <Presentation className="w-3.5 h-3.5 text-neutral-200" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-white text-xs tracking-tight">PPT-Agent-Studio</span>
            <span className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-[#1C1C1C] text-neutral-300 border border-[#2E2E2E]">
              MONOCHROME
            </span>
          </div>
          <p className="text-[11px] text-neutral-400 truncate max-w-[260px]">
            {presentation?.title || '未命名演示文稿'}
          </p>
        </div>
      </div>

      {/* Center History & Creation Controls */}
      <div className="flex items-center gap-1 bg-[#121212] p-1 rounded-xl border border-[#242424]">
        <button
          onClick={triggerUndo}
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          className="p-1.5 rounded-lg hover:bg-[#202020] disabled:opacity-25 disabled:hover:bg-transparent text-neutral-300 transition"
        >
          <Undo2 className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={triggerRedo}
          disabled={!canRedo}
          title="重做 (Ctrl+Y)"
          className="p-1.5 rounded-lg hover:bg-[#202020] disabled:opacity-25 disabled:hover:bg-transparent text-neutral-300 transition"
        >
          <Redo2 className="w-3.5 h-3.5" />
        </button>

        <div className="w-[1px] h-3.5 bg-[#2E2E2E] mx-1" />

        <button
          onClick={handleNewSlide}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg bg-[#1C1C1C] hover:bg-[#262626] text-neutral-200 border border-[#2E2E2E] transition"
        >
          <Plus className="w-3.5 h-3.5 text-neutral-300" />
          <span>新建页</span>
        </button>
      </div>

      {/* Right Action Tools: Import, Export, Settings, Status */}
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
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#141414] hover:bg-[#1E1E1E] text-neutral-200 border border-[#2A2A2A] transition"
        >
          <Upload className="w-3.5 h-3.5 text-neutral-400" />
          <span>导入 PPTX</span>
        </button>

        <button
          onClick={handleExport}
          title="导出原生 PPTX 文件"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-white hover:bg-neutral-200 text-black shadow-sm transition"
        >
          <Download className="w-3.5 h-3.5" />
          <span>导出 PPTX</span>
        </button>

        <button
          onClick={() => setSettingsOpen(true)}
          title="模型与服务设置"
          className="p-2 rounded-lg text-neutral-400 hover:text-white hover:bg-[#1C1C1C] transition"
        >
          <Settings className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-1.5 pl-2.5 border-l border-[#242424]">
          <Circle
            className={`w-2 h-2 fill-current ${
              wsConnected ? 'text-white animate-pulse' : 'text-neutral-500'
            }`}
          />
          <span className="text-[10px] text-neutral-400 font-mono tracking-wider">
            {wsConnected ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  )
}
