// Renders the item detail panel over any route when the URL has `?item=<task>:<key>`.
import { lazy, Suspense, useRef } from 'react'
import { useSearchParams } from 'react-router'
import { Link2 } from 'lucide-react'
import { IconButton, Mono, SidePanel, Skeleton, toast } from '@/components'
import { ITEM_PARAM, useCloseItem } from './useOpenItem'
import styles from './AppShell.module.css'

const ItemPanel = lazy(() => import('@/features/item/ItemPanel'))

export function PeekHost() {
  const [params] = useSearchParams()
  const itemId = params.get(ITEM_PARAM)
  const close = useCloseItem()
  // The panel keeps showing the last item while its exit animation plays.
  const lastItem = useRef(itemId)
  if (itemId) lastItem.current = itemId
  const shownItem = itemId ?? lastItem.current

  const copyLink = () => {
    navigator.clipboard
      .writeText(window.location.href)
      .then(() => toast.success('Enlace copiado'))
      .catch(() => toast.error('No se pudo copiar el enlace'))
  }

  return (
    <SidePanel
      open={itemId != null}
      onClose={close}
      storageKey="kalmora.peek.width"
      aria-label={shownItem ? `Partida ${shownItem}` : undefined}
      title={shownItem && <Mono>{shownItem}</Mono>}
      actions={<IconButton icon={<Link2 />} label="Copiar enlace" size="sm" onClick={copyLink} tooltipSide="bottom" />}
    >
      {shownItem && (
        <Suspense
          fallback={
            <div className={styles.peekLoading} role="status">
              <span className="sr-only">Cargando la partida…</span>
              <Skeleton width={200} height={18} />
              <Skeleton lines={5} />
            </div>
          }
        >
          <ItemPanel itemId={shownItem} onClose={close} />
        </Suspense>
      )}
    </SidePanel>
  )
}
