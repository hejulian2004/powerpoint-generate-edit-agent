import React from 'react'

interface CircularProgressProps {
  percentage: number
  size?: number
  strokeWidth?: number
  currentTokens: number
  maxTokens: number
  isCompressed?: boolean
  limitKey?: string
}

export const ContextUsageIndicator: React.FC<CircularProgressProps> = ({
  percentage,
  size = 28,
  strokeWidth = 3,
  currentTokens,
  maxTokens,
  isCompressed = false,
  limitKey = '256k'
}) => {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clampedPct = Math.min(100, Math.max(0, percentage))
  const strokeDashoffset = circumference - (clampedPct / 100) * circumference

  // Color gradient / thresholds:
  // < 75%: Teal / Emerald / Blue
  // 75% - 89%: Amber
  // >= 90%: Rose / Red (Auto-compressed trigger boundary)
  let progressColor = '#10B981' // emerald-500
  let badgeBg = 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-800'

  if (clampedPct >= 90 || isCompressed) {
    progressColor = '#F43F5E' // rose-500
    badgeBg = 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:border-rose-800'
  } else if (clampedPct >= 75) {
    progressColor = '#F59E0B' // amber-500
    badgeBg = 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800'
  }

  const formatTokens = (num: number) => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
    if (num >= 1000) return `${(num / 1000).toFixed(0)}K`
    return `${num}`
  }

  return (
    <div
      className="flex items-center gap-2 px-2.5 py-1 bg-elevated/80 border border-line rounded-xl text-[11px] select-none group relative"
      title={`上下文容量: ${currentTokens.toLocaleString()} / ${maxTokens.toLocaleString()} Tokens (${clampedPct.toFixed(1)}%)\n上限模式: ${limitKey.toUpperCase()}\n≥90% 自动执行历史滑动窗口压缩`}
    >
      {/* SVG Circular Ring */}
      <div className="relative flex items-center justify-center shrink-0">
        <svg width={size} height={size} className="transform -rotate-90">
          {/* Background Track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-line opacity-40"
            fill="transparent"
          />
          {/* Progress Arc */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={progressColor}
            strokeWidth={strokeWidth}
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            fill="transparent"
            className="transition-all duration-500 ease-out"
          />
        </svg>
        <span className="absolute text-[8.5px] font-bold font-tabular text-main">
          {Math.round(clampedPct)}
        </span>
      </div>

      {/* Text Info */}
      <div className="flex flex-col leading-tight">
        <div className="flex items-center gap-1 font-medium text-main">
          <span>上下文</span>
          <span className={`text-[9px] px-1 py-0.2 rounded font-semibold border ${badgeBg}`}>
            {limitKey.toUpperCase()}
          </span>
          {isCompressed && (
            <span className="text-[9px] text-rose-600 dark:text-rose-400 font-semibold animate-pulse">
              已压缩
            </span>
          )}
        </div>
        <div className="text-[10px] text-muted font-tabular">
          {formatTokens(currentTokens)} / {formatTokens(maxTokens)}
        </div>
      </div>
    </div>
  )
}
