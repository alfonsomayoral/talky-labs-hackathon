# fe/tasks-ap-bank — 3.A Bandeja AP y 3.D Bancos

Worktree `/Users/alfonsomayoral/Talky/talky-wt/fe-tasks-ap-bank`, puerto 5177 (entrada `fe-tasks-ap-bank` en `/Users/alfonsomayoral/Talky/.claude/launch.json`). Rama basada en `hackathon/frontend` 200692c; aún sin el merge de lo posterior (kit 2.C en 3cb7318).

## Hecho

**AP (`src/features/tasks/ap/`)**
- `model.ts`: sankey tipo de documento → decisión (`apSankey`), facetas y filtro (`facetCounts`, `filterRows`; el recuento de cada faceta ignora su propia selección), documento frente al maestro (`masterCompare`: proveedor, NIF del emisor, destinatario, dominio del remitente, IBAN contra ficha, histórico y factor, moneda, retención y certificado art. 43), casación línea a línea con pedido y entradas (`lineMatches`, tolerancia 2 % o 150 €), destino del duplicado (`duplicateTarget`: del mes, histórico o ausente) y `prettyXml`.
- `ApPage.tsx`: cabecera, sankey (`ApSankey.tsx`; pulsar banda o nodo fija las facetas Tipo/Decisión), lista `DataTable` con facetas Decisión, Motivo y Tipo más búsqueda; la ficha se elige con `?doc=<doc_id>`.
- `ApDocCard.tsx`: ficha con el documento al lado (`DocumentPane.tsx`: PDF en iframe con blob, XML formateado, mensaje), cabecera extraída, tabla frente al maestro, casación por línea, beneficiario y bloqueo, abono rectificado y enlace al duplicado. Botón «Razonamiento y asiento» abre el peek (`useOpenItem`).
- `useDocContext.ts`: lee la Facturae/CFDI (`api.einvoice`) y las entradas de los pedidos (`api.goodsReceipts`).

**Bancos (`src/features/tasks/bank/`)**
- `model.ts`: apuntes de la 572 en la moneda de la cuenta (`bookLinesOf`; USD con `amount_doc` y sin las líneas de valoración MXN), vista enfrentada por bloques (`recView`, forma banco:libro 1:1, N:1, 1:N), sin casar por categoría con «con ajuste / falta el ajuste / queda abierta», ajustes y su efecto en la 572 (`adjustmentsOf`, `glAdjustments` incluye los ajustes de otras filas que mueven esta 572), puente de saldo (`balanceBridge`) y resumen por cuenta (`accountSummary`).
- `BankPage.tsx`: rejilla de las 12 cuentas con estado, saldo del extracto, líneas casadas, sin casar, ajustes y abiertas sin ajuste.
- `unmatchedByCategory(view, glAdjustments, sameCurrency)`: por categoría, lo que sus ajustes dejan sin cubrir en importe (`uncovered`), contando los ajustes archivados en otra cuenta. Los ajustes no nombran su línea y uno puede cubrir varias (recibo devuelto + comisión), por eso por importe y no por recuento; en la cuenta USD (ajustes en MXN) `uncovered` es null. La insignia dice «Con ajuste», «Falta ajuste por X», «Falta el ajuste» o «Sin ajuste: queda abierta».
- `BankAccountPage.tsx` + `RecFaceView.tsx`: puente, sin casar por categoría, extracto frente a libro con conectores SVG por bloque y filtro Todo/Casadas/Sin casar, registro crudo N43/CAMT (`api.rawBankDetails`) de la línea elegida y ajustes.
- `useAccountData.ts`: diario de la 572 hasta fin de mes (`queryJournal` paginado), apuntes referenciados fuera del mes (`getJournalEntries`) y detalle crudo.

## Verificación
- `npm run typecheck`, `npm run lint` y `npm run build` en verde. `npm run test`: 127 en verde, 36 omitidas, y 1 fichero que falla al cargar, `src/engine/score/parity.test.ts`. Ese fallo no es de esta rama: lee `null!.deliverables` cuando no hay fixture y ya está arreglado en `hackathon/frontend` (64d4011), así que se va con el merge. `npx vitest run src/features/tasks`: 30 en verde (AP 16, bancos 14).
- Navegador (5177, julio + referencia golden, sin errores de consola en AP):
  - AP: sankey 305 documentos; `API005229` (fraude: dominio `ffiinstalacionesel-es.es` frente a `ffiinstalacionesel.es` e IBAN marcados), `API005209` (duplicado de `API005148`, histórico, con factura y asiento), `API005587` (abono), `API005230` (26 líneas casadas con entradas).
  - AP: pulsar el nodo «Duplicado» del sankey deja 14; la faceta Motivo «Destinatario incorrecto» deja 3 (API005225, API005226, API005227); «Limpiar» vuelve a 305.
  - Bancos, las 12 cuentas recorridas: ninguna con «Sin explicar». CMA-1100 con residuo −3.228,89 y «Desde BIN-1100: Cuenta bancaria equivocada…» en Ajustes. Los «Falta ajuste por» coinciden con el residuo, que es el control de research: CMA-1100 −3.228,89 (domiciliaciones BL0001846/BL0001847, facturas rechazadas por AP, p. ej. API005227) y CMA-1200 −2.644,96. «Recibo devuelto» de CMA-1200 sale «Con ajuste»: 4 líneas, 2 ajustes. Consola: las únicas entradas son de un recargado en caliente a mitad de edición (`view.blocks is not iterable`, firma antigua); al recorrer las 12 cuentas no salió ninguna nueva.
  - Bancos: rejilla con saldos iguales al golden; BIN-1200 con N:1 (nómina en dos lotes BL0004009/BL0004010), 1:N (remesa SEPA BL0003036 contra 19 pagos), comisiones sin contabilizar con ajuste y registro N43 22/23; puente que cuadra al céntimo en 11 de 12 cuentas (residuos iguales al informe de research: CMA-1000 −5.265,44; BIN-1100 +70.117; BAE-1100 −900.000).

## Sin verificar
- Septiembre (resultados importados) sin probar.
- La rejilla de bancos sigue usando `accountSummary` con el estado de las partidas del motor; no cambia con este arreglo.

## A medias
1. **ProcessMap en las dos páginas.** El kit (`src/features/item/kit/`) está en `hackathon/frontend` 3cb7318 (wip). A 03/10 la coordinadora aún no ha avisado: le faltan lint, test y el README del kit. No se hace el merge hasta el aviso. Siguiente paso: `git merge hackathon/frontend`; en `ApPage.tsx` y `BankPage.tsx` añadir arriba `<ProcessMap flow={processFlow('ap' | 'bank_rec', data, api.core, run)} selectedId={…} onSelect={…} />`; en AP, al seleccionar un nodo poner `filter.only = findFlowFilter(flow, id)?.items` (el campo `only` de `ApFilter` ya existe y ya filtra); en bancos, filtrar la rejilla por las cuentas de los items del nodo.
2. **Usar el kit en lugar de lo local**, si su API lo permite: `JournalEntryView` para los ajustes (`BankAccountPage.tsx`, sección «Ajustes», hoy tabla propia), `RawBankRecord` para el registro crudo, `MasterCompare`/`EvidenceList` si cubren lo de `ApDocCard.tsx`/`DocumentPane.tsx`. No es obligatorio: lo local funciona.
3. **Cerrar paquetes:** suite completa (`npm run typecheck && npm run lint && npm run test && npm run build`), recorrido sin errores de consola y rehacer los dos commits `wip:` como `feat: add ap inbox view` y `feat: add bank reconciliation views` Los `wip:` ya están en `origin/fe/tasks-ap-bank`, así que reescribirlos (`git reset --soft 200692c`) obligaría a un push forzado: decidir con la coordinadora o dejarlos y que el merge `--no-ff` lleve un asunto `feat:`.

## Peticiones a la coordinadora
- Ninguna sobre ficheros compartidos. Nota: `PROBLEM.md` llama N:1 a «una remesa contra varios pagos»; la vista usa banco:libro, así que la remesa SEPA sale como 1:N y la nómina en dos lotes como N:1.

## Commits
- `3823989 wip: ap inbox with sankey, faceted list and document ficha`
- `a98507d wip: bank account grid and face-to-face reconciliation with balance bridge`
- `3b12453 fix: show what each bank category leaves without adjustment, by amount and across accounts`
