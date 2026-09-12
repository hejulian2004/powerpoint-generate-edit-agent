import React, { useState, useRef, useEffect } from 'react'
import {
  Send, Sparkles, Wrench, Eye, CheckCircle2,
  Bot, User, Loader2, SlidersHorizontal, ShieldCheck, Activity
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { PropertyPanel } from './PropertyPanel'
import { ContextUsageIndicator } from './ContextUsageIndicator'

const QUICK_PROMPTS = [
  '一键生成《AI Agent 架构》完整PPT',
  '排版生成发展历程时间线',
  '生成 3 栏核心特性卡片',
  '生成核心效能 KPI 指标卡',
  '两栏对比：传统模式 vs 智能协同',
  '自动规整当前页卡片对齐与间距',
  '切换为钛金黑曜深色主题'
]

export const ChatPanel: React.FC = () => {
  const {
    messages,
    isAgentThinking,
    thinkingStatus,
    visualRemediation,
    generationStage,
    contextUsage,
    sendChatMessage,
    activeRightTab,
    setActiveRightTab,
    selectedElementId
  } = usePPTStore()

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isAgentThinking])

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!input.trim() || isAgentThinking) return
    sendChatMessage(input)
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
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

          {/* Quick Prompt Suggestions */}
          <div className="px-3 py-2 border-t border-line bg-panel">
            <div className="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar">
              {QUICK_PROMPTS.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => sendChatMessage(prompt)}
                  disabled={isAgentThinking}
                  className="text-[11px] whitespace-nowrap px-2.5 py-1 rounded-lg bg-elevated hover:bg-line text-secondary hover:text-main border border-line font-medium transition-all disabled:opacity-40"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          {/* Input Box */}
          <form onSubmit={handleSubmit} className="p-3 border-t border-line bg-panel">
            <div className="relative flex items-center bg-subtle rounded-xl border border-line-strong focus-within:border-blue-500 transition-colors">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                placeholder="输入排版需求或微调指令..."
                className="w-full bg-transparent text-xs text-main placeholder-line-focus px-3 py-2.5 resize-none focus:outline-none leading-relaxed"
              />
              <button
                type="submit"
                disabled={!input.trim() || isAgentThinking}
                className="absolute right-2 bottom-2 p-1.5 rounded-lg bg-inverted hover:bg-inverted-hover disabled:opacity-30 disabled:hover:bg-inverted text-inverted-text transition-all shadow-xs"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-[10px] text-muted mt-1.5 px-1 font-medium">
              Enter 发送 · Shift+Enter 换行
            </p>
          </form>
        </div>
      )}
    </aside>
  )
}
