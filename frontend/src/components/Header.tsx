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
    mutationStatus,
    pendingMutations,
    editLockState,
    sessionTakenOver,
    needsResync,
    triggerUndo,
    triggerRedo,
    addNewSlide,
    setSettingsOpen,
    setPptspecModalOpen,
    awaitDirectSyncBarrier
  } = usePPTStore()

  const canAuthor = editLockState === 'editable' && !sessionTakenOver && !needsResync

  const pendingCount = pendingMutations.length
  const syncFailed = mutationStatus === 'failed' || mutationStatus === 'rolled_back'
  const syncLabel = syncFailed
    ? 'SYNC FAILED'
    : !wsConnected && pendingCount > 0
    ? `OFFLINE · ${pendingCount}`
    : pendingCount > 0
    ? `SYNC · ${pendingCount}`
    : wsConnected
    ? 'LIVE'
    : 'OFFLINE'
  const syncDot = syncFailed
    ? 'bg-rose-500 shadow-[0_0_6px_rgba(244,63,94,0.5)]'
    : !wsConnected && pendingCount > 0
    ? 'bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.5)] animate-pulse'
    : pendingCount > 0
    ? 'bg-amber-400 shadow-[0_0_6px_rgba(245,158,11,0.4)]'
    : wsConnected
    ? 'bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]'
    : 'bg-line-focus'

  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!canAuthor) {
      alert('演示文稿正在被 Agent 编辑，暂不可导入。')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    const formData = new FormData()
    formData.append('file', file)

    try {
      // Upload replaces the whole document: refuse if local edits are unsynced,
      // otherwise they would be silently discarded.
      await awaitDirectSyncBarrier({ timeoutMs: 10000 })
    } catch {
      alert('本地修改尚未同步完成，已取消导入。请等待同步完成或重试。')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    try {
      // Pin the replacement to the revision the user can actually see: after the
      // barrier the local view is synced, so these stamps describe the document
      // the user intends to replace. Both are always sent — the server rejects a
      // replacement that omits either stamp, so we never fall back to "current".
      const { documentEpoch, confirmedRevision } = usePPTStore.getState()
      const params = new URLSearchParams({
        session_id: sessionId,
        expected_epoch: documentEpoch ?? '',
        expected_revision: String(confirmedRevision)
      })
      const res = await fetch(`/api/upload?${params.toString()}`, {
        method: 'POST',
        body: formData
      })
      if (!res.ok) throw new Error('Upload failed')
      // The upload response is a canonical snapshot: adopt it in one step.
      const snapshot = await res.json()
      usePPTStore.getState().adoptCanonicalSnapshot(snapshot)
    } catch (err) {
      alert(`上传失败: ${err}`)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleExport = async () => {
    try {
      // Export must correspond to one committed revision, not a local prediction.
      await awaitDirectSyncBarrier({ timeoutMs: 10000 })
    } catch {
      alert('本地修改尚未同步完成，已取消导出。请等待同步完成或重试。')
      return
    }
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
          disabled={!canAuthor}
          title="使用外部 AI 分析结果生成 PPT (CanonicalPPTSpec)"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 transition-all shadow-xs disabled:opacity-40 disabled:cursor-not-allowed"
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
          disabled={!canAuthor}
          title="导入本地 PPTX 演示文稿并转换为 PPT-IR"
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-panel hover:bg-subtle text-secondary hover:text-main border border-line hover:border-line-strong shadow-xs transition-all disabled:opacity-40 disabled:cursor-not-allowed"
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
          <span className={`w-1.5 h-1.5 rounded-full ${syncDot}`} />
          <span className="text-[11px] text-muted font-tabular font-medium">
            {syncLabel}
          </span>
        </div>
      </div>
    </header>
  )
}
