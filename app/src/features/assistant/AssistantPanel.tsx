// The assistant as a side panel over any screen, toggled with ⌘J / Ctrl+J. Mount it once in the shell.
import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { Maximize2, RotateCcw } from 'lucide-react'
import { IconButton, QueryState, SidePanel } from '@/components'
import { Composer, Conversation, Presets } from './Chat'
import { useAssistantStore } from './store'
import { useAssistantChat } from './useAssistantChat'
import styles from './Assistant.module.css'

export const ASSISTANT_ROUTE = '/asistente'

/** ⌘J / Ctrl+J toggles the panel, also while typing (like ⌘K). */
export function useAssistantShortcut() {
  const toggle = useAssistantStore((s) => s.togglePanel)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'j') {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [toggle])
}

export function AssistantPanel() {
  useAssistantShortcut()
  const open = useAssistantStore((s) => s.panelOpen)
  const setOpen = useAssistantStore((s) => s.setPanelOpen)
  const { pathname } = useLocation()
  // The page already is the assistant: no panel on top of it.
  const visible = open && pathname !== ASSISTANT_ROUTE
  return (
    <SidePanel open={visible} onClose={() => setOpen(false)} storageKey="kalmora.assistant.width" defaultWidth={480} aria-label="Asistente" title="Asistente" actions={visible && <PanelActions />} footer={visible && <PanelComposer />}>
      {visible && <PanelBody />}
    </SidePanel>
  )
}

function PanelActions() {
  const chat = useAssistantChat()
  const navigate = useNavigate()
  const setOpen = useAssistantStore((s) => s.setPanelOpen)
  return (
    <>
      {chat.turns.length > 0 && <IconButton icon={<RotateCcw />} label="Nueva conversación" size="sm" onClick={chat.clear} disabled={chat.busy} tooltipSide="bottom" />}
      <IconButton
        icon={<Maximize2 />}
        label="Abrir a pantalla completa"
        size="sm"
        tooltipSide="bottom"
        onClick={() => {
          setOpen(false)
          navigate(ASSISTANT_ROUTE)
        }}
      />
    </>
  )
}

function PanelComposer() {
  const chat = useAssistantChat()
  if (!chat.ready) return null
  return <Composer onAsk={chat.ask} mode={chat.mode} onModeChange={chat.setMode} busy={chat.busy} autoFocus />
}

function PanelBody() {
  const chat = useAssistantChat()
  if (!chat.ready) {
    return (
      <div className={styles.panelBody}>
        <QueryState status={chat.status} error={chat.error}>
          {null}
        </QueryState>
      </div>
    )
  }
  return (
    <div className={styles.panelBody}>
      {chat.turns.length === 0 ? (
        <div className={styles.panelWelcome}>
          <h2 className={styles.panelHeadline}>¿Por dónde empezamos?</h2>
          <Presets onAsk={chat.ask} disabled={chat.busy} />
        </div>
      ) : (
        <Conversation turns={chat.turns} onAsk={chat.ask} />
      )}
    </div>
  )
}
