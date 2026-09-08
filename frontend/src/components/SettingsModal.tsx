import React, { useState, useEffect } from 'react'
import { X, Check, Key, Server, Cpu } from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'

export const SettingsModal: React.FC = () => {
  const { settingsOpen, setSettingsOpen } = usePPTStore()

  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1')
  const [apiKey, setApiKey] = useState('')
  const [defaultModel, setDefaultModel] = useState('gpt-4o')
  const [reasoningModel, setReasoningModel] = useState('gpt-4o')
  const [visionModel, setVisionModel] = useState('gpt-4o')
  const [fastModel, setFastModel] = useState('gpt-4o-mini')
  const [enableVisionLoop, setEnableVisionLoop] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savedSuccess, setSavedSuccess] = useState(false)

  useEffect(() => {
    if (settingsOpen) {
      fetch('/api/settings')
        .then((r) => r.json())
        .then((data) => {
          if (data.openai_base_url) setBaseUrl(data.openai_base_url)
          if (data.default_model) setDefaultModel(data.default_model)
          if (data.reasoning_model) setReasoningModel(data.reasoning_model)
          if (data.vision_model) setVisionModel(data.vision_model)
          if (data.fast_model) setFastModel(data.fast_model)
          if (data.enable_vision_loop !== undefined) setEnableVisionLoop(data.enable_vision_loop)
        })
        .catch(() => {})
    }
  }, [settingsOpen])

  if (!settingsOpen) return null

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          openai_base_url: baseUrl,
          openai_api_key: apiKey,
          default_model: defaultModel,
          reasoning_model: reasoningModel,
          vision_model: visionModel,
          fast_model: fastModel,
          enable_vision_loop: enableVisionLoop
        })
      })
      if (res.ok) {
        setSavedSuccess(true)
        setTimeout(() => {
          setSavedSuccess(false)
          setSettingsOpen(false)
        }, 800)
      }
    } catch (err) {
      alert(`保存失败: ${err}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in select-none">
      <div className="bg-[#0E0E0E] border border-[#222222] rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#222222]">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-neutral-200" />
            <h2 className="text-sm font-semibold text-white">LLM Provider 与模型路由配置</h2>
          </div>
          <button
            onClick={() => setSettingsOpen(false)}
            className="p-1 rounded-lg text-neutral-400 hover:text-white hover:bg-[#1E1E1E] transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSave} className="p-6 space-y-4">
          <div>
            <label className="flex items-center gap-1.5 text-xs font-medium text-neutral-300 mb-1.5">
              <Server className="w-3.5 h-3.5 text-neutral-400" />
              <span>OpenAI Compatible API Base URL</span>
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1 或兼容端点"
              className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2 text-xs text-neutral-100 focus:outline-none focus:border-white font-mono"
            />
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-xs font-medium text-neutral-300 mb-1.5">
              <Key className="w-3.5 h-3.5 text-neutral-400" />
              <span>API Key</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-...（留空则使用当前配置或测试模拟模式）"
              className="w-full bg-[#141414] border border-[#262626] rounded-lg px-3 py-2 text-xs text-neutral-100 focus:outline-none focus:border-white font-mono"
            />
          </div>

          <div className="grid grid-cols-2 gap-3 pt-2">
            <div>
              <label className="text-[11px] font-medium text-neutral-400 block mb-1">
                Reasoning Model (规划模型)
              </label>
              <input
                type="text"
                value={reasoningModel}
                onChange={(e) => setReasoningModel(e.target.value)}
                className="w-full bg-[#141414] border border-[#262626] rounded-lg px-2.5 py-1.5 text-xs text-neutral-200 font-mono focus:border-white"
              />
            </div>

            <div>
              <label className="text-[11px] font-medium text-neutral-400 block mb-1">
                Vision Model (视觉自省模型)
              </label>
              <input
                type="text"
                value={visionModel}
                onChange={(e) => setVisionModel(e.target.value)}
                className="w-full bg-[#141414] border border-[#262626] rounded-lg px-2.5 py-1.5 text-xs text-neutral-200 font-mono focus:border-white"
              />
            </div>
          </div>

          <div className="pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={enableVisionLoop}
                onChange={(e) => setEnableVisionLoop(e.target.checked)}
                className="rounded bg-[#141414] border-[#262626] text-white focus:ring-0 accent-white"
              />
              <span className="text-xs text-neutral-300">
                启用 Vision Loop 多模态视觉闭环自检
              </span>
            </label>
          </div>

          <div className="pt-4 flex items-center justify-end gap-2 border-t border-[#222222]">
            <button
              type="button"
              onClick={() => setSettingsOpen(false)}
              className="px-4 py-2 text-xs text-neutral-400 hover:text-white transition"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-white hover:bg-neutral-200 disabled:opacity-50 text-black text-xs font-semibold rounded-lg transition"
            >
              {savedSuccess ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  <span>已保存</span>
                </>
              ) : (
                <span>保存并应用</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
