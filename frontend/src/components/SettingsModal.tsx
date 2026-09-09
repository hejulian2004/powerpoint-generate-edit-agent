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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm p-4 animate-in fade-in select-none">
      <div className="bg-panel border border-line rounded-2xl w-full max-w-lg shadow-2xl shadow-slate-300/50 overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-line bg-panel">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-muted" />
            <h2 className="text-sm font-semibold text-main">LLM Provider 与模型路由配置</h2>
          </div>
          <button
            onClick={() => setSettingsOpen(false)}
            className="p-1 rounded-lg text-muted hover:text-main hover:bg-elevated transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Form */}
        <form onSubmit={handleSave} className="p-6 space-y-4 bg-panel">
          <div>
            <label className="flex items-center gap-1.5 text-xs font-semibold text-secondary mb-1.5">
              <Server className="w-3.5 h-3.5 text-muted" />
              <span>OpenAI 兼容端点 (Base URL)</span>
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="w-full bg-subtle border border-line-strong rounded-lg px-3 py-2 text-xs text-main focus:outline-none focus:border-blue-500 font-tabular font-medium"
            />
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-xs font-semibold text-secondary mb-1.5">
              <Key className="w-3.5 h-3.5 text-muted" />
              <span>API Key</span>
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-...（留空则使用环境变量或本地仿真运行）"
              className="w-full bg-subtle border border-line-strong rounded-lg px-3 py-2 text-xs text-main focus:outline-none focus:border-blue-500 font-tabular font-medium"
            />
          </div>

          <div className="grid grid-cols-2 gap-3 pt-2">
            <div>
              <label className="text-xs font-semibold text-secondary block mb-1">
                规划模型 (Reasoning)
              </label>
              <input
                type="text"
                value={reasoningModel}
                onChange={(e) => setReasoningModel(e.target.value)}
                className="w-full bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary block mb-1">
                视觉自省模型 (Vision)
              </label>
              <input
                type="text"
                value={visionModel}
                onChange={(e) => setVisionModel(e.target.value)}
                className="w-full bg-subtle border border-line-strong rounded-lg px-2.5 py-1.5 text-xs text-main font-tabular font-medium focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="pt-2">
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={enableVisionLoop}
                onChange={(e) => setEnableVisionLoop(e.target.checked)}
                className="rounded bg-subtle border-line-strong text-main focus:ring-0 accent-inverted w-4 h-4 cursor-pointer"
              />
              <span className="text-xs font-medium text-secondary">
                启用多模态视觉闭环自检 (Vision Loop 自省优化)
              </span>
            </label>
          </div>

          <div className="pt-4 flex items-center justify-end gap-2.5 border-t border-line">
            <button
              type="button"
              onClick={() => setSettingsOpen(false)}
              className="px-4 py-2 text-xs font-medium text-muted hover:text-main transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-inverted hover:bg-inverted-hover disabled:opacity-50 text-inverted-text text-xs font-medium rounded-lg transition-all shadow-xs"
            >
              {savedSuccess ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  <span>已保存并应用</span>
                </>
              ) : (
                <span>保存配置</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
