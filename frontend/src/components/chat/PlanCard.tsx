import React from 'react'
import { ListChecks, Check, ShieldAlert } from 'lucide-react'
import type { PendingConfirmation, PendingPlan } from '../../store/usePPTStore'

interface PlanCardProps {
  plan: PendingPlan
  onConfirm: () => void
  onCancel: () => void
  disabled?: boolean
}

export const PlanCard: React.FC<PlanCardProps> = ({ plan, onConfirm, onCancel, disabled }) => {
  const review = plan.planReview || {}
  const approved = review.approved !== false

  return (
    <div className="border border-amber-300 bg-amber-50/60 rounded-xl p-3 space-y-2 shadow-xs">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-800">
        <ListChecks className="w-3.5 h-3.5" />
        <span>待确认计划</span>
        <span className={`ml-auto text-[9px] px-1.5 py-0.5 rounded font-medium ${
          approved ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-200 text-amber-900'
        }`}>
          {approved ? '评审通过' : '评审有建议'}
        </span>
      </div>

      <p className="text-[11px] text-main whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto custom-scrollbar">
        {plan.plan || '（无计划内容）'}
      </p>

      {review.recommendations && (
        <p className="text-[10px] text-amber-700 bg-amber-100/70 rounded px-2 py-1">
          评审建议: {review.recommendations}
        </p>
      )}

      <div className="flex items-center justify-end gap-2 pt-0.5">
        <button
          type="button"
          onClick={onCancel}
          disabled={disabled}
          className="px-2.5 py-1 rounded-lg text-[11px] font-medium border border-line text-secondary hover:text-main hover:bg-elevated disabled:opacity-40 transition-colors"
        >
          取消
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={disabled}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-40 transition-colors"
        >
          <Check className="w-3 h-3" />
          确认执行
        </button>
      </div>
    </div>
  )
}

interface ConfirmationCardProps {
  confirmation: PendingConfirmation
  onConfirm: () => void
  onCancel: () => void
  disabled?: boolean
}

export const ConfirmationCard: React.FC<ConfirmationCardProps> = ({
  confirmation,
  onConfirm,
  onCancel,
  disabled
}) => {
  const confidence =
    typeof confirmation.confidence === 'number'
      ? `${Math.round(confirmation.confidence * 100)}%`
      : '未知'

  return (
    <div className="border border-sky-300 bg-sky-50/60 rounded-xl p-3 space-y-2 shadow-xs">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold text-sky-800">
        <ShieldAlert className="w-3.5 h-3.5" />
        <span>需确认的操作</span>
        <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded bg-sky-100 text-sky-700 font-medium">
          置信度 {confidence}
        </span>
      </div>
      <p className="text-[11px] text-secondary">
        {confirmation.message || `Agent 请求执行「${confirmation.tool}」，请确认后继续。`}
      </p>
      <div className="flex items-center justify-end gap-2 pt-0.5">
        <button
          type="button"
          onClick={onCancel}
          disabled={disabled}
          className="px-2.5 py-1 rounded-lg text-[11px] font-medium border border-line text-secondary hover:text-main hover:bg-elevated disabled:opacity-40 transition-colors"
        >
          拒绝
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={disabled}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-40 transition-colors"
        >
          <Check className="w-3 h-3" />
          允许执行
        </button>
      </div>
    </div>
  )
}
