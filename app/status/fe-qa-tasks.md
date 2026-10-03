# fe/qa-tasks — 5.A + 5.B QA y pulido: tareas y datos

Recorrido de `/tareas/*`, `/balance`, `/datos/*`, `/comparar` y `/coste` con julio (golden) y con la ejecución de septiembre `phase_test-research-qa` (prototipos del research, 719 partidas).

## Hecho

- **Importes MXN recortados en las tablas.** Las columnas de importe no cabían con importes de 3100 y la tabla recortaba por la izquierda: `-15.603.148,68 MXN` se leía `5.603.148,68 MXN`. Anchos ajustados al mayor importe de julio y septiembre en `tasks/ap/ApPage.tsx`, `tasks/ar-billing/ArBillingPage.tsx`, `tasks/ar-cash/ArCashPage.tsx`, `tasks/close/ClosePage.tsx`, `data-explorer/JournalPage.tsx` y `data-explorer/StatementsPage.tsx`.
- **Balance, tabla de cuentas** (`ledger/LedgerPage.tsx`): columna «Moneda» e importes sin divisa para que quepan las 5 columnas sin scroll horizontal; ordenar por Registrado, Después o Correcto compara en EUR.
- **Balance sin golden** (`ledger/LedgerPage.tsx`): la sección vacía «Hueco cerrado por tarea» pasa a «Movimiento por tarea» (Σ|asientos| de cada tarea en EUR, de `trialBalance.eur.movementByTask`); subtítulo y descripción ya no hablan de un balance correcto que no existe.
- **AP, art. 43** (`tasks/ap/model.ts`): las fechas del certificado salen como fechas (`31 ago 2026`, «Vigente hasta 15 ago 2026»), no en ISO. Test en `model.test.ts`.
- **AP, ordenar por Total** (`tasks/ap/ApPage.tsx`): ordena por el valor en EUR; antes las facturas en MXN subían arriba.
- **Cierre, deterioro** (`tasks/close/ClosePage.tsx`): «Partidas abiertas» de la provisión con `Amount` en vez de un número sin moneda.

## Verificación

- `npm run typecheck`, `npm run lint`, `npm run test` (52 ficheros, 346 tests) y `npm run build`: en verde.
- Navegador, julio + golden: las 14 rutas abren sin errores de consola; las vistas de tarea abren con su mapa de decisión. 321 de 726 partidas abiertas en su panel en las 5 pestañas (todo AP y Facturación, parte de Cobros) sin errores ni textos rotos.
- Navegador, septiembre: las 16 rutas (incluidas `BANH-3100-MXN`, `BANH-3100-USD` y `BIN-1200`) sin errores de consola. Barrido de todas las filas de cada tabla (con scroll) sin importes desbordados. Balance sin golden revisado con captura.
- Casos nuevos de septiembre en AP: art. 43 caducado `API004580` (cascada §2.2.4, bloqueo de pago, certificado frente al maestro).

## Sin verificar

- El resto de partidas de julio en su panel (de la 322 a la 726) y las de septiembre: en curso.
- DUA en USD (`API004940`, `API004952`–`API004954`), embargo (`API005192`) y dominios parecidos (`API005263`, `API005264`): en curso.

## Peticiones a la coordinadora

- **`DataTable` (sesión de shell):** una celda alineada a la derecha cuyo contenido no cabe se recorta por la izquierda y se pierden los primeros dígitos del importe, sin elipsis. Mis columnas ya caben, pero cualquier tabla nueva puede repetirlo.

## Commits

- `bcbdd6a fix: show the art. 43 certificate dates in the AP master comparison as dates`
- `45c3a88 fix: keep large MXN amounts whole in the task, balance and data tables`
- `74a71b7 fix: show the provision from open items as money in the bad debt view`
- `acfc2ca fix: sort the AP inbox totals by their value in EUR`
- `add181d feat: show how much each task moves the ledger when there is no golden`
