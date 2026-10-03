# fe/qa-tasks — 5.A + 5.B QA y pulido: tareas y datos

Recorrido de `/tareas/*`, `/balance` y `/datos/*` con julio (golden) y con la ejecución de septiembre `phase_test-research-qa` (prototipos del research, 719 partidas, sin golden). Comparar y Coste son de `fe/qa-core`: solo se recorrieron, sin tocarlos.

## Hecho

### PR #154 (fusionada)

- **Importes MXN recortados en las tablas.** Las columnas de importe no cabían con importes de 3100 y la tabla recortaba por la izquierda: `-15.603.148,68 MXN` se leía `5.603.148,68 MXN`. Anchos ajustados al mayor importe de julio y septiembre en `tasks/ap/ApPage.tsx`, `tasks/ar-billing/ArBillingPage.tsx`, `tasks/ar-cash/ArCashPage.tsx`, `tasks/close/ClosePage.tsx`, `data-explorer/JournalPage.tsx` y `data-explorer/StatementsPage.tsx`.
- **Balance, tabla de cuentas** (`ledger/LedgerPage.tsx`): columna «Moneda» e importes sin divisa para que quepan las 5 columnas sin scroll horizontal; ordenar por Registrado, Después o Correcto compara en EUR.
- **Balance sin golden** (`ledger/LedgerPage.tsx`): la sección vacía «Hueco cerrado por tarea» pasa a «Movimiento por tarea» (Σ|asientos| de cada tarea en EUR); subtítulo y descripción ya no hablan de un balance correcto que no existe.
- **AP, art. 43** (`tasks/ap/model.ts`): fechas del certificado como fechas, no en ISO.
- **AP, ordenar por Total** (`tasks/ap/ApPage.tsx`): por valor en EUR.
- **Cierre, deterioro** (`tasks/close/ClosePage.tsx`): «Partidas abiertas» de la provisión con `Amount`.

### PR #161 (fusionada)

- **AP, datos de cada acción del maestro** (`tasks/ap/model.ts` → `actionDetails`, `tasks/ap/ApDocCard.tsx`): la ficha enseñaba solo «Registrar embargo» o «Actualizar datos bancarios». Ahora muestra lo que trae `action_data`: referencia e importe del embargo (`API005192`, 61.930,20 €), IBAN anterior y nuevo con certificado y fecha (`API005196`), factor, IBAN y fecha de la cesión (`API005190`), vigencia y referencia del certificado art. 43 (`API005622`), validez de la proforma. Fechas con `formatDate`, importe con `Amount`, IBAN y referencias con `Mono`. Tests en `model.test.ts`.
- **Contraste** (petición de qa-shell-demo, `--brand-line` de #153): `--ink-4` → `--ink-3` en el «—» de AP y del mapa de calor, nombres de grupo del mapa de calor, recuento de cada maestro y placeholder del diario; bordes de selección y foco de `--brand` a `--brand-line` en ledger, ar-cash, ap, bank, ar-billing, ic y data-explorer.

## Verificación

- `npm run typecheck`, `npm run lint`, `npm run test` (55 ficheros, 357 tests) y `npm run build`: en verde tras fusionar `origin/hackathon/frontend`.
- **Septiembre:** las 719 partidas abiertas en su panel en las 5 pestañas (Razonamiento, Resumen, Asiento, Evidencia, Golden) sin errores de consola ni textos rotos (`NaN`, `undefined`, «no existe»). Las 16 rutas sin errores; todas las filas de cada tabla (con scroll) sin importes desbordados.
- **Julio:** las 726 partidas abiertas en sus 5 pestañas sin incidencias; las 14 rutas sin errores de consola; Balance con 8 columnas sin scroll horizontal.
- **Casos nuevos de septiembre:**
  - art. 43 caducado (`API004580`, `API004661`, `API004702`): nodo «Bloqueo de pago 3» en el mapa, cascada §2.2.4 y certificado frente al maestro;
  - DUA y facturas en USD (`API004940`, `API004952`–`API004954`): ficha en US$ y asiento en EUR de la sociedad en el panel;
  - embargo (`API005192`): referencia e importe en la ficha;
  - dominio parecido (`API005263`): `señalizaci0nesvial.es` frente a la ficha, «posible suplantación»;
  - intereses: están en Bancos, 7 partidas (`INTEREST_NOT_BOOKED` y `LOAN_INTEREST_NOT_BOOKED`, por ejemplo `BIN-1000/BL0004088`, −466.875 €), resueltas con su ajuste y con su nodo en el mapa; 12 de 12 cuentas conciliadas. Intragrupo no trae diferencia de intereses en septiembre, así que la tarjeta act/360 no aparece.
  - `BANH-3100-USD`: puente en US$ y ajustes en MXN de la sociedad.
- Contraste comprobado en el navegador: selección del mapa de calor `#ea580c` y textos atenuados en `--ink-3`.

## Sin verificar

- Recorrido con teclado y lector de pantalla de cada vista: solo se revisó con ratón y texto.
- Listas en anchos menores de 1440 px.

## Pendiente

Paquete cerrado en modo cierre. Nada de esto rompe nada; queda para después:

- **Ficha AP de documentos que no son factura:** el apartado «Pago» enseña «El proveedor» y «Sin bloqueo», que no aplican a una proforma, un certificado o un embargo. Ocultarlo en `NOT_INVOICE` (`tasks/ap/ApDocCard.tsx`).
- **Dominio parecido:** la fila «Dominio del remitente» marca la diferencia, pero no resalta el carácter que cambia (`señalizaci0nesvial.es`).
- **Balance, tabla de cuentas:** a 1440 px la descripción de la cuenta queda cortada en las filas largas; con golden caben justas las 8 columnas.
- **Bancos, mapa de decisión de septiembre:** «Intereses de préstamo sin contabilizar» sale con 2 líneas sin casar y 3 ajustes. Viene de la entrega del prototipo, no de la app, pero conviene que el backend lo cuadre.
- **Sin verificar:** teclado y lector de pantalla en cada vista, y anchos menores de 1440 px.

## Peticiones a la coordinadora

- Resueltas: `DataTable` ya no recorta por la izquierda (#157) y `MasterCompare` formatea la fecha de la cesión.

## Commits

- `bcbdd6a fix: show the art. 43 certificate dates in the AP master comparison as dates`
- `45c3a88 fix: keep large MXN amounts whole in the task, balance and data tables`
- `74a71b7 fix: show the provision from open items as money in the bad debt view`
- `acfc2ca fix: sort the AP inbox totals by their value in EUR`
- `add181d feat: show how much each task moves the ledger when there is no golden`
- `f758c0b feat: show what each master data action carries in the AP card`
- `f44d060 fix: raise the contrast of muted text and selection borders in task, balance and data views`
