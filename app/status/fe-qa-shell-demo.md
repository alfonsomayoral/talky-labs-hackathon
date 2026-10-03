# fe/qa-shell-demo — 5.B pulido transversal y 5.C demo

## Hecho

Contraste (WCAG AA: 4,5:1 en texto, 3:1 en indicadores):
- Tokens nuevos en `src/design/tokens.css`: `--brand-line` (#EA580C) para indicadores naranjas y `--brand-strong` (#9A3412) para hover y active del primario.
- Botón primario con fondo `--brand-ink` (blanco sobre él: 5,2:1; antes 2,8:1). Lo aprobó el usuario. `src/components/Button/Button.module.css`.
- Anillo de foco global, subrayado de pestaña, casilla de `FilterChip`, foco de `DataTable` y tirador de `SidePanel` con `--brand-line`, o `--brand-ink` donde hay un icono blanco encima.
- Texto gris pequeño que no llegaba a 4,5:1: títulos de sección, subtítulo del selector y pie de la barra lateral (`--ink-2` sobre `--ground`); grupos y placeholder de ⌘K, títulos de atajos, `hint` de `Menu`, importe cero de `Amount`, opciones de `SegmentedControl` y contador de `Tabs`. Iconos de botones sin texto (cerrar aviso, quitar `Pill`, quitar filtro, `Metric.hint`) a `--ink-3`.
- Las reglas, en `src/components/README.md`.

Foco, ARIA y teclado:
- Shell (`src/shell/AppShell.tsx`): enlace «Saltar al contenido» (primer Tab) que enfoca `<main id="contenido">` sin tocar la URL. Título de pestaña por ruta, `pageTitle()` en `src/shell/routeCrumbs.ts` («BIN-1200 · Bancos · Kalmora Close»).
- Barra lateral: la cifra de Atención se lee como «56 pendientes, con urgentes» (antes era un `aria-label` sobre un `span`, que no se anuncia). Listas de cada sección con nombre.
- `DataTable`: con Tab se llega a las cabeceras ordenables y a las de grupo (antes tenían `tabIndex=-1`). `aria-rowcount` y `aria-rowindex` coherentes con la virtualización.
- `Toaster`: región `aria-live="polite"` siempre montada, para que se anuncie cada aviso; los errores, con `role="alert"`.
- Estados homogéneos: `QueryState` anuncia la carga con texto («Cargando…») y el error como `alert`. La carga del panel de partida (`PeekHost`) hace lo mismo.
- `FilterBar` pasa de `toolbar` a `group` (no tenía navegación con flechas). `Metric.hint` es un botón. El tirador de `SidePanel` tiene `aria-valuemax`.
- Todo compatible con las props actuales: no cambia ninguna firma.

`DataTable`, petición de qa-tasks (segunda PR): en una celda alineada a la derecha que no cabía, el importe se recortaba por la izquierda (`-15.603.148,68 MXN` se leía `5.603.148,68 MXN`). Ahora la celda usa `justify-content: safe flex-end`, de modo que lo que no cabe empieza en el borde izquierdo, y su contenido termina en elipsis por la derecha. Las celdas centradas usan `safe center`. Solo CSS, sin cambios en las props. Los anchos que qa-tasks puso como parche pueden volver a su valor.

Demo (5.C): sección «Recorrido de demo» en `app/README.md`, con los 7 pasos sobre julio (URL y qué enseñar). **`app/README.md` no es de mi carpeta**: revísalo en esta PR.

## Verificación

- `npm run typecheck` (salida 0), `npm run lint` (oxlint, salida 0), `npm run test` (54 ficheros, 352 tests en verde), `npm run build` correcto.
- Tests nuevos: `pageTitle` (`src/shell/routeCrumbs.test.ts`), ordenar con el teclado en `DataTable` (`DataTable.test.tsx`) y anuncios de carga y error en `QueryState` (`QueryState.test.tsx`).
- Navegador, puerto 5174, julio con la referencia golden cargada:
  - Recorrido de demo completo sin recargar: Resumen → `g a` Atención → tarjeta `API005229` → ⌘K `API004128` (panel con el asiento de 7 líneas) → `g 4` Bancos → `BIN-1200` → casación N:1 `BL0004009`+`BL0004010` → `g c` Comparar → `g e` Entregables (nota 100,00) → `g i` Asistente («¿Qué partidas tengo que revisar?»: 56, 11,6 M€). **Cero errores y cero avisos en consola.**
  - Teclado: el primer Tab muestra el enlace de salto y Enter enfoca `<main>`; el panel de partida recibe el foco al abrirse y Esc lo cierra.
  - Contraste medido en el DOM, en todas las rutas: shell y componentes base, sin fallos. Los que quedan son de otras carpetas (abajo).

- Recorte de `DataTable`, en Actividad: con la columna de importe a 64 px, antes los 5 primeros importes perdían el principio y ahora no pierden ninguno y acaban en «…». A 128 px siguen alineados a la derecha, con 12 px de padding. Consola sin errores. Comprobaciones en la segunda PR: typecheck y lint con salida 0, 354 tests en verde y build correcto. Es CSS de maquetación, que jsdom no calcula, así que no tiene test de vitest.

## Sin verificar

- Lectores de pantalla reales (VoiceOver): revisé roles y nombres en el árbol de accesibilidad, pero no lo escuché.
- Septiembre: lo prepara la coordinadora. Los cambios son de estilo y ARIA, no dependen de los datos.

## Peticiones a la coordinadora

- Revisar `app/README.md` (sección «Recorrido de demo»), incluido en esta PR.
- Contraste en carpetas ajenas, para qa-core y qa-tasks. Todo es `--ink-4` (2,5:1) como texto; basta con `--ink-3` (o `--ink-2` sobre gris):
  - `features/item/kit/ProcessMap.module.css`: artículos «§2.1» de las columnas, y etiqueta, recuento y artículo de las ramas vacías.
  - `features/tasks/ap/Ap.module.css`, `features/item/kit/MasterCompare.module.css`, `features/item/kit/JournalEntryView.module.css` y `features/ledger/Ledger.module.css`: el «—» de las celdas vacías.
  - `features/ledger/Ledger.module.css`: nombres de grupo de cuentas en la cabecera del mapa de calor.
  - `features/compare/TaskScores.module.css`: el peso «30 %» de cada tarea.
  - `features/assistant/Assistant.module.css`: la nota «Respuestas locales sobre la ejecución activa…».
  - `features/data-explorer`: el recuento de cada tipo de maestro («Clientes 87»).
  - `features/attention/AttentionPage.module.css`: el recuento de los segmentos (`--ink-3` sobre `--bg-muted`, 4,4:1).
- Muchas vistas marcan la selección con `border-color: var(--brand)` (2,8:1, por debajo de 3:1). Con `--brand-line` cumple sin cambiar el aspecto: attention, activity, ledger, ar-cash, ap, bank, ar-billing, ic, compare, runs, data-explorer, `item/kit/ProcessMap`.
- Errores en línea como `<p>` sin `role="alert"` en `item/kit/EvidenceList.tsx`, `item/kit/RawBankRecord.tsx` e `item/tabs/evidenceEntries.tsx`. Para que sean como el resto: `EmptyState size="sm"`, o `role="alert"`.

## Commits

- `ea8ab61 fix: raise contrast of orange fills, focus rings and small grey text`
- `81befaa feat: add skip link, page titles and spoken badges to the shell`
- `5fa4ca8 fix: make tables, toasts and query states work with keyboard and screen readers`
- `68f4b11 fix: darken unselected segments and tab counts on grey fills`
- `f931b59 docs: add the demo walkthrough over july to the readme`
- `8812ce1 docs: document orange indicators, grey text and table keys in the component guide`
- `de1b2eb fix: keep the start of right-aligned table cells that do not fit`
