import { create } from 'zustand'
import type { PresentationIR, SlideIR, ElementIR, ChatMessage } from '../types/ppt'

interface PPTState {
  presentation: PresentationIR | null
  activeSlideId: string | null
  selectedElementId: string | null
  activeRightTab: 'copilot' | 'inspector'
  messages: ChatMessage[]
  wsConnected: boolean
  isAgentThinking: boolean
  thinkingStatus: string
  canUndo: boolean
  canRedo: boolean
  settingsOpen: boolean
  zoom: number
  showGrid: boolean

  // Actions
  setPresentation: (pres: PresentationIR) => void
  setActiveSlideId: (id: string) => void
  setSelectedElementId: (id: string | null) => void
  setActiveRightTab: (tab: 'copilot' | 'inspector') => void
  setSettingsOpen: (open: boolean) => void
  setZoom: (zoom: number) => void
  setShowGrid: (show: boolean) => void
  addMessage: (msg: ChatMessage) => void
  updateLastMessage: (partial: Partial<ChatMessage>) => void
  setAgentThinking: (thinking: boolean, status?: string) => void
  
  // Quick Canvas Tools
  addShapeQuick: (shapeType: string) => void
  addTextQuick: () => void
  addConnectorQuick: () => void

  // API / WS
  ws: WebSocket | null
  initWebSocket: () => void
  sendChatMessage: (text: string) => void
  triggerUndo: () => void
  triggerRedo: () => void
  updateElementDirect: (elemId: string, updates: Record<string, any>) => void
  getActiveSlide: () => SlideIR | null
  getSelectedElement: () => ElementIR | null
}

export const usePPTStore = create<PPTState>((set, get) => ({
  presentation: null,
  activeSlideId: null,
  selectedElementId: null,
  activeRightTab: 'copilot',
  messages: [
    {
      id: 'welcome',
      role: 'assistant',
      content: '我是你的 PPT 设计助理。你可以在画布上直接选取、调整图元属性，或在下方输入指令由我进行全局规划、配色升级与智能排版。',
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
  showGrid: false,
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

  setSelectedElementId: (id) => {
    set({
      selectedElementId: id,
      activeRightTab: id ? 'inspector' : get().activeRightTab
    })
  },

  setActiveRightTab: (tab) => set({ activeRightTab: tab }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setZoom: (zoom) => set({ zoom }),
  setShowGrid: (show) => set({ showGrid: show }),

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

  addShapeQuick: (shapeType = 'roundRect') => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().sendChatMessage(`请在当前页添加一个 ${shapeType} 矩形卡片`)
  },

  addTextQuick: () => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().sendChatMessage(`请在当前页添加一个文本标题`)
  },

  addConnectorQuick: () => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().sendChatMessage(`请在当前页添加一条带箭头的连接线`)
  },

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
          set({ isAgentThinking: true, thinkingStatus: data.text || 'Agent 正在规划方案...' })
        } else if (type === 'tool_executing') {
          set({ isAgentThinking: true, thinkingStatus: `执行工具: ${data.tool}...` })
        } else if (type === 'tool_completed') {
          set({ isAgentThinking: true, thinkingStatus: `工具完成: ${data.tool}` })
        } else if (type === 'vision_loop') {
          set({ isAgentThinking: true, thinkingStatus: data.text || '视觉多模态校验中...' })
        } else if (type === 'agent_finished') {
          set({ isAgentThinking: false, thinkingStatus: '' })
          get().addMessage({
            id: `msg_${Date.now()}`,
            role: 'assistant',
            content: data.summary || '已根据要求完成修改。',
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

    set({ isAgentThinking: true, thinkingStatus: '分析需求与视觉结构...', activeRightTab: 'copilot' })

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', message: text }))
    } else {
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
  },

  getSelectedElement: () => {
    const slide = get().getActiveSlide()
    const { selectedElementId } = get()
    if (!slide || !selectedElementId) return null
    return slide.elements.find((e) => e.id === selectedElementId) || null
  }
}))
