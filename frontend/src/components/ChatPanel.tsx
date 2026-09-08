import React, { useState, useRef, useEffect } from 'react'
import {
  Send, Sparkles, Wrench, Eye, CheckCircle2,
  Bot, User, Loader2, SlidersHorizontal, ShieldCheck, Activity
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { PropertyPanel } from './PropertyPanel'

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
    <aside className="w-[390px] bg-[#0D0E13] border-l border-[#1F212B] flex flex-col shrink-0 h-full overflow-hidden select-none">
      {/* Segmented Tab Switcher */}
      <div className="h-12 px-3 border-b border-[#1F212B] flex items-center justify-between bg-[#0E0F14] shrink-0">
        <div className="flex bg-[#13141B] p-1 rounded-xl border border-[#212330] text-xs font-medium w-full">
          <button
            onClick={() => setActiveRightTab('copilot')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg transition-all ${
              activeRightTab === 'copilot'
                ? 'bg-[#F1F2F6] text-[#0A0B0E] font-semibold shadow-sm'
                : 'text-[#82869A] hover:text-[#F1F2F6]'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI 协同设计</span>
          </button>
          <button
            onClick={() => setActiveRightTab('inspector')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg transition-all ${
              activeRightTab === 'inspector'
                ? 'bg-[#F1F2F6] text-[#0A0B0E] font-semibold shadow-sm'
                : 'text-[#82869A] hover:text-[#F1F2F6]'
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
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Messages Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
            {messages.map((msg) => {
              const isUser = msg.role === 'user'
              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} space-y-1.5`}
                >
                  <div className="flex items-center gap-1.5 text-[10px] text-[#63677A] px-1">
                    {isUser ? (
                      <>
                        <span>你</span>
                        <User className="w-3 h-3 text-[#7B7F92]" />
                      </>
                    ) : (
                      <>
                        <Bot className="w-3 h-3 text-[#7B7F92]" />
                        <span>PPT 协同架构师 (LangGraph)</span>
                      </>
                    )}
                  </div>

                  <div
                    className={`max-w-[92%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed whitespace-pre-wrap ${
                      isUser
                        ? 'bg-[#F1F2F6] text-[#0A0B0E] rounded-tr-none shadow-sm font-normal'
                        : 'bg-[#14151E] text-[#D8DAE5] border border-[#232533] rounded-tl-none shadow-sm'
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
                          className="bg-[#111219] border border-[#212330] rounded-xl p-2.5 text-[11px] text-[#C2C6D6] shadow-sm"
                        >
                          <div className="flex items-center gap-1.5 text-[#F1F2F6] font-medium mb-1">
                            <Wrench className="w-3 h-3 text-[#73778A]" />
                            <span className="font-tabular text-[11px] text-[#A2A6B7]">{tc.tool}</span>
                            <CheckCircle2 className="w-3 h-3 text-emerald-400 ml-auto" />
                          </div>
                          <div className="text-[10px] text-[#787C8F] truncate font-tabular bg-[#0D0E13] px-2 py-1 rounded border border-[#1A1C26]">
                            {tc.result?.message || JSON.stringify(tc.arguments)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Vision Loop: Creative Director's Critique */}
                  {msg.visionCritique && (
                    <div className="w-full bg-[#12131C] border border-[#303345] rounded-xl p-3 my-1 text-xs text-[#C8CBD8]">
                      <div className="flex items-center gap-1.5 font-medium text-[#F1F2F6] text-[11px] mb-1.5">
                        <Eye className="w-3.5 h-3.5 text-[#888C9E]" />
                        <span>排版与视觉平衡自检 (Vision Loop)</span>
                      </div>
                      <p className="text-[11px] text-[#9EA2B4] whitespace-pre-wrap leading-relaxed">
                        {msg.visionCritique}
                      </p>
                    </div>
                  )}

                  {/* Multidimensional Visual Quality Report */}
                  {msg.visualReview && (
                    <div className="w-full bg-[#11121A] border border-[#262838] rounded-xl p-3 my-1 text-xs text-[#C8CBD8]">
                      <div className="flex items-center justify-between font-medium text-[#F1F2F6] text-[11px] mb-2 pb-1.5 border-b border-[#1D1F2C]">
                        <div className="flex items-center gap-1.5">
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                          <span>多维度视觉健康评分</span>
                        </div>
                        <span className="font-tabular font-semibold text-emerald-400">
                          {msg.visualReview.score.toFixed(1)} / 100
                        </span>
                      </div>

                      {msg.visualReview.quality_score && (
                        <div className="grid grid-cols-4 gap-1.5 mb-2 text-center text-[10px]">
                          <div className="bg-[#171824] rounded px-1 py-1">
                            <div className="text-[#7A7E92]">几何 (40%)</div>
                            <div className="font-tabular font-medium text-[#E2E4ED]">
                              {msg.visualReview.quality_score.geometry.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-[#171824] rounded px-1 py-1">
                            <div className="text-[#7A7E92]">可读 (25%)</div>
                            <div className="font-tabular font-medium text-[#E2E4ED]">
                              {msg.visualReview.quality_score.readability.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-[#171824] rounded px-1 py-1">
                            <div className="text-[#7A7E92]">对比 (15%)</div>
                            <div className="font-tabular font-medium text-[#E2E4ED]">
                              {msg.visualReview.quality_score.contrast.toFixed(0)}
                            </div>
                          </div>
                          <div className="bg-[#171824] rounded px-1 py-1">
                            <div className="text-[#7A7E92]">平衡 (20%)</div>
                            <div className="font-tabular font-medium text-[#E2E4ED]">
                              {msg.visualReview.quality_score.balance.toFixed(0)}
                            </div>
                          </div>
                        </div>
                      )}

                      {msg.visualReview.defects_count !== undefined && msg.visualReview.defects_count > 0 && (
                        <div className="text-[10px] text-[#8E92A6] flex items-center gap-1">
                          <Activity className="w-3 h-3 text-sky-400 shrink-0" />
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
              <div className="bg-[#14151E] border border-[#262939] rounded-xl p-3 text-xs text-[#C8CBD8] space-y-2">
                <div className="flex items-center gap-2.5">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-[#F1F2F6] shrink-0" />
                  <span className="truncate font-medium">{thinkingStatus || 'Agent 正在规划排版策略...'}</span>
                </div>

                {/* Real-time Visual Remediation Telemetry Banner */}
                {visualRemediation && (
                  <div className="bg-[#0F1017] border border-[#212332] rounded-lg p-2 text-[10px] text-[#9A9EB2] space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#1C1E2A] text-[#C4C7D7] font-medium">
                        {visualRemediation.phase === 'evaluating' && '体检中'}
                        {visualRemediation.phase === 'diagnosed' && '已诊断'}
                        {visualRemediation.phase === 'fixing' && '自愈中'}
                        {visualRemediation.phase === 'committed' && '已提交'}
                        {visualRemediation.phase === 'rolled_back' && '已回滚'}
                      </span>
                      {visualRemediation.score !== undefined && (
                        <span className="font-tabular text-emerald-400 font-semibold">
                          当前得分: {visualRemediation.score.toFixed(1)}
                        </span>
                      )}
                    </div>

                    {visualRemediation.quality_score && (
                      <div className="flex gap-2 text-[9px] text-[#7B7F94] font-tabular">
                        <span>几何:{visualRemediation.quality_score.geometry.toFixed(0)}</span>
                        <span>可读:{visualRemediation.quality_score.readability.toFixed(0)}</span>
                        <span>对比:{visualRemediation.quality_score.contrast.toFixed(0)}</span>
                        <span>平衡:{visualRemediation.quality_score.balance.toFixed(0)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick Prompt Suggestions */}
          <div className="px-3 py-2 border-t border-[#1F212B] bg-[#0D0E13]">
            <div className="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar">
              {QUICK_PROMPTS.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => sendChatMessage(prompt)}
                  disabled={isAgentThinking}
                  className="text-[11px] whitespace-nowrap px-2.5 py-1 rounded-lg bg-[#14151D] hover:bg-[#1C1E2A] text-[#9A9EB0] hover:text-[#F1F2F6] border border-[#222533] hover:border-[#333649] transition-all disabled:opacity-40"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          {/* Input Box */}
          <form onSubmit={handleSubmit} className="p-3 border-t border-[#1F212B] bg-[#0E0F14]">
            <div className="relative flex items-center bg-[#13141C] rounded-xl border border-[#232533] focus-within:border-[#52566A] transition-colors">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                placeholder="输入排版需求或微调指令..."
                className="w-full bg-transparent text-xs text-[#F1F2F6] placeholder-[#55586A] px-3 py-2.5 resize-none focus:outline-none leading-relaxed"
              />
              <button
                type="submit"
                disabled={!input.trim() || isAgentThinking}
                className="absolute right-2 bottom-2 p-1.5 rounded-lg bg-[#F1F2F6] hover:bg-white disabled:opacity-20 disabled:hover:bg-[#F1F2F6] text-[#0A0B0E] transition-all shadow-sm"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-[10px] text-[#55586A] mt-1.5 px-1">
              Enter 发送 · Shift+Enter 换行
            </p>
          </form>
        </div>
      )}
    </aside>
  )
}
