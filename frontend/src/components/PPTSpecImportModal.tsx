import React, { useState } from 'react'
import {
  X, Copy, Check, Sparkles, AlertCircle, AlertTriangle,
  FileText, Image as ImageIcon, Loader2, ArrowRight
} from 'lucide-react'
import { usePPTStore } from '../store/usePPTStore'

interface AssetRequirement {
  slide_id: string
  asset_type: 'figure' | 'table'
  label: string
  page?: number | null
  caption?: string | null
}

interface NormalizationResult {
  valid: boolean
  normalization_id: string | null
  spec: any
  warnings: string[]
  errors: string[]
  summary: {
    slides?: number
    claims?: number
    metrics?: number
    figures?: number
    complete_tables?: number
    table_placeholders?: number
  }
  asset_requirements: AssetRequirement[]
}

export const PPTSpecImportModal: React.FC = () => {
  const { pptspecModalOpen, setPptspecModalOpen, sessionId, setPresentation } = usePPTStore()

  const [rawInput, setRawInput] = useState('')
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null)
  const [isNormalizing, setIsNormalizing] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [normResult, setNormResult] = useState<NormalizationResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  if (!pptspecModalOpen) return null

  const handleCopyPrompt = async (type: 'general' | 'strict') => {
    try {
      const res = await fetch(`/api/pptspec/prompts/${type}`)
      if (!res.ok) throw new Error('获取提示词失败')
      const data = await res.json()
      await navigator.clipboard.writeText(data.prompt)
      const label = type === 'general' ? '通用论文分析提示词' : '严格 JSON 提示词（含 Schema）'
      setCopyFeedback(`已复制${label}到剪贴板！`)
      setTimeout(() => setCopyFeedback(null), 3000)
    } catch (err: any) {
      alert(`复制失败: ${err.message}`)
    }
  }

  const handleNormalize = async () => {
    if (!rawInput.trim() || isNormalizing) return
    setIsNormalizing(true)
    setErrorMessage(null)
    setNormResult(null)

    try {
      const res = await fetch('/api/pptspec/normalize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: rawInput }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || '解析失败')
      }
      const data: NormalizationResult = await res.json()
      setNormResult(data)
    } catch (err: any) {
      setErrorMessage(err.message || '解析请求发生异常')
    } finally {
      setIsNormalizing(false)
    }
  }

  const handleGenerate = async () => {
    if (!normResult?.normalization_id || !normResult.valid || isGenerating) return
    setIsGenerating(true)
    setErrorMessage(null)

    try {
      const res = await fetch('/api/pptspec/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          normalization_id: normResult.normalization_id,
          session_id: sessionId,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || '生成失败')
      }

      const data = await res.json()
      if (data.presentation) {
        setPresentation(data.presentation)
      }
      setPptspecModalOpen(false)
    } catch (err: any) {
      setErrorMessage(`生成中断: ${err.message}`)
    } finally {
      setIsGenerating(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
      <div className="w-full max-w-3xl max-h-[90vh] bg-[#10121A] border border-[#232635] rounded-2xl shadow-2xl flex flex-col overflow-hidden text-[#E2E5F0]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-[#1E2130] flex items-center justify-between bg-[#141622]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white tracking-tight">
                AI 分析结果生成 PPT (PR13)
              </h2>
              <p className="text-xs text-[#8A8F9E]">
                使用外部 AI (ChatGPT/Claude/Gemini/Qwen) 分析论文后，将结果粘贴到此处。
              </p>
            </div>
          </div>
          <button
            onClick={() => setPptspecModalOpen(false)}
            className="p-1.5 rounded-lg text-[#717688] hover:text-white hover:bg-[#1E2130] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-5 custom-scrollbar">
          {/* Prompt Copy Buttons */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={() => handleCopyPrompt('general')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#1B1E2B] hover:bg-[#25293A] border border-[#2D3145] text-[#D8DAE5] hover:text-white transition-all shadow-sm"
            >
              <Copy className="w-3.5 h-3.5 text-blue-400" />
              <span>复制通用论文分析提示词</span>
            </button>
            <button
              onClick={() => handleCopyPrompt('strict')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-[#1B1E2B] hover:bg-[#25293A] border border-[#2D3145] text-[#D8DAE5] hover:text-white transition-all shadow-sm"
            >
              <Copy className="w-3.5 h-3.5 text-emerald-400" />
              <span>复制严格 JSON 提示词</span>
            </button>
            {copyFeedback && (
              <span className="flex items-center gap-1 text-xs text-emerald-400 animate-fade-in">
                <Check className="w-3.5 h-3.5" />
                {copyFeedback}
              </span>
            )}
          </div>

          {/* Paste Textarea */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[#9AA0B4]">外部 AI 输出内容：</label>
            <textarea
              rows={8}
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
              placeholder="在此粘贴外部 AI 输出的 Markdown 大纲、JSON、包含 ```json 代码块的内容或中文页面大纲..."
              className="w-full bg-[#0C0D13] border border-[#222533] focus:border-blue-500 rounded-xl p-3 text-xs text-[#E1E4F0] placeholder-[#55596D] focus:outline-none transition-all font-mono leading-relaxed"
            />
          </div>

          {/* Parse Button */}
          <div className="flex justify-start">
            <button
              onClick={handleNormalize}
              disabled={!rawInput.trim() || isNormalizing}
              className="flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:hover:bg-blue-600 text-white transition-all shadow-md"
            >
              {isNormalizing ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>正在智能归一化与校验...</span>
                </>
              ) : (
                <>
                  <FileText className="w-3.5 h-3.5" />
                  <span>解析内容</span>
                </>
              )}
            </button>
          </div>

          {/* Error Banner */}
          {errorMessage && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl flex items-start gap-2.5 text-xs text-red-400">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <div className="flex-1 whitespace-pre-line">{errorMessage}</div>
            </div>
          )}

          {/* Normalization Preview Result */}
          {normResult && (
            <div className="space-y-4 pt-2 border-t border-[#1C1F2B]">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-1.5">
                  <Check className="w-4 h-4 text-emerald-400" />
                  <span>解析完成预览</span>
                </h3>
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                  normResult.valid ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'
                }`}>
                  {normResult.valid ? '校验通过 (Ready)' : '校验未通过 (Invalid)'}
                </span>
              </div>

              {/* Summary Stats Badges */}
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
                <div className="bg-[#141620] border border-[#232635] p-2.5 rounded-xl text-center">
                  <div className="text-[11px] text-[#7A7F92]">Slides</div>
                  <div className="text-base font-bold text-white mt-0.5">{normResult.summary.slides || 0}</div>
                </div>
                <div className="bg-[#141620] border border-[#232635] p-2.5 rounded-xl text-center">
                  <div className="text-[11px] text-[#7A7F92]">Claims</div>
                  <div className="text-base font-bold text-white mt-0.5">{normResult.summary.claims || 0}</div>
                </div>
                <div className="bg-[#141620] border border-[#232635] p-2.5 rounded-xl text-center">
                  <div className="text-[11px] text-[#7A7F92]">Metrics</div>
                  <div className="text-base font-bold text-blue-400 mt-0.5">{normResult.summary.metrics || 0}</div>
                </div>
                <div className="bg-[#141620] border border-[#232635] p-2.5 rounded-xl text-center">
                  <div className="text-[11px] text-[#7A7F92]">Figures</div>
                  <div className="text-base font-bold text-purple-400 mt-0.5">{normResult.summary.figures || 0}</div>
                </div>
                <div className="bg-[#141620] border border-[#232635] p-2.5 rounded-xl text-center">
                  <div className="text-[11px] text-[#7A7F92]">Full Tables</div>
                  <div className="text-base font-bold text-emerald-400 mt-0.5">{normResult.summary.complete_tables || 0}</div>
                </div>
                <div className="bg-[#141620] border border-[#232635] p-2.5 rounded-xl text-center">
                  <div className="text-[11px] text-[#7A7F92]">Table Placeh.</div>
                  <div className="text-base font-bold text-amber-400 mt-0.5">{normResult.summary.table_placeholders || 0}</div>
                </div>
              </div>

              {/* Asset Requirements Checklist */}
              {normResult.asset_requirements.length > 0 && (
                <div className="bg-[#141620] border border-[#232635] rounded-xl p-3.5 space-y-2">
                  <div className="text-xs font-medium text-[#C0C4D5] flex items-center gap-1.5">
                    <ImageIcon className="w-3.5 h-3.5 text-blue-400" />
                    <span>需要手动插入资源清单（生成后在 PPT 中粘贴）：</span>
                  </div>
                  <div className="space-y-1.5 max-h-36 overflow-y-auto custom-scrollbar">
                    {normResult.asset_requirements.map((asset, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs text-[#959AB0] bg-[#0E1017] px-2.5 py-1.5 rounded-lg border border-[#1E212E]">
                        <span className="font-mono text-blue-400">{asset.slide_id}</span>
                        <span>→</span>
                        <span className="text-white font-medium">{asset.label}</span>
                        {asset.page && <span className="text-[#656A7D]">(论文第 {asset.page} 页)</span>}
                        {asset.caption && <span className="text-[#72778A] truncate max-w-[240px]">- {asset.caption}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Warnings */}
              {normResult.warnings.length > 0 && (
                <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl space-y-1 text-xs text-amber-300">
                  <div className="font-medium flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                    <span>规范性提示 (Warnings):</span>
                  </div>
                  <ul className="list-disc list-inside space-y-0.5 text-amber-200/80">
                    {normResult.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Errors */}
              {normResult.errors.length > 0 && (
                <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl space-y-1 text-xs text-red-300">
                  <div className="font-medium flex items-center gap-1.5">
                    <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                    <span>真实性/合法性错误 (Errors):</span>
                  </div>
                  <ul className="list-disc list-inside space-y-0.5 text-red-200">
                    {normResult.errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3.5 border-t border-[#1E2130] flex items-center justify-between bg-[#141622]">
          <span className="text-xs text-[#6B7082]">
            {normResult?.valid
              ? '结构归一化已通过 Truthfulness Guard，可启动 LangGraph 生成。'
              : '请先解析内容并确保无阻止性错误。'}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPptspecModalOpen(false)}
              className="px-3 py-1.5 text-xs font-medium rounded-lg text-[#9AA0B4] hover:text-white hover:bg-[#1C1F2D] transition-colors"
            >
              取消
            </button>
            <button
              onClick={handleGenerate}
              disabled={!normResult?.valid || !normResult?.normalization_id || isGenerating}
              className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-30 disabled:hover:bg-emerald-600 text-white transition-all shadow-md font-semibold"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>LangGraph 执行中...</span>
                </>
              ) : (
                <>
                  <span>确认生成 PPT</span>
                  <ArrowRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
