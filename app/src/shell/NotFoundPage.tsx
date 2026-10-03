import { useLocation } from 'react-router'
import { Compass } from 'lucide-react'
import { ButtonLink, EmptyState, Mono } from '@/components'
import styles from './AppShell.module.css'

export default function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <div className={styles.notFound}>
      <EmptyState
        icon={<Compass />}
        title="Página no encontrada"
        description={
          <>
            No existe ninguna vista en <Mono>{pathname}</Mono>.
          </>
        }
        action={
          <ButtonLink to="/" variant="primary">
            Ir al resumen
          </ButtonLink>
        }
      />
    </div>
  )
}
