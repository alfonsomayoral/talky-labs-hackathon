// Local deterministic provider: answers from the derived run with the same functions and EUR
// conversions as Resumen and Atención, so the figures always agree with those screens.

import type { ApRow, AttentionItem, BankRecRow, ItemId, TaskKey, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { outcomeEntry } from '@/domain/catalog/policy'
import { PIPELINE } from '@/domain/catalog/labels'
import { itemEntries, parseItemId, sortAttention } from '@/engine'
import { buildRows, groupByPriority } from '@/features/attention/attentionModel'
import { TASK_META, apCascade, itemEurCents, itemRows, processFlow, reasoningSteps, reasoningSummary } from '@/features/item/kit'
import { attentionSummary, balanceSummary, banksControl, eur, eurConverter, longMonth, type ToEur } from '@/features/overview/model'
import { pendingAttentionItems } from '@/shell/attentionBadge'
import { formatDuration, formatNumber, formatPercent } from '@/lib/format'
import { detectIntent } from './intent'
import type { AssistantAnswer, AssistantCard, AssistantContext, CardItem, Citation, Intent, MetricDatum, TableCell } from './types'

export const PRESET_QUESTIONS = [
  'Resumen del último mes contable',
  '¿Qué partidas tengo que revisar?',
  '¿Por qué no cuadra el balance?',
  '¿Cómo ha decidido el agente la bandeja de proveedores?',
] as const

const limitOf = (ctx: AssistantContext) => (ctx.mode === 'deep' ? 15 : 5)

const text = (t: string): TableCell => ({ kind: 'text', text: t })
const mono = (t: string): TableCell => ({ kind: 'mono', text: t })
const number = (value: number): TableCell => ({ kind: 'number', value })
const money = (cents: number, currency: string): TableCell => ({ kind: 'money', amounts: [{ cents, currency }] })
const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`
const roundOrNull = (cents: number | null) => (cents == null ? null : Math.round(cents))

function answer(intent: Intent['kind'], body: Partial<AssistantAnswer> & { text: string }): AssistantAnswer {
  return { cards: [], citations: [], links: [], ...body, intent, source: 'local' }
}

function toEurOf(ctx: AssistantContext): ToEur {
  return eurConverter(ctx.core.companies, ctx.core.fxRates, ctx.meta.month)
}

function attentionItems(list: readonly AttentionItem[], itemsById: ReadonlyMap<ItemId, WorkItem>): CardItem[] {
  return list.map((a) => {
    const item = itemsById.get(a.item)
    return { item: a.item, title: a.title, amount: a.impact, currency: item?.currency ?? 'EUR', priority: a.priority }
  })
}

const workItems = (list: readonly WorkItem[]): CardItem[] =>
  list.map((it) => ({ item: it.id, title: it.title, amount: it.amount, currency: it.currency ?? 'EUR', status: it.status }))

const itemCitations = (items: readonly CardItem[]): Citation[] => items.map((i) => ({ item: i.item }))

const policyCitations = (refs: Iterable<string | null | undefined>): Citation[] =>
  [...new Set([...refs].filter((r): r is string => !!r))].map((policy_ref) => ({ policy_ref }))

// ---------------------------------------------------------------- resumen del mes
function summary(ctx: AssistantContext): AssistantAnswer {
  const { data, meta, run } = ctx
  const toEur = toEurOf(ctx)
  const stats = data.stats
  const auto = stats.byStatus.AUTO ?? 0
  const attention = attentionSummary(data.attention, data.itemsById, toEur)
  const pending = pendingAttentionItems(data.attention, ctx.overrides)
  const needs = attentionSummary(pending, data.itemsById, toEur)
  const balance = data.trialBalance ? balanceSummary(data.trialBalance, toEur) : null
  const golden = run.source === 'golden'
  const cost = run.manifest?.cost_usd_total

  const sentences = [
    `${golden ? 'La solución de referencia resuelve' : 'El agente ha resuelto'} ${formatNumber(auto)} de ${plural(stats.items, 'partida', 'partidas')} sin intervención en el cierre de ${longMonth(meta.month)}.`,
    needs.count ? `Quedan ${plural(needs.count, 'partida pendiente', 'partidas pendientes')} de una persona por ${eur(needs.impactEur)}.` : 'No queda ninguna partida pendiente de una persona.',
  ]
  if (balance?.score != null) sentences.push(`Los asientos entregados cierran el ${formatPercent(balance.score)} del hueco del balance.`)
  if (data.score) sentences.push(`La nota es ${formatNumber(data.score.total, { decimals: 2 })} sobre 100.`)
  if (golden) sentences.push('Es la solución publicada por los organizadores, no la salida del agente.')

  const byPriority = stats.attention.byPriority
  const metrics: MetricDatum[] = [
    {
      label: 'Autonomía',
      value: { kind: 'percent', value: stats.items ? auto / stats.items : null },
      comparison: `${formatNumber(auto)} de ${formatNumber(stats.items)} partidas`,
    },
    {
      label: 'En atención',
      value: { kind: 'number', value: attention.count },
      delta: eur(attention.impactEur),
      comparison: (['P0', 'P1', 'P2', 'P3'] as const)
        .filter((p) => byPriority[p])
        .map((p) => `${p} ${byPriority[p]}`)
        .join(' · '),
      hint: 'Importe en EUR (3100 al tipo de cierre).',
    },
  ]
  if (balance?.score != null) {
    metrics.push({ label: 'Hueco del balance cerrado', value: { kind: 'percent', value: balance.score }, comparison: `${eur(balance.gapRecordedEur)} → ${eur(balance.gapAfterEur)}` })
  }
  metrics.push({
    label: 'Nota',
    value: data.score ? { kind: 'text', text: formatNumber(data.score.total, { decimals: 2 }) } : { kind: 'text', text: '—' },
    comparison: data.score ? 'sobre 100, como score.py' : 'Sin golden no hay nota',
  })
  if (cost != null) metrics.push({ label: 'Coste', value: { kind: 'money', cents: Math.round(cost * 100), currency: 'USD' } })

  const rows = PIPELINE.map((task): TableCell[] => {
    const t = stats.byTask[task]
    const score = data.score?.tasks[task]?.score
    return [text(TASK_META[task].label), number(t.items), number(t.auto), number(t.needsHuman), number(t.blocked), number(t.open), { kind: 'percent', value: score ?? null }]
  })
  const top = attentionItems(sortAttention(pending).slice(0, limitOf(ctx)), data.itemsById)
  const cards: AssistantCard[] = [
    { type: 'metric', metrics },
    {
      type: 'table',
      title: 'Por tarea',
      columns: [{ label: 'Tarea' }, ...['Partidas', 'Resueltas', 'Persona', 'Bloqueadas', 'Abiertas', 'Nota'].map((label) => ({ label, align: 'right' as const }))],
      rows,
    },
  ]
  if (top.length) cards.push({ type: 'items', title: 'Te necesitan', items: top, total: needs.count })
  return answer('summary', { text: sentences.join(' '), cards, citations: itemCitations(top), links: [{ label: 'Abrir el resumen', to: '/' }] })
}

// ---------------------------------------------------------------- qué revisar
function review(ctx: AssistantContext): AssistantAnswer {
  const { data } = ctx
  const toEur = toEurOf(ctx)
  const pending = pendingAttentionItems(data.attention, ctx.overrides)
  const needs = attentionSummary(pending, data.itemsById, toEur)
  const all = attentionSummary(data.attention, data.itemsById, toEur)
  const links = [{ label: 'Abrir Atención', to: '/atencion' }]
  if (!needs.count) {
    const t = all.count ? `No queda nada pendiente: las ${formatNumber(all.count)} partidas en atención ya están resueltas o pospuestas.` : 'Ninguna partida necesita a una persona.'
    return answer('review', { text: t, links })
  }
  const rows = buildRows(data.attention, data.itemsById, ctx.overrides).filter((r) => r.resolution === 'pending')
  const fraud = rows.filter((r) => r.family === 'fraud').length
  const p0 = pending.filter((a) => a.priority === 'P0').length
  const sentences = [`Quedan ${plural(needs.count, 'partida', 'partidas')} pendientes de una persona por ${eur(needs.impactEur)} (en EUR, 3100 al tipo de cierre).`]
  if (fraud) sentences.push(`${plural(fraud, 'tiene', 'tienen')} señales de posible fraude: van primero y no se paga nada hasta confirmarlo.`)
  else if (p0) sentences.push(`Empieza por ${plural(p0, 'partida P0', 'partidas P0')}.`)
  if (all.count > needs.count) sentences.push(`Ya se han resuelto o pospuesto ${formatNumber(all.count - needs.count)}.`)

  const top = attentionItems(sortAttention(pending).slice(0, limitOf(ctx)), data.itemsById)
  const cards: AssistantCard[] = [
    {
      type: 'metric',
      metrics: [
        { label: 'Pendientes', value: { kind: 'number', value: needs.count }, comparison: `de ${formatNumber(all.count)} en atención` },
        { label: 'Importe pendiente', value: { kind: 'money', cents: Math.round(needs.impactEur), currency: 'EUR' }, hint: 'En EUR, 3100 al tipo de cierre.' },
        { label: 'Posible fraude', value: { kind: 'number', value: fraud } },
      ],
    },
    {
      type: 'table',
      title: 'Por prioridad',
      columns: [{ label: 'Prioridad' }, { label: 'Partidas', align: 'right' }, { label: 'Importe', align: 'right' }],
      rows: groupByPriority(rows).map((g) => [mono(g.priority), number(g.rows.length), { kind: 'money', amounts: g.totals }]),
    },
    { type: 'items', title: 'Por dónde empezar', items: top, total: needs.count },
  ]
  return answer('review', { text: sentences.join(' '), cards, citations: [...itemCitations(top), ...policyCitations(sortAttention(pending).slice(0, limitOf(ctx)).map((a) => a.policy_ref))], links })
}

// ---------------------------------------------------------------- por qué no cuadra el balance
function balance(ctx: AssistantContext): AssistantAnswer {
  const { data, core } = ctx
  const links = [{ label: 'Abrir el balance', to: '/balance' }]
  const tb = data.trialBalance
  if (!tb) return answer('balance', { text: 'Todavía se está sumando el diario para calcular el balance registrado. Vuelve a preguntar en unos segundos.', links })
  const toEur = toEurOf(ctx)
  const b = balanceSummary(tb, toEur)
  const unbalanced = data.stats.unbalancedEntries
  const currencyOf = new Map(core.companies.map((c) => [c.code, c.currency]))
  const limit = limitOf(ctx)
  const sentences: string[] = []
  const cards: AssistantCard[] = []

  if (b.score != null) {
    sentences.push(
      `Los asientos entregados cierran el ${formatPercent(b.score)} del hueco entre el balance registrado y el correcto: de ${eur(b.gapRecordedEur)} a ${eur(b.gapAfterEur)} (en EUR, 3100 al tipo de cierre).`,
    )
    const gaps = tb.rows
      .filter((r) => r.truth !== null && r.truth !== r.after)
      .map((r) => ({ r, eurGap: Math.abs(toEur(r.company, (r.truth ?? 0) - r.after)) }))
      .sort((x, y) => y.eurGap - x.eurGap)
    if (gaps.length) {
      sentences.push(`La diferencia que queda está en ${plural(gaps.length, 'cuenta', 'cuentas')}; las mayores, abajo.`)
      cards.push({
        type: 'table',
        title: 'Dónde queda la diferencia',
        columns: [{ label: 'Sociedad' }, { label: 'Cuenta' }, { label: 'Después', align: 'right' }, { label: 'Correcto', align: 'right' }, { label: 'Diferencia', align: 'right' }],
        rows: gaps.slice(0, limit * 2).map(({ r }) => {
          const cur = currencyOf.get(r.company) ?? 'EUR'
          return [mono(r.company), mono(r.account), money(r.after, cur), money(r.truth ?? 0, cur), money((r.truth ?? 0) - r.after, cur)]
        }),
      })
    } else sentences.push('Después de la ejecución el balance coincide con el correcto en todas las cuentas.')
    cards.unshift({
      type: 'metric',
      metrics: [
        { label: 'Hueco cerrado', value: { kind: 'percent', value: b.score }, comparison: 'como score.py' },
        { label: 'Hueco registrado', value: { kind: 'money', cents: roundOrNull(b.gapRecordedEur), currency: 'EUR' } },
        { label: 'Hueco después', value: { kind: 'money', cents: roundOrNull(b.gapAfterEur), currency: 'EUR' } },
        { label: 'Asientos descuadrados', value: { kind: 'number', value: unbalanced } },
      ],
    })
  } else {
    sentences.push('Sin golden no se conoce el balance correcto: solo se puede ver cuánto mueve el balance cada tarea.')
    cards.push({ type: 'metric', metrics: [{ label: 'Asientos descuadrados', value: { kind: 'number', value: unbalanced } }] })
  }
  if (unbalanced) sentences.push(`Hay ${plural(unbalanced, 'asiento descuadrado', 'asientos descuadrados')} en la entrega: cada uno es una partida P0.`)

  cards.push({
    type: 'table',
    title: 'Movimiento por tarea (EUR)',
    columns: [{ label: 'Tarea' }, { label: 'Σ|movimiento|', align: 'right' }],
    rows: b.movement.map((m) => [text(TASK_META[m.task].label), money(Math.round(m.amountEur), 'EUR')]),
  })
  const pending = pendingAttentionItems(data.attention, ctx.overrides).filter((a) => a.affects_tb)
  const top = attentionItems(sortAttention(pending).slice(0, limit), data.itemsById)
  if (top.length) cards.push({ type: 'items', title: 'Pendientes que mueven el balance', items: top, total: pending.length })
  return answer('balance', { text: sentences.join(' '), cards, citations: itemCitations(top), links })
}

// ---------------------------------------------------------------- cómo decidió un proceso
function process(ctx: AssistantContext, task: TaskKey | null): AssistantAnswer {
  if (!task) {
    return answer('process', {
      text: '¿De qué proceso? Pregunta, por ejemplo, «¿Cómo ha decidido el agente la bandeja de proveedores?», o por facturación, cobros, bancos, intragrupo o cierre.',
    })
  }
  const { data, core, run } = ctx
  const flow = processFlow(task, data, core, run)
  const meta = TASK_META[task]
  const ends = flow.nodes.filter((n) => !n.unit && !flow.links.some((l) => l.source === n.id) && n.column > 0 && n.count > 0)
  const sentences = [`${meta.title}: ${plural(flow.total.count, 'partida', 'partidas')} por ${eur(flow.total.amount)} (en EUR).`]
  if (ends.length) sentences.push(`Terminan así: ${ends.map((n) => `${n.label}, ${formatNumber(n.count)}${n.section ? ` (${n.section})` : ''}`).join('; ')}.`)

  const rows: TableCell[][] = []
  for (const n of flow.nodes) {
    const stage = flow.columns[n.column]?.title ?? ''
    rows.push([text(stage), text(n.label), mono(n.section ?? '—'), number(n.count), money(Math.round(n.amount), 'EUR')])
    if (ctx.mode === 'deep') for (const s of n.breakdown) rows.push([text(''), text(`· ${s.label}`), mono(s.section ?? '—'), number(s.count), money(Math.round(s.amount), 'EUR')])
  }
  const exceptions = flow.nodes.filter((n) => n.tone === 'danger' || n.tone === 'warn').flatMap((n) => [...n.filter.items])
  const flagged = [...new Set(exceptions)]
    .map((id) => data.itemsById.get(id))
    .filter((it): it is WorkItem => !!it)
    .sort((a, b) => Math.abs(itemEurCents(b, b.amount ?? 0, core)) - Math.abs(itemEurCents(a, a.amount ?? 0, core)))
  const top = workItems(flagged.slice(0, limitOf(ctx)))
  const cards: AssistantCard[] = [
    { type: 'process', task },
    {
      type: 'table',
      title: 'Caminos de la política',
      columns: [{ label: 'Etapa' }, { label: 'Camino' }, { label: 'Artículo' }, { label: 'Partidas', align: 'right' }, { label: 'Importe (EUR)', align: 'right' }],
      rows,
    },
  ]
  if (top.length) cards.push({ type: 'items', title: 'Excepciones de mayor importe', items: top, total: flagged.length })
  const refs = [...flow.columns.map((c) => c.section), ...flow.nodes.map((n) => n.section)]
  return answer('process', { text: sentences.join(' '), cards, citations: [...itemCitations(top), ...policyCitations(refs)], links: [{ label: `Abrir ${meta.label}`, to: meta.route }] })
}

// ---------------------------------------------------------------- explicar una partida
/** The item a token names: a full id, a key of any task, or the last part of a bank key. */
export function findItem(itemsById: ReadonlyMap<ItemId, WorkItem>, token: string): WorkItem | null {
  const direct = itemsById.get(token)
  if (direct) return direct
  const upper = token.toUpperCase()
  for (const task of TASK_KEYS) {
    const hit = itemsById.get(`${task}:${token}`) ?? itemsById.get(`${task}:${upper}`)
    if (hit) return hit
  }
  for (const it of itemsById.values()) if (it.key.endsWith(`/${token}`) || it.key.endsWith(`/${upper}`)) return it
  return null
}

/** An id to suggest that exists in this run: an AP document key when it reads as one, else any item id. */
function exampleId(itemsById: ReadonlyMap<ItemId, WorkItem>): string | null {
  const items = [...itemsById.values()]
  const ap = items.find((i) => i.task === 'ap')
  if (ap && detectIntent(ap.key).kind === 'explain') return ap.key
  return items[0]?.id ?? null
}

function explain(ctx: AssistantContext, token: string): AssistantAnswer {
  const { data, core, run } = ctx
  const item = findItem(data.itemsById, token)
  if (!item) {
    const task = parseItemId(token)?.task
    const example = exampleId(data.itemsById)
    return answer('explain', {
      text: `No encuentro ${token} en la ejecución activa${task ? ` (${TASK_META[task].label})` : ''}. Comprueba el id${example ? `: por ejemplo, «Explica ${example}»` : ''}.`,
    })
  }
  const rows = itemRows(run, item)
  const events = data.eventsByItem.get(item.id) ?? []
  const cascade = item.task === 'ap' ? apCascade((rows[0] ?? null) as Partial<ApRow> | null, events) : null
  const steps = reasoningSteps(events, cascade)
  const s = reasoningSummary({ item, rows, core, entries: itemEntries(core, run, item.id) })
  const pending = data.attention.filter((a) => a.item === item.id)
  const sentences = [`Así se decidió ${item.key} (${TASK_META[item.task].label}).`]
  if (pending.length) sentences.push(`Está en Atención: ${pending.map((a) => `${a.priority} · ${a.title}`).join('; ')}.`)
  if (data.eventsSynthesized) sentences.push('La ejecución no trae trace/events.jsonl: los pasos se reconstruyen desde la entrega.')
  return answer('explain', {
    text: sentences.join(' '),
    cards: [{ type: 'reasoning', item: item.id, headline: s.headline, facts: s.facts, steps }],
    citations: [{ item: item.id }, ...policyCitations([...item.policyRefs, ...steps.map((x) => x.policyRef)])],
    links: [{ label: `Abrir ${TASK_META[item.task].label}`, to: TASK_META[item.task].route }],
  })
}

// ---------------------------------------------------------------- estado de una cuenta bancaria
function bank(ctx: AssistantContext, account: string | null): AssistantAnswer {
  const { data, core, run } = ctx
  const control = banksControl(core.tasks.bank_accounts, run.deliverables.bank_rec, data.items)
  const rows = run.deliverables.bank_rec as BankRecRow[]
  const accounts = core.tasks.bank_accounts.length ? core.tasks.bank_accounts : rows.map((r) => String(r.account))
  const stateOf = (a: string) => (control.missing.includes(a) ? 'No entregada' : control.unexplained.includes(a) ? 'Diferencias sin explicar' : 'Conciliada')
  const itemsOf = (a: string) => data.items.filter((it) => it.task === 'bank_rec' && it.key.startsWith(`${a}/`))

  if (!account) {
    return answer('bank', {
      text: `${formatNumber(control.reconciled)} de ${plural(control.total, 'cuenta conciliada', 'cuentas conciliadas')}.${control.unexplained.length ? ` Con diferencias sin explicar: ${control.unexplained.join(', ')}.` : ''}`,
      cards: [
        {
          type: 'table',
          title: 'Cuentas',
          columns: [{ label: 'Cuenta' }, { label: 'Sociedad' }, { label: 'Estado' }, { label: 'Abiertas', align: 'right' }],
          rows: accounts.map((a) => [
            mono(a),
            mono(core.bankAccounts.find((b) => b.id === a)?.company ?? '—'),
            text(stateOf(a)),
            number(itemsOf(a).filter((it) => it.status === 'OPEN').length),
          ]),
        },
      ],
      links: [{ label: 'Abrir Bancos', to: TASK_META.bank_rec.route }],
    })
  }

  const info = core.bankAccounts.find((b) => b.id === account)
  const row = rows.find((r) => String(r.account) === account)
  if (!info && !row) return answer('bank', { text: `No encuentro la cuenta ${account} en el maestro ni en la entrega.` })
  const items = itemsOf(account)
  const matches = Array.isArray(row?.matches) ? row.matches.length : 0
  const unmatchedBank = Array.isArray(row?.unmatched_bank) ? row.unmatched_bank.length : 0
  const unmatchedBook = Array.isArray(row?.unmatched_book) ? row.unmatched_book.length : 0
  const adjustments = Array.isArray(row?.adjustments) ? row.adjustments.length : 0
  const state = stateOf(account)
  const who = info ? ` (${info.bank}, sociedad ${info.company}, cuenta contable ${info.gl_account})` : ''
  const t = row
    ? `${account}${who}: ${state.toLowerCase()}. ${plural(matches, 'casación', 'casaciones')}, ${plural(unmatchedBank, 'línea del banco', 'líneas del banco')} y ${plural(unmatchedBook, 'apunte del libro', 'apuntes del libro')} sin casar, ${plural(adjustments, 'ajuste', 'ajustes')}.`
    : `${account}${who} no está en la entrega de conciliación bancaria.`

  const byOutcome = new Map<string, WorkItem[]>()
  for (const it of items) byOutcome.set(it.outcome, [...(byOutcome.get(it.outcome) ?? []), it])
  const table: TableCell[][] = [...byOutcome].map(([outcome, list]) => {
    const entry = outcomeEntry('bank_rec', outcome)
    return [text(entry?.label ?? (outcome === 'MATCH' ? 'Casación' : outcome)), mono(entry?.section ?? '—'), number(list.length), number(list.filter((it) => it.status === 'OPEN').length)]
  })
  const open = items.filter((it) => it.status !== 'AUTO')
  const top = workItems([...open, ...items.filter((it) => it.status === 'AUTO' && it.outcome !== 'MATCH')].slice(0, limitOf(ctx)))
  const cards: AssistantCard[] = [
    {
      type: 'metric',
      metrics: [
        { label: 'Estado', value: { kind: 'text', text: state } },
        { label: 'Casaciones', value: { kind: 'number', value: matches } },
        { label: 'Sin casar', value: { kind: 'number', value: unmatchedBank + unmatchedBook } },
        { label: 'Ajustes', value: { kind: 'number', value: adjustments } },
      ],
    },
  ]
  if (table.length) {
    cards.push({ type: 'table', title: 'Partidas por categoría', columns: [{ label: 'Categoría' }, { label: 'Artículo' }, { label: 'Partidas', align: 'right' }, { label: 'Abiertas', align: 'right' }], rows: table })
  }
  if (top.length) cards.push({ type: 'items', title: open.length ? 'Abiertas y ajustes' : 'Diferencias explicadas', items: top, total: open.length || undefined })
  return answer('bank', {
    text: t,
    cards,
    citations: [...itemCitations(top), ...policyCitations(items.flatMap((it) => it.policyRefs))],
    links: [{ label: `Abrir ${account}`, to: `${TASK_META.bank_rec.route}/${account}` }],
  })
}

// ---------------------------------------------------------------- coste
function cost(ctx: AssistantContext): AssistantAnswer {
  const m = ctx.run.manifest
  const links = [{ label: 'Abrir Coste', to: '/coste' }]
  if (!m) {
    const why = ctx.run.source === 'golden' ? 'La referencia (golden) no trae manifiesto' : 'El paquete no trae manifest.json'
    return answer('cost', { text: `${why}: no hay coste, modelos ni tiempos de esta ejecución.`, links })
  }
  const models = m.models ?? []
  const calls = models.reduce((s, x) => s + x.calls, 0)
  const tokens = models.reduce((s, x) => s + x.input_tokens + x.output_tokens, 0)
  const total = m.cost_usd_total ?? (models.length ? models.reduce((s, x) => s + x.cost_usd, 0) : null)
  const sentences = [
    total != null ? `La ejecución ha costado ${formatNumber(total, { decimals: 2 })} USD en modelos` : 'El manifiesto no trae el coste total',
  ]
  sentences[0] += m.runtime_s != null ? ` y ha tardado ${formatDuration(m.runtime_s * 1000)}.` : '.'
  if (models.length) sentences.push(`${plural(calls, 'llamada', 'llamadas')} a ${plural(models.length, 'modelo', 'modelos')}.`)
  const cards: AssistantCard[] = [
    {
      type: 'metric',
      metrics: [
        { label: 'Coste', value: total != null ? { kind: 'money', cents: Math.round(total * 100), currency: 'USD' } : { kind: 'text', text: '—' } },
        { label: 'Duración', value: { kind: 'text', text: m.runtime_s != null ? formatDuration(m.runtime_s * 1000) : '—' } },
        { label: 'Llamadas', value: { kind: 'number', value: calls } },
        { label: 'Tokens', value: { kind: 'number', value: tokens } },
      ],
    },
  ]
  if (models.length) {
    cards.push({
      type: 'table',
      title: 'Por modelo',
      columns: [{ label: 'Modelo' }, { label: 'Proveedor' }, ...['Llamadas', 'Entrada', 'Salida', 'Coste'].map((label) => ({ label, align: 'right' as const }))],
      rows: models.map((x) => [mono(x.name), text(x.provider), number(x.calls), number(x.input_tokens), number(x.output_tokens), money(Math.round(x.cost_usd * 100), 'USD')]),
    })
  }
  return answer('cost', { text: sentences.join(' '), cards, links })
}

function unknown(ctx: AssistantContext): AssistantAnswer {
  const example = exampleId(ctx.data.itemsById)
  return answer('unknown', {
    text: `No sé responder a eso con los datos de la ejecución. Puedo darte el resumen del mes, lo que hay que revisar, por qué no cuadra el balance, cómo decidió un proceso, explicar una partida${example ? ` («Explica ${example}»)` : ''}, el estado de una cuenta bancaria («¿Cómo está BIN-1100?») o el coste.`,
  })
}

/** Deterministic answer to a question over the active run. */
export function answerLocally(question: string, ctx: AssistantContext): AssistantAnswer {
  const intent = detectIntent(question)
  switch (intent.kind) {
    case 'summary':
      return summary(ctx)
    case 'review':
      return review(ctx)
    case 'balance':
      return balance(ctx)
    case 'process':
      return process(ctx, intent.task)
    case 'explain':
      return explain(ctx, intent.token)
    case 'bank':
      return bank(ctx, intent.account)
    case 'cost':
      return cost(ctx)
    case 'unknown':
      return unknown(ctx)
  }
}
