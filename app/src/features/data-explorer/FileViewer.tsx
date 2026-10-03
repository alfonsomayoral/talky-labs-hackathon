// Shows one inbox file: PDF in an iframe (blob URL), XML indented, JSON pretty-printed, text as is.
import { useEffect, useState } from 'react'
import { Download, FileQuestion } from 'lucide-react'
import { EmptyState, Skeleton } from '@/components'
import type { DatasetApi } from '@/domain/types'
import { fileKind, fileName, prettyJson, prettyXml } from './model'
import styles from './DataExplorer.module.css'

type Loaded = { path: string; url: string; text: string | null } | { path: string; error: string }

export function FileViewer({ api, path }: { api: DatasetApi; path: string }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const kind = fileKind(path)

  useEffect(() => {
    let alive = true
    let url: string | null = null
    api.readFile(path).then(
      async (blob) => {
        const typed = kind === 'pdf' && blob.type !== 'application/pdf' ? new Blob([blob], { type: 'application/pdf' }) : blob
        const text = kind === 'pdf' || kind === 'other' ? null : await blob.text()
        if (!alive) return
        url = URL.createObjectURL(typed)
        setLoaded({ path, url, text: text === null ? null : kind === 'xml' ? prettyXml(text) : kind === 'json' ? prettyJson(text) : text })
      },
      (e: unknown) => alive && setLoaded({ path, error: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [api, path, kind])

  if (!loaded || loaded.path !== path) return <Skeleton height={480} radius="var(--radius-lg)" />
  if ('error' in loaded) return <EmptyState size="sm" icon={<FileQuestion />} title="No se pudo leer el fichero" description={loaded.error} />
  return (
    <div className={styles.viewer}>
      <div className={styles.viewerBar}>
        <span className={styles.viewerPath}>{path}</span>
        <a className={styles.link} href={loaded.url} download={fileName(path)}>
          <Download aria-hidden className={styles.inlineIcon} /> Descargar
        </a>
      </div>
      {kind === 'pdf' ? (
        <iframe className={styles.pdf} src={loaded.url} title={fileName(path)} />
      ) : loaded.text !== null ? (
        <pre className={styles.code}>{loaded.text}</pre>
      ) : (
        <EmptyState size="sm" icon={<FileQuestion />} title="Sin vista previa para este tipo de fichero" description="Descárgalo para abrirlo." />
      )}
    </div>
  )
}
