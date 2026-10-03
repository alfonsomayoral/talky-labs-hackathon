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

### 4.A Explorador de datos (`/datos/*`), commits `aa8c3b5` (wip) y `828d3e0`, verificado

- `src/features/data-explorer/model.ts` + `model.test.ts` (9 tests): rutas `dataPath`, filtros del diario en la URL (`sociedad`, `cuenta`, `origen`, `desde`, `hasta`, `q`), enlaces cruzados (`vendorLinks`, `customerLinks`, `itemsCiting`, `itemsCitingEntry`, `partnerPath`, `bankLineItems`) y ficheros (`fileKind`, `prettyXml`, `prettyJson`).
- `DataExplorerPage.tsx`: subrutas con `<Routes>` y estado vacío sin dataset.
- `common.tsx`: `SectionTabs`, `useApi`, `useRunItems`, `TextLink`, `DetailHeader`, `Facts`, `ItemLinks` (abre la partida con `useOpenItem`), `tableHeight`, `NotFound`.
- `MastersPage.tsx`: 8 maestros. La fila de una cuenta bancaria abre su extracto del mes.
- `PartyPages.tsx`: fichas de proveedor (facturas, histórico de documentos, pedidos, partidas que lo citan), cliente (contratos, facturas, partidas abiertas, pagarés) y proyecto (PEP, contratos, pedidos).
- `JournalPage.tsx`: diario con `api.queryJournal`, páginas de 500, filtros en la URL y «Cargar más».
- `EntryPage.tsx`: asiento con líneas, cuadre, origen y partidas que lo citan.
- `AccountPage.tsx`: cuenta con saldo registrado por sociedad y sus asientos.
- `DocumentsPage.tsx` + `FileViewer.tsx`: bandeja (AP, facturación, remesas y avisos), ficha de documento y visor (PDF, XML indentado, JSON, texto) con descarga.
- `StatementsPage.tsx`: lista de extractos (cuenta, sociedad, banco, formato, mes, líneas, saldos) y ficha de extracto: datos de la cuenta con enlace a su cuenta contable, líneas con importe coloreado y partidas, y al seleccionar una línea (clic o `j`/`k`) su registro crudo de `api.rawBankDetails` con conceptos y referencias, más «Abrir la partida» (o «Abrir el cobro» y «Abrir la conciliación» si alimenta dos).
- `DataExplorer.module.css`: estilos de todo 4.A, solo con tokens.

## Verificación

- Antes del commit `828d3e0`, sin `KALMORA_DEV_PHASE`: `typecheck` y `lint` sin errores; `test`: `Test Files 36 passed (36)`, `Tests 229 passed (229)`; `build` correcto (solo el aviso de chunk > 500 kB que ya había).
- 4.A en el navegador (puerto 5176), con julio y la referencia golden: `/datos` y los 8 maestros, `/datos/proveedores/V100009` y `V100045`, `/datos/clientes/C200001`, `/datos/proyectos/OB-1100-2511`, `/datos/cuentas/40090000`, `/datos/diario` (filtro por sociedad, cuenta y fecha en la URL; «Cargar más» llega a 869 de 869), `/datos/diario/1100-2026-1600000418` (cuadrado, con su partida `bank_rec`), `/datos/documentos`, `/datos/documentos/API004128` (PDF), `API004315` (XML), `/datos/documentos/fichero?path=…` (JSON y CSV), `/datos/extractos`, `/datos/extractos/BAE-1100/2026-07` (N43 con registros 22 y 23) y `/datos/extractos/BANH-3100-MXN/2026-07` (CSV en MXN, una línea con cobro y conciliación). «Abrir la partida» abre `?item=bank_rec:BAE-1100/BL0000044`. Rutas inexistentes muestran `NotFound`. Cero errores en consola.
- 4.C: `typecheck`, `lint` y `build` en verde antes de `3db7f65`. En el navegador, con la referencia golden (estados vacíos) y con un paquete sintético con confianzas: 2 modelos, Gantt de 6 tareas, curva con 363 partidas, ECE 4,4 %, umbral al 90 % (150 automáticas, 6 errores reales). El paquete sintético vive fuera del repo. Cero errores en consola.

## Sin verificar

- 4.C con un informe real del backend (`outputs/runs/<uuid>.json`): solo con el test de `normalizeManifest` y el manifiesto sintético.
- 4.A con `phase_test` (septiembre): solo julio.
- Extractos CAMT.053: se ha revisado N43 y CSV, no CAMT.

## Peticiones a la coordinadora

- 4.A y 4.C listos para integrar en `hackathon/frontend`. La rama ya contiene `hackathon/frontend` hasta `754a270`, incluido el `wip` de 2.C (`3cb7318`), así que el merge solo añade `src/features/data-explorer/`, `src/features/observability/` y este fichero.
- `TASK_LABEL` está duplicado en `observability/model.ts` y `overview/model.ts` (`TASK_META`). Estaría mejor un catálogo único de nombres de tarea en `src/domain/catalog/`.
- Rutas de detalle acordadas con 4.D (⌘K): `/datos/proveedores/:id`, `/datos/clientes/:id`, `/datos/cuentas/:account` y `/datos/diario/:entryId`. Además existen `/datos/proyectos/:id`, `/datos/documentos/:id` y `/datos/extractos/:account/:month`.

## Commits

- `3db7f65 feat: add cost page with model usage, task timeline and confidence calibration`
- `aa8c3b5 wip: data explorer pages without statements and styles`
- `fb8a07a Merge remote-tracking branch 'origin/hackathon/frontend' into fe/explorer-cost` (trae el arreglo de `parity.test.ts`)
- `828d3e0 feat: add data explorer with masters, journal, documents and statements`

El `wip` ya estaba en `origin` con un merge encima, así que no se ha reescrito: 4.A queda en `aa8c3b5` + `828d3e0`.
