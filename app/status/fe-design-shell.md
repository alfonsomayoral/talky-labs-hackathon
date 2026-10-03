# fe/design-shell — Refinado de diseño + 4.D Búsqueda y teclado

## Hecho
- **`Dialog` respeta `autoFocus` y el primer campo** (`src/components/Dialog/Dialog.tsx`). Al abrir, el foco va a un hijo con `autoFocus`; si no hay, al primer campo (`input`, `select`, `textarea`); si tampoco, al primer control que no sea el botón de cerrar. Si no hay ninguno, va al propio panel, ya sin anillo de foco.
- **Atajos por página en `?`** (`src/lib/keyboard.ts`): `usePageShortcuts(title, [{ label, keys }])` registra un grupo mientras la página está montada, y `ShortcutsDialog` lo muestra junto a General y Listas. Solo sirve para mostrarlos: la página sigue gestionando sus teclas. Está documentado en `src/components/README.md`.
- **Contador de Atención en la barra lateral** (`src/shell/attentionBadge.ts`, `Sidebar.tsx`). Descuenta las entradas resueltas o pospuestas de `useOverridesStore` (run activo), reutilizando `overrideFor`/`resolutionOf` de `attentionModel`. Una nota deja la entrada pendiente. La marca de urgente (P0) solo se tiene en cuenta en lo pendiente.
- **4.D Búsqueda ⌘K** (`src/shell/entitySearch.ts`, `src/shell/useEntitySearch.tsx`, montado en `AppShell`):
  - **Partidas.** Se buscan por su clave, por la línea bancaria de su evidencia y por el asiento de su evidencia. Abren el panel con `useOpenItem`. La primera partida añade «Ver en <tarea>», que lleva a la ruta de la tarea con `?item=`.
  - **Proveedores, clientes y cuentas.** Se buscan por id, nombre (sin acentos), NIF o descripción.
  - **Líneas bancarias.** Llevan a `/datos/extractos/:account/:month`.
  - **Asientos.** Usan `api.queryJournal` en el worker, a partir de 6 caracteres. Es otro proveedor y su resultado llega aparte.
  - **Orden.** Primero el id exacto, luego el prefijo y luego el texto contenido. Máximo 5 resultados por grupo.
  - **Rutas del Explorador**, acordadas con la sesión 4.A (fe/explorer-cost): `/datos/proveedores/:id`, `/datos/clientes/:id`, `/datos/cuentas/:account`, `/datos/diario/:entryId` y `/datos/extractos/:account/:month`.
  - **Acción «Descargar la entrega…»**: por ahora lleva a `/entregables`.
- **Refinado visual:**
  - La insignia urgente seguía en naranja cuando Atención estaba activa (`.active .badge` ganaba en especificidad). Ahora se queda en rojo.
  - Se quita el anillo de foco del contenedor del diálogo.
  - Muestra de `--ground` en la galería.
  - La hoja flotante sobre `#F4F3EF` ya estaba hecha; se ha revisado y no hay cambios.

## Verificación
- `npm run typecheck`: sin errores.
- `npm run lint` (oxlint): sin hallazgos.
- `npm run test`:
  - Con `KALMORA_DEV_PHASE=/Users/alfonsomayoral/Talky/participant/phase_dev`: 28 ficheros pasan y 2 se saltan; 153 tests pasan y 18 se saltan.
  - Sin esa variable falla `src/engine/score/parity.test.ts` (ver peticiones).
  - Tests nuevos: `Dialog.test.tsx` (3), `lib/keyboard.test.tsx` (2), `shell/attentionBadge.test.ts` (3) y `shell/entitySearch.test.ts` (7).
- `npm run build`: correcto. Solo aparece el aviso de tamaño de chunk que ya había.
- Navegador, en el puerto 5174, con julio y la referencia golden cargados:
  - **⌘K** encuentra `API004128` (Enter abre `?item=ap:API004128`), `BL0000085` (cobro, casación bancaria y línea de extracto), `V100045` (proveedor y sus asientos), `40090000` (cuenta) y el asiento `1100-2026-1400000003`.
  - **Contador de Atención**: 56, igual que «Quedan 56» en Atención. Tras posponer una entrada con `p`, ambos pasan a 55.
  - **Galería `/dev/ui`**: j/j/Enter abre el panel de partida.
  - **Ayuda `?`**: sin anillo en el panel e insignia urgente en rojo con Atención activa.
  - Consola sin errores.

## Sin verificar
- **Grupo de atajos de una página real en `?`.** Ninguna página llama todavía a `usePageShortcuts`; solo lo cubren los tests.
- **Enlaces de ⌘K a `/datos/...`.** Navegan, pero las páginas de detalle llegan con 4.A.
- **Refinado de densidad, tipografía y estados vacíos en Actividad, tareas, Balance, Ejecuciones y Entregables.** En esta rama aún son marcadores (h1 sin `Page`); habrá que revisarlos cuando se integren.
- **Teclas reales en el panel del navegador.** La tecla `?` enviada por el panel no dispara el atajo, pero un `KeyboardEvent` real sí abre la ayuda. Es una limitación de la emulación, no de la app.

## Peticiones a la coordinadora
- **`src/engine/score/parity.test.ts` falla en cualquier worktree.**
  - Causa: `devPhase()` busca `<app>/../../participant/phase_dev`, que en `talky-wt/*` no existe. Vitest ejecuta el cuerpo de `describe.skipIf` al recoger los tests, y `golden.deliverables` revienta con `null`.
  - Arreglo propuesto: mover `loadGolden` dentro de un `beforeAll`, o poner `KALMORA_DEV_PHASE` en el `.env.local` de cada worktree y cargarlo en `vitest.config.ts`.
- **Atención (2.D)**: llamar `usePageShortcuts('Atención', [{ label: 'Aceptar', keys: ['A'] }, { label: 'Posponer', keys: ['P'] }, { label: 'Nota', keys: ['N'] }])` desde `AttentionPage`.
- **Resumen (2.B)**: «Te necesitan (56)» no descuenta las correcciones; la barra lateral sí. Puede reutilizar `pendingAttention` de `@/shell/attentionBadge`.
- **Entregables (2.A)**: exponer una función `downloadDelivery(run)` para que «Descargar la entrega…» de ⌘K descargue directamente en vez de llevar a la página.

## Commits
- `da74b6a fix: focus the first field or autoFocus element when a dialog opens`
- `3017193 feat: let pages list their own shortcuts in the help dialog`
- `85f2824 feat: count only pending attention entries in the sidebar badge`
- `9e1729d feat: search items, master data and journal entries from the command palette`
- `7a82c89 style: keep the urgent badge red when active and drop the ring on focused dialogs`
