import React, { useRef } from 'react'
import {
  Undo2, Redo2, Plus, Upload, Download, Settings,
  Layers, Sparkles
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
    setPptspecModalOpen,
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
    <header className="h-12 bg-[#0E0F13] border-b border-[#20222B] flex items-center justify-between px-4 select-none shrink-0 z-20">
      {/* Brand & Document Name */}
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-[#181922] border border-[#2B2E3C] flex items-center justify-center text-[#E2E5F0] shadow-sm">
          <Layers className="w-3.5 h-3.5" />
        </div>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-xs text-[#F1F2F6] tracking-tight">
            PPT-Agent-Studio
          </span>
          <span className="text-[#3F4354] text-xs">/</span>
          <span className="text-xs text-[#9599AA] truncate max-w-[280px] font-normal hover:text-[#D4D7E5] transition-colors">
            {presentation?.title || '未命名演示文稿'}
          </span>
        </div>
      </div>

      {/* Center History & Creation Controls */}
      <div className="flex items-center gap-0.5 bg-[#14151C] p-1 rounded-lg border border-[#232531]">
        <button
          onClick={triggerUndo}
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          className="p-1.5 rounded-md hover:bg-[#1E202B] disabled:opacity-20 disabled:hover:bg-transparent text-[#A2A6B7] hover:text-[#F1F2F6] transition-colors"
        >
          <Undo2 className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={triggerRedo}
          disabled={!canRedo}
          title="重做 (Ctrl+Y)"
          className="p-1.5 rounded-md hover:bg-[#1E202B] disabled:opacity-20 disabled:hover:bg-transparent text-[#A2A6B7] hover:text-[#F1F2F6] transition-colors"
        >
          <Redo2 className="w-3.5 h-3.5" />
        </button>

        <div className="w-[1px] h-3.5 bg-[#252836] mx-1" />

        <button
          onClick={handleNewSlide}
          title="新增一页幻灯片"
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-[#1B1D27] hover:bg-[#232635] text-[#D8DAE5] hover:text-white border border-[#2B2E3C] transition-all"
        >
          <Plus className="w-3.5 h-3.5 text-[#9599AA]" />
          <span>新建页</span>
        </button>
      </div>

      {/* Right Action Tools: Import, Export, Settings, Status */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setPptspecModalOpen(true)}
          title="使用外部 AI 分析结果生成 PPT (CanonicalPPTSpec)"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 hover:text-white border border-blue-500/30 transition-all shadow-sm"
        >
          <Sparkles className="w-3.5 h-3.5 text-blue-400" />
          <span>AI 论文导入生成</span>
        </button>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pptx"
          className="hidden"
          onChange={handleUpload}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          title="导入本地 PPTX 演示文稿并转换为 PPT-IR"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#14151C] hover:bg-[#1C1E28] text-[#C5C8D8] hover:text-white border border-[#242633] hover:border-[#333647] transition-all"
        >
          <Upload className="w-3.5 h-3.5 text-[#888C9E]" />
          <span>导入 PPTX</span>
        </button>

        <button
          onClick={handleExport}
          title="导出工业级原生 OOXML 演示文稿"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#F1F2F6] hover:bg-white text-[#0B0C10] shadow-sm transition-all"
        >
          <Download className="w-3.5 h-3.5" />
          <span>导出 PPTX</span>
        </button>

        <button
          onClick={() => setSettingsOpen(true)}
          title="模型与服务配置"
          className="p-1.5 rounded-lg text-[#7F8395] hover:text-[#F1F2F6] hover:bg-[#191B24] transition-colors"
        >
          <Settings className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-1.5 pl-2.5 border-l border-[#222430]">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              wsConnected ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]' : 'bg-[#555869]'
            }`}
          />
          <span className="text-[11px] text-[#787C8F] font-tabular">
            {wsConnected ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  )
}
