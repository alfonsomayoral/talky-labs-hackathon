# fe/explorer-cost — 4.A Explorador de datos + 4.C Coste y calibración

## Hecho

### 4.C Coste y calibración (`/coste`), commit `3db7f65`, verificado

- `src/features/observability/model.ts`: funciones puras.
  - `costSummary(manifest)`: modelos, llamadas, tokens, coste y duración. Lee el informe del backend ya normalizado por `normalizeManifest`.
  - `taskTimeline(manifest, events)`: usa `manifest.tasks` si trae inicio y fin; si no, el primer y último evento real de cada tarea (`ts + duration_ms`). Devuelve null sin tiempos.
  - `confidencePoints`, `reliabilityBins`, `expectedCalibrationError`, `thresholdStats`: la confianza sale de `WorkItem.confidence` (el último DECIDE) y el acierto de `score.perItem[id].exact`.
- `src/features/observability/CostPage.tsx`: indicadores, tabla de modelos, Gantt por tarea y estados vacíos explicados (golden, sin manifiesto, sin tiempos).
- `src/features/observability/Calibration.tsx`: curva de fiabilidad en SVG con diagonal e histograma, deslizador de umbral (automáticas, a persona, errores esperados y reales), ECE y lista de «errores que pasarían el umbral», que abre cada partida con `useOpenItem`. Sin confianza muestra un estado vacío que lo explica.
- `src/features/observability/model.test.ts`: 8 tests, con un paquete sintético de confianzas (0,95 bien calibrada y 0,75 sobreconfiada, ECE 0,2).

### 4.A Explorador de datos (`/datos/*`), a medias, commit `wip`

Escrito, sin verificar en el navegador:

- `model.ts` + `model.test.ts` (9 tests en verde): rutas `dataPath`, filtros del diario en la URL (`sociedad`, `cuenta`, `origen`, `desde`, `hasta`, `q`), enlaces cruzados (`vendorLinks`, `customerLinks`, `itemsCiting`, `itemsCitingEntry`, `partnerPath`, `bankLineItems`) y ficheros (`fileKind`, `prettyXml`, `prettyJson`).
- `DataExplorerPage.tsx`: subrutas con `<Routes>`, más un estado vacío cuando no hay dataset cargado.
- `common.tsx`: `SectionTabs`, `useApi`, `useRunItems`, `TextLink`, `DetailHeader`, `Facts`, `ItemLinks` (abre la partida con `useOpenItem`), `tableHeight` y `NotFound`.
- `MastersPage.tsx`: 8 maestros (proveedores, clientes, contratos, proyectos, plan de cuentas, impuestos en puntos básicos, centros de coste, cuentas bancarias).
- `PartyPages.tsx`: fichas de proveedor (facturas, histórico de documentos, pedidos, partidas que lo citan, diario), cliente (contratos, facturas, partidas abiertas, pagarés) y proyecto (PEP, contratos, pedidos).
- `JournalPage.tsx`: diario con `api.queryJournal`, páginas de 500 y filtros en la URL; exporta `useJournal` y `useJournalColumns`.
- `EntryPage.tsx`: ficha de asiento con líneas, cuadre, origen (factura AP o AR) y partidas que lo citan.
- `AccountPage.tsx`: ficha de cuenta con saldo registrado por sociedad (`recordedTrialBalance`) y sus asientos.
- `DocumentsPage.tsx` + `FileViewer.tsx`: bandeja (AP, facturación, remesas y avisos), ficha de documento y visor (PDF en `iframe` con blob URL, XML indentado, JSON formateado, texto).

## A medias

1. **`src/features/data-explorer/StatementsPage.tsx` no existe.** `DataExplorerPage.tsx` lo importa y **`typecheck` falla** solo por eso (TS2307). Siguiente paso: escribir `StatementsPage` y `StatementPage`.
   - `StatementsPage` (`/datos/extractos`): `DataTable` de `core.bankStatements` con cuenta, sociedad (de `core.bankAccounts`), banco, formato, mes, nº de líneas, saldo inicial y final (`<Amount>` en la moneda de la cuenta). Al abrir una fila, `dataPath.statement(account, month)`. Lleva `PageHeader` con `filters={<SectionTabs />}` y `Page fill`, como `DocumentsPage`.
   - `StatementPage` (`/datos/extractos/:account/:month`): `Facts` de la cuenta (IBAN, cuenta contable con `TextLink` a `dataPath.account`, formato, `rawPath`, saldos). `DataTable` de las líneas (`bank_line`, fechas, importe con `colorize`, texto y partidas de `bankLineItems(run.itemsById, account, line)`). Al seleccionar una línea, un panel con el registro crudo: `api.rawBankDetails(account, month)` cargado una vez, indexado por `bank_line`, mostrando `raw` en `<pre>`, `concepts` y `references`. Botón «Abrir la partida» con `useOpenItem`.
2. **`src/features/data-explorer/DataExplorer.module.css` no existe.** Todos los ficheros de 4.A usan estas clases: `link`, `muted`, `block`, `flags`, `kinds`, `kind` (con `[aria-current=page]` en marca), `headerStack`, `count`, `input`, `journalForm`, `more`, `error`, `detailHeader`, `detailTitleRow`, `detailTitle`, `detailSubtitle`, `facts`, `itemList`, `itemRow`, `itemTitle`, `linkList`, `tableWrap`, `table`, `num`, `ellipsis`, `balances`, `balance`, `viewer`, `viewerBar`, `viewerPath`, `inlineIcon`, `pdf` (alto ~70vh), `code` (`<pre>` mono con scroll) y `body`. `tableWrap`, `table` y `num` pueden copiarse de `observability/CostPage.module.css`. Solo tokens de `design/tokens.css`.
3. Después: `npm run typecheck && npm run lint && npm run test && npm run build`. Recorrido en el navegador por `/datos`, `/datos/maestros/*`, `/datos/proveedores/V100045`, `/datos/clientes/<id>`, `/datos/cuentas/40090000`, `/datos/diario` (filtros, «Cargar más»), `/datos/diario/<id>`, `/datos/documentos/API004128` (PDF y XML), `/datos/documentos/fichero?path=…` y `/datos/extractos/BIN-1100/2026-07`, con cero errores en consola. Luego un commit `feat: add data explorer with masters, journal, documents and statements` que sustituya el `wip`.

## Verificación

- 4.C: `typecheck`, `lint` y `build` en verde antes del commit `3db7f65`. Con `KALMORA_DEV_PHASE` definido: `Test Files 26 passed | 2 skipped`, `Tests 146 passed | 18 skipped`.
- 4.C en el navegador (puerto 5176), con julio:
  - Con la referencia golden: los estados vacíos de modelos, tiempos y calibración se muestran bien.
  - Con un paquete sintético con confianzas: 2 modelos, Gantt de 6 tareas, curva con 363 partidas, ECE 4,4 % y umbral al 90 % (150 automáticas, 6 errores reales). Pulsar un error abre `?item=ap:API004239`.
  - Cero errores en consola.
- El paquete sintético se genera con `make_bundle.py` en el scratchpad de la sesión, fuera del repo, y lo sirve el dev server con `KALMORA_RUNS=<scratchpad>/runs`. No se ha commiteado ningún dato.
- 4.A: solo `model.test.ts` (9 tests en verde). Nada revisado en el navegador.

## Sin verificar

- Todas las pantallas de 4.A en el navegador.
- 4.C con un informe real del backend (`outputs/runs/<uuid>.json`): solo se ha probado con el test de `normalizeManifest` y con el manifiesto sintético.

## Peticiones a la coordinadora

- `src/engine/score/parity.test.ts` revienta al recoger tests en los worktrees si no se define `KALMORA_DEV_PHASE`. `devPhase()` resuelve `../../participant/phase_dev`, que no existe en `talky-wt/<rama>/`. Además, el cuerpo de `describe.skipIf(!ready)` lee `golden.deliverables` con `golden = null`. Arreglo propuesto: crear `golden` dentro de los tests o en un `beforeAll`, o resolver la ruta de datos igual que `.env.local`.
- `TASK_LABEL` está duplicado en `observability/model.ts` y `overview/model.ts` (`TASK_META`). Estaría mejor un catálogo único de nombres de tarea en `src/domain/catalog/`.
- Rutas de detalle acordadas con 4.D (⌘K): `/datos/proveedores/:id`, `/datos/clientes/:id`, `/datos/cuentas/:account` y `/datos/diario/:entryId`. Además existen `/datos/proyectos/:id`, `/datos/documentos/:id` y `/datos/extractos/:account/:month`.

## Commits

- `3db7f65 feat: add cost page with model usage, task timeline and confidence calibration`
- `wip: data explorer pages without statements and styles` (ver `git log`)
