// `/datos/diario/:entryId`: one journal entry with its lines, balance check and what points at it.
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router'
import { CircleCheck, CircleX } from 'lucide-react'
import { Amount, Badge, Mono, Page, Section, Skeleton } from '@/components'
import type { JournalEntry } from '@/domain/types'
import { formatDate } from '@/lib/format'
import { DetailHeader, Facts, ItemLinks, NotFound, TextLink, useAccountNames, useApi, useRunItems } from './common'
import { dataPath, itemsCitingEntry, partnerPath } from './model'
import styles from './DataExplorer.module.css'

export function EntryPage() {
  const { entryId = '' } = useParams()
  const api = useApi()
  const [result, setResult] = useState<{ id: string; entry: JournalEntry | null } | null>(null)

  useEffect(() => {
    let alive = true
    api.getJournalEntries([entryId]).then(
      (list) => alive && setResult({ id: entryId, entry: list[0] ?? null }),
      () => alive && setResult({ id: entryId, entry: null }),
    )
    return () => {
      alive = false
    }
  }, [api, entryId])

  if (!result || result.id !== entryId)
    return (
      <Page>
        <Skeleton width={320} height={28} />
        <Skeleton height={240} radius="var(--radius-lg)" />
      </Page>
    )
  if (!result.entry) return <NotFound what={`No hay ningún asiento ${entryId}`} />
  return <Entry entry={result.entry} />
}

function Entry({ entry }: { entry: JournalEntry }) {
  const { core } = useApi()
  const names = useAccountNames(core)
  const run = useRunItems()
  const related = useMemo(() => (run ? itemsCitingEntry(run.items, entry.id) : []), [run, entry.id])
  const origin = useMemo(() => {
    const ap = core.apInvoices.find((i) => i.journal_entry === entry.id)
    if (ap) return { label: `Factura de proveedor ${ap.doc_id}`, to: dataPath.vendor(ap.vendor) }
    const ar = core.arInvoices.find((i) => i.journal_entry === entry.id)
    if (ar) return { label: `Factura emitida ${ar.id}`, to: dataPath.customer(ar.customer) }
    return null
  }, [core, entry.id])

  const debit = entry.lines.reduce((s, l) => s + (l.debit || 0), 0)
  const credit = entry.lines.reduce((s, l) => s + (l.credit || 0), 0)
  const balanced = debit === credit

  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Diario', to: '/datos/diario' }, { label: entry.id }]}
        title={<Mono>{entry.id}</Mono>}
        subtitle={entry.header_text}
        actions={
          <Badge tone={balanced ? 'ok' : 'danger'} icon={balanced ? <CircleCheck /> : <CircleX />}>
            {balanced ? 'Cuadrado' : 'Descuadrado'}
          </Badge>
        }
      />
      <Facts
        items={[
          { label: 'Sociedad', value: <TextLink to={dataPath.journal({ company: entry.company })} mono>{entry.company}</TextLink> },
          { label: 'Clase de documento', value: <Mono>{entry.doc_type}</Mono> },
          { label: 'Fecha contable', value: formatDate(entry.posting_date) },
          { label: 'Fecha del documento', value: formatDate(entry.document_date) },
          { label: 'Referencia', value: entry.reference ? <Mono>{entry.reference}</Mono> : '—' },
          { label: 'Origen', value: <TextLink to={dataPath.journal({ source: entry.source })} mono>{entry.source}</TextLink> },
          { label: 'Moneda', value: entry.currency },
          ...(origin ? [{ label: 'Procede de', value: <TextLink to={origin.to}>{origin.label}</TextLink> }] : []),
        ]}
      />
      <Section title="Líneas" count={entry.lines.length}>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.num}>#</th>
                <th>Cuenta</th>
                <th>Descripción</th>
                <th className={styles.num}>Debe</th>
                <th className={styles.num}>Haber</th>
                <th>Socio</th>
                <th>CeCo / PEP</th>
                <th>IVA</th>
                <th>Asignación</th>
                <th>Texto</th>
              </tr>
            </thead>
            <tbody>
              {entry.lines.map((l) => {
                const partner = partnerPath(core, l.partner)
                return (
                  <tr key={l.line}>
                    <td className={styles.num}>{l.line}</td>
                    <td>
                      <TextLink to={dataPath.account(l.account)} mono>
                        {l.account}
                      </TextLink>
                    </td>
                    <td className={styles.ellipsis}>{names.get(l.account) ?? '—'}</td>
                    <td className={styles.num}>{l.debit ? <Amount cents={l.debit} currency={l.currency || entry.currency} /> : null}</td>
                    <td className={styles.num}>{l.credit ? <Amount cents={l.credit} currency={l.currency || entry.currency} /> : null}</td>
                    <td>{l.partner ? partner ? <TextLink to={partner} mono>{l.partner}</TextLink> : <Mono>{l.partner}</Mono> : null}</td>
                    <td>{l.cost_center || l.wbs ? <Mono>{l.cost_center ?? l.wbs}</Mono> : null}</td>
                    <td>{l.tax_code ? <Mono>{l.tax_code}</Mono> : null}</td>
                    <td>{l.assignment ? <Mono>{l.assignment}</Mono> : null}</td>
                    <td className={styles.ellipsis}>{l.text}</td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td />
                <td colSpan={2}>Total</td>
                <td className={styles.num}>
                  <Amount cents={debit} currency={entry.currency} />
                </td>
                <td className={styles.num}>
                  <Amount cents={credit} currency={entry.currency} />
                </td>
                <td colSpan={5}>{balanced ? null : <span className={styles.error}>Diferencia <Amount cents={debit - credit} currency={entry.currency} signed /></span>}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Section>
      <Section title="Partidas que lo citan" count={run ? related.length : undefined}>
        <ItemLinks items={related} empty={run ? 'Ninguna partida de la ejecución activa cita este asiento.' : 'Abre una ejecución para ver las partidas que lo citan.'} />
      </Section>
    </Page>
  )
}
