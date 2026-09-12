import { create } from 'zustand'
import type {
  PresentationIR,
  SlideIR,
  ElementIR,
  GroupElementIR
} from '../types/presentation-ir.generated'
import type {
  ChatMessage,
  VisualRemediationEvent,
  VisualQualityScore,
  PPTEditorState,
  PatchRecord,
  MutationStatus,
  ContextUsageData
} from '../types/editor'
import type { CanonicalSnapshot, UIContextWire } from '../types/protocol'
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

export type MutationPrecondition =
  | { kind: 'field'; elementId: string; fields: Record<string, any> }
  | {
      kind: 'structure'
      elementId: string
      slideId: string
      elementType: string
      // Group ids from outermost down to the element's immediate parent.
      ancestorPath: string[]
      // For group targets: child ids observed at authoring time.
      childIds?: string[]
    }
  | {
      kind: 'slide'
      slideId: string
      // Slide background observed at authoring time (set_slide_background).
      background?: any
    }

// How a mutation may be replayed onto a newer authoritative snapshot.
// - 'safe': purely additive / idempotent; replay unconditionally.
// - 'preconditioned': replay only when every captured precondition still holds.
// - 'never': never auto-replay on stale; treat as a conflict (fail safe).
export type RebasePolicy = 'safe' | 'preconditioned' | 'never'

const REBASE_POLICY: Record<string, RebasePolicy> = {
  create_slide: 'safe',
  update_element: 'preconditioned',
  delete_element: 'preconditioned',
  duplicate_element: 'preconditioned',
  group_elements: 'preconditioned',
  ungroup_elements: 'preconditioned',
  // Destructive / whole-slide or whole-deck operations are never replayed onto a
  // newer authoritative snapshot: replaying them could delete or rewrite content
  // the user never saw. They fail safe as conflicts.
  delete_slide: 'never',
  duplicate_slide: 'never',
  clear_slide_elements: 'never',
  generate_slide_layout: 'preconditioned',
  align_elements: 'preconditioned',
  set_slide_background: 'preconditioned',
  optimize_layout: 'never',
  apply_theme: 'never',
  undo: 'never',
  redo: 'never'
}

const rebasePolicyFor = (operationName: string): RebasePolicy =>
  REBASE_POLICY[operationName] ?? 'never'

export interface PendingMutation {
  mutationId: string
  operations: MutationOperation[]
  description?: string
  documentEpoch?: string | null
  // Wire CAS stamp for the CURRENT attempt only. `undefined` means this logical
  // mutation has never been sent; the first dispatch stamps `confirmedRevision`.
  // A rebase establishes ONE new attempt (per queue position); a plain
  // retry-without-stale (network drop / lost ACK) reuses this exact stamp.
  attemptExpectedRevision?: number | null
  // Frozen at authoring: the canonical revision the user saw when creating this
  // logical operation. Retry and rebase must never change it.
  authoredBaseRevision?: number | null
  // Per-client logical ordering. Never mutated.
  clientSequence?: number
  // Field-level conflict detection used when rebasing onto an authoritative deck.
  precondition?: MutationPrecondition
  // Structural conflict detection for a multi-op batch.
  preconditions?: MutationPrecondition[]
  // The original wire message, retained so a rebased entry can be re-dispatched.
  lastMessage?: Record<string, any>
}

interface OutboxEntry {
  message: Record<string, any>
  mutation: PendingMutation
}

const GEOMETRY_KEYS = ['x', 'y', 'width', 'height', 'start_x', 'start_y', 'end_x', 'end_y']

let mutationCounter = 0

const selectTargetOnAck = new Set<string>()

const newMutationId = () => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `mut_${crypto.randomUUID()}`
  }
  // Test / legacy-runtime fallback only. The UUID path is the production
  // implementation and guarantees session-wide cross-client uniqueness.
  return `mut_${Date.now().toString(36)}_${(mutationCounter += 1).toString(36)}`
}

const existsInElements = (elements: ElementIR[], id: string | null | undefined): boolean => {
  if (!id) return false
  for (const el of elements) {
    if (el.id === id) return true
    if (isGroup(el) && existsInElements(el.children, id)) return true
  }
  return false
}

const findElementById = (elements: ElementIR[], id: string): ElementIR | null => {
  for (const el of elements) {
    if (el.id === id) return el
    if (isGroup(el)) {
      const found = findElementById(el.children, id)
      if (found) return found
    }
  }
  return null
}

const findElementInPresentation = (
  pres: PresentationIR | null | undefined,
  id: string
): ElementIR | null => {
  if (!pres) return null
  for (const slide of pres.slides) {
    const found = findElementById(slide.elements, id)
    if (found) return found
  }
  return null
}

const findElementRecord = (
  elements: ElementIR[],
  id: string,
  ancestors: string[] = []
): { element: ElementIR; ancestorPath: string[] } | null => {
  for (const el of elements) {
    if (el.id === id) return { element: el, ancestorPath: ancestors }
    if (isGroup(el)) {
      const found = findElementRecord(el.children, id, [...ancestors, el.id])
      if (found) return found
    }
  }
  return null
}

const slideOf = (
  pres: PresentationIR | null | undefined,
  slideId: string | null | undefined
): SlideIR | null => {
  if (!pres) return null
  const target = slideId || pres.active_slide_id || pres.slides[0]?.id
  return pres.slides.find((s) => s.id === target) ?? null
}

// Structure fingerprint frozen at authoring: existence, element type, slide id,
// ancestor/group path, and (for groups) child ids.
const captureStructurePrecondition = (
  pres: PresentationIR | null,
  slideId: string | null | undefined,
  elementId: string
): MutationPrecondition | null => {
  const slide = slideOf(pres, slideId)
  if (!slide) return null
  const record = findElementRecord(slide.elements, elementId)
  if (!record) return null
  const precondition: MutationPrecondition = {
    kind: 'structure',
    elementId,
    slideId: slide.id,
    elementType: record.element.type,
    ancestorPath: record.ancestorPath
  }
  if (isGroup(record.element)) {
    precondition.childIds = record.element.children.map((c) => c.id)
  }
  return precondition
}

const captureBackgroundPrecondition = (
  pres: PresentationIR | null,
  slideId: string | null | undefined
): MutationPrecondition | null => {
  const slide = slideOf(pres, slideId)
  if (!slide) return null
  return { kind: 'slide', slideId: slide.id, background: slide.background }
}

const captureFieldPrecondition = (
  pres: PresentationIR | null,
  slideId: string | null | undefined,
  elementId: string,
  fields: string[]
): MutationPrecondition | null => {
  const el = findElementInPresentation(pres, elementId)
  if (!el) return null
  const slide = slideOf(pres, slideId)
  if (!slide) return null
  return {
    kind: 'field',
    elementId,
    fields: Object.fromEntries(fields.map((key) => [key, (el as any)[key]]))
  }
}

const preconditionConflicts = (
  authoritative: PresentationIR,
  pre: MutationPrecondition
): boolean => {
  if (pre.kind === 'field') {
    const remoteEl = findElementInPresentation(authoritative, pre.elementId)
    if (!remoteEl) return true
    // No local-effect ledger: any field the user did not author in THIS exact
    // precondition that differs remotely is a foreign conflict. Simpler and
    // fail-safe; never excuse a remote value.
    return Object.keys(pre.fields).some(
      (key) => JSON.stringify((remoteEl as any)[key]) !== JSON.stringify(pre.fields[key])
    )
  }
  if (pre.kind === 'structure') {
    const slide = authoritative.slides.find((s) => s.id === pre.slideId)
    if (!slide) return true
    const record = findElementRecord(slide.elements, pre.elementId)
    if (!record) return true
    if (record.element.type !== pre.elementType) return true
    if (record.ancestorPath.join('/') !== pre.ancestorPath.join('/')) return true
    if (pre.childIds && isGroup(record.element)) {
      const ids = record.element.children.map((c) => c.id).join('/')
      if (ids !== pre.childIds.join('/')) return true
    }
    return false
  }
  // slide precondition: existence plus any captured background snapshot.
  const slide = authoritative.slides.find((s) => s.id === pre.slideId)
  if (!slide) return true
  if (pre.background !== undefined) {
    if (JSON.stringify(slide.background) !== JSON.stringify(pre.background)) return true
  }
  return false
}

// Best-effort local replay so a stale structural edit does not flicker. Operations
// whose result id is server-generated (group / duplicate) are left to the ACK.
const applyOperationOptimistic = (
  pres: PresentationIR,
  op: MutationOperation
): PresentationIR => {
  const payload = op.payload ?? {}
  if (op.name === 'update_element') {
    if (!payload.element_id) return pres
    const { slide_id, element_id, ...fields } = payload
    return applyUpdateToPresentation(pres, slide_id, element_id, fields)
  }
  if (op.name === 'delete_element') {
    const slideId = payload.slide_id || pres.active_slide_id || pres.slides[0]?.id
    if (!payload.element_id) return pres
    const ids = new Set<string>([String(payload.element_id)])
    return {
      ...pres,
      slides: pres.slides.map((s) =>
        s.id === slideId ? { ...s, elements: removeElementsById(s.elements, ids) } : s
      )
    }
  }
  if (op.name === 'delete_slide') {
    const sid = typeof payload.slide_id === 'string' ? payload.slide_id : undefined
    if (!sid) return pres
    return { ...pres, slides: pres.slides.filter((s) => s.id !== sid) }
  }
  if (op.name === 'ungroup_elements') {
    const groupId = payload.group_id
    const slideId = payload.slide_id || pres.active_slide_id || pres.slides[0]?.id
    if (!groupId) return pres
    return {
      ...pres,
      slides: pres.slides.map((s) => {
        if (s.id !== slideId) return s
        const out: ElementIR[] = []
        for (const el of s.elements) {
          if (isGroup(el) && el.id === groupId) out.push(...el.children)
          else out.push(el)
        }
        return { ...s, elements: out }
      })
    }
  }
  return pres
}

const rebuildOptimistic = (
  pres: PresentationIR,
  mutations: PendingMutation[]
): PresentationIR => {
  let next = pres
  for (const m of mutations) {
    for (const op of m.operations) next = applyOperationOptimistic(next, op)
  }
  return next
}

const applyUpdateToPresentation = (
  pres: PresentationIR,
  slideId: string | null | undefined,
  elemId: string,
  updates: Record<string, any>
): PresentationIR => {
  const targetSlideId = slideId || pres.active_slide_id || pres.slides[0]?.id
  return {
    ...pres,
    slides: pres.slides.map((s) =>
      s.id === targetSlideId
        ? { ...s, elements: s.elements.map((el) => applyElementUpdate(el, elemId, updates)) }
        : s
    )
  }
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
  isBootstrapping: boolean
  sessionTakenOver: boolean
  editLockState: EditLockState
  needsResync: boolean
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
  // Provenance for `previewSvg`: the slide id it actually depicts. Invariant:
  // `previewSvg != null` implies `previewSlideId` identifies exactly that slide.
  // Never derive it from `activeSlideId` (a foreign broadcast must not relabel it).
  previewSlideId: string | null
  qualityScore: VisualQualityScore | null
  history: PatchRecord[]
  mutationStatus: MutationStatus
  pendingMutations: PendingMutation[]
  outbox: OutboxEntry[]
  // Single-flight: at most one mutation is unacknowledged at a time. The next
  // mutation is only sent once the server confirms the in-flight one, so its
  // CAS revision is always the real server version (never a local prediction).
  inFlightMutationId: string | null
  inFlightMessage: Record<string, any> | null
  // CAS bookkeeping mirroring the last server-confirmed document identity + revision.
  documentEpoch: string | null
  confirmedRevision: number
  hasServerRevision: boolean
  // UI context (never document state): identifies this client's selection so the
  // Agent can bind deictic references ("这个") to explicit element ids.
  clientId: string
  uiContextRevision: number
  // Monotonic per-client logical mutation ordering.
  clientSequence: number
  contextUsage: ContextUsageData | null
  setContextUsage: (usage: ContextUsageData | null) => void

  // Actions
  setSessionId: (id: string) => void
  setPresentation: (pres: PresentationIR) => void
  adoptCanonicalSnapshot: (snapshot: CanonicalSnapshot) => void
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
    options?: {
      selectTargetOnAck?: boolean
      precondition?: MutationPrecondition
      preconditions?: MutationPrecondition[]
    }
  ) => void
  sendMutationBatch: (
    operations: MutationOperation[],
    description?: string,
    preconditions?: MutationPrecondition[]
  ) => void
  sendOrQueueMutation: (message: Record<string, any>, mutation: PendingMutation) => void
  dispatchNextMutation: () => void
  flushOutbox: () => void
  // Resolves only when all local mutations are committed server-side and a
  // server revision is known. Rejects with code LOCAL_CHANGES_NOT_SYNCED when
  // offline, failed, rolled back, or the timeout elapses.
  awaitDirectSyncBarrier: (options?: { timeoutMs?: number }) => Promise<void>
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
  bootstrapWorkspace: () => Promise<void>
  initWebSocket: () => void
  sendChatMessage: (text: string) => Promise<void>
  triggerUndo: () => void
  triggerRedo: () => void
  updateElementDirect: (elemId: string, updates: Record<string, any>) => void
  updateElementsDirect: (entries: Array<{ id: string; updates: Record<string, any> }>) => void
  getActiveSlide: () => SlideIR | null
  getSelectedElement: () => ElementIR | null
  getEditorState: () => PPTEditorState
}

export type EditLockState = 'editable' | 'agent_lock_pending' | 'agent_locked'

// Central authorization predicate: the single question that decides whether this
// client may author a document mutation. Enforced at the store choke points
// (`executeDirectAction` / `sendOrQueueMutation` / `dispatchNextMutation` and the
// optimistic authoring paths), not merely by disabled buttons.
const canAuthorMutation = (state: {
  editLockState: EditLockState
  sessionTakenOver: boolean
  needsResync: boolean
}): boolean =>
  state.editLockState === 'editable' &&
  !state.sessionTakenOver &&
  !state.needsResync

export const usePPTStore = create<PPTState>((set, get) => ({
  sessionId: '',
  isBootstrapping: false,
  sessionTakenOver: false,
  editLockState: 'editable',
  needsResync: false,
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
  previewSlideId: null,
  qualityScore: null,
  history: [],
  mutationStatus: 'idle',
  pendingMutations: [],
  outbox: [],
  inFlightMutationId: null,
  inFlightMessage: null,
  documentEpoch: null,
  confirmedRevision: 0,
  hasServerRevision: false,
  clientId: (() => {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return `client_${crypto.randomUUID()}`
    }
    return `client_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  })(),
  uiContextRevision: 0,
  clientSequence: 0,
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

  setSessionId: (id: string) => {
    if (typeof localStorage !== 'undefined' && id) {
      localStorage.setItem('ppt_session_hint', id)
    }
    set({ sessionId: id })
  },
  setMutationStatus: (status) => set({ mutationStatus: status }),

  bootstrapWorkspace: async () => {
    if (get().isBootstrapping) return
    set({ isBootstrapping: true })
    try {
      const hint = typeof localStorage !== 'undefined'
        ? localStorage.getItem('ppt_session_hint')
        : null
      const query = hint ? `?hint=${encodeURIComponent(hint)}` : ''
      const res = await fetch(`/api/workspace/bootstrap${query}`)
      if (!res.ok) {
        throw new Error(`workspace bootstrap failed: ${res.status}`)
      }
      const data = await res.json()
      if (data.session_id) {
        if (typeof localStorage !== 'undefined') {
          localStorage.setItem('ppt_session_hint', data.session_id)
        }
        set({ sessionId: data.session_id })
      }
      if (data.snapshot) {
        get().adoptCanonicalSnapshot(data.snapshot)
      }
    } catch (e) {
      // The backend workspace is the sole authority. If bootstrap is unavailable
      // we still open the socket; the server rejects/closes an invalid session.
      console.error('workspace bootstrap failed', e)
    } finally {
      set({ isBootstrapping: false })
      get().initWebSocket()
    }
  },

  setPresentation: (pres) => set({
    presentation: pres,
    confirmedPresentation: pres,
    activeSlideId: pres.active_slide_id || (pres.slides[0] ? pres.slides[0].id : null)
  }),

  // The single entry point for adopting a server document. Installs the
  // authoritative snapshot and reconciles any pending/outbox mutations by epoch,
  // so a replacement (generate/upload/restore) never leaves a stale CAS token.
  adoptCanonicalSnapshot: (snapshot) => {
    if (!snapshot || !snapshot.presentation) return
    set((state) => {
      const loadedEpoch: string | null = snapshot.document_epoch ?? null
      const loadedRevision: number =
        typeof snapshot.version === 'number'
          ? snapshot.version
          : (snapshot.presentation.version ?? state.confirmedRevision)
      const epochChanged = loadedEpoch !== null
        && state.documentEpoch !== null
        && loadedEpoch !== state.documentEpoch
      let outbox = state.outbox
      let pendingMutations = state.pendingMutations
      if (epochChanged) {
        outbox = outbox.filter(
          (entry) => entry.mutation.documentEpoch == null || entry.mutation.documentEpoch === loadedEpoch
        )
        pendingMutations = pendingMutations.filter(
          (m) => m.documentEpoch == null || m.documentEpoch === loadedEpoch
        )
      }
      const hasPending = pendingMutations.length > 0
      const inFlightSurvives = pendingMutations.some(
        (m) => m.mutationId === state.inFlightMutationId
      )
      // `active_slide_id` has no canonical document authority: the server hint
      // must never yank this client off the slide it is currently viewing.
      const serverActive =
        snapshot.active_slide_id || snapshot.presentation.slides?.[0]?.id || null
      const keepLocalActive = !!state.activeSlideId && (
        hasPending || snapshot.presentation.slides.some((s) => s.id === state.activeSlideId)
      )
      const snapshotLock = snapshot.edit_lock
      const snapshotLocked = !!snapshotLock && snapshotLock.locked === true
      return {
        sessionId: snapshot.session_id || state.sessionId,
        presentation: hasPending ? state.presentation : snapshot.presentation,
        confirmedPresentation: snapshot.presentation,
        activeSlideId: keepLocalActive ? state.activeSlideId : serverActive,
        canUndo: snapshot.can_undo ?? state.canUndo,
        canRedo: snapshot.can_redo ?? state.canRedo,
        editLockState: snapshotLocked ? 'agent_locked' : 'editable',
        needsResync: snapshotLocked ? state.needsResync : false,
        selectedElementId: hasPending ? state.selectedElementId : null,
        selectedElementIds: hasPending ? state.selectedElementIds : [],
        selectionScope: hasPending ? state.selectionScope : [],
        editingElementId: null,
        outbox,
        pendingMutations,
        inFlightMutationId: inFlightSurvives ? state.inFlightMutationId : null,
        inFlightMessage: inFlightSurvives ? state.inFlightMessage : null,
        documentEpoch: loadedEpoch ?? state.documentEpoch,
        confirmedRevision: loadedRevision,
        hasServerRevision: true,
        mutationStatus: hasPending ? 'pending' : 'idle'
      }
    })
    get().dispatchNextMutation()
  },

  setActiveSlideId: (id) => {
    set((state) => ({
      activeSlideId: id,
      // The cached preview only belongs to the slide it depicts. If we are moving
      // to a different slide, drop it rather than let components read a stale SVG.
      previewSvg: state.previewSlideId === id ? state.previewSvg : null,
      previewScore: state.previewSlideId === id ? state.previewScore : null,
      qualityScore: state.previewSlideId === id ? state.qualityScore : null,
      previewSlideId: state.previewSlideId === id ? state.previewSlideId : null,
      selectedElementId: null,
      selectedElementIds: [],
      selectionScope: [],
      editingElementId: null,
      uiContextRevision: state.uiContextRevision + 1
    }))
    // Navigation is CLIENT-LOCAL UI state, never a shared document field. We only
    // ask the server for a preview of the newly viewed slide; the server must not
    // treat this as a session-wide active-slide change nor broadcast it.
    const { ws } = get()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'preview_request', slide_id: id }))
    }
  },

  setSelectedElementId: (id) => {
    set((state) => {
      if (id && state.selectedElementIds.includes(id)) {
        return {
          selectedElementId: id,
          activeRightTab: 'inspector',
          uiContextRevision: state.uiContextRevision + 1
        }
      }
      return {
        selectedElementId: id,
        selectedElementIds: id ? [id] : [],
        editingElementId: id === null ? null : state.editingElementId,
        activeRightTab: id ? 'inspector' : state.activeRightTab,
        uiContextRevision: state.uiContextRevision + 1
      }
    })
  },

  setSelectedElementIds: (ids) => {
    set((state) => ({
      selectedElementIds: ids,
      selectedElementId: ids.length ? ids[ids.length - 1] : null,
      editingElementId: null,
      activeRightTab: ids.length ? 'inspector' : state.activeRightTab,
      uiContextRevision: state.uiContextRevision + 1
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
        activeRightTab: ids.length ? 'inspector' : state.activeRightTab,
        uiContextRevision: state.uiContextRevision + 1
      }
    })
  },

  selectAllElements: () => {
    const slide = get().getActiveSlide()
    if (!slide) return
    get().setSelectedElementIds(slide.elements.map((e) => e.id))
  },

  clearSelection: () => {
    set((state) => ({
      selectedElementId: null,
      selectedElementIds: [],
      selectionScope: [],
      editingElementId: null,
      uiContextRevision: state.uiContextRevision + 1
    }))
  },

  enterGroup: (groupId) => {
    set((state) => (
      state.selectionScope.includes(groupId)
        ? state
        : {
            selectionScope: [...state.selectionScope, groupId],
            uiContextRevision: state.uiContextRevision + 1
          }
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
        editingElementId: null,
        uiContextRevision: state.uiContextRevision + 1
      }
    })
  },

  setEditingElementId: (id) => {
    set((state) => ({
      editingElementId: id,
      selectedElementId: id ?? state.selectedElementId,
      activeRightTab: id ? 'inspector' : state.activeRightTab,
      uiContextRevision: state.uiContextRevision + 1
    }))
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
    // Choke point: no mutation may be authored while the Agent owns the document,
    // the session was taken over, or a resync is pending.
    if (!canAuthorMutation(get())) return
    const state = get()
    const { ws, documentEpoch } = state
    const sequence = mutation.clientSequence ?? (state.clientSequence + 1)
    const stampedMutation: PendingMutation = {
      ...mutation,
      documentEpoch,
      authoredBaseRevision: mutation.authoredBaseRevision ?? state.confirmedRevision,
      clientSequence: sequence,
      lastMessage: message
    }
    const online = !!ws && ws.readyState === WebSocket.OPEN
    set((s) => ({
      pendingMutations: [...s.pendingMutations, stampedMutation],
      outbox: [...s.outbox, { message, mutation: stampedMutation }],
      clientSequence: sequence,
      mutationStatus: online ? 'pending' : 'offline'
    }))
    get().dispatchNextMutation()
  },

  dispatchNextMutation: () => {
    // Never dispatch while frozen/taken-over/resyncing: a queued mutation from a
    // previous epoch must not leak into the Agent's document.
    if (!canAuthorMutation(get())) return
    const {
      ws, outbox, inFlightMutationId, documentEpoch, confirmedRevision, hasServerRevision
    } = get()
    if (inFlightMutationId !== null) return
    if (!ws || ws.readyState !== WebSocket.OPEN || outbox.length === 0) return
    // Every direct mutation is mutation-bearing and MUST carry CAS stamps. Until
    // the canonical snapshot has established a document identity, the client has
    // no stamp to send: keep the edit queued rather than emit an unstamped write
    // the gateway will (correctly) reject.
    if (!hasServerRevision || documentEpoch == null) return

    const [head] = outbox
    // A retried mutation must reuse the CAS stamp it was first sent with: the
    // server may have already committed it (idempotent replay) or rejected it as
    // stale. Re-stamping here would let a stale retry pass CAS against a deck it
    // never observed. `attemptExpectedRevision === undefined` means "never sent".
    const alreadySent = head.mutation.attemptExpectedRevision !== undefined
    const sendEpoch = alreadySent
      ? (head.mutation.documentEpoch ?? documentEpoch)
      : documentEpoch
    const expectedRevision = alreadySent
      ? (head.mutation.attemptExpectedRevision ?? null)
      : (hasServerRevision ? confirmedRevision : null)
    const payload: Record<string, any> = {
      ...head.message,
      mutation_id: head.mutation.mutationId,
      document_epoch: sendEpoch,
      client_id: get().clientId,
      client_sequence: head.mutation.clientSequence ?? 0
    }
    if (expectedRevision !== null) payload.expected_revision = expectedRevision

    ws.send(JSON.stringify(payload))
    set((state) => ({
      outbox: state.outbox.slice(1),
      pendingMutations: state.pendingMutations.map((m) =>
        m.mutationId === head.mutation.mutationId
          ? { ...m, documentEpoch: sendEpoch, attemptExpectedRevision: expectedRevision }
          : m
      ),
      inFlightMutationId: head.mutation.mutationId,
      inFlightMessage: head.message,
      mutationStatus: 'pending'
    }))
  },

  flushOutbox: () => {
    get().dispatchNextMutation()
  },

  awaitDirectSyncBarrier: (options) => {
    const timeoutMs = options?.timeoutMs ?? 10000
    // Barrier-gated actions (chat / export / upload / generate / restore) require
    // a LIVE transport: a clean local state while offline still cannot guarantee
    // the server will observe committed edits, so it must hard-fail, never
    // silently succeed. Direct GUI mutations remain queued in the outbox instead.
    const isOnline = () => {
      const s = get()
      return !!s.ws && s.ws.readyState === WebSocket.OPEN
    }
    const isSynced = () => {
      const s = get()
      return (
        isOnline() &&
        s.pendingMutations.length === 0 &&
        s.outbox.length === 0 &&
        s.inFlightMutationId === null &&
        s.hasServerRevision &&
        s.mutationStatus !== 'failed' &&
        s.mutationStatus !== 'rolled_back'
      )
    }
    if (isSynced()) return Promise.resolve()

    return new Promise<void>((resolve, reject) => {
      const deadline = Date.now() + timeoutMs
      let timer: number | undefined
      const fail = () => {
        if (timer !== undefined) window.clearTimeout(timer)
        reject(Object.assign(new Error('LOCAL_CHANGES_NOT_SYNCED'), {
          code: 'LOCAL_CHANGES_NOT_SYNCED'
        }))
      }
      const tick = () => {
        const s = get()
        if (isSynced()) {
          if (timer !== undefined) window.clearTimeout(timer)
          resolve()
          return
        }
        if (s.mutationStatus === 'failed' || s.mutationStatus === 'rolled_back') {
          fail()
          return
        }
        const offline = !isOnline()
        if (offline || Date.now() >= deadline) {
          fail()
          return
        }
        timer = window.setTimeout(tick, 25)
      }
      timer = window.setTimeout(tick, 0)
    })
  },

  sendMutationBatch: (operations, description, preconditions) => {
    if (operations.length === 0) return
    if (operations.length === 1) {
      const operation = operations[0]
      get().executeDirectAction(operation.name, operation.payload, { preconditions })
      return
    }
    const { sessionId } = get()
    const mutationId = newMutationId()
    const mutation: PendingMutation = { mutationId, operations, description, preconditions }
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
    if (!canAuthorMutation(get())) return
    const { sessionId, activeSlideId } = get()
    const mutationId = newMutationId()
    if (options?.selectTargetOnAck) selectTargetOnAck.add(mutationId)
    const finalPayload = { slide_id: activeSlideId, ...payload }
    const mutation: PendingMutation = {
      mutationId,
      operations: [{ name: action, payload: finalPayload }],
      precondition: options?.precondition,
      preconditions: options?.preconditions
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
    const { activeSlideId, confirmedPresentation, presentation } = get()
    const base = confirmedPresentation ?? presentation
    // Resolve a 1-based slide number to its STABLE id at authoring time using the
    // same predicate the backend uses (`id === ref || slide_num === ref`), first
    // match in a single ordered pass and NO index fallback. The wire call always
    // carries the resolved stable id so a remote reorder cannot delete the wrong
    // slide.
    const ref = String(slideIdOrNum)
    const resolved = base?.slides.find((s) => s.id === ref || String(s.slide_num) === ref)
    const slideId = resolved?.id ?? (typeof slideIdOrNum === 'string' ? slideIdOrNum : activeSlideId)
    if (!slideId) return
    get().executeDirectAction(
      'delete_slide',
      { slide_id_or_num: slideId }
    )
  },

  duplicateSlide: (slideId: string) => {
    get().executeDirectAction(
      'duplicate_slide',
      { slide_id: slideId }
    )
  },

  clearSlideElements: (slideId?: string, keepTitle = true) => {
    const { activeSlideId } = get()
    const target = slideId ?? activeSlideId
    get().executeDirectAction(
      'clear_slide_elements',
      { slide_id: target, keep_title: keepTitle }
    )
  },

  deleteSelectedElement: () => {
    const { selectedElementId, activeSlideId, confirmedPresentation, presentation } = get()
    if (!selectedElementId) return
    const base = confirmedPresentation ?? presentation
    get().executeDirectAction(
      'delete_element',
      { element_id: selectedElementId, slide_id: activeSlideId },
      { precondition: captureStructurePrecondition(base, activeSlideId, selectedElementId) ?? undefined }
    )
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

    const base = get().confirmedPresentation ?? get().presentation
    get().sendMutationBatch(
      selectedElementIds.map((id) => ({
        name: 'delete_element',
        payload: { slide_id: activeSlideId, element_id: id }
      })),
      '批量删除图元',
      selectedElementIds
        .map((id) => captureStructurePrecondition(base, activeSlideId, id))
        .filter((p): p is MutationPrecondition => p !== null)
    )
    set({ selectedElementId: null, selectedElementIds: [], editingElementId: null })
  },

  duplicateSelectedElement: () => {
    const { selectedElementId, activeSlideId, confirmedPresentation, presentation } = get()
    if (!selectedElementId) return
    const base = confirmedPresentation ?? presentation
    get().executeDirectAction(
      'duplicate_element',
      { element_id: selectedElementId, slide_id: activeSlideId },
      {
        selectTargetOnAck: true,
        precondition: captureStructurePrecondition(base, activeSlideId, selectedElementId) ?? undefined
      }
    )
  },

  duplicateSelectedElements: () => {
    const { selectedElementIds, activeSlideId } = get()
    if (selectedElementIds.length === 0) return
    const base = get().confirmedPresentation ?? get().presentation
    get().sendMutationBatch(
      selectedElementIds.map((id) => ({
        name: 'duplicate_element',
        payload: { slide_id: activeSlideId, element_id: id }
      })),
      '批量复制图元',
      selectedElementIds
        .map((id) => captureStructurePrecondition(base, activeSlideId, id))
        .filter((p): p is MutationPrecondition => p !== null)
    )
  },

  groupSelectedElements: (groupName = '组合') => {
    const { selectedElementIds, activeSlideId, confirmedPresentation, presentation } = get()
    if (selectedElementIds.length < 2) return
    const base = confirmedPresentation ?? presentation
    get().executeDirectAction(
      'group_elements',
      {
        element_ids: selectedElementIds,
        group_name: groupName
      },
      {
        selectTargetOnAck: true,
        preconditions: selectedElementIds
          .map((id) => captureStructurePrecondition(base, activeSlideId, id))
          .filter((p): p is MutationPrecondition => p !== null)
      }
    )
    set({ selectedElementId: null, selectedElementIds: [], editingElementId: null })
  },

  ungroupSelectedElement: () => {
    const elem = get().getSelectedElement()
    if (!elem || elem.type !== 'group') return
    const base = get().confirmedPresentation ?? get().presentation
    get().executeDirectAction(
      'ungroup_elements',
      { group_id: elem.id },
      { precondition: captureStructurePrecondition(base, get().activeSlideId, elem.id) ?? undefined }
    )
  },

  alignSelectedElements: (alignment: AlignMode) => {
    const { selectedElementIds, activeSlideId, confirmedPresentation, presentation } = get()
    if (selectedElementIds.length < 2) return
    const base = confirmedPresentation ?? presentation
    // Align rewrites geometry on every involved element: freeze each element's
    // x/y so a remote geometry change is a conflict, not a silent overwrite.
    const preconditions = selectedElementIds
      .map((id) => captureFieldPrecondition(base, activeSlideId, id, ['x', 'y']))
      .filter((p): p is MutationPrecondition => p !== null)
    get().executeDirectAction(
      'align_elements',
      { alignment, element_ids: selectedElementIds },
      { preconditions }
    )
  },

  setSlideBackgroundDirect: (color: string) => {
    const { activeSlideId, confirmedPresentation, presentation } = get()
    const base = confirmedPresentation ?? presentation
    get().executeDirectAction(
      'set_slide_background',
      { color, slide_id: activeSlideId },
      { precondition: captureBackgroundPrecondition(base, activeSlideId) ?? undefined }
    )
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
    const sessionId = get().sessionId
    if (!sessionId) {
      // Workspace not bootstrapped yet; App calls bootstrapWorkspace() first.
      return
    }
    const existingWs = get().ws
    if (existingWs) {
      existingWs.close()
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws?session_id=${sessionId}`

    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      set({ wsConnected: true, ws, sessionTakenOver: false })
      // NOTE: do NOT flush the outbox here. The server's presentation_loaded
      // snapshot first reconciles document_epoch/revision; only mutations that
      // still match the live deck are safe to replay.
    }

    ws.onclose = (event) => {
      const code = (event as CloseEvent | undefined)?.code
      // Newest-tab-wins: a superseded tab must never auto-reconnect (that would
      // fight the tab that took over the workspace).
      if (get().sessionTakenOver || code === 4001) {
        set({
          ws: null,
          wsConnected: false,
          sessionTakenOver: true,
          inFlightMutationId: null,
          inFlightMessage: null,
          mutationStatus: 'idle'
        })
        return
      }
      const { outbox, pendingMutations, inFlightMutationId, inFlightMessage } = get()
      let nextOutbox = outbox
      if (inFlightMutationId !== null && inFlightMessage) {
        const inflight = pendingMutations.find((m) => m.mutationId === inFlightMutationId)
        if (inflight) {
          nextOutbox = [{ message: inFlightMessage, mutation: inflight }, ...outbox]
        }
      }
      set({
        wsConnected: false,
        ws: null,
        inFlightMutationId: null,
        inFlightMessage: null,
        outbox: nextOutbox,
        mutationStatus: nextOutbox.length > 0 || pendingMutations.length > 0 ? 'offline' : 'idle'
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

        if (type === 'document_frozen') {
          const locked = data.edit_lock?.locked !== false
          if (!locked) {
            set({ editLockState: 'editable' })
            return
          }
          // The Agent now owns the document. Any local mutation chain is obsolete:
          // it was authored against a revision the Agent is about to rewrite and
          // must never be replayed into the Agent's result. Retire it fully and
          // wait for the turn's terminal canonical snapshot.
          set((state) => {
            for (const p of state.pendingMutations) selectTargetOnAck.delete(p.mutationId)
            return {
              editLockState: 'agent_locked',
              needsResync: true,
              pendingMutations: [],
              outbox: [],
              inFlightMutationId: null,
              inFlightMessage: null,
              presentation: state.confirmedPresentation ?? state.presentation,
              mutationStatus: 'resyncing'
            }
          })
        } else if (type === 'session_taken_over') {
          set({ sessionTakenOver: true })
          get().addMessage({
            id: `takeover_${Date.now()}`,
            role: 'assistant',
            content: '该工作区已在其他标签页打开，本页已停止同步与编辑。',
            timestamp: Date.now()
          })
        } else if (type === 'presentation_loaded') {
          // Adopt through the SAME canonical path as every other server document
          // (ACK, CAS rejection, REST, upload). A bespoke branch here would be a
          // second source of truth for epoch/revision reconciliation.
          get().adoptCanonicalSnapshot(data)
        } else if (type === 'preview_update') {
          // Preview is client-local: apply it only when it depicts the slide this
          // client is actually viewing. A broadcast triggered by another client's
          // mutation must not repaint our canvas with a foreign slide.
          if (data.slide_id && data.slide_id !== get().activeSlideId) {
            return
          }
          set({
            previewSlideId: data.slide_id ?? null,
            previewSvg: data.svg,
            previewScore: data.score,
            qualityScore: data.quality_score
          })
        } else if (type === 'presentation_updated') {
          if (data.edit_lock) {
            const locked = data.edit_lock.locked === true
            set((state) => ({
              editLockState: locked ? 'agent_locked' : 'editable',
              needsResync: locked ? state.needsResync : false
            }))
          }
          const serverPres: PresentationIR = data.presentation
          const ackId: string | undefined = data.last_mutation_id
          const shouldSelectTarget = !!ackId && selectTargetOnAck.has(ackId)
          if (ackId) selectTargetOnAck.delete(ackId)
          let localNavHint: string | null = null
          set((state) => {
            let pending = state.pendingMutations
            let inFlightMutationId = state.inFlightMutationId
            if (ackId) {
              const idx = pending.findIndex((p) => p.mutationId === ackId)
              pending = idx >= 0 ? pending.slice(idx + 1) : pending.filter((p) => p.mutationId !== ackId)
              if (state.inFlightMutationId === ackId) {
                inFlightMutationId = null
              }
            }
            const isLocalAck = !!ackId && (
              state.pendingMutations.some((p) => p.mutationId === ackId) ||
              state.inFlightMutationId === ackId
            )
            const localActive = state.activeSlideId
            const localActiveValid = !!localActive &&
              !!serverPres?.slides?.some((s) => s.id === localActive)
            // Navigation is client-local: the shared document's `active_slide_id`
            // has no authority over a viewer. The ONLY way a mutation moves this
            // client's view is a mutation-scoped `local_view_hint` attached to
            // THIS client's own ACK (e.g. a create_slide whose new id this client
            // could not have known). Remote broadcasts, and other clients'
            // mutations reflected by the shared active_slide_id, never navigate.
            const hint = isLocalAck ? data.local_view_hint : null
            const hintSid = hint?.active_slide_id
            const hintValid = !!hintSid &&
              !!serverPres?.slides?.some((s) => s.id === hintSid)
            const activeSid = hintValid
              ? hintSid
              : (localActiveValid
                ? localActive
                : (data.active_slide_id || state.activeSlideId || serverPres?.slides?.[0]?.id))
            if (hintValid) localNavHint = hintSid
            // The cached preview must always match the slide it depicts. If this
            // snapshot moves us to a different slide, drop the stale preview; the
            // initiator then requests the new slide's preview below.
            const previewBelongs = !!state.previewSvg && state.previewSlideId === activeSid
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
              previewSvg: previewBelongs ? state.previewSvg : null,
              previewScore: previewBelongs ? state.previewScore : null,
              qualityScore: previewBelongs ? state.qualityScore : null,
              previewSlideId: previewBelongs ? state.previewSlideId : null,
              canUndo: data.can_undo ?? state.canUndo,
              canRedo: data.can_redo ?? state.canRedo,
              mutationStatus: pending.length === 0 ? 'committed' : 'pending',
              documentEpoch: data.document_epoch ?? state.documentEpoch,
              confirmedRevision: typeof data.version === 'number' ? data.version : state.confirmedRevision,
              hasServerRevision: typeof data.version === 'number' ? true : state.hasServerRevision,
              pendingMutations: pending,
              inFlightMutationId,
              inFlightMessage: inFlightMutationId === null ? null : state.inFlightMessage,
              selectedElementIds: selectedIds,
              selectedElementId: selectedId,
              editingElementId: editingId,
              activeRightTab: selectedId ? 'inspector' : state.activeRightTab
            }
          })
          // A local_view_hint moved THIS client to a newly created slide. Fetch its
          // preview now so the canvas never shows the previous slide's SVG.
          if (localNavHint) {
            const { ws } = get()
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'preview_request', slide_id: localNavHint }))
            }
          }
          get().dispatchNextMutation()
        } else if (type === 'mutation_rejected') {
          const rejectedId: string | undefined = data.mutation_id
          if (rejectedId) selectTargetOnAck.delete(rejectedId)
          const error: string = data.error ?? ''
          if (error === 'stale_connection' || error === 'session_taken_over') {
            // A superseded socket may not write. Stop all authoring locally.
            set({ sessionTakenOver: true })
            return
          }
          if (error === 'document_frozen') {
            // Retire the in-flight/queued chain (it must never be replayed into
            // the Agent's document) and wait for the terminal snapshot.
            set((state) => {
              for (const p of state.pendingMutations) selectTargetOnAck.delete(p.mutationId)
              return {
                editLockState: 'agent_locked',
                needsResync: true,
                pendingMutations: [],
                outbox: [],
                inFlightMutationId: null,
                inFlightMessage: null,
                presentation: state.confirmedPresentation ?? state.presentation,
                mutationStatus: 'resyncing'
              }
            })
            return
          }
          const isStale = error === 'stale_mutation' || error === 'document_epoch_mismatch'
          if (isStale) {
            const authoritative: PresentationIR | undefined = data.presentation
            const preState = get()
            const priorEpoch = preState.documentEpoch
            const serverEpoch = data.document_epoch ?? priorEpoch
            const epochChanged = !!priorEpoch && !!serverEpoch && priorEpoch !== serverEpoch

            if (epochChanged || !authoritative) {
              // Different document identity (or no snapshot to rebase onto):
              // auto-replay is forbidden because it is not the same deck anymore.
              set((state) => {
                for (const p of state.pendingMutations) selectTargetOnAck.delete(p.mutationId)
                const nextPres = authoritative ?? state.confirmedPresentation ?? state.presentation
                return {
                  pendingMutations: [],
                  outbox: [],
                  inFlightMutationId: null,
                  inFlightMessage: null,
                  presentation: nextPres,
                  confirmedPresentation: nextPres,
                  activeSlideId:
                    data.active_slide_id
                    ?? nextPres?.active_slide_id
                    ?? nextPres?.slides?.[0]?.id
                    ?? state.activeSlideId,
                  documentEpoch: serverEpoch ?? state.documentEpoch,
                  confirmedRevision:
                    typeof data.version === 'number' ? data.version : state.confirmedRevision,
                  hasServerRevision: true,
                  canUndo: data.can_undo ?? state.canUndo,
                  canRedo: data.can_redo ?? state.canRedo,
                  selectedElementId: null,
                  selectedElementIds: [],
                  selectionScope: [],
                  editingElementId: null,
                  mutationStatus: 'resynced'
                }
              })
              get().addMessage({
                id: `sys_${Date.now()}`,
                role: 'assistant',
                content: '文档已被替换（epoch 变化），本地未提交的修改无法安全重放，已丢弃。请重新编辑。',
                timestamp: Date.now()
              })
              return
            }

            // Same epoch: explicit rebase. Install the authoritative snapshot,
            // drop only foreign conflicts, replay the rest optimistically, and
            // establish a NEW CAS attempt for the queue HEAD ONLY. Tail survivors
            // keep `attemptExpectedRevision === undefined`; each is stamped with
            // the then-current confirmed revision after the preceding ACK, so a
            // local ordered queue can never stale itself. `authoredBaseRevision`
            // is frozen and never rewritten.
            const baseRevision = typeof data.version === 'number' ? data.version : preState.confirmedRevision
            const conflicts: string[] = []
            const surviving: PendingMutation[] = []
            for (const m of preState.pendingMutations) {
              const preconditions: MutationPrecondition[] = [
                ...(m.precondition ? [m.precondition] : []),
                ...(m.preconditions ?? [])
              ]
              // RebasePolicy is enforced HERE, centrally, never per-call-site.
              // Any op that is not explicitly replayable makes the whole
              // mutation a conflict; 'preconditioned' ops with no captured
              // precondition also fail safe (missing precondition == conflict).
              const policies = m.operations.map((op) => rebasePolicyFor(op.name))
              let conflicted: boolean
              if (policies.some((p) => p === 'never')) {
                conflicted = true
              } else if (policies.every((p) => p === 'safe')) {
                conflicted = false
              } else {
                conflicted = preconditions.length === 0 || preconditions.some((pre) =>
                  preconditionConflicts(authoritative, pre)
                )
              }
              if (conflicted) {
                const label = preconditions
                  .map((p) => (p.kind === 'field' || p.kind === 'structure' ? p.elementId : p.slideId))
                  .filter(Boolean)
                conflicts.push(...label)
                selectTargetOnAck.delete(m.mutationId)
                continue
              }
              surviving.push({ ...m, documentEpoch: serverEpoch })
            }
            if (surviving.length) {
              surviving[0] = { ...surviving[0], attemptExpectedRevision: baseRevision }
            }

            const optimistic = rebuildOptimistic(authoritative, surviving)

            const localActiveSurvives = !!preState.activeSlideId &&
              optimistic.slides.some((s) => s.id === preState.activeSlideId)

            set({
              presentation: optimistic,
              confirmedPresentation: authoritative,
              activeSlideId: localActiveSurvives
                ? preState.activeSlideId
                : (authoritative.active_slide_id ?? optimistic.slides[0]?.id ?? preState.activeSlideId),
              documentEpoch: serverEpoch,
              confirmedRevision: baseRevision,
              hasServerRevision: true,
              canUndo: data.can_undo ?? preState.canUndo,
              canRedo: data.can_redo ?? preState.canRedo,
              pendingMutations: surviving,
              outbox: surviving.map((m) => ({ message: m.lastMessage ?? {}, mutation: m })),
              inFlightMutationId: null,
              inFlightMessage: null,
              // A conflict means the authoritative deck changed under the
              // selection: drop stale selection/scope so it cannot point at a
              // removed or regrouped object.
              selectedElementId: conflicts.length ? null : preState.selectedElementId,
              selectedElementIds: conflicts.length ? [] : preState.selectedElementIds,
              selectionScope: conflicts.length ? [] : preState.selectionScope,
              editingElementId: conflicts.length ? null : preState.editingElementId,
              mutationStatus: surviving.length ? 'pending' : 'resynced'
            })

            if (conflicts.length) {
              get().addMessage({
                id: `sys_${Date.now()}`,
                role: 'assistant',
                content: `检测到与服务器修改的字段冲突，已跳过 ${conflicts.length} 个元素：${conflicts.join(', ')}。`,
                timestamp: Date.now()
              })
            }
            if (surviving.length) {
              get().dispatchNextMutation()
            }
            return
          }
          set((state) => {
            const pending = rejectedId
              ? state.pendingMutations.filter((p) => p.mutationId !== rejectedId)
              : state.pendingMutations
            const outbox = rejectedId
              ? state.outbox.filter((entry) => entry.mutation.mutationId !== rejectedId)
              : state.outbox
            const rollback = pending.length === 0 && state.confirmedPresentation
            const inFlightMutationId =
              rejectedId && state.inFlightMutationId === rejectedId ? null : state.inFlightMutationId
            return {
              pendingMutations: pending,
              outbox,
              inFlightMutationId,
              inFlightMessage: inFlightMutationId === null ? null : state.inFlightMessage,
              presentation: rollback ? state.confirmedPresentation : state.presentation,
              mutationStatus: rollback ? 'rolled_back' : 'pending',
              documentEpoch: data.document_epoch ?? state.documentEpoch,
              confirmedRevision: typeof data.version === 'number' ? data.version : state.confirmedRevision,
              hasServerRevision: typeof data.version === 'number' ? true : state.hasServerRevision
            }
          })
          get().dispatchNextMutation()
        } else if (type === 'active_slide_changed') {
          // Deprecated: active slide is client-local UI state. A session-global
          // navigation broadcast must not move this client's view.
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

  sendChatMessage: async (text) => {
    const { addMessage } = get()
    if (!text.trim()) return

    // The Agent must observe every committed local edit before planning or the
    // turn could target a revision that no longer exists.
    try {
      await get().awaitDirectSyncBarrier({ timeoutMs: 10000 })
    } catch {
      addMessage({
        id: `barrier_${Date.now()}`,
        role: 'assistant',
        content: '本地修改尚未同步完成，已取消本次发送。请等待同步完成或重试。',
        timestamp: Date.now()
      })
      return
    }

    // Re-read the live transport AFTER the barrier: the socket can drop or be
    // taken over while we awaited. There is deliberately NO REST fallback — a
    // REST chat would bypass the session's single-frontend ownership and the
    // websocket edit-lock stream, so a missing socket fails closed instead.
    const current = get()
    if (
      !current.ws ||
      current.ws.readyState !== WebSocket.OPEN ||
      current.sessionTakenOver
    ) {
      set({ editLockState: 'editable', isAgentThinking: false, thinkingStatus: '' })
      addMessage({
        id: `notsynced_${Date.now()}`,
        role: 'assistant',
        content: '实时连接不可用（本地修改未同步或会话已被接管），已取消本次发送。请检查连接或刷新页面后重试。',
        timestamp: Date.now()
      })
      return
    }

    // Request-scoped UI context: never written into the document, it lets the
    // Agent bind "这个/它" to the elements this client currently has selected.
    const uiContext: UIContextWire = {
      client_id: current.clientId,
      ui_context_revision: current.uiContextRevision,
      active_slide_id: current.activeSlideId,
      selected_element_ids: current.selectedElementIds,
      primary_selected_element_id: current.selectedElementId,
      selection_scope: current.selectionScope,
      editing_element_id: current.editingElementId
    }

    addMessage({
      id: `user_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now()
    })

    set({
      isAgentThinking: true,
      thinkingStatus: '分析需求与视觉结构...',
      activeRightTab: 'copilot',
      // Enter the freeze before the server ack so a fast local edit can't slip in
      // between "Send" and the server's document_frozen broadcast.
      editLockState: 'agent_lock_pending'
    })

    current.ws.send(JSON.stringify({
      type: 'chat',
      message: text,
      session_id: current.sessionId,
      document_epoch: current.documentEpoch,
      base_revision: current.confirmedRevision,
      ui_context: uiContext
    }))
  },

  triggerUndo: () => {
    const { sessionId } = get()
    const mutationId = newMutationId()
    const mutation: PendingMutation = {
      mutationId,
      operations: [{ name: 'undo', payload: {} }],
      description: '撤销'
    }
    get().sendOrQueueMutation(
      { type: 'undo', session_id: sessionId, mutation_id: mutationId },
      mutation
    )
  },

  triggerRedo: () => {
    const { sessionId } = get()
    const mutationId = newMutationId()
    const mutation: PendingMutation = {
      mutationId,
      operations: [{ name: 'redo', payload: {} }],
      description: '重做'
    }
    get().sendOrQueueMutation(
      { type: 'redo', session_id: sessionId, mutation_id: mutationId },
      mutation
    )
  },

  updateElementDirect: (elemId, updates) => {
    // Guard BEFORE the optimistic apply so a frozen document never drifts locally.
    if (!canAuthorMutation(get())) return
    const { activeSlideId, presentation, confirmedPresentation, sessionId } = get()

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
    // Precondition is captured from the last server-CONFIRMED state (not the
    // optimistic view) so a rebase compares against what the server actually had.
    const canonicalEl = findElementInPresentation(confirmedPresentation ?? presentation, elemId)
    const precondition: MutationPrecondition | undefined = canonicalEl
      ? {
          kind: 'field',
          elementId: elemId,
          fields: Object.fromEntries(
            Object.keys(updates).map((key) => [key, (canonicalEl as any)[key]])
          )
        }
      : undefined
    const mutationId = newMutationId()
    const mutation: PendingMutation = {
      mutationId,
      operations: [{ name: 'update_element', payload }],
      precondition
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
    // Guard BEFORE the optimistic apply so a frozen document never drifts locally.
    if (!canAuthorMutation(get())) return
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
      previewSlideId,
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
        slide_id: previewSlideId ?? activeSlideId ?? '',
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
