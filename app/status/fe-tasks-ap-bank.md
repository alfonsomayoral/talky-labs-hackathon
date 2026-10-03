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
- `BankAccountPage.tsx` + `RecFaceView.tsx`: puente, sin casar por categoría, extracto frente a libro con conectores SVG por bloque y filtro Todo/Casadas/Sin casar, registro crudo N43/CAMT (`api.rawBankDetails`) de la línea elegida y ajustes.
- `useAccountData.ts`: diario de la 572 hasta fin de mes (`queryJournal` paginado), apuntes referenciados fuera del mes (`getJournalEntries`) y detalle crudo.

## Verificación
- `npm run typecheck` y `npm run lint` en verde; `npx vitest run src/features/tasks`: 29 pruebas en verde (AP 16, bancos 13). Sin ejecutar todavía la suite completa ni `npm run build`.
- Navegador (5177, julio + referencia golden, sin errores de consola en AP):
  - AP: sankey 305 documentos; `API005229` (fraude: dominio `ffiinstalacionesel-es.es` frente a `ffiinstalacionesel.es` e IBAN marcados), `API005209` (duplicado de `API005148`, histórico, con factura y asiento), `API005587` (abono), `API005230` (26 líneas casadas con entradas).
  - Bancos: rejilla con saldos iguales al golden; BIN-1200 con N:1 (nómina en dos lotes BL0004009/BL0004010), 1:N (remesa SEPA BL0003036 contra 19 pagos), comisiones sin contabilizar con ajuste y registro N43 22/23; puente que cuadra al céntimo en 11 de 12 cuentas (residuos iguales al informe de research: CMA-1000 −5.265,44; BIN-1100 +70.117; BAE-1100 −900.000).

## Sin verificar
- El arreglo de `glAdjustments` para CMA-1100 (antes dejaba 427.928,18 € de residuo porque el ajuste `WRONG_BANK_ACCOUNT` está en la fila de BIN-1100): probado con vitest, **no revisado en el navegador**. Esperado tras el arreglo: residuo de CMA-1100 = −3.228,89 € más la apertura.
- `npm run build` y `npm run test` completos.
- Pulsar en el navegador las facetas y el sankey.
- Septiembre (resultados importados) sin probar.

## A medias
1. **ProcessMap en las dos páginas.** El kit (`src/features/item/kit/`) está en `hackathon/frontend` 3cb7318 (wip). Siguiente paso: `git merge hackathon/frontend`; en `ApPage.tsx` y `BankPage.tsx` añadir arriba `<ProcessMap flow={processFlow('ap' | 'bank_rec', data, api.core, run)} selectedId={…} onSelect={…} />`; en AP, al seleccionar un nodo poner `filter.only = findFlowFilter(flow, id)?.items` (el campo `only` de `ApFilter` ya existe y ya filtra); en bancos, filtrar la rejilla por las cuentas de los items del nodo.
2. **Usar el kit en lugar de lo local**, si su API lo permite: `JournalEntryView` para los ajustes (`BankAccountPage.tsx`, sección «Ajustes», hoy tabla propia), `RawBankRecord` para el registro crudo, `MasterCompare`/`EvidenceList` si cubren lo de `ApDocCard.tsx`/`DocumentPane.tsx`. No es obligatorio: lo local funciona.
3. **Revisar CMA-1100 en el navegador** (`/tareas/bancos/CMA-1100`): el puente no debe tener «Sin explicar» y la sección Ajustes debe mostrar «Desde BIN-1100: Cuenta bancaria equivocada…».
4. **Cerrar paquetes:** suite completa (`npm run typecheck && npm run lint && npm run test && npm run build`), recorrido sin errores de consola y rehacer los dos commits `wip:` como `feat: add ap inbox view` y `feat: add bank reconciliation views` (por ejemplo `git reset --soft 200692c` y dos commits por carpeta, antes del merge; o commits `feat:` nuevos encima).

## Peticiones a la coordinadora
- Ninguna sobre ficheros compartidos. Nota: `PROBLEM.md` llama N:1 a «una remesa contra varios pagos»; la vista usa banco:libro, así que la remesa SEPA sale como 1:N y la nómina en dos lotes como N:1.

## Commits
- `3823989 wip: ap inbox with sankey, faceted list and document ficha`
- `a98507d wip: bank account grid and face-to-face reconciliation with balance bridge`
