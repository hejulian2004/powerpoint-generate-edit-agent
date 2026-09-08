import React, { useState, useRef, useEffect } from 'react'
import {
  Send, Sparkles, Wrench, Eye, CheckCircle2,
  Bot, User, Loader2, Sliders
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'
import { PropertyPanel } from './PropertyPanel'

const QUICK_PROMPTS = [
  '为当前页添加 3 个特性卡片',
  '自动规整当前页卡片排版',
  '将主题切换为深色科技风格',
  '添加从卡片 1 指向卡片 2 的连接线',
  '优化当前页的标题层级与字号'
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
    <aside className="w-[380px] bg-slate-950 border-l border-slate-800/80 flex flex-col shrink-0 h-full overflow-hidden select-none">
      {/* Segmented Tab Switcher */}
      <div className="h-12 px-3 border-b border-slate-800/80 flex items-center justify-between bg-slate-950 shrink-0">
        <div className="flex bg-slate-900 p-1 rounded-xl border border-slate-800/90 text-xs font-medium w-full">
          <button
            onClick={() => setActiveRightTab('copilot')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg transition ${
              activeRightTab === 'copilot'
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>AI Copilot</span>
          </button>
          <button
            onClick={() => setActiveRightTab('inspector')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg transition ${
              activeRightTab === 'inspector'
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
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
                  <div className="flex items-center gap-1.5 text-[10px] text-slate-500 px-1">
                    {isUser ? (
                      <>
                        <span>你</span>
                        <User className="w-3 h-3 text-slate-400" />
                      </>
                    ) : (
                      <>
                        <Bot className="w-3 h-3 text-blue-400" />
                        <span>PPT Agent</span>
                      </>
                    )}
                  </div>

                  <div
                    className={`max-w-[90%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed whitespace-pre-wrap ${
                      isUser
                        ? 'bg-blue-600 text-white rounded-tr-none shadow-md shadow-blue-600/20'
                        : 'bg-slate-900 text-slate-200 border border-slate-800 rounded-tl-none shadow-sm'
                    }`}
                  >
                    {msg.content}
                  </div>

                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="w-full pl-2 space-y-1 my-1">
                      {msg.toolCalls.map((tc, idx) => (
                        <div
                          key={idx}
                          className="bg-slate-900/90 border border-slate-800/90 rounded-xl p-2.5 text-[11px] font-mono text-slate-300 shadow-sm"
                        >
                          <div className="flex items-center gap-1.5 text-blue-400 font-semibold mb-0.5">
                            <Wrench className="w-3 h-3" />
                            <span>{tc.tool}</span>
                            <CheckCircle2 className="w-3 h-3 text-emerald-400 ml-auto" />
                          </div>
                          <div className="text-[10px] text-slate-400 truncate font-mono">
                            {tc.result?.message || JSON.stringify(tc.arguments)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {msg.visionCritique && (
                    <div className="w-full bg-indigo-950/40 border border-indigo-500/30 rounded-xl p-3 my-1 text-xs text-indigo-200">
                      <div className="flex items-center gap-1.5 font-semibold text-indigo-400 text-[11px] mb-1">
                        <Eye className="w-3.5 h-3.5" />
                        <span>Vision Loop 视觉自省</span>
                      </div>
                      <p className="text-[11px] text-indigo-200/90 whitespace-pre-wrap leading-relaxed">
                        {msg.visionCritique}
                      </p>
                    </div>
                  )}
                </div>
              )
            })}

            {isAgentThinking && (
              <div className="flex items-center gap-2 bg-blue-950/30 border border-blue-500/30 rounded-xl p-3 text-xs text-blue-300 animate-pulse">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-400 shrink-0" />
                <span className="truncate">{thinkingStatus || 'Agent 正在规划修改...'}</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Quick Prompt Suggestions */}
          <div className="px-3 py-2 border-t border-slate-800/60 bg-slate-950">
            <div className="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar">
              {QUICK_PROMPTS.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => sendChatMessage(prompt)}
                  disabled={isAgentThinking}
                  className="text-[11px] whitespace-nowrap px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 hover:border-slate-700 transition disabled:opacity-40"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>

          {/* Input Box */}
          <form onSubmit={handleSubmit} className="p-3 border-t border-slate-800 bg-slate-950">
            <div className="relative flex items-center bg-slate-900 rounded-xl border border-slate-800 focus-within:border-blue-500 transition">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={2}
                placeholder="给 Agent 下达排版或内容修改指令..."
                className="w-full bg-transparent text-xs text-slate-100 placeholder-slate-500 px-3 py-2 resize-none focus:outline-none"
              />
              <button
                type="submit"
                disabled={!input.trim() || isAgentThinking}
                className="absolute right-2 bottom-2 p-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-30 disabled:hover:bg-blue-600 text-white transition shadow-sm"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-[10px] text-slate-500 mt-1.5 px-1">
              按 Enter 发送 · Shift+Enter 换行
            </p>
          </form>
        </div>
      )}
    </aside>
  )
}
