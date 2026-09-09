/**
 * Precision UI Theme Design Tokens
 * Centralized theme tokens and color definitions for PPT Agent Studio
 */

export const themeColors = {
  surface: {
    canvas: '#F8FAFC',
    panel: '#FFFFFF',
    elevated: '#F1F5F9',
    subtle: '#F8FAFC',
    inverted: '#0F172A',
    invertedHover: '#1E293B',
  },
  border: {
    subtle: '#E2E8F0',
    strong: '#CBD5E1',
    focus: '#94A3B8',
  },
  content: {
    primary: '#0F172A',
    secondary: '#475569',
    muted: '#64748B',
    inverted: '#FFFFFF',
  },
} as const

export const DEFAULT_COLOR_SWATCHES = [
  '#0F172A', '#475569', '#94A3B8', '#CBD5E1',
  '#3B82F6', '#10B981', '#F59E0B', '#EF4444',
] as const

export const SLIDE_THEME_PRESETS = [
  { id: 'stark_white', name: '纯白明晰 (White)', bg: '#FFFFFF', primary: '#0F172A' },
  { id: 'monochrome_studio', name: '钛金雅灰 (Studio)', bg: '#F8FAFC', primary: '#1E293B' },
  { id: 'matte_graphite', name: '哑光石墨 (Graphite)', bg: '#1E293B', primary: '#F8FAFC' },
  { id: 'slate_silver', name: '沉稳黑曜 (Black)', bg: '#0A0A0A', primary: '#FFFFFF' },
] as const
