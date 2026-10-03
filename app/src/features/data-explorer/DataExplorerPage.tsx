// `/datos/*` Datos: ¿qué hay en las entradas? Masters, journal, inbox documents and bank statements, cross-linked.
import { Route, Routes } from 'react-router'
import { Database } from 'lucide-react'
import { ButtonLink, EmptyState, Page, QueryState } from '@/components'
import { useDatasetStore } from '@/data/stores'
import { AccountPage } from './AccountPage'
import { NotFound } from './common'
import { DocumentPage, DocumentsPage, LooseFilePage } from './DocumentsPage'
import { EntryPage } from './EntryPage'
import { JournalPage } from './JournalPage'
import { MastersPage } from './MastersPage'
import { CustomerPage, ProjectPage, VendorPage } from './PartyPages'
import { StatementPage, StatementsPage } from './StatementsPage'

export default function DataExplorerPage() {
  const api = useDatasetStore((s) => s.api)
  const status = useDatasetStore((s) => s.status)
  const error = useDatasetStore((s) => s.error)
  if (!api)
    return (
      <Page>
        <QueryState
          status={status === 'ready' ? 'idle' : status}
          error={error}
          idle={
            <EmptyState
              icon={<Database />}
              title="No hay datos cargados"
              description="Sube la carpeta de una fase (erp/, inbox/, bank/, tasks/) para explorar sus maestros, diario, documentos y extractos."
              action={
                <ButtonLink to="/ejecuciones/nueva" variant="primary">
                  Nuevo cierre
                </ButtonLink>
              }
            />
          }
        >
          {null}
        </QueryState>
      </Page>
    )
  return (
    <Routes>
      <Route index element={<MastersPage />} />
      <Route path="maestros/:kind" element={<MastersPage />} />
      <Route path="proveedores/:id" element={<VendorPage />} />
      <Route path="clientes/:id" element={<CustomerPage />} />
      <Route path="proyectos/:id" element={<ProjectPage />} />
      <Route path="cuentas/:account" element={<AccountPage />} />
      <Route path="diario" element={<JournalPage />} />
      <Route path="diario/:entryId" element={<EntryPage />} />
      <Route path="documentos" element={<DocumentsPage />} />
      <Route path="documentos/fichero" element={<LooseFilePage />} />
      <Route path="documentos/:id" element={<DocumentPage />} />
      <Route path="extractos" element={<StatementsPage />} />
      <Route path="extractos/:account/:month" element={<StatementPage />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
