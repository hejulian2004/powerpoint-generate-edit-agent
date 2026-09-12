import type { LucideIcon } from 'lucide-react'
import { Minimize2, MessageSquarePlus, Eye, ListChecks, CircleHelp } from 'lucide-react'

/** Metadata for a slash command shown in the composer palette. */
export interface ChatCommand {
  /** Command token without the leading slash (e.g. "review"). */
  name: string
  label: string
  description: string
  icon: LucideIcon
  /** Placeholder shown after the command, e.g. "[页码|描述|all]". */
  argsPlaceholder?: string
  /** Whether the command takes free-form arguments (keeps the palette open). */
  takesArgs?: boolean
}

/**
 * Extensible registry. Adding a command here surfaces it in the palette; the
 * executor lives in ChatPanel (which owns the store actions).
 */
export const CHAT_COMMANDS: ChatCommand[] = [
  {
    name: 'compress',
    label: '压缩上下文',
    description: '立即压缩历史对话，释放上下文窗口（不影响 PPT）',
    icon: Minimize2
  },
  {
    name: 'new',
    label: '新对话',
    description: '清空对话与 Agent 记忆，保留当前 PPT 进度',
    icon: MessageSquarePlus
  },
  {
    name: 'review',
    label: '视觉审查',
    description: '审查排版与美观；可指定页码/描述，或 all 审查全部',
    icon: Eye,
    takesArgs: true,
    argsPlaceholder: '[页码|描述|all]'
  },
  {
    name: 'plan',
    label: '计划模式',
    description: '开启后每个任务先出计划，由你确认后再执行',
    icon: ListChecks
  },
  {
    name: 'help',
    label: '帮助',
    description: '查看可用快捷命令',
    icon: CircleHelp
  }
]

/** Returns commands whose name starts with the typed query (without slash). */
export const matchCommands = (query: string): ChatCommand[] => {
  const q = query.toLowerCase()
  if (!q) return CHAT_COMMANDS
  return CHAT_COMMANDS.filter((c) => c.name.toLowerCase().startsWith(q))
}

/** Builds the local assistant message shown by the `/help` command. */
export const buildHelpMessage = () => ({
  id: `help_${Date.now()}`,
  role: 'assistant' as const,
  content:
    '可用快捷命令：\n' +
    CHAT_COMMANDS.map(
      (c) => `/${c.name}${c.argsPlaceholder ? ' ' + c.argsPlaceholder : ''} — ${c.description}`
    ).join('\n'),
  timestamp: Date.now()
})

/** Parses "/name args" into a command and its argument string. */
export const parseCommand = (
  raw: string
): { command: ChatCommand; args: string } | null => {
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/')) return null
  const body = trimmed.slice(1)
  const spaceIdx = body.search(/\s/)
  const name = (spaceIdx === -1 ? body : body.slice(0, spaceIdx)).toLowerCase()
  const args = spaceIdx === -1 ? '' : body.slice(spaceIdx + 1).trim()
  const command = CHAT_COMMANDS.find((c) => c.name === name)
  if (!command) return null
  return { command, args }
}
