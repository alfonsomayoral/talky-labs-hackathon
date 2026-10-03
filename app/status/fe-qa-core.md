# fe/qa-core — 5.A–5.B QA y pulido: núcleo

Paquete cerrado. Tanda 1 fusionada en la PR #158; tanda 2 en esta PR.

## Hecho

Tanda 1 (PR #158): cifras que cuadran entre pantallas y arreglos encontrados con septiembre.

- **Atención en EUR, como Resumen y Asistente.** La cabecera decía «Quedan 60 · 6,9 M€ + 49,7 M MXN» mientras Resumen y Asistente decían «60 · 9,4 M€». Ahora suma en EUR con `attentionSummary` y `eurConverter` de `features/overview/model`. `src/features/attention/AttentionPage.tsx`.
- **Hueco del balance de Entregables en EUR** desde `trialBalance.eur` (69,8 M€ en julio, igual que Resumen y Balance). Las cifras crudas de `score.py` llevan «(score.py, MXN sin convertir)» y van sin símbolo de moneda. `src/features/deliverables/ScoreCard.tsx`.
- **Asiento en el panel estrecho:** `JournalEntryView` ya no corta Debe y Haber. `src/features/item/kit/JournalEntryView.tsx` y `.module.css`.
- **Asistente sin ids de julio:** sugiere un id que existe en la ejecución activa; el placeholder ya no cita un id. `src/features/assistant/engine/local.ts` (con test), `src/features/assistant/Chat.tsx`.

Tanda 2 (esta PR):

- **Contraste**, en `overview`, `attention`, `activity`, `item`, `runs`, `deliverables`, `compare`, `observability` y `assistant`:
  - texto con `--ink-4` pasa a `--ink-3`: artículos de columna y ramas vacías de `ProcessMap`, «—» de `MasterCompare` y `JournalEntryView`, peso de `TaskScores` y nota de la caja de pregunta del Asistente;
  - recuento de los segmentos de Atención a `--ink-2`;
  - selección, foco y controles con `--brand` pasan a `--brand-line`: bordes de selección, `box-shadow` de la fila seleccionada de Atención, anillos de foco (`outline`), foco de la caja del Asistente, foco de nodos de `PipelineDag`, y línea y deslizador del umbral de Coste. Ya no queda `var(--brand)` en el CSS de estas carpetas.
- **Errores de lectura de evidencias con `role="alert"`**, solo en los estados de error: `item/kit/EvidenceList.tsx` (diario), `item/kit/RawBankRecord.tsx` (extracto) y `item/tabs/evidenceEntries.tsx` (entradas de mercancía y diario).
- **Fecha de la cesión al factor** con `formatDate` en `item/kit/MasterCompare.tsx` («desde 12 mar 2025», antes «desde 2025-03-12»). Lo pidió qa-tasks.

## Verificación

- Tras `git merge origin/hackathon/frontend`: `npm run typecheck` (salida 0), `npm run lint` (oxlint, salida 0), `npm run test` (55 ficheros, 360 tests en verde) y `npm run build` correcto.
- Navegador, puerto 5176, **septiembre** (`phase_test` + `phase_test-research-qa`):
  - Resumen, Atención y Asistente dan las mismas cifras: 645 de 719 partidas resueltas, 60 en atención por 9,4 M€, y P0 2 · P1 14 · P2 44. Las preguntas 1 a 4 del Asistente responden sin golden.
  - Sin golden, Comparar, la pestaña Golden, Entregables y Coste explican lo que falta. Cero errores en consola.
  - Casos nuevos abiertos en el panel, con todas sus pestañas y sin errores: DUA en USD `API004940` (documento en 28.800 US$, asiento cuadrado en EUR), embargo `API005192`, y dominios parecidos `API005263` y `API005264`.
  - Teclado: `j`/`k`, `Enter` y `Esc` en Actividad y en el panel; `j`, `a` y «Deshacer» en Atención; ⌘K y ⌘J.
- Navegador, **julio** con golden:
  - Entregables da 100,00 y un hueco de 69,8 M€ → 0 €.
  - La cesión de `API004175` sale «desde 12 mar 2025».
  - Color calculado en el DOM: recuento de segmentos `rgb(75, 85, 99)` y selección de Atención `rgb(234, 88, 12)`.
  - Tras el merge, Resumen, Atención, Entregables, Comparar, Coste y Asistente cargan sin errores en consola.

## Sin verificar

- No se ha abierto una partida por cada resultado de cada tarea en julio. Las vistas por tarea son de qa-tasks.
- Estados de carga y de error de cada pantalla: solo se han visto de paso.
- Modo Profundo del Asistente: en este worktree no hay clave, así que responde el motor local, como se espera.

## Pendiente (cosmético, sin arreglar)

- Comparar muestra el selector «Solo diferencias / Todo» también en el estado vacío sin golden.
- `ProcessMap` dentro del Asistente lateral (⌘J) se corta en horizontal y hay que desplazarlo.
- Con el panel muy estrecho, `JournalEntryView` oculta la etiqueta de la cuenta y deja solo el número; el pie «4 líneas · EUR» pasa a dos líneas.
- Quedan textos auxiliares con `--ink-4` fuera de la lista de la coordinadora: texto de línea y asignación del asiento, `MasterCompare .state` y el placeholder del Asistente.

## Peticiones a la coordinadora

- Ninguna abierta. El «-0 €» de `formatMoney` ya lo resolvió la PR #162.

## Commits

- `8ad3343 fix: keep debit and credit visible when the item panel is narrow`
- `07814c3 fix: show the pending attention total in EUR like the overview`
- `1ad2720 fix: suggest item ids that exist in the active run in the assistant`
- `4ee8d57 fix: show the deliverables balance gap in EUR and label the scorer units`
- `0d1b76f docs: report the first qa-core batch`
- `28e71a0 fix: raise text and selection contrast in the core views`
- `db93862 fix: announce evidence read errors as alerts`
- `7f7b782 fix: format the factoring assignment date in the master comparison`
