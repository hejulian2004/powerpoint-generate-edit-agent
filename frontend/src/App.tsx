import React, { useEffect } from 'react'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { SlideCanvas } from './components/SlideCanvas'
import { ChatPanel } from './components/ChatPanel'
import { SettingsModal } from './components/SettingsModal'
import { PPTSpecImportModal } from './components/PPTSpecImportModal'
import { usePPTStore } from './store/usePPTStore'

export const App: React.FC = () => {
  const { bootstrapWorkspace, bootstrapError } = usePPTStore()

  useEffect(() => {
    bootstrapWorkspace()

    // Global keyboard shortcuts for power-user editing
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isEditable = !!target && (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable
      )
      const mod = e.ctrlKey || e.metaKey
      const key = e.key.toLowerCase()
      const store = usePPTStore.getState()

      // Editable targets keep their native editing shortcuts (undo, select-all, delete...).
      if (isEditable) return

      if (mod && key === 'z') {
        e.preventDefault()
        if (e.shiftKey) {
          store.triggerRedo()
        } else {
          store.triggerUndo()
        }
      } else if (mod && key === 'y') {
        e.preventDefault()
        store.triggerRedo()
      } else if (mod && key === 'g') {
        e.preventDefault()
        if (e.shiftKey) {
          store.ungroupSelectedElement()
        } else {
          store.groupSelectedElements()
        }
      } else if (mod && key === 'a') {
        e.preventDefault()
        store.selectAllElements()
      } else if (mod && key === 'd') {
        e.preventDefault()
        store.duplicateSelectedElements()
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault()
        store.deleteSelectedElements()
      } else if (e.key === 'Escape') {
        if (store.editingElementId) {
          store.setEditingElementId(null)
        } else if (store.selectionScope.length > 0) {
          store.exitGroup()
        } else {
          store.clearSelection()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className="flex flex-col w-screen h-screen bg-canvas text-main antialiased overflow-hidden">
      {bootstrapError && (
        <div className="flex items-center justify-between gap-3 px-4 py-2 text-xs font-medium bg-rose-50 text-rose-700 border-b border-rose-200 shrink-0">
          <span>工作区启动失败：{bootstrapError}（未连接到服务器，请刷新重试）</span>
          <button
            onClick={() => bootstrapWorkspace()}
            className="px-2 py-1 rounded border border-rose-300 hover:bg-rose-100 transition-colors"
          >
            重试
          </button>
        </div>
      )}
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <SlideCanvas />
        <ChatPanel />
      </div>
      <SettingsModal />
      <PPTSpecImportModal />
    </div>
  )
}

export default App
