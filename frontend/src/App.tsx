import React, { useEffect } from 'react'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { SlideCanvas } from './components/SlideCanvas'
import { ChatPanel } from './components/ChatPanel'
import { SettingsModal } from './components/SettingsModal'
import { PPTSpecImportModal } from './components/PPTSpecImportModal'
import { usePPTStore } from './store/usePPTStore'

export const App: React.FC = () => {
  const { initWebSocket, triggerUndo, triggerRedo } = usePPTStore()

  useEffect(() => {
    initWebSocket()

    // Global keyboard shortcuts for Undo / Redo
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault()
        if (e.shiftKey) {
          triggerRedo()
        } else {
          triggerUndo()
        }
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
        e.preventDefault()
        triggerRedo()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className="flex flex-col w-screen h-screen bg-canvas text-main antialiased overflow-hidden select-none">
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
