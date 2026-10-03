# Componentes base

Import everything from `@/components`. Live examples: `/dev/ui` (dev only). Tokens: `src/design/tokens.css`.

## Rules

- **Colour carries meaning only.** Orange (`--brand`) = primary action, selection, focus. Status colours = status. Everything else is ink on white with hairline borders (`--line`).
- **One primary button per view** (orange pill). The rest: `secondary` (bordered) or `ghost`.
- **Orange text on white** must use `--brand-ink` (#C2410C), never `--brand` (fails contrast at 12–13px). Status text on tinted fills uses `--ok-ink`, `--warn-ink`, `--danger-ink`, `--info-ink`.
- **Ids, accounts, codes, policy refs** → `Mono`. **Money** → `Amount` (never format cents by hand), right-aligned in tables. Dates/percent/durations → `@/lib/format`.
- **Density:** rows 36px, 13px text, 16px lucide icons with 1.5 stroke (set globally by `LucideProvider` in `main.tsx`; just render `<Icon />`).
- No banners, illustrations, gradients or heavy shadows. Empty states: an icon, a sentence, one action.
- Copy in Spanish; identifiers in English.

## Status vocabulary (`status.ts`)

| Concept | Map | Values |
| --- | --- | --- |
| `ItemStatus` | `ITEM_STATUS`, `ITEM_STATUS_ORDER` | AUTO «Resuelto» ok/green · NEEDS_HUMAN «Necesita persona» warn/amber · BLOCKED «Bloqueado» danger/red · OPEN «Abierto» neutral/gray |
| `Priority` | `PRIORITY` | P0 danger/red · P1 warn/amber · P2 info/blue · P3 neutral/gray |
| `Provenance` | `PROVENANCE` | RULE «Regla» info · HISTORY «Histórico» · MODEL «Modelo» · HUMAN «Humano» brand · REFERENCE «Referencia» |
| Confidence | `confidenceLevel(p)` | ≥ 0,9 «Alta» ok · ≥ 0,7 «Media» warn · else «Baja» danger · null → nothing |

`Tone` = `neutral | brand | ok | warn | danger | info`; `toneColor(tone)` gives the CSS colour for custom SVG.

## Catalogue

**Action**
- `Button` — `variant` primary|secondary(default)|ghost|danger, `size` sm|md, `loading`, `leadingIcon`, `trailingIcon`, plus all `<button>` props. `ButtonLink` = same look on a router `Link` (`to`). `buttonClassName()` for custom elements.
- `IconButton` — `icon`, `label` (required: aria-label + tooltip), `shortcut?`, `variant` ghost|secondary, `size`, `active` (pressed).
- `Kbd` — one key per element: `<Kbd>G</Kbd><Kbd>R</Kbd>`.
- `TalkyMark` — Talky's logo mark (inline SVG): `size` (px, 22 default), `title` (accessible name; omit next to text).

**Status**
- `StatusDot` — `status` or `tone`, `label` (pass `""` when text sits next to it), `pulse` for in-progress.
- `Badge` — `tone`, `variant` soft|outline, `dot`, `icon`. `StatusBadge({status})` and `PriorityBadge({priority})` are the canonical forms — use them, don't recolour.
- `Pill` — rounded tag for metadata/counts: `tone`, `icon`, `count`, `onRemove`.
- `ProvenanceBadge` — `provenance`, `compact` (icon only).
- `ConfidenceBand` — `value` 0..1|null, `showValue`.

**Data**
- `Amount` — `cents`, `currency` (EUR default; **pass the company currency**, MXN for 3100), `signed`, `compact` («1,2 M€», exact value in tooltip), `decimals`, `mono`, `colorize` (green +/red −), `hideCurrency`. null → «—», zero muted.
- `Mono` — `muted`. For ids: API004128, 40090000, BL0000085, §2.2.3.
- `KeyValue` — `items: {label, value, mono?}[]`, `columns` 1|2, `labelWidth`.
- `Metric` — `label`, `value` (preformatted), `delta` + `deltaTone` ok|danger|neutral, `comparison`, `hint` (info tooltip), `size` md|lg, `loading`. 3–4 per row.
- `Sparkline` — `values`, `width`, `height`, `tone`, `area`, `showLast`, `aria-label`.
- `ProgressBar` — simple: `value`/`max`/`tone`; stacked: `segments` (+ `statusSegments(counts)` for item statuses in canonical order), `showLegend`, `size` sm|md, `label`.
- `DataTable` — see below.

**Structure**
- `Page` — route wrapper (24px padding). `fill` makes it viewport-high so a DataTable scrolls inside; `width="narrow"` caps at 960px.
- `PageHeader` — `title`, `subtitle`, `breadcrumb` (in-page context; the topbar already shows the route), `actions`, `filters` (a FilterBar).
- `Card` — `title`, `description`, `actions`, `padding` none|sm|md, `interactive`.
- `Section` — titled block without surface: `title`, `description`, `count`, `actions`.
- `Tabs` — `tabs: {id, label, count?, disabled?}[]`, `value`, `onChange`, `idPrefix`; wrap content in `TabPanel` with the same `idPrefix`.
- `SegmentedControl` — `options: {value, label, icon?}[]`, `value`, `onChange`, `aria-label` (required), `size`.
- `FilterBar` — row of chips: `onClear` (pass only while a filter is active), `end` slot (count, ViewOptions).
- `FilterChip` — multi-select facet: `label`, `options: {value, label, count?, icon?}[]`, `selected: string[]`, `onChange`, `searchable` (auto when > 7 options).
- `ViewOptions` — «Vista» popover: `groupBy {options, value|null, onChange}`, `sort {options (column ids), value: SortState|null, onChange}`. Share the same `SortState` with the DataTable.
- `EmptyState` — `icon` (lucide element), `title`, `description`, `action`, `size` sm|md.
- `Skeleton` — `width`, `height`, `radius`, `lines`.
- `QueryState` — `status` (as `useDerivedRun().status`), `error`, `isEmpty`, `onRetry`, overrides `idle|loading|empty`; children may be a function (rendered only when ready). Default idle state: «Sin ejecución activa» + «Nuevo cierre».
- `Breadcrumb` — `items: {label, to?}[]`.

**Layers** (Esc closes only the topmost one; `lib/keyboard` `useLayer`)
- `SidePanel` — non-modal right panel: `open`, `onClose`, `title`, `actions`, `footer`, `defaultWidth` 560, `minWidth`, `storageKey` (remember dragged width). Tab cycles inside; list j/k keep working behind it. For item details use the shell's peek (`useOpenItem`), not your own panel.
- `Dialog` — modal: `open`, `onClose`, `title`, `description`, `footer` (primary last), `size` sm|md|lg, `placement` center|top, `bare`. On open, focus goes to an `autoFocus` child, else the first field, else the first control after the header.
- `Menu` — `trigger` (a Button/IconButton element), `items` (`{id, label, icon?, hint?, description?, checked?, disabled?, danger?, onSelect}` | `{type:'separator'}` | `{type:'label'}`), `side`, `align`.
- `Popover` — low-level anchored surface (`open`, `onClose`, `anchor`, `side`, `align`, `initialFocus`). Prefer Menu/FilterChip/ViewOptions.
- `Tooltip` — `content`, `shortcut`, `side`, `delay`; child must accept pointer/focus handlers. Supplementary only.
- `toast(title, {description, tone, action, duration})`, `toast.success`, `toast.error`, `toast.dismiss(id)`. `<Toaster />` is mounted once in `main.tsx`.

## DataTable

```tsx
const columns = useMemo<Column<WorkItem>[]>(() => [
  { id: 'id', header: 'Partida', width: 220, cell: (r) => <Mono>{r.key}</Mono>, sortValue: (r) => r.key },
  { id: 'counterparty', header: 'Contraparte', width: 'minmax(200px, 1fr)', cell: (r) => r.counterparty },
  { id: 'amount', header: 'Importe', width: 140, align: 'right', cell: (r) => <Amount cents={r.amount} currency={r.currency ?? 'EUR'} />, sortValue: (r) => r.amount },
  { id: 'status', header: 'Estado', width: 150, cell: (r) => <StatusBadge status={r.status} /> },
], [])

<DataTable aria-label="Partidas" rows={items} columns={columns} getRowId={(r) => r.id}
  groupBy={(r) => r.status} groupOrder={ITEM_STATUS_ORDER} renderGroup={(k) => ITEM_STATUS[k as ItemStatus].label}
  sort={sort} onSortChange={setSort}
  selectedId={activeItemId} onOpen={(r) => openItem(r.id)} globalKeys />
```

- Virtualized (tested with 40k rows); header is sticky; rows 36px. **Memoize `columns`** (and `rows`), or sorting reruns every render.
- `width`: px number or any grid track; default `minmax(0, 1fr)`. Horizontal scroll appears when fixed widths exceed the space.
- Sort: click a header with `sortValue` (asc → desc → off); nulls last. Controlled with `sort`/`onSortChange` or uncontrolled with `defaultSort`.
- Groups: `groupBy`, `groupOrder`, `renderGroup`; headers collapse on click and show counts.
- Keyboard: `j`/`k`/`↓`/`↑` move the cursor (brand-soft row), `Enter` → `onOpen`. `globalKeys` listens on the whole page (use it on the page's main list, once per page).
- Height: inside `<Page fill>` it fills the remaining space; elsewhere pass `height` (px).
- Built on `@tanstack/react-virtual` only (sorting/grouping are a few pure functions in `DataTable/model.ts`), so column definitions need no TanStack Table types.

## Shell hooks (`@/shell/…`)

- `useOpenItem()` → `(itemId) => void` sets `?item=<task>:<key>`; the shell's `PeekHost` renders `ItemPanel` in a SidePanel. `useActiveItemId()` reads it (highlight the open row). Peek pattern for lists: `selectedId={activeItemId}` + `onOpen={(r) => openItem(r.id)}`, and in `onSelectedChange` call `openItem(id)` when a peek is open so j/k move it.
- `<PageActions>…</PageActions>` (from `@/shell/PageActions`) portals buttons into the topbar's right slot.
- ⌘K already searches items (by key, bank line or journal entry of their evidence), vendors, customers, accounts, bank lines and journal entries (`shell/useEntitySearch.tsx`). Entity results link to the explorer: `/datos/proveedores/:id`, `/datos/clientes/:id`, `/datos/cuentas/:account`, `/datos/diario/:entryId`, `/datos/extractos/:account/:month` (`explorerRoute` in `shell/entitySearch.ts`).
- `registerCommandProvider((query) => Command[] | Promise<Command[]>)` (from `@/shell/commands`) adds ⌘K results; returns an unregister function. `Command = {id, label, group?, hint?, icon?, keywords?, shortcut?, run(ctx)}`, `ctx = {navigate, openItem}`.
- Global keys (`lib/keyboard.ts`): ⌘K/Ctrl+K palette, `?` shortcuts help, `g` + NAV letter navigates, Esc closes the top layer. Single-key hotkeys are ignored while typing or with a modal open; use `shouldIgnoreHotkey(e)` for your own. ⌘J is reserved for the assistant panel.
- `usePageShortcuts(title, [{label, keys}])` (from `@/lib/keyboard`) lists a page's own keys in the `?` help while the page is mounted, e.g. `usePageShortcuts('Atención', [{ label: 'Aceptar', keys: ['A'] }])`. Display only: the page still handles the keys.
