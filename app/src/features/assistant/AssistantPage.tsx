// `/asistente`: ask the close in plain language; answers carry figures, items and reasoning.
import { RotateCcw } from 'lucide-react'
import { Button, Page, QueryState } from '@/components'
import { PageActions } from '@/shell/PageActions'
import { Composer, Conversation, Presets } from './Chat'
import { useAssistantChat } from './useAssistantChat'
import styles from './Assistant.module.css'

export default function AssistantPage() {
  const chat = useAssistantChat()
  const empty = chat.turns.length === 0

  if (!chat.ready) {
    return (
      <Page width="narrow">
        <h1 className={styles.headline}>¿Por dónde empezamos?</h1>
        <QueryState status={chat.status} error={chat.error}>
          {null}
        </QueryState>
      </Page>
    )
  }

  return (
    <Page width="narrow" className={styles.page}>
      {!empty && (
        <PageActions>
          <Button size="sm" variant="ghost" leadingIcon={<RotateCcw aria-hidden />} onClick={chat.clear} disabled={chat.busy}>
            Nueva conversación
          </Button>
        </PageActions>
      )}
      {empty ? (
        <div className={styles.welcome}>
          <h1 className={styles.headline}>¿Por dónde empezamos?</h1>
          <Composer onAsk={chat.ask} mode={chat.mode} onModeChange={chat.setMode} busy={chat.busy} autoFocus />
          <Presets onAsk={chat.ask} disabled={chat.busy} />
        </div>
      ) : (
        <>
          <Conversation turns={chat.turns} onAsk={chat.ask} />
          <div className={styles.dock}>
            <Composer onAsk={chat.ask} mode={chat.mode} onModeChange={chat.setMode} busy={chat.busy} autoFocus />
          </div>
        </>
      )}
    </Page>
  )
}
