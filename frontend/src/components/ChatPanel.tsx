import React, { useState, useRef, useEffect } from 'react'
import {
  Send, Sparkles, Wrench, Eye, CheckCircle2,
  Bot, User, Loader2, SlidersHorizontal
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
                </div>
              )
            })}

            {isAgentThinking && (
              <div className="flex items-center gap-2.5 bg-[#14151E] border border-[#262939] rounded-xl p-3 text-xs text-[#C8CBD8]">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-[#F1F2F6] shrink-0" />
                <span className="truncate">{thinkingStatus || 'Agent 正在规划排版策略...'}</span>
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
