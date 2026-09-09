import { create } from 'zustand'
import type {
  PresentationIR,
  SlideIR,
  ElementIR,
  ChatMessage,
  VisualRemediationEvent,
  VisualQualityScore,
  PPTEditorState,
  PatchRecord,
  MutationStatus
} from '../types/ppt'

interface PPTState {
  sessionId: string
  presentation: PresentationIR | null
  activeSlideId: string | null
  selectedElementId: string | null
  activeRightTab: 'copilot' | 'inspector'
  messages: ChatMessage[]
  wsConnected: boolean
  isAgentThinking: boolean
  thinkingStatus: string
  visualRemediation: VisualRemediationEvent | null
  canUndo: boolean
  canRedo: boolean
  settingsOpen: boolean
  pptspecModalOpen: boolean
  zoom: number
  showGrid: boolean
  previewSvg: string | null
  previewScore: number | null
  qualityScore: VisualQualityScore | null
  history: PatchRecord[]
  mutationStatus: MutationStatus

  // Actions
  setSessionId: (id: string) => void
  setPresentation: (pres: PresentationIR) => void
  setActiveSlideId: (id: string) => void
  setSelectedElementId: (id: string | null) => void
  setActiveRightTab: (tab: 'copilot' | 'inspector') => void
  setSettingsOpen: (open: boolean) => void
  setPptspecModalOpen: (open: boolean) => void
  setZoom: (zoom: number) => void
  setShowGrid: (show: boolean) => void
  setMutationStatus: (status: MutationStatus) => void
  addMessage: (msg: ChatMessage) => void
  updateLastMessage: (partial: Partial<ChatMessage>) => void
  setAgentThinking: (thinking: boolean, status?: string) => void

  // Quick Canvas Tools
  addShapeQuick: (shapeType: string, x?: number, y?: number) => void
  addTextQuick: (x?: number, y?: number) => void
  addConnectorQuick: () => void

  // Direct GUI Actions (decoupled from chat dialogue)
  executeDirectAction: (action: string, payload?: Record<string, any>) => void
  addNewSlide: (backgroundColor?: string) => void
  deleteSlide: (slideIdOrNum: string | number) => void
  deleteSelectedElement: () => void
  duplicateSelectedElement: () => void
  setSlideBackgroundDirect: (color: string) => void
  optimizeLayoutDirect: () => void
  applyThemeDirect: (themePreset: string) => void

  // API / WS
  ws: WebSocket | null
  initWebSocket: () => void
  sendChatMessage: (text: string) => void
  triggerUndo: () => void
  triggerRedo: () => void
  updateElementDirect: (elemId: string, updates: Record<string, any>) => void
  getActiveSlide: () => SlideIR | null
  getSelectedElement: () => ElementIR | null
  getEditorState: () => PPTEditorState
}

export const usePPTStore = create<PPTState>((set, get) => ({
  sessionId: 'sess_default',
  presentation: null,
  activeSlideId: null,
  selectedElementId: null,
  activeRightTab: 'copilot',
  messages: [
    {
      id: 'welcome',
      role: 'assistant',
      content: '我是你的 PPT 协同架构师（由 LangGraph 状态机驱动）。我支持一键生成多页主题演示文稿、自动编排时间线/指标/特性卡片、规整排版与图元属性微调。',
      timestamp: Date.now()
    }
  ],
  wsConnected: false,
  isAgentThinking: false,
  thinkingStatus: '',
  visualRemediation: null,
  canUndo: false,
  canRedo: false,
  settingsOpen: false,
  pptspecModalOpen: false,
  zoom: 1.0,
  showGrid: false,
  previewSvg: null,
  previewScore: null,
  qualityScore: null,
  history: [],
  mutationStatus: 'idle',
  ws: null,

  setSessionId: (id: string) => set({ sessionId: id }),
  setMutationStatus: (status) => set({ mutationStatus: status }),

  setPresentation: (pres) => set({
    presentation: pres,
    activeSlideId: pres.active_slide_id || (pres.slides[0] ? pres.slides[0].id : null)
  }),

  setActiveSlideId: (id) => {
    set({ activeSlideId: id, selectedElementId: null })
    const { ws, sessionId } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'select_slide', slide_id: id, session_id: sessionId }))
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
  setPptspecModalOpen: (open) => set({ pptspecModalOpen: open }),
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

  executeDirectAction: (action: string, payload: Record<string, any> = {}) => {
    const { ws, sessionId, activeSlideId } = get()
    const finalPayload = { slide_id: activeSlideId, ...payload }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: 'direct_action',
        action,
        payload: finalPayload,
        session_id: sessionId
      }))
    }
  },

  addNewSlide: (backgroundColor = '#FFFFFF') => {
    get().executeDirectAction('create_slide', {
      title: '新建幻灯片',
      background_color: backgroundColor
    })
  },

  deleteSlide: (slideIdOrNum: string | number) => {
    get().executeDirectAction('delete_slide', {
      slide_id_or_num: String(slideIdOrNum)
    })
  },

  deleteSelectedElement: () => {
    const { selectedElementId, activeSlideId } = get()
    if (!selectedElementId) return
    get().executeDirectAction('delete_element', {
      element_id: selectedElementId,
      slide_id: activeSlideId
    })
    set({ selectedElementId: null })
  },

  duplicateSelectedElement: () => {
    const { selectedElementId, activeSlideId } = get()
    if (!selectedElementId) return
    get().executeDirectAction('duplicate_element', {
      element_id: selectedElementId,
      slide_id: activeSlideId
    })
  },

  setSlideBackgroundDirect: (color: string) => {
    const { activeSlideId } = get()
    get().executeDirectAction('set_slide_background', {
      color,
      slide_id: activeSlideId
    })
  },

  optimizeLayoutDirect: () => {
    const { activeSlideId } = get()
    get().executeDirectAction('optimize_layout', {
      layout_mode: 'horizontal_cards',
      slide_id: activeSlideId
    })
  },

  applyThemeDirect: (themePreset: string) => {
    get().executeDirectAction('apply_theme', {
      theme_preset: themePreset
    })
  },

  addShapeQuick: (shapeType = 'roundRect', x = 200, y = 200) => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().executeDirectAction('add_shape', {
      shape_type: shapeType,
      x,
      y,
      width: 280,
      height: 160,
      fill_color: '#F8FAFC',
      border_color: '#CBD5E1',
      text: ''
    })
  },

  addTextQuick: (x = 200, y = 200) => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().executeDirectAction('add_text', {
      text: '点击输入文本',
      x,
      y,
      width: 360,
      height: 60,
      font_size: 24,
      font_color: '#0F172A',
      bold: true
    })
  },

  addConnectorQuick: () => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().executeDirectAction('add_connector', {
      start_x: 200,
      start_y: 260,
      end_x: 440,
      end_y: 260,
      border_color: '#94A3B8'
    })
  },

  initWebSocket: () => {
    const existingWs = get().ws
    if (existingWs) {
      existingWs.close()
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws?session_id=${get().sessionId}`

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
            sessionId: data.session_id || get().sessionId,
            presentation: data.presentation,
            activeSlideId: data.active_slide_id || data.presentation.slides[0]?.id,
            canUndo: data.can_undo ?? false,
            canRedo: data.can_redo ?? false
          })
        } else if (type === 'preview_update') {
          set({
            previewSvg: data.svg,
            previewScore: data.score,
            qualityScore: data.quality_score,
            mutationStatus: 'committed'
          })
        } else if (type === 'presentation_updated') {
          set((state) => ({
            sessionId: data.session_id || state.sessionId,
            presentation: data.presentation,
            activeSlideId: data.active_slide_id || state.activeSlideId || data.presentation.slides[0]?.id,
            canUndo: data.can_undo ?? state.canUndo,
            canRedo: data.can_redo ?? state.canRedo,
            mutationStatus: 'committed'
          }))
        } else if (type === 'active_slide_changed') {
          set({ activeSlideId: data.active_slide_id })
        } else if (type === 'agent_thinking') {
          set({ isAgentThinking: true, thinkingStatus: data.text || 'Agent 正在规划方案...' })
        } else if (type === 'tool_executing') {
          set({ isAgentThinking: true, thinkingStatus: `执行工具: ${data.tool}...` })
        } else if (type === 'tool_completed') {
          set({ isAgentThinking: true, thinkingStatus: `工具完成: ${data.tool}` })
        } else if (type === 'visual_remediation') {
          set({
            isAgentThinking: true,
            thinkingStatus: data.text || '视觉排版自愈中...',
            visualRemediation: data
          })
        } else if (type === 'vision_loop') {
          set({ isAgentThinking: true, thinkingStatus: data.text || '视觉多模态校验中...' })
        } else if (type === 'agent_finished') {
          set({ isAgentThinking: false, thinkingStatus: '', visualRemediation: null })
          get().addMessage({
            id: `msg_${Date.now()}`,
            role: 'assistant',
            content: data.summary || '已根据要求完成修改。',
            timestamp: Date.now(),
            toolCalls: data.tools_executed,
            visionCritique: data.vision_critique,
            visualReview: data.visual_review
          })
        } else if (type === 'agent_error') {
          set({ isAgentThinking: false, thinkingStatus: '', visualRemediation: null, mutationStatus: 'failed' })
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
    const { ws, addMessage, sessionId } = get()
    if (!text.trim()) return

    addMessage({
      id: `user_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now()
    })

    set({ isAgentThinking: true, thinkingStatus: '分析需求与视觉结构...', activeRightTab: 'copilot' })

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'chat', message: text, session_id: sessionId }))
    } else {
      fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId })
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
          fetch(`/api/presentation?session_id=${encodeURIComponent(sessionId)}`)
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
    const { ws, sessionId } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'undo', session_id: sessionId }))
    } else {
      fetch(`/api/action/undo?session_id=${encodeURIComponent(sessionId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.success) {
            fetch(`/api/presentation?session_id=${encodeURIComponent(sessionId)}`)
              .then((r) => r.json())
              .then((p) => set({ presentation: p }))
          }
        })
    }
  },

  triggerRedo: () => {
    const { ws, sessionId } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'redo', session_id: sessionId }))
    } else {
      fetch(`/api/action/redo?session_id=${encodeURIComponent(sessionId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.success) {
            fetch(`/api/presentation?session_id=${encodeURIComponent(sessionId)}`)
              .then((r) => r.json())
              .then((p) => set({ presentation: p }))
          }
        })
    }
  },

  updateElementDirect: (elemId, updates) => {
    const { ws, activeSlideId, presentation } = get()

    // Optimistic local update for instantaneous smooth feedback
    if (presentation) {
      const updateElInArray = (elements: ElementIR[]): ElementIR[] => {
        return elements.map((el) => {
          if (el.id === elemId) {
            const updatedEl: any = { ...el, ...updates }

            // Style adjustments
            if (updates.fill_color !== undefined) {
              updatedEl.style = {
                ...updatedEl.style,
                fill: updates.fill_color ? { type: 'solid', color: updates.fill_color, alpha: 1.0 } : { type: 'none', alpha: 0 }
              }
            }
            if (updates.border_color !== undefined || updates.border_width !== undefined) {
              updatedEl.style = {
                ...updatedEl.style,
                border: {
                  ...updatedEl.style?.border,
                  color: updates.border_color ?? updatedEl.style?.border?.color ?? '#2D303F',
                  width: updates.border_width ?? updatedEl.style?.border?.width ?? 1.0,
                  style: 'solid',
                  alpha: 1.0
                }
              }
            }
            if (updates.radius !== undefined) {
              updatedEl.style = { ...updatedEl.style, radius: updates.radius }
            }
            if (updates.opacity !== undefined) {
              updatedEl.style = { ...updatedEl.style, opacity: updates.opacity }
            }

            // Typography adjustments on text_content
            if (updatedEl.text_content) {
              const tc = JSON.parse(JSON.stringify(updatedEl.text_content))
              if (updates.text !== undefined) {
                tc.plain_text = updates.text
                if (tc.paragraphs && tc.paragraphs[0] && tc.paragraphs[0].runs && tc.paragraphs[0].runs[0]) {
                  tc.paragraphs[0].runs[0].text = updates.text
                }
              }
              if (tc.paragraphs) {
                tc.paragraphs.forEach((p: any) => {
                  if (updates.align) p.align = updates.align
                  p.runs?.forEach((r: any) => {
                    if (!r.font) r.font = {}
                    if (updates.font_family !== undefined) r.font.name = updates.font_family
                    if (updates.font_size !== undefined) r.font.size = updates.font_size
                    if (updates.font_color !== undefined) r.font.color = updates.font_color
                    if (updates.bold !== undefined) r.font.bold = updates.bold
                    if (updates.italic !== undefined) r.font.italic = updates.italic
                  })
                })
              }
              updatedEl.text_content = tc
            }
            return updatedEl
          }
          if (el.type === 'group' && (el as any).children) {
            return {
              ...el,
              children: updateElInArray((el as any).children)
            }
          }
          return el
        })
      }

      const updatedSlides = presentation.slides.map((s) => {
        if (s.id !== (activeSlideId || presentation.slides[0]?.id)) return s
        return { ...s, elements: updateElInArray(s.elements) }
      })
      set({ presentation: { ...presentation, slides: updatedSlides }, mutationStatus: 'pending' })
    }

    const payload = {
      slide_id: activeSlideId,
      element_id: elemId,
      ...updates
    }
    const { sessionId } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'direct_update_element', payload, session_id: sessionId }))
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

    const findInArray = (elements: ElementIR[]): ElementIR | null => {
      for (const el of elements) {
        if (el.id === selectedElementId) return el
        if (el.type === 'group' && (el as any).children) {
          const found = findInArray((el as any).children)
          if (found) return found
        }
      }
      return null
    }

    return findInArray(slide.elements)
  },

  getEditorState: (): PPTEditorState => {
    const {
      getActiveSlide,
      getSelectedElement,
      history,
      previewSvg,
      previewScore,
      qualityScore,
      isAgentThinking,
      thinkingStatus,
      visualRemediation,
      activeSlideId,
      mutationStatus
    } = get()

    return {
      slide: getActiveSlide(),
      selectedElement: getSelectedElement(),
      history,
      preview: previewSvg ? {
        slide_id: activeSlideId || '',
        svg: previewSvg,
        score: previewScore ?? undefined,
        quality_score: qualityScore ?? undefined
      } : null,
      agentStatus: {
        isThinking: isAgentThinking,
        thinkingStatus,
        visualRemediation
      },
      mutationStatus
    }
  }
}))
