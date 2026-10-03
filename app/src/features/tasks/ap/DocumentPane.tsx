// The received document next to the ficha: one tab per file and one for the message that brought it.
import { useState } from 'react'
import { FileText } from 'lucide-react'
import { EmptyState, Tabs } from '@/components'
import type { ApInboxDoc } from '@/domain/types'
import { DocumentViewer, EmailView } from '@/features/item/kit'
import styles from './Ap.module.css'

const MESSAGE = 'message'

const fileName = (path: string) => path.slice(path.lastIndexOf('/') + 1)

export function DocumentPane({ doc }: { doc: ApInboxDoc | null }) {
  const files = doc?.files.filter((f) => !f.endsWith('/message.json')) ?? []
  const [tab, setTab] = useState<string | null>(null)
  const current = tab && (tab === MESSAGE || files.includes(tab)) ? tab : (files[0] ?? MESSAGE)

  if (!doc) return <EmptyState size="sm" icon={<FileText />} title="Sin documento en la bandeja" description="Esta partida no tiene ficheros en inbox/ap." />

  return (
    <div className={styles.docPane}>
      <Tabs
        aria-label="Ficheros del documento"
        value={current}
        onChange={setTab}
        tabs={[...files.map((f) => ({ id: f, label: fileName(f) })), { id: MESSAGE, label: 'Mensaje' }]}
      />
      <div className={styles.docBody}>{current === MESSAGE ? <EmailView message={doc.message} /> : <DocumentViewer key={current} path={current} height={520} />}</div>
    </div>
  )
}
