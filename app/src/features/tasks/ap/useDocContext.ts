// Async evidence of one AP document: the e-invoice summary (Facturae/CFDI) and the goods receipts of its POs.
import { useEffect, useState } from 'react'
import type { ApRow, DatasetApi, EInvoiceSummary, GoodsReceipt } from '@/domain/types'

export interface DocContext {
  status: 'loading' | 'ready' | 'error'
  einvoice: EInvoiceSummary | null
  receipts: GoodsReceipt[]
  error: string | null
}

const LOADING: DocContext = { status: 'loading', einvoice: null, receipts: [], error: null }

export function useDocContext(api: DatasetApi, row: ApRow, files: readonly string[]): DocContext {
  const [state, setState] = useState<{ key: string; ctx: DocContext } | null>(null)
  const key = `${api.meta.id}|${row.doc_id}`

  useEffect(() => {
    let alive = true
    const xml = files.find((f) => f.toLowerCase().endsWith('.xml'))
    const pos = [...new Set((row.lines ?? []).map((l) => l.po).filter((p): p is string => !!p))]
    Promise.all([
      xml && api.einvoice ? api.einvoice(xml).catch(() => null) : Promise.resolve(null),
      Promise.all(pos.map((po) => api.goodsReceipts({ po }))).then((lists) => lists.flat()),
    ]).then(
      ([einvoice, receipts]) => alive && setState({ key, ctx: { status: 'ready', einvoice, receipts, error: null } }),
      (e: unknown) => alive && setState({ key, ctx: { ...LOADING, status: 'error', error: e instanceof Error ? e.message : String(e) } }),
    )
    return () => {
      alive = false
    }
  }, [api, row, files, key])

  return state?.key === key ? state.ctx : LOADING
}
