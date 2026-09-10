import { create } from 'zustand'
import type {
  PresentationIR,
  SlideIR,
  ElementIR,
  GroupElementIR,
  ChatMessage,
  VisualRemediationEvent,
  VisualQualityScore,
  PPTEditorState,
  PatchRecord,
  MutationStatus,
  ContextUsageData
} from '../types/ppt'
import {
  cloneElement,
  isConnector,
  isGroup,
  recomputeGroupBounds,
  scaleElement,
  syncConnectorBounds,
  syncTransform,
  translateElement
} from '../editor/geometry/adapter'

export type AlignMode =
  | 'left' | 'center' | 'right'
  | 'top' | 'middle' | 'bottom'
  | 'distribute_h' | 'distribute_v'

export interface MutationOperation {
  name: string
  payload: Record<string, any>
}

export interface PendingMutation {
  mutationId: string
  operations: MutationOperation[]
  description?: string
  documentEpoch?: string | null
  expectedRevision?: number | null
}

interface OutboxEntry {
  message: Record<string, any>
  mutation: PendingMutation
}

const GEOMETRY_KEYS = ['x', 'y', 'width', 'height', 'start_x', 'start_y', 'end_x', 'end_y']

let mutationCounter = 0

const selectTargetOnAck = new Set<string>()

const newMutationId = () =>
  `mut_${Date.now().toString(36)}_${(mutationCounter += 1).toString(36)}`

const existsInElements = (elements: ElementIR[], id: string | null | undefined): boolean => {
  if (!id) return false
  for (const el of elements) {
    if (el.id === id) return true
    if (isGroup(el) && existsInElements(el.children, id)) return true
  }
  return false
}

const removeElementsById = (elements: ElementIR[], ids: Set<string>): ElementIR[] => {
  const result: ElementIR[] = []
  for (const el of elements) {
    if (ids.has(el.id)) continue
    if (isGroup(el)) {
      const children = removeElementsById(el.children, ids)
      const changed =
        children.length !== el.children.length ||
        children.some((child, index) => child !== el.children[index])
      if (changed) {
        const nextGroup: GroupElementIR = { ...el, children }
        recomputeGroupBounds(nextGroup)
        result.push(nextGroup)
      } else {
        result.push(el)
      }
    } else {
      result.push(el)
    }
  }
  return result
}

const applyElementUpdate = (
  el: ElementIR,
  targetId: string,
  updates: Record<string, any>
): ElementIR => {
  if (el.id !== targetId) {
    if (isGroup(el)) {
      let changed = false
      const children = el.children.map((child) => {
        const next = applyElementUpdate(child, targetId, updates)
        if (next !== child) changed = true
        return next
      })
      if (!changed) return el
      const nextGroup: GroupElementIR = { ...el, children }
      recomputeGroupBounds(nextGroup)
      return nextGroup
    }
    return el
  }

  const updated = cloneElement(el)
  const hasGeometry = GEOMETRY_KEYS.some((key) => updates[key] !== undefined)

  if (hasGeometry) {
    const hasEndpoints =
      updates.start_x !== undefined ||
      updates.start_y !== undefined ||
      updates.end_x !== undefined ||
      updates.end_y !== undefined

    if (isConnector(updated)) {
      if (hasEndpoints) {
        if (updates.start_x !== undefined) updated.start_x = updates.start_x
        if (updates.start_y !== undefined) updated.start_y = updates.start_y
        if (updates.end_x !== undefined) updated.end_x = updates.end_x
        if (updates.end_y !== undefined) updated.end_y = updates.end_y
        syncConnectorBounds(updated)
      } else {
        const sx = updates.width !== undefined && updated.width > 0 ? updates.width / updated.width : 1
        const sy = updates.height !== undefined && updated.height > 0 ? updates.height / updated.height : 1
        const dx = updates.x !== undefined ? updates.x - updated.x : 0
        const dy = updates.y !== undefined ? updates.y - updated.y : 0
        if (sx !== 1 || sy !== 1) scaleElement(updated, sx, sy)
        if (dx !== 0 || dy !== 0) translateElement(updated, dx, dy)
      }
    } else if (isGroup(updated)) {
      const sx = updates.width !== undefined && updated.width > 0 ? updates.width / updated.width : 1
      const sy = updates.height !== undefined && updated.height > 0 ? updates.height / updated.height : 1
      const dx = updates.x !== undefined ? updates.x - updated.x : 0
      const dy = updates.y !== undefined ? updates.y - updated.y : 0
      if (sx !== 1 || sy !== 1) scaleElement(updated, sx, sy)
      if (dx !== 0 || dy !== 0) translateElement(updated, dx, dy)
    } else {
      if (updates.x !== undefined) updated.x = updates.x
      if (updates.y !== undefined) updated.y = updates.y
      if (updates.width !== undefined) updated.width = updates.width
      if (updates.height !== undefined) updated.height = updates.height
      syncTransform(updated)
    }
  }

  if (updates.fill_color !== undefined) {
    updated.style = {
      ...updated.style,
      fill: updates.fill_color
        ? { type: 'solid', color: updates.fill_color, alpha: 1.0 }
        : { type: 'none', alpha: 0 }
    }
  }
  if (updates.border_color !== undefined || updates.border_width !== undefined) {
    updated.style = {
      ...updated.style,
      border: {
        ...updated.style?.border,
        color: updates.border_color ?? updated.style?.border?.color ?? '#2D303F',
        width: updates.border_width ?? updated.style?.border?.width ?? 1.0,
        style: 'solid',
        alpha: 1.0
      }
    }
  }
  if (updates.radius !== undefined) {
    updated.style = { ...updated.style, radius: updates.radius }
  }
  if (updates.opacity !== undefined) {
    updated.style = { ...updated.style, opacity: updates.opacity }
  }

  if (!('text_content' in updated)) return updated

  const typographyRequested =
    updates.text !== undefined ||
    updates.font_family !== undefined ||
    updates.font_size !== undefined ||
    updates.font_color !== undefined ||
    updates.bold !== undefined ||
    updates.italic !== undefined ||
    updates.align !== undefined

  if (!typographyRequested) return updated

  let tc = (updated as any).text_content
    ? JSON.parse(JSON.stringify((updated as any).text_content))
    : null

  if (!tc || !tc.paragraphs || tc.paragraphs.length === 0) {
    tc = {
      plain_text: updates.text ?? '点击输入文本',
      paragraphs: [
        {
          align: updates.align || 'left',
          line_spacing: 1.25,
          runs: [
            {
              text: updates.text ?? '点击输入文本',
              font: {
                name: updates.font_family ?? 'Segoe UI',
                size: updates.font_size ?? 18,
                color: updates.font_color ?? '#1E293B',
                bold: updates.bold ?? false,
                italic: updates.italic ?? false
              }
            }
          ]
        }
      ]
    }
  }

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
  ;(updated as any).text_content = tc
  return updated
}

interface PPTState {
  sessionId: string
  presentation: PresentationIR | null
  confirmedPresentation: PresentationIR | null
  activeSlideId: string | null
  selectedElementId: string | null
  selectedElementIds: string[]
  selectionScope: string[]
  activeRightTab: 'copilot' | 'inspector'
  editingElementId: string | null
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
  snapEnabled: boolean
  showSmartGuides: boolean
  previewSvg: string | null
  previewScore: number | null
  qualityScore: VisualQualityScore | null
  history: PatchRecord[]
  mutationStatus: MutationStatus
  pendingMutations: PendingMutation[]
  outbox: OutboxEntry[]
  // CAS bookkeeping mirroring the last server-confirmed document identity + revision.
  documentEpoch: string | null
  confirmedRevision: number
  contextUsage: ContextUsageData | null
  setContextUsage: (usage: ContextUsageData | null) => void

  // Actions
  setSessionId: (id: string) => void
  setPresentation: (pres: PresentationIR) => void
  setActiveSlideId: (id: string) => void
  setSelectedElementId: (id: string | null) => void
  setSelectedElementIds: (ids: string[]) => void
  toggleElementSelection: (id: string) => void
  selectAllElements: () => void
  clearSelection: () => void
  enterGroup: (groupId: string) => void
  exitGroup: () => void
  setEditingElementId: (id: string | null) => void
  setActiveRightTab: (tab: 'copilot' | 'inspector') => void
  setSettingsOpen: (open: boolean) => void
  setPptspecModalOpen: (open: boolean) => void
  setZoom: (zoom: number) => void
  setShowGrid: (show: boolean) => void
  setSnapEnabled: (enabled: boolean) => void
  setShowSmartGuides: (show: boolean) => void
  setMutationStatus: (status: MutationStatus) => void
  addMessage: (msg: ChatMessage) => void
  updateLastMessage: (partial: Partial<ChatMessage>) => void
  setAgentThinking: (thinking: boolean, status?: string) => void

  // Quick Canvas Tools
  addShapeQuick: (shapeType: string, x?: number, y?: number) => void
  addTextQuick: (x?: number, y?: number) => void
  addConnectorQuick: () => void

  // Direct GUI Actions (decoupled from chat dialogue)
  executeDirectAction: (
    action: string,
    payload?: Record<string, any>,
    options?: { selectTargetOnAck?: boolean }
  ) => void
  sendMutationBatch: (operations: MutationOperation[], description?: string) => void
  sendOrQueueMutation: (message: Record<string, any>, mutation: PendingMutation) => void
  flushOutbox: () => void
  addNewSlide: (backgroundColor?: string) => void
  deleteSlide: (slideIdOrNum: string | number) => void
  duplicateSlide: (slideId: string) => void
  clearSlideElements: (slideId?: string, keepTitle?: boolean) => void
  deleteSelectedElement: () => void
  deleteSelectedElements: () => void
  duplicateSelectedElement: () => void
  duplicateSelectedElements: () => void
  groupSelectedElements: (groupName?: string) => void
  ungroupSelectedElement: () => void
  alignSelectedElements: (alignment: AlignMode) => void
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
  updateElementsDirect: (entries: Array<{ id: string; updates: Record<string, any> }>) => void
  getActiveSlide: () => SlideIR | null
  getSelectedElement: () => ElementIR | null
  getEditorState: () => PPTEditorState
}

export const usePPTStore = create<PPTState>((set, get) => ({
  sessionId: 'sess_default',
  presentation: null,
  confirmedPresentation: null,
  activeSlideId: null,
  selectedElementId: null,
  selectedElementIds: [],
  selectionScope: [],
  editingElementId: null,
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
  snapEnabled: true,
  showSmartGuides: true,
  previewSvg: null,
  previewScore: null,
  qualityScore: null,
  history: [],
  mutationStatus: 'idle',
  pendingMutations: [],
  outbox: [],
  documentEpoch: null,
  confirmedRevision: 0,
  contextUsage: {
    current_tokens: 1200,
    max_tokens: 256 * 1024,
    usage_percent: 0.46,
    is_compressed: false,
    compression_ratio: 1.0,
    tokens_saved: 0,
    context_limit_key: '256k',
    threshold_reached: false
  },
  setContextUsage: (usage) => set({ contextUsage: usage }),
  ws: null,

  setSessionId: (id: string) => set({ sessionId: id }),
  setMutationStatus: (status) => set({ mutationStatus: status }),

  setPresentation: (pres) => set({
    presentation: pres,
    confirmedPresentation: pres,
    activeSlideId: pres.active_slide_id || (pres.slides[0] ? pres.slides[0].id : null)
  }),

  setActiveSlideId: (id) => {
    set({
      activeSlideId: id,
      selectedElementId: null,
      selectedElementIds: [],
      selectionScope: [],
      editingElementId: null
    })
    const { ws, sessionId } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'select_slide', slide_id: id, session_id: sessionId }))
    }
  },

  setSelectedElementId: (id) => {
    set((state) => {
      if (id && state.selectedElementIds.includes(id)) {
        return {
          selectedElementId: id,
          activeRightTab: 'inspector'
        }
      }
      return {
        selectedElementId: id,
        selectedElementIds: id ? [id] : [],
        editingElementId: id === null ? null : state.editingElementId,
        activeRightTab: id ? 'inspector' : state.activeRightTab
      }
    })
  },

  setSelectedElementIds: (ids) => {
    set((state) => ({
      selectedElementIds: ids,
      selectedElementId: ids.length ? ids[ids.length - 1] : null,
      editingElementId: null,
      activeRightTab: ids.length ? 'inspector' : state.activeRightTab
    }))
  },

  toggleElementSelection: (id) => {
    set((state) => {
      const exists = state.selectedElementIds.includes(id)
      const ids = exists
        ? state.selectedElementIds.filter((x) => x !== id)
        : [...state.selectedElementIds, id]
      return {
        selectedElementIds: ids,
        selectedElementId: ids.length ? ids[ids.length - 1] : null,
        editingElementId: null,
        activeRightTab: ids.length ? 'inspector' : state.activeRightTab
      }
    })
  },

  selectAllElements: () => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().setSelectedElementIds(slide.elements.map((e) => e.id))
  },

  clearSelection: () => {
    set({
      selectedElementId: null,
      selectedElementIds: [],
      selectionScope: [],
      editingElementId: null
    })
  },

  enterGroup: (groupId) => {
    set((state) => (
      state.selectionScope.includes(groupId)
        ? state
        : { selectionScope: [...state.selectionScope, groupId] }
    ))
  },

  exitGroup: () => {
    set((state) => {
      if (state.selectionScope.length === 0) return state
      const scope = state.selectionScope.slice(0, -1)
      const groupId = state.selectionScope[state.selectionScope.length - 1]
      return {
        selectionScope: scope,
        selectedElementId: groupId,
        selectedElementIds: [groupId],
        editingElementId: null
      }
    })
  },

  setEditingElementId: (id) => {
    set({
      editingElementId: id,
      selectedElementId: id ?? get().selectedElementId,
      activeRightTab: id ? 'inspector' : get().activeRightTab
    })
  },

  setActiveRightTab: (tab) => set({ activeRightTab: tab }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setPptspecModalOpen: (open) => set({ pptspecModalOpen: open }),
  setZoom: (zoom) => set({ zoom }),
  setShowGrid: (show) => set({ showGrid: show }),
  setSnapEnabled: (enabled) => set({ snapEnabled: enabled }),
  setShowSmartGuides: (show) => set({ showSmartGuides: show }),

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

  sendOrQueueMutation: (message, mutation) => {
    const { ws, pendingMutations, documentEpoch, confirmedRevision } = get()
    // Base revision stamps the document generation + version this mutation was
    // computed against, so the server can reject stale/offline edits via CAS.
    const baseRevision = confirmedRevision + pendingMutations.length
    const stampedMutation: PendingMutation = {
      ...mutation,
      documentEpoch,
      expectedRevision: baseRevision
    }
    const enriched = {
      ...message,
      mutation_id: mutation.mutationId,
      document_epoch: documentEpoch,
      expected_revision: baseRevision
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      set((state) => ({
        pendingMutations: [...state.pendingMutations, stampedMutation],
        mutationStatus: 'pending'
      }))
      ws.send(JSON.stringify(enriched))
      return
    }
    set((state) => ({
      pendingMutations: [...state.pendingMutations, stampedMutation],
      outbox: [...state.outbox, { message: enriched, mutation: stampedMutation }],
      mutationStatus: 'offline'
    }))
  },

  flushOutbox: () => {
    const { ws, outbox } = get()
    if (!ws || ws.readyState !== WebSocket.OPEN || outbox.length === 0) return
    const queued = [...outbox]
    set({ outbox: [] })
    for (let i = 0; i < queued.length; i += 1) {
      if (ws.readyState !== WebSocket.OPEN) {
        set((state) => ({ outbox: [...queued.slice(i), ...state.outbox] }))
        return
      }
      ws.send(JSON.stringify(queued[i].message))
    }
  },

  sendMutationBatch: (operations, description) => {
    if (operations.length === 0) return
    if (operations.length === 1) {
      const operation = operations[0]
      get().executeDirectAction(operation.name, operation.payload)
      return
    }
    const { sessionId } = get()
    const mutationId = newMutationId()
    const mutation: PendingMutation = { mutationId, operations, description }
    get().sendOrQueueMutation(
      {
        type: 'batch_mutation',
        mutations: operations,
        session_id: sessionId,
        mutation_id: mutationId,
        description
      },
      mutation
    )
  },

  executeDirectAction: (action: string, payload: Record<string, any> = {}, options) => {
    const { sessionId, activeSlideId } = get()
    const mutationId = newMutationId()
    if (options?.selectTargetOnAck) selectTargetOnAck.add(mutationId)
    const finalPayload = { slide_id: activeSlideId, ...payload }
    const mutation: PendingMutation = {
      mutationId,
      operations: [{ name: action, payload: finalPayload }]
    }
    get().sendOrQueueMutation(
      {
        type: 'direct_action',
        action,
        payload: finalPayload,
        session_id: sessionId,
        mutation_id: mutationId
      },
      mutation
    )
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

  duplicateSlide: (slideId: string) => {
    get().executeDirectAction('duplicate_slide', { slide_id: slideId })
  },

  clearSlideElements: (slideId?: string, keepTitle = true) => {
    get().executeDirectAction('clear_slide_elements', {
      slide_id: slideId ?? get().activeSlideId,
      keep_title: keepTitle
    })
  },

  deleteSelectedElement: () => {
    const { selectedElementId, activeSlideId } = get()
    if (!selectedElementId) return
    get().executeDirectAction('delete_element', {
      element_id: selectedElementId,
      slide_id: activeSlideId
    })
    set({ selectedElementId: null, selectedElementIds: [], editingElementId: null })
  },

  deleteSelectedElements: () => {
    const { selectedElementIds, activeSlideId, presentation } = get()
    if (selectedElementIds.length === 0) return

    if (presentation) {
      const slideId = activeSlideId || presentation.slides[0]?.id
      const ids = new Set(selectedElementIds)
      const updatedSlides = presentation.slides.map((s) =>
        s.id === slideId ? { ...s, elements: removeElementsById(s.elements, ids) } : s
      )
      set({ presentation: { ...presentation, slides: updatedSlides } })
    }

    get().sendMutationBatch(
      selectedElementIds.map((id) => ({
        name: 'delete_element',
        payload: { slide_id: activeSlideId, element_id: id }
      })),
      '批量删除图元'
    )
    set({ selectedElementId: null, selectedElementIds: [], editingElementId: null })
  },

  duplicateSelectedElement: () => {
    const { selectedElementId, activeSlideId } = get()
    if (!selectedElementId) return
    get().executeDirectAction(
      'duplicate_element',
      {
        element_id: selectedElementId,
        slide_id: activeSlideId
      },
      { selectTargetOnAck: true }
    )
  },

  duplicateSelectedElements: () => {
    const { selectedElementIds, activeSlideId } = get()
    if (selectedElementIds.length === 0) return
    get().sendMutationBatch(
      selectedElementIds.map((id) => ({
        name: 'duplicate_element',
        payload: { slide_id: activeSlideId, element_id: id }
      })),
      '批量复制图元'
    )
  },

  groupSelectedElements: (groupName = '组合') => {
    const { selectedElementIds } = get()
    if (selectedElementIds.length < 2) return
    get().executeDirectAction(
      'group_elements',
      {
        element_ids: selectedElementIds,
        group_name: groupName
      },
      { selectTargetOnAck: true }
    )
    set({ selectedElementId: null, selectedElementIds: [], editingElementId: null })
  },

  ungroupSelectedElement: () => {
    const elem = get().getSelectedElement()
    if (!elem || elem.type !== 'group') return
    get().executeDirectAction('ungroup_elements', { group_id: elem.id })
  },

  alignSelectedElements: (alignment: AlignMode) => {
    const { selectedElementIds } = get()
    if (selectedElementIds.length < 2) return
    get().executeDirectAction('align_elements', {
      alignment,
      element_ids: selectedElementIds
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
    get().executeDirectAction(
      'add_shape',
      {
        shape_type: shapeType,
        x,
        y,
        width: 280,
        height: 160,
        fill_color: '#F8FAFC',
        border_color: '#CBD5E1',
        text: ''
      },
      { selectTargetOnAck: true }
    )
  },

  addTextQuick: (x = 200, y = 200) => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().executeDirectAction(
      'add_text',
      {
        text: '点击输入文本',
        x,
        y,
        width: 360,
        height: 60,
        font_size: 24,
        font_color: '#0F172A',
        bold: true
      },
      { selectTargetOnAck: true }
    )
  },

  addConnectorQuick: () => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().executeDirectAction(
      'add_connector',
      {
        start_x: 200,
        start_y: 260,
        end_x: 440,
        end_y: 260,
        border_color: '#94A3B8'
      },
      { selectTargetOnAck: true }
    )
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
      // NOTE: do NOT flush the outbox here. The server's presentation_loaded
      // snapshot first reconciles document_epoch/revision; only mutations that
      // still match the live deck are safe to replay.
    }

    ws.onclose = () => {
      const { outbox, pendingMutations } = get()
      set({
        wsConnected: false,
        ws: null,
        mutationStatus: outbox.length > 0 || pendingMutations.length > 0 ? 'offline' : 'idle'
      })
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
          set((state) => {
            const loadedEpoch: string | null = data.document_epoch ?? null
            const loadedRevision: number = data.version ?? data.presentation?.version ?? state.confirmedRevision
            const epochChanged = loadedEpoch !== null
              && state.documentEpoch !== null
              && loadedEpoch !== state.documentEpoch
            let outbox = state.outbox
            let pendingMutations = state.pendingMutations
            if (epochChanged) {
              // The deck was replaced (checkpoint restore / new document). Any
              // queued or in-flight mutation bound to the old epoch is obsolete.
              outbox = outbox.filter(
                (entry) => entry.mutation.documentEpoch == null || entry.mutation.documentEpoch === loadedEpoch
              )
              pendingMutations = pendingMutations.filter(
                (m) => m.documentEpoch == null || m.documentEpoch === loadedEpoch
              )
            }
            const hasPending = pendingMutations.length > 0
            return {
              sessionId: data.session_id || state.sessionId,
              presentation: hasPending ? state.presentation : data.presentation,
              confirmedPresentation: data.presentation,
              activeSlideId: data.active_slide_id || data.presentation.slides[0]?.id,
              canUndo: data.can_undo ?? false,
              canRedo: data.can_redo ?? false,
              selectedElementId: hasPending ? state.selectedElementId : null,
              selectedElementIds: hasPending ? state.selectedElementIds : [],
              selectionScope: hasPending ? state.selectionScope : [],
              editingElementId: null,
              outbox,
              pendingMutations,
              documentEpoch: loadedEpoch ?? state.documentEpoch,
              confirmedRevision: loadedRevision,
              mutationStatus: hasPending ? 'pending' : 'idle'
            }
          })
          get().flushOutbox()
        } else if (type === 'preview_update') {
          set({
            previewSvg: data.svg,
            previewScore: data.score,
            qualityScore: data.quality_score
          })
        } else if (type === 'presentation_updated') {
          const serverPres: PresentationIR = data.presentation
          const ackId: string | undefined = data.last_mutation_id
          const shouldSelectTarget = !!ackId && selectTargetOnAck.has(ackId)
          if (ackId) selectTargetOnAck.delete(ackId)
          set((state) => {
            let pending = state.pendingMutations
            if (ackId) {
              const idx = pending.findIndex((p) => p.mutationId === ackId)
              pending = idx >= 0 ? pending.slice(idx + 1) : pending.filter((p) => p.mutationId !== ackId)
            }
            const activeSid = data.active_slide_id || state.activeSlideId || serverPres?.slides?.[0]?.id
            const serverSlide = serverPres?.slides?.find((s) => s.id === activeSid)
            const adopting = pending.length === 0
            const presentation = adopting ? serverPres : state.presentation

            const currentSlide = adopting
              ? serverSlide
              : state.presentation?.slides?.find((s) => s.id === activeSid)

            let selectedIds = state.selectedElementIds.filter((id) =>
              existsInElements(currentSlide?.elements ?? [], id)
            )
            let selectedId = state.selectedElementId
            if (selectedId && !selectedIds.includes(selectedId)) {
              selectedId = selectedIds.length ? selectedIds[selectedIds.length - 1] : null
            }
            if (!selectedId && selectedIds.length) {
              selectedId = selectedIds[selectedIds.length - 1]
            }
            const targetId: string | undefined = data.last_target_id
            if (
              shouldSelectTarget &&
              targetId &&
              existsInElements(currentSlide?.elements ?? [], targetId)
            ) {
              selectedIds = [targetId]
              selectedId = targetId
            }
            const editingId = state.editingElementId && existsInElements(
              currentSlide?.elements ?? [],
              state.editingElementId
            )
              ? state.editingElementId
              : null

            return {
              sessionId: data.session_id || state.sessionId,
              presentation,
              confirmedPresentation: serverPres,
              activeSlideId: activeSid,
              canUndo: data.can_undo ?? state.canUndo,
              canRedo: data.can_redo ?? state.canRedo,
              mutationStatus: pending.length === 0 ? 'committed' : 'pending',
              documentEpoch: data.document_epoch ?? state.documentEpoch,
              confirmedRevision: typeof data.version === 'number' ? data.version : state.confirmedRevision,
              pendingMutations: pending,
              selectedElementIds: selectedIds,
              selectedElementId: selectedId,
              editingElementId: editingId,
              activeRightTab: selectedId ? 'inspector' : state.activeRightTab
            }
          })
        } else if (type === 'mutation_rejected') {
          const rejectedId: string | undefined = data.mutation_id
          if (rejectedId) selectTargetOnAck.delete(rejectedId)
          set((state) => {
            const pending = rejectedId
              ? state.pendingMutations.filter((p) => p.mutationId !== rejectedId)
              : state.pendingMutations
            const outbox = rejectedId
              ? state.outbox.filter((entry) => entry.mutation.mutationId !== rejectedId)
              : state.outbox
            const rollback = pending.length === 0 && state.confirmedPresentation
            return {
              pendingMutations: pending,
              outbox,
              presentation: rollback ? state.confirmedPresentation : state.presentation,
              mutationStatus: rollback ? 'rolled_back' : 'pending',
              documentEpoch: data.document_epoch ?? state.documentEpoch,
              confirmedRevision: typeof data.version === 'number' ? data.version : state.confirmedRevision
            }
          })
        } else if (type === 'active_slide_changed') {
          set({ activeSlideId: data.active_slide_id })
        } else if (type === 'context_usage') {
          if (data.usage) {
            set({ contextUsage: data.usage })
          }
        } else if (type === 'agent_thinking') {
          set({ isAgentThinking: true, thinkingStatus: data.text || 'Agent 正在规划方案...' })
        } else if (type === 'subagent_lifecycle') {
          set({ isAgentThinking: true, thinkingStatus: data.text || '独立 Subagent 盲审中...' })
        } else if (type === 'plan_critique') {
          set({ isAgentThinking: true, thinkingStatus: data.text || '方案结构盲审中...' })
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
              .then((p) => set({ presentation: p, confirmedPresentation: p }))
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
              .then((p) => set({ presentation: p, confirmedPresentation: p }))
          }
        })
    }
  },

  updateElementDirect: (elemId, updates) => {
    const { activeSlideId, presentation, sessionId } = get()

    if (presentation) {
      const slideId = activeSlideId || presentation.slides[0]?.id
      const updatedSlides = presentation.slides.map((s) =>
        s.id === slideId
          ? { ...s, elements: s.elements.map((el) => applyElementUpdate(el, elemId, updates)) }
          : s
      )
      set({ presentation: { ...presentation, slides: updatedSlides } })
    }

    const payload = {
      slide_id: activeSlideId,
      element_id: elemId,
      ...updates
    }
    const mutationId = newMutationId()
    const mutation: PendingMutation = {
      mutationId,
      operations: [{ name: 'update_element', payload }]
    }
    get().sendOrQueueMutation(
      {
        type: 'direct_update_element',
        payload,
        session_id: sessionId,
        mutation_id: mutationId
      },
      mutation
    )
  },

  updateElementsDirect: (entries) => {
    if (entries.length === 0) return
    const { activeSlideId, presentation, sessionId } = get()

    if (presentation) {
      const slideId = activeSlideId || presentation.slides[0]?.id
      const updatedSlides = presentation.slides.map((s) => {
        if (s.id !== slideId) return s
        let elements = s.elements
        for (const entry of entries) {
          elements = elements.map((el) => applyElementUpdate(el, entry.id, entry.updates))
        }
        return { ...s, elements }
      })
      set({ presentation: { ...presentation, slides: updatedSlides } })
    }

    if (entries.length === 1) {
      const entry = entries[0]
      const payload = { slide_id: activeSlideId, element_id: entry.id, ...entry.updates }
      const mutationId = newMutationId()
      const mutation: PendingMutation = {
        mutationId,
        operations: [{ name: 'update_element', payload }]
      }
      get().sendOrQueueMutation(
        {
          type: 'direct_update_element',
          payload,
          session_id: sessionId,
          mutation_id: mutationId
        },
        mutation
      )
      return
    }

    const operations: MutationOperation[] = entries.map((entry) => ({
      name: 'update_element',
      payload: { slide_id: activeSlideId, element_id: entry.id, ...entry.updates }
    }))
    get().sendMutationBatch(operations, '批量更新图元几何')
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
