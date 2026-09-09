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
    sessionId,
    triggerUndo,
    triggerRedo,
    addNewSlide,
    setSettingsOpen,
    setPptspecModalOpen
  } = usePPTStore()

  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch(`/api/upload?session_id=${encodeURIComponent(sessionId)}`, {
        method: 'POST',
        body: formData
      })
      if (!res.ok) throw new Error('Upload failed')
      const presRes = await fetch(`/api/presentation?session_id=${encodeURIComponent(sessionId)}`)
      const presData = await presRes.json()
      usePPTStore.getState().setPresentation(presData)
    } catch (err) {
      alert(`上传失败: ${err}`)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleExport = () => {
    window.location.href = `/api/export?session_id=${encodeURIComponent(sessionId)}`
  }

  const handleNewSlide = () => {
    addNewSlide()
  }

  return (
    <header className="h-12 bg-panel border-b border-line flex items-center justify-between px-4 select-none shrink-0 z-20 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
      {/* Brand & Document Name */}
      <div className="flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-inverted border border-inverted flex items-center justify-center text-inverted-text shadow-sm">
          <Layers className="w-3.5 h-3.5" />
        </div>
        <div className="flex items-center gap-2">
          <span className="font-semibold text-xs text-main tracking-tight">
            PPT-Agent-Studio
          </span>
          <span className="text-line-strong text-xs">/</span>
          <span className="text-xs text-muted truncate max-w-[280px] font-medium hover:text-main transition-colors">
            {presentation?.title || '未命名演示文稿'}
          </span>
        </div>
      </div>

      {/* Center History & Creation Controls */}
      <div className="flex items-center gap-0.5 bg-elevated p-1 rounded-lg border border-line">
        <button
          onClick={triggerUndo}
          disabled={!canUndo}
          title="撤销 (Ctrl+Z)"
          className="p-1.5 rounded-md hover:bg-panel disabled:opacity-30 disabled:hover:bg-transparent text-muted hover:text-main transition-all shadow-none hover:shadow-xs"
        >
          <Undo2 className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={triggerRedo}
          disabled={!canRedo}
          title="重做 (Ctrl+Y)"
          className="p-1.5 rounded-md hover:bg-panel disabled:opacity-30 disabled:hover:bg-transparent text-muted hover:text-main transition-all shadow-none hover:shadow-xs"
        >
          <Redo2 className="w-3.5 h-3.5" />
        </button>

        <div className="w-[1px] h-3.5 bg-line-strong mx-1" />

        <button
          onClick={handleNewSlide}
          title="新增一页幻灯片"
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-panel hover:bg-subtle text-main border border-line-strong shadow-xs hover:border-line-focus transition-all"
        >
          <Plus className="w-3.5 h-3.5 text-muted" />
          <span>新建页</span>
        </button>
      </div>

      {/* Right Action Tools: Import, Export, Settings, Status */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setPptspecModalOpen(true)}
          title="使用外部 AI 分析结果生成 PPT (CanonicalPPTSpec)"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 transition-all shadow-xs"
        >
          <Sparkles className="w-3.5 h-3.5 text-blue-600" />
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
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-panel hover:bg-subtle text-secondary hover:text-main border border-line hover:border-line-strong shadow-xs transition-all"
        >
          <Upload className="w-3.5 h-3.5 text-muted" />
          <span>导入 PPTX</span>
        </button>

        <button
          onClick={handleExport}
          title="导出工业级原生 OOXML 演示文稿"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-inverted hover:bg-inverted-hover text-inverted-text shadow-xs transition-all"
        >
          <Download className="w-3.5 h-3.5" />
          <span>导出 PPTX</span>
        </button>

        <button
          onClick={() => setSettingsOpen(true)}
          title="模型与服务配置"
          className="p-1.5 rounded-lg text-muted hover:text-main hover:bg-elevated transition-colors"
        >
          <Settings className="w-4 h-4" />
        </button>

        <div className="flex items-center gap-1.5 pl-2.5 border-l border-line">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              wsConnected ? 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]' : 'bg-line-focus'
            }`}
          />
          <span className="text-[11px] text-muted font-tabular font-medium">
            {wsConnected ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </div>
    </header>
  )
}
