import React, { useState, useRef, useEffect, useMemo } from 'react'
import {
  Send, Sparkles, Wrench, Eye, CheckCircle2,
  Bot, User, Loader2, SlidersHorizontal, ShieldCheck, Activity,
  Paperclip, X, FileText, FileType2, Image as ImageIcon, Presentation,
  Zap
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { PropertyPanel } from './PropertyPanel'
import { ContextUsageIndicator } from './ContextUsageIndicator'
import { buildHelpMessage, matchCommands, parseCommand, type ChatCommand } from './chat/chatCommands'
import { PlanCard, ConfirmationCard } from './chat/PlanCard'

type AttachmentKind = 'pdf' | 'pptx' | 'image' | 'text' | 'unknown'

interface PendingAttachment {
  id: string
  file: File
  name: string
  kind: AttachmentKind
  previewUrl?: string
}

// Mirrors the backend importer capability: only OOXML .pptx is importable.
// Legacy .ppt / macro .pptm are intentionally NOT advertised.
const PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

const kindFromFile = (file: File): AttachmentKind => {
  const name = (file.name || '').toLowerCase()
  const type = (file.type || '').toLowerCase()
  if (name.endsWith('.pdf') || type === 'application/pdf') return 'pdf'
  if (name.endsWith('.pptx') || type === PPTX_MIME) return 'pptx'
  if (type.startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|svg|heic)$/.test(name)) return 'image'
  if (type.startsWith('text/') || /\.(txt|md|markdown|csv|tsv|json|log|rst|ya?ml)$/.test(name)) return 'text'
  return 'unknown'
}

const AttachmentIcon: React.FC<{ kind: AttachmentKind; className?: string }> = ({ kind, className }) => {
  if (kind === 'image') return <ImageIcon className={className} />
  if (kind === 'pptx') return <Presentation className={className} />
  if (kind === 'pdf') return <FileType2 className={className} />
  return <FileText className={className} />
}

export const ChatPanel: React.FC = () => {
  const {
    messages,
    isAgentThinking,
    thinkingStatus,
    visualRemediation,
    generationStage,
    contextUsage,
    sendChatMessage,
    sendChatWithAttachments,
    activeRightTab,
    setActiveRightTab,
    selectedElementId,
    interactionMode,
    setInteractionMode,
    pendingPlan,
    confirmPlan,
    cancelPlan,
    pendingConfirmation,
    confirmConfirmation,
    cancelConfirmation,
    resetConversation,
    requestContextCompression,
    requestVisualReview,
    addMessage
  } = usePPTStore()

  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<PendingAttachment[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [activeCommandIndex, setActiveCommandIndex] = useState(0)
  const [paletteDismissed, setPaletteDismissed] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const attachmentsRef = useRef<PendingAttachment[]>([])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isAgentThinking])

  useEffect(() => {
    attachmentsRef.current = attachments
  }, [attachments])

  // Object URLs for image previews are client-only; revoke them on unmount so a
  // long session does not leak blobs.
  useEffect(() => {
    return () => {
      attachmentsRef.current.forEach((a) => a.previewUrl && URL.revokeObjectURL(a.previewUrl))
    }
  }, [])

  const addFiles = (incoming: FileList | File[] | null | undefined) => {
    if (!incoming) return
    const next: PendingAttachment[] = []
    const rejected: string[] = []
    for (const file of Array.from(incoming)) {
      if (!file) continue
      const kind = kindFromFile(file)
      if (kind === 'unknown') {
        // Never attach a file the backend cannot read: an attachment that
        // silently contributes no content would let the model answer about a
        // file it never saw.
        rejected.push(file.name || '未命名文件')
        continue
      }
      next.push({
        id: `att_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        file,
        name: file.name || '未命名文件',
        kind,
        previewUrl: kind === 'image' ? URL.createObjectURL(file) : undefined
      })
    }
    if (rejected.length) {
      addMessage({
        id: `attach_rejected_${Date.now()}`,
        role: 'assistant',
        content: `不支持该文件格式：${rejected.join('、')}。支持 PDF / PPTX / 图片 / 文本文档。`,
        timestamp: Date.now()
      })
    }
    if (next.length) setAttachments((prev) => [...prev, ...next])
  }

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.id === id)
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl)
      return prev.filter((a) => a.id !== id)
    })
  }

  const clearAttachments = () => {
    setAttachments((prev) => {
      prev.forEach((a) => a.previewUrl && URL.revokeObjectURL(a.previewUrl))
      return []
    })
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(e.target.files)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = e.clipboardData?.files
    if (files && files.length > 0) {
      e.preventDefault()
      addFiles(files)
    }
  }

  // Slash-command palette: active while the input is a bare "/query" token.
  const commandQuery = input.startsWith('/') ? input.slice(1) : null
  const filteredCommands = useMemo(
    () => (commandQuery !== null ? matchCommands(commandQuery.split(' ')[0]) : []),
    [commandQuery]
  )
  const paletteOpen =
    commandQuery !== null && !commandQuery.includes(' ') && !paletteDismissed && filteredCommands.length > 0

  const handleInputChange = (value: string) => {
    setInput(value)
    setActiveCommandIndex(0)
    setPaletteDismissed(false)
  }

  const runCommand = (command: ChatCommand, args: string) => {
    switch (command.name) {
      case 'compress':
        requestContextCompression()
        break
      case 'new':
        resetConversation()
        break
      case 'review':
        requestVisualReview(args || undefined)
        break
      case 'plan': {
        if (/^(off|false|关闭|退出|停用)$/i.test(args)) setInteractionMode('auto')
        else if (/^(on|true|开启|启用)$/i.test(args)) setInteractionMode('plan')
        else setInteractionMode(interactionMode === 'plan' ? 'auto' : 'plan')
        break
      }
      case 'help':
        addMessage(buildHelpMessage())
        break
    }
  }

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (isAgentThinking) return

    // Commands are control-plane only: they are never sent to the LLM transcript.
    if (attachments.length === 0) {
      const parsed = parseCommand(input)
      if (parsed) {
        runCommand(parsed.command, parsed.args)
        setInput('')
        return
      }
    }

    const hasContent = input.trim().length > 0 || attachments.length > 0
    if (!hasContent) return
    if (attachments.length > 0) {
      sendChatWithAttachments(input, attachments.map((a) => a.file))
      setInput('')
      clearAttachments()
    } else {
      sendChatMessage(input)
      setInput('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (paletteOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActiveCommandIndex((i) => Math.min(i + 1, filteredCommands.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActiveCommandIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setPaletteDismissed(true)
        return
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault()
        const command = filteredCommands[activeCommandIndex]
        if (command) {
          runCommand(command, '')
          setInput('')
        }
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <aside className="w-[390px] bg-panel border-l border-line flex flex-col shrink-0 h-full overflow-hidden shadow-xs">
      {/* Segmented Tab Switcher */}
      <div className="h-12 px-3 border-b border-line flex items-center justify-between bg-panel shrink-0">
        <div className="flex bg-elevated p-1 rounded-xl border border-line text-xs font-medium w-full">
          <button
            onClick={() => setActiveRightTab('copilot')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg transition-all ${
              activeRightTab === 'copilot'
                ? 'bg-panel text-main font-semibold shadow-xs'
                : 'text-muted hover:text-main'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI 协同设计</span>
          </button>
          <button
            onClick={() => setActiveRightTab('inspector')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg transition-all ${
              activeRightTab === 'inspector'
                ? 'bg-panel text-main font-semibold shadow-xs'
                : 'text-muted hover:text-main'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span>图元属性 {selectedElementId ? '●' : ''}</span>
          </button>
        </div>
      </div>

      {/* Mode 1: Property Inspector */}
      {activeRightTab === 'inspector' ? (
        <PropertyPanel />
      ) : (
        /* Mode 2: Copilot Chat */
        <div className="flex-1 flex flex-col overflow-hidden bg-canvas">
          {/* Main Agent Dialogue Header with Context Usage Progress */}
          <div className="px-3 py-2 border-b border-line bg-panel flex items-center justify-between shrink-0">
            <div className="flex items-center gap-1.5 text-xs text-secondary font-medium">
              <Bot className="w-3.5 h-3.5 text-blue-600" />
              <span className="font-semibold text-main">主 Agent 协同工作台</span>
              <span className="text-[10px] text-muted">（唯一对外对话）</span>
            </div>
            {contextUsage && (
              <ContextUsageIndicator
                percentage={contextUsage.usage_percent}
                currentTokens={contextUsage.current_tokens}
                maxTokens={contextUsage.max_tokens}
                isCompressed={contextUsage.is_compressed}
                limitKey={contextUsage.context_limit_key}
              />
            )}
          </div>

          {/* Messages Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
            {messages.map((msg) => {
              const isUser = msg.role === 'user'
              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} space-y-1.5`}
                >
                  <div className="flex items-center gap-1.5 text-[10px] text-muted px-1 font-medium">
                    {isUser ? (
                      <>
                        <span>你</span>
                        <User className="w-3 h-3 text-muted" />
                      </>
                    ) : (
                      <>
                        <Bot className="w-3 h-3 text-blue-600" />
                        <span>PPT 协同架构师 (LangGraph)</span>
                      </>
                    )}
                  </div>

                  <div
                    className={`max-w-[92%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed whitespace-pre-wrap ${
                      isUser
                        ? 'bg-inverted text-inverted-text rounded-tr-none shadow-xs font-normal'
                        : 'bg-panel text-main border border-line rounded-tl-none shadow-xs'
                    }`}
                  >
                    {msg.content}
                  </div>

                  {/* Tool Calls: Architectural Action Log */}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="w-full pl-2 space-y-1.5 my-1">
                      {msg.toolCalls.map((tc, idx) => (
                        <div
                          key={idx}
                          className="bg-panel border border-line rounded-xl p-2.5 text-[11px] text-secondary shadow-xs"
                        >
                          <div className="flex items-center gap-1.5 text-main font-semibold mb-1">
                            <Wrench className="w-3 h-3 text-muted" />
                            <span className="font-tabular text-[11px] text-secondary">{tc.tool}</span>
                            <CheckCircle2 className="w-3 h-3 text-emerald-600 ml-auto" />
                          </div>
                          <div className="text-[10px] text-muted truncate font-tabular bg-subtle px-2 py-1 rounded border border-line">
                            {tc.result?.message || JSON.stringify(tc.arguments)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Vision Loop: Creative Director's Critique */}
                  {msg.visionCritique && (
                    <div className="w-full bg-panel border border-line rounded-xl p-3 my-1 text-xs text-secondary shadow-xs">
                      <div className="flex items-center gap-1.5 font-semibold text-main text-[11px] mb-1.5">
                        <Eye className="w-3.5 h-3.5 text-blue-600" />
                        <span>排版与视觉平衡自检 (Vision Loop)</span>
                      </div>
                      <p className="text-[11px] text-muted whitespace-pre-wrap leading-relaxed">
                        {msg.visionCritique}
                      </p>
                    </div>
                  )}

                  {/* Multidimensional Visual Quality Report */}
                  {msg.visualReview && (
                    <div className="w-full bg-panel border border-line rounded-xl p-3 my-1 text-xs text-secondary shadow-xs">
                      <div className="flex items-center justify-between font-semibold text-main text-[11px] mb-2 pb-1.5 border-b border-line">
                        <div className="flex items-center gap-1.5">
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                          <span>多维度视觉健康评分</span>
                        </div>
                        <span className="font-tabular font-bold text-emerald-600">
                          {msg.visualReview.score.toFixed(1)} / 100
                        </span>
                      </div>

                      {msg.visualReview.quality_score && (
                        <div className="grid grid-cols-5 gap-1 mb-2 text-center text-[9px]">
                          <div className="bg-subtle border border-line rounded px-1 py-1">
                            <div className="text-muted">几何 (30%)</div>
                            <div className="font-tabular font-semibold text-main">
                              {msg.visualReview.quality_score.geometry.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-subtle border border-line rounded px-1 py-1">
                            <div className="text-muted">可读 (20%)</div>
                            <div className="font-tabular font-semibold text-main">
                              {msg.visualReview.quality_score.readability.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-subtle border border-line rounded px-1 py-1">
                            <div className="text-muted">对比 (15%)</div>
                            <div className="font-tabular font-semibold text-main">
                              {msg.visualReview.quality_score.contrast.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-subtle border border-line rounded px-1 py-1">
                            <div className="text-muted">平衡 (15%)</div>
                            <div className="font-tabular font-semibold text-main">
                              {msg.visualReview.quality_score.balance.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-subtle border border-line rounded px-1 py-1">
                            <div className="text-muted">美观 (20%)</div>
                            <div className="font-tabular font-semibold text-main">
                              {(msg.visualReview.quality_score.aesthetics ?? 100).toFixed(0)}
                            </div>
                          </div>
                        </div>
                      )}

                      {msg.visualReview.defects_count !== undefined && msg.visualReview.defects_count > 0 && (
                        <div className="text-[10px] text-muted flex items-center gap-1 font-medium">
                          <Activity className="w-3 h-3 text-sky-600 shrink-0" />
                          <span>
                            检测到 {msg.visualReview.defects_count} 项排版特征
                            {msg.visualReview.needs_auto_correction ? '，已通过闭环事务自动修复' : '，排版指标良好'}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}

            {isAgentThinking && (
              <div className="bg-panel border border-line-strong rounded-xl p-3 text-xs text-secondary space-y-2 shadow-xs">
                <div className="flex items-center gap-2.5">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600 shrink-0" />
                  <span className="truncate font-semibold text-main">{thinkingStatus || 'Agent 正在规划排版策略...'}</span>
                </div>

                {/* Generation stage progress (paper analysis -> preview -> critics) */}
                {generationStage && (generationStage.phase || generationStage.status) && (
                  <div className="bg-subtle border border-line rounded-lg p-2 text-[10px] text-muted space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-800 font-semibold">
                        {generationStage.phase || generationStage.status}
                      </span>
                      {generationStage.total ? (
                        <span className="font-tabular text-indigo-600 font-bold">
                          {generationStage.current ?? 0} / {generationStage.total}
                        </span>
                      ) : null}
                    </div>
                  </div>
                )}

                {/* Real-time Visual Remediation Telemetry Banner */}
                {visualRemediation && (
                  <div className="bg-subtle border border-line rounded-lg p-2 text-[10px] text-muted space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 font-semibold">
                        {visualRemediation.phase === 'evaluating' && '体检中'}
                        {visualRemediation.phase === 'diagnosed' && '已诊断'}
                        {visualRemediation.phase === 'fixing' && '自愈中'}
                        {visualRemediation.phase === 'committed' && '已提交'}
                        {visualRemediation.phase === 'rolled_back' && '已回滚'}
                      </span>
                      {visualRemediation.score !== undefined && (
                        <span className="font-tabular text-emerald-600 font-bold">
                          当前得分: {visualRemediation.score.toFixed(1)}
                        </span>
                      )}
                    </div>

                    {visualRemediation.quality_score && (
                      <div className="flex gap-2 text-[9px] text-muted font-tabular">
                        <span>几何:{visualRemediation.quality_score.geometry.toFixed(0)}</span>
                        <span>可读:{visualRemediation.quality_score.readability.toFixed(0)}</span>
                        <span>对比:{visualRemediation.quality_score.contrast.toFixed(0)}</span>
                        <span>平衡:{visualRemediation.quality_score.balance.toFixed(0)}</span>
                        <span>美观:{(visualRemediation.quality_score.aesthetics ?? 100).toFixed(0)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input Box */}
          <form
            onSubmit={handleSubmit}
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(e) => { e.preventDefault(); setIsDragging(false); addFiles(e.dataTransfer?.files) }}
            className={`p-3 border-t bg-panel transition-colors ${isDragging ? 'border-blue-400 bg-blue-50/40' : 'border-line'}`}
          >
            {/* Slash-command palette */}
            {paletteOpen && (
              <div className="mb-2 border border-line rounded-xl bg-panel shadow-md overflow-hidden">
                {filteredCommands.map((command, idx) => {
                  const Icon = command.icon
                  const active = idx === activeCommandIndex
                  return (
                    <button
                      key={command.name}
                      type="button"
                      onMouseEnter={() => setActiveCommandIndex(idx)}
                      onClick={() => {
                        runCommand(command, '')
                        setInput('')
                      }}
                      className={`w-full flex items-start gap-2 px-3 py-2 text-left transition-colors ${
                        active ? 'bg-blue-50' : 'hover:bg-subtle'
                      }`}
                    >
                      <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${active ? 'text-blue-600' : 'text-muted'}`} />
                      <span className="min-w-0">
                        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-main">
                          /{command.name}
                          {command.argsPlaceholder && (
                            <span className="text-[9px] text-muted font-normal">{command.argsPlaceholder}</span>
                          )}
                        </span>
                        <span className="block text-[10px] text-muted truncate">{command.description}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}

            {/* Plan mode indicator */}
            {interactionMode === 'plan' && (
              <div className="mb-2 flex items-center gap-1.5 text-[10px] text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1">
                <Zap className="w-3 h-3" />
                <span className="font-medium">计划模式已开启：每个任务先出计划，确认后执行</span>
                <button
                  type="button"
                  onClick={() => setInteractionMode('auto')}
                  className="ml-auto text-amber-700 hover:text-amber-900"
                  aria-label="关闭计划模式"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            )}

            {/* Pending plan / confirmation gates */}
            {pendingPlan && (
              <div className="mb-2">
                <PlanCard
                  plan={pendingPlan}
                  onConfirm={confirmPlan}
                  onCancel={cancelPlan}
                  disabled={isAgentThinking}
                />
              </div>
            )}
            {pendingConfirmation && (
              <div className="mb-2">
                <ConfirmationCard
                  confirmation={pendingConfirmation}
                  onConfirm={confirmConfirmation}
                  onCancel={cancelConfirmation}
                  disabled={isAgentThinking}
                />
              </div>
            )}

            {/* Attachment chips */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {attachments.map((att) => (
                  <div
                    key={att.id}
                    className="flex items-center gap-1.5 bg-subtle border border-line rounded-lg pl-1.5 pr-1 py-1 text-[10px] text-secondary max-w-[190px]"
                    title={att.name}
                  >
                    {att.previewUrl ? (
                      <img src={att.previewUrl} alt={att.name} className="w-5 h-5 rounded object-cover shrink-0" />
                    ) : (
                      <AttachmentIcon kind={att.kind} className="w-3.5 h-3.5 text-muted shrink-0" />
                    )}
                    <span className="truncate font-medium">{att.name}</span>
                    <button
                      type="button"
                      onClick={() => removeAttachment(att.id)}
                      className="p-0.5 rounded hover:bg-elevated text-muted hover:text-main shrink-0"
                      aria-label={`移除 ${att.name}`}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="relative flex items-center bg-subtle rounded-xl border border-line-strong focus-within:border-blue-500 transition-colors">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.pptx,.txt,.md,.markdown,.csv,.tsv,.json,.log,.rst,.yaml,.yml,image/*"
                onChange={handleFileSelect}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isAgentThinking}
                className="absolute left-2 bottom-2 p-1.5 rounded-lg text-muted hover:text-main hover:bg-elevated disabled:opacity-30 transition-colors"
                title="添加附件（PDF / PPTX / 图片 / 文档，也可粘贴或拖拽）"
                aria-label="添加附件"
              >
                <Paperclip className="w-3.5 h-3.5" />
              </button>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => handleInputChange(e.target.value)}
                onKeyDown={handleKeyDown}
                onPaste={handlePaste}
                rows={2}
                placeholder="输入需求，或输入 / 使用快捷功能，也可粘贴/拖入文件..."
                className="w-full bg-transparent text-xs text-main placeholder-line-focus pl-9 pr-3 py-2.5 resize-none focus:outline-none leading-relaxed"
              />
              <button
                type="submit"
                disabled={(!input.trim() && attachments.length === 0) || isAgentThinking}
                className="absolute right-2 bottom-2 p-1.5 rounded-lg bg-inverted hover:bg-inverted-hover disabled:opacity-30 disabled:hover:bg-inverted text-inverted-text transition-all shadow-xs"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-[10px] text-muted mt-1.5 px-1 font-medium">
              Enter 发送 · Shift+Enter 换行 · 输入 / 快捷功能 · 支持粘贴/拖拽附件
            </p>
          </form>
        </div>
      )}
    </aside>
  )
}
