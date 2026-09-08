import { create } from 'zustand'
import type { PresentationIR, SlideIR, ChatMessage } from '../types/ppt'

interface PPTState {
  presentation: PresentationIR | null
  activeSlideId: string | null
  selectedElementId: string | null
  messages: ChatMessage[]
  wsConnected: boolean
  isAgentThinking: boolean
  thinkingStatus: string
  canUndo: boolean
  canRedo: boolean
  settingsOpen: boolean
  zoom: number

  // Actions
  setPresentation: (pres: PresentationIR) => void
  setActiveSlideId: (id: string) => void
  setSelectedElementId: (id: string | null) => void
  setSettingsOpen: (open: boolean) => void
  setZoom: (zoom: number) => void
  addMessage: (msg: ChatMessage) => void
  updateLastMessage: (partial: Partial<ChatMessage>) => void
  setAgentThinking: (thinking: boolean, status?: string) => void
  
  // API / WS
  ws: WebSocket | null
  initWebSocket: () => void
  sendChatMessage: (text: string) => void
  triggerUndo: () => void
  triggerRedo: () => void
  updateElementDirect: (elemId: string, updates: Record<string, any>) => void
  getActiveSlide: () => SlideIR | null
}

export const usePPTStore = create<PPTState>((set, get) => ({
  presentation: null,
  activeSlideId: null,
  selectedElementId: null,
  messages: [
    {
      id: 'welcome',
      role: 'assistant',
      content: '👋 你好！我是 PPT-Agent-Studio 智能助手。你可以通过自然语言指挥我创建幻灯片、添加图表卡片、修改字体色彩、规整排版布局或直接审查设计。请告诉我你的演示文稿需求！',
      timestamp: Date.now()
    }
  ],
  wsConnected: false,
  isAgentThinking: false,
  thinkingStatus: '',
  canUndo: false,
  canRedo: false,
  settingsOpen: false,
  zoom: 1.0,
  ws: null,

  setPresentation: (pres) => set({
    presentation: pres,
    activeSlideId: pres.active_slide_id || (pres.slides[0] ? pres.slides[0].id : null)
  }),

  setActiveSlideId: (id) => {
    set({ activeSlideId: id, selectedElementId: null })
    const { ws } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'select_slide', slide_id: id }))
    }
  },

  setSelectedElementId: (id) => set({ selectedElementId: id }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setZoom: (zoom) => set({ zoom }),

  addMessage: (msg) => set((state) => ({ messages: [...state.messages, msg] })),

  updateLastMessage: (partial) => set((state) => {
    const msgs = [...state.messages]
    if (msgs.length === 0) return state
    const last = msgs[msgs.length - 1]
    msgs[msgs.length - 1] = { ...last, ...partial }
    return { messages: msgs }
  }),

  setAgentThinking: (thinking, status = '') => set({
    isAgentThinking: thinking,
    thinkingStatus: status
  }),

  initWebSocket: () => {
    const existingWs = get().ws
    if (existingWs) {
      existingWs.close()
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      set({ wsConnected: true, ws })
    }

    ws.onclose = () => {
      set({ wsConnected: false, ws: null })
      // Auto reconnect after 3 seconds
      setTimeout(() => {
        get().initWebSocket()
      }, 3000)
    }

    ws.onerror = () => {
      set({ wsConnected: false })
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const type = data.type

        if (type === 'presentation_loaded') {
          set({
            presentation: data.presentation,
            activeSlideId: data.active_slide_id || data.presentation.slides[0]?.id,
            canUndo: data.can_undo ?? false,
            canRedo: data.can_redo ?? false
          })
        } else if (type === 'presentation_updated') {
          set((state) => ({
            presentation: data.presentation,
            activeSlideId: state.activeSlideId || data.presentation.slides[0]?.id,
            canUndo: data.can_undo ?? state.canUndo,
            canRedo: data.can_redo ?? state.canRedo
          }))
        } else if (type === 'active_slide_changed') {
          set({ activeSlideId: data.active_slide_id })
        } else if (type === 'agent_thinking') {
          set({ isAgentThinking: true, thinkingStatus: data.text || 'Agent 正在思考...' })
        } else if (type === 'tool_executing') {
          set({ isAgentThinking: true, thinkingStatus: `正在调用工具: ${data.tool}...` })
        } else if (type === 'tool_completed') {
          set({ isAgentThinking: true, thinkingStatus: `完成工具调用: ${data.tool}` })
        } else if (type === 'vision_loop') {
          set({ isAgentThinking: true, thinkingStatus: data.text || 'Vision Loop 质检中...' })
        } else if (type === 'agent_finished') {
          set({ isAgentThinking: false, thinkingStatus: '' })
          get().addMessage({
            id: `msg_${Date.now()}`,
            role: 'assistant',
            content: data.summary || '已根据您的需求修改完成。',
            timestamp: Date.now(),
            toolCalls: data.tools_executed,
            visionCritique: data.vision_critique
          })
        } else if (type === 'agent_error') {
          set({ isAgentThinking: false, thinkingStatus: '' })
          get().addMessage({
            id: `err_${Date.now()}`,
            role: 'assistant',
            content: `⚠️ 执行出错: ${data.error}`,
            timestamp: Date.now()
          })
        }
      } catch (e) {
        console.error('Error handling WebSocket message:', e)
      }
    }
  },

  sendChatMessage: (text) => {
    const { ws, addMessage } = get()
    if (!text.trim()) return

    addMessage({
      id: `user_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now()
    })

    set({ isAgentThinking: true, thinkingStatus: 'Agent 正在分析需求...' })

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', message: text }))
    } else {
      // Fallback to REST API
      fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
      })
        .then((res) => res.json())
        .then((data) => {
          set({ isAgentThinking: false })
          addMessage({
            id: `msg_${Date.now()}`,
            role: 'assistant',
            content: data.reply,
            timestamp: Date.now(),
            toolCalls: data.tools_executed,
            visionCritique: data.vision_critique
          })
          // Reload presentation
          fetch('/api/presentation')
            .then((r) => r.json())
            .then((p) => set({ presentation: p }))
        })
        .catch((err) => {
          set({ isAgentThinking: false })
          addMessage({
            id: `err_${Date.now()}`,
            role: 'assistant',
            content: `请求失败: ${err}`,
            timestamp: Date.now()
          })
        })
    }
  },

  triggerUndo: () => {
    const { ws } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'undo' }))
    } else {
      fetch('/api/action/undo', { method: 'POST' })
        .then((r) => r.json())
        .then((data) => {
          if (data.success) {
            fetch('/api/presentation')
              .then((r) => r.json())
              .then((p) => set({ presentation: p }))
          }
        })
    }
  },

  triggerRedo: () => {
    const { ws } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'redo' }))
    } else {
      fetch('/api/action/redo', { method: 'POST' })
        .then((r) => r.json())
        .then((data) => {
          if (data.success) {
            fetch('/api/presentation')
              .then((r) => r.json())
              .then((p) => set({ presentation: p }))
          }
        })
    }
  },

  updateElementDirect: (elemId, updates) => {
    const { ws, activeSlideId } = get()
    const payload = {
      slide_id: activeSlideId,
      element_id: elemId,
      ...updates
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'direct_update_element', payload }))
    }
  },

  getActiveSlide: () => {
    const { presentation, activeSlideId } = get()
    if (!presentation || !presentation.slides.length) return null
    if (activeSlideId) {
      const found = presentation.slides.find((s) => s.id === activeSlideId)
      if (found) return found
    }
    return presentation.slides[0]
  }
}))
