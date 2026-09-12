// Editor-only (UI) types. These describe client state and chat rendering, not
// the canonical document contract. IR types live in `presentation-ir.generated.ts`.

import type { ElementIR, SlideIR } from './presentation-ir.generated'

export interface PatchRecord {
  id: string
  timestamp: number
  action: string
  description: string
  slide_id?: string
  element_id?: string
}

export interface VisualQualityScore {
  geometry: number
  readability: number
  contrast: number
  balance: number
  aesthetics: number
  total: number
}

export interface VisualRemediationEvent {
  type: 'visual_remediation'
  phase: 'evaluating' | 'diagnosed' | 'fixing' | 'committed' | 'rolled_back'
  status: string
  slide_id?: string
  text: string
  score?: number
  quality_score?: VisualQualityScore
  defects_count?: number
  critical_count?: number
  auto_executable_count?: number
  action?: Record<string, any>
  applied_count?: number
  applied_fixes?: any[]
  iteration?: number
  max_iterations?: number
  score_before?: number
  score_after?: number
  delta?: number
}

export interface ContextUsageData {
  current_tokens: number
  max_tokens: number
  usage_percent: number
  is_compressed: boolean
  compression_ratio: number
  tokens_saved: number
  context_limit_key: string
  threshold_reached: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  toolCalls?: Array<{
    tool: string
    arguments: any
    result?: any
    auto_correct?: boolean
    reason?: string
  }>
  visionCritique?: string
  visualReview?: {
    score: number
    quality_score?: VisualQualityScore
    defects_count?: number
    needs_auto_correction?: boolean
    critique_summary?: string
  }
  isStreaming?: boolean
}

export type MutationStatus = 'idle' | 'pending' | 'committed' | 'rolled_back' | 'resynced' | 'resyncing' | 'failed' | 'offline'

export interface PreviewUpdateEvent {
  type: 'preview_update'
  session_id: string
  slide_id: string
  svg: string
  score: number
  quality_score?: VisualQualityScore
  version: number
}

export interface PPTEditorState {
  slide: SlideIR | null
  selectedElement: ElementIR | null
  history: PatchRecord[]
  preview: {
    slide_id: string
    svg: string
    score?: number
    quality_score?: VisualQualityScore
  } | null
  agentStatus: {
    isThinking: boolean
    thinkingStatus: string
    visualRemediation?: VisualRemediationEvent | null
  }
  mutationStatus?: MutationStatus
}
