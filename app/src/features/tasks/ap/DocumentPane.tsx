// The received document next to the ficha: PDF in an iframe, XML as text, and the message that brought it.
import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import { EmptyState, KeyValue, Skeleton, Tabs } from '@/components'
import type { ApInboxDoc, DatasetApi } from '@/domain/types'
import { formatDateTime } from '@/lib/format'
import { prettyXml } from './model'
import styles from './Ap.module.css'

const MESSAGE = 'message'

const fileName = (path: string) => path.slice(path.lastIndexOf('/') + 1)

export function DocumentPane({ api, doc }: { api: DatasetApi; doc: ApInboxDoc | null }) {
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
      <div className={styles.docBody}>{current === MESSAGE ? <MessageView doc={doc} /> : <FileView key={current} api={api} path={current} />}</div>
    </div>
  )
}

function MessageView({ doc }: { doc: ApInboxDoc }) {
  const m = doc.message
  return (
    <div className={styles.message}>
      <KeyValue
        items={[
          { label: 'Canal', value: m.channel },
          { label: 'Recibido', value: formatDateTime(m.received_at) },
          { label: 'Buzón', value: m.mailbox, mono: true },
          ...(m.from ? [{ label: 'De', value: m.from, mono: true }] : []),
          ...(m.subject ? [{ label: 'Asunto', value: m.subject }] : []),
          ...(m.source ? [{ label: 'Origen', value: m.source }] : []),
          ...(m.uploaded_by ? [{ label: 'Subido por', value: m.uploaded_by }] : []),
        ]}
      />
      {m.body && <pre className={styles.messageBody}>{m.body}</pre>}
    </div>
  )
}

function FileView({ api, path }: { api: DatasetApi; path: string }) {
  const isPdf = path.toLowerCase().endsWith('.pdf')
  const [state, setState] = useState<{ url?: string; text?: string; error?: string } | null>(null)

  useEffect(() => {
    let alive = true
    let url: string | null = null
    const load = isPdf
      ? api.readFile(path).then((blob) => {
          url = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }))
          return { url }
        })
      : api.readText(path).then((text) => ({ text: path.toLowerCase().endsWith('.xml') ? prettyXml(text) : text }))
    load.then(
      (s) => alive && setState(s),
      (e: unknown) => alive && setState({ error: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [api, path, isPdf])

  if (!state) return <Skeleton height={480} />
  if (state.error) return <EmptyState size="sm" icon={<FileText />} title="No se pudo abrir el fichero" description={state.error} />
  if (state.url) return <iframe className={styles.pdf} src={state.url} title={fileName(path)} />
  return <pre className={styles.xml}>{state.text}</pre>
}
