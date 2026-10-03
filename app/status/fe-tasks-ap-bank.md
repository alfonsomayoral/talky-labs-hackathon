# fe/tasks-ap-bank — 3.A Bandeja AP y 3.D Bancos

Worktree `/Users/alfonsomayoral/Talky/talky-wt/fe-tasks-ap-bank`, puerto 5177. AP y Bancos ya están integrados en `hackathon/frontend`. Esta entrega solo añade la explicación de las domiciliaciones que se quedan sin ajuste.

## Este cambio: domiciliaciones sin ajuste

**Problema.** Tras 37b4774 la rejilla da 12/12 cuentas conciliadas con golden. Pero la ficha de CMA-1100 y la de CMA-1200 marcaban en rojo «Falta ajuste por …» en «Domiciliación sin contabilizar». Golden deja esas domiciliaciones sin ajuste a propósito.

**Regla, comprobada en julio por importe y en la misma sociedad:** una domiciliación lleva ajuste si su factura de AP del mismo importe está contabilizada (`POST` o `POST_PAYMENT_BLOCK`). Queda abierta si la factura tiene otra decisión o si no existe en la bandeja.
- CMA-1100: BL0001847 (2.157,48 €) casa con API005227, rechazada (`WRONG_ADDRESSEE`). BL0001846 (1.071,41 €) no tiene factura de ese importe en la bandeja.
- CMA-1200: BL0001835 (2.644,96 €) casa con API005221, rechazada (`ARITHMETIC_ERROR`).

**Cambios:**
- `bank/model.ts`: nueva `openDirectDebits(lines, adjustments, apRows, company, currency)`. Para cada domiciliación del extracto, consume el ajuste de su mismo importe. Si no hay ajuste, devuelve la factura de AP de ese importe y si falta de verdad el ajuste, que es cuando la factura está contabilizada. Tiene test en `model.test.ts`.
- `bank/BankAccountPage.tsx`, sección «Sin casar por categoría»:
  - la insignia va en rojo solo cuando se debe un ajuste y falta;
  - las domiciliaciones abiertas a propósito dan una insignia neutra, «Con ajuste; 2 quedan abiertas», y una línea por domiciliación con el motivo y enlace a `/tareas/ap?doc=…`;
  - la cuenta USD (ajustes en MXN) no se compara por importe y se queda como estaba.

**Verificación:**
- `npm run typecheck`, `npm run lint`, `npm run test` (41 ficheros, 276 pruebas) y `npm run build` en verde, tras hacer merge de `hackathon/frontend` 0d5bdda.
- Navegador, julio + golden, las 12 cuentas:
  - ninguna insignia roja y ninguna cuenta con «Sin explicar»;
  - CMA-1100: «Con ajuste; 2 quedan abiertas», con «BL0001846 queda abierta: no hay factura de ese importe en la bandeja de AP» y «BL0001847 queda abierta: su factura API005227 tiene la decisión «Rechazar» en AP»;
  - CMA-1200: «Con ajuste; 1 queda abierta», con BL0001835 → API005221;
  - el enlace API005227 abre `/tareas/ap?doc=API005227` con su ficha.
- Septiembre sin ejecución: `/tareas/ap`, `/tareas/bancos` y `/tareas/bancos/CMA-1100` muestran «Sin ejecución activa».
- Consola sin errores nuevos.
- Sin verificar: una entrega en la que de verdad falte el ajuste de una domiciliación contabilizada. Solo lo cubre el test unitario; golden no tiene ese caso.

---

## Hecho

**AP (`src/features/tasks/ap/`)**
- `ApPage.tsx`: abre con el `ProcessMap` del kit (`useProcessFlow('ap')`). El nodo elegido va en `?nodo=` y filtra la lista con `findFlowFilter(...).items` a través de `ApFilter.only`; «Limpiar» también quita el nodo. Debajo:
  - el sankey tipo de documento → decisión (`ApSankey.tsx`); pulsar una banda o un nodo fija las facetas Tipo y Decisión;
  - la lista `DataTable` con facetas Decisión, Motivo y Tipo, más búsqueda;
  - la ficha, que se elige con `?doc=<doc_id>`.
- `ApDocCard.tsx`: ficha con estas secciones:
  - el documento al lado;
  - la cabecera extraída;
  - la **cascada §2.2** (`PolicyCascade` + `apCascade(row, events)` del kit);
  - documento frente al maestro;
  - casación línea a línea con pedido y entradas;
  - beneficiario y bloqueo;
  - abono rectificado y duplicado.
  - Además, el botón «Razonamiento y asiento» abre el `ItemPanel`.
- `DocumentPane.tsx`: una pestaña por fichero con `DocumentViewer` del kit (PDF, XML con resumen de e-factura, JSON) y otra con `EmailView` para el mensaje.
- `model.ts`: `apSankey`, `facetCounts`/`filterRows`, `masterCompare`, `lineMatches` (tolerancia 2 % o 150 €), `duplicateTarget`, `duplicatesOf`.
  - `masterCompare` sigue siendo local, porque `MasterCompare` del kit compara por igualdad de texto. No distingue «distinto pero justificado» (IBAN del factor) ni equipara NIF y NIF-IVA, y marcaría ✗ falsos.
- `useDocContext.ts`: Facturae/CFDI y entradas de los pedidos.

**Bancos (`src/features/tasks/bank/`)**
- `BankPage.tsx`: abre con el `ProcessMap` del kit (`useProcessFlow('bank_rec')`). El nodo va en `?nodo=` y deja en la rejilla solo las cuentas con partidas en ese nodo. Debajo, la rejilla de las 12 cuentas.
- `BankAccountPage.tsx` + `RecFaceView.tsx`:
  - puente de saldo;
  - sin casar por categoría;
  - extracto frente a libro con conectores 1:1, N:1 y 1:N;
  - registro crudo con `RawBankRecord` del kit;
  - ajustes con `JournalEntryView` del kit, cuadre por asiento incluido, más los ajustes de otras cuentas que mueven esta 572.
- `model.ts`:
  - `bookLinesOf`/`bookAmount`, con USD por `amount_doc`;
  - `recView`;
  - `unmatchedByCategory(view, glAdjustments, sameCurrency)`: lo que los ajustes dejan sin cubrir, por importe, contando los archivados en otra cuenta. Uno puede cubrir varias líneas (recibo devuelto + comisión). En la cuenta USD, con ajustes en MXN, el importe es null;
  - `adjustmentsOf`/`glAdjustments`;
  - `balanceBridge`;
  - `accountSummary`.
- `useAccountData.ts`: diario de la 572 hasta fin de mes y apuntes referenciados fuera del mes. El registro crudo ya lo lee `RawBankRecord`.

## Verificación
- `npm run typecheck`, `npm run lint`, `npm run test` (37 ficheros, 247 pruebas) y `npm run build` en verde tras el merge de 6d8e1ce y la integración del kit.
- Navegador (5177, julio + referencia golden, nota 100):
  - **AP, mapa y lista:**
    - el mapa muestra 305 recibidos, 12 no son factura, 14 duplicados, 18 rechazadas y 19 retenidas;
    - pulsar «Rechazadas» pone `?nodo=ap/reject` y deja 18;
    - el nodo «Duplicado» del sankey deja 14;
    - la faceta Motivo «Destinatario incorrecto» deja 3.
  - **AP, fichas:**
    - `API005229`: la cascada corta en «IBAN frente a la ficha», el dominio `ffiinstalacionesel-es.es` aparece marcado y el PDF abre en `DocumentViewer`;
    - `API004128`: el panel muestra razonamiento, «Asiento 7» y «Golden ✓».
  - **Bancos, mapa:** pulsar «Traspaso en tránsito» deja solo BAE-1100.
  - **Bancos, las 12 cuentas:**
    - ninguna tiene «Sin explicar»;
    - residuos iguales a research: CMA-1000 −5.265,44; BIN-1100 +70.117; BAE-1100 −900.000; CMA-1100 −3.228,89; CMA-1200 −2.644,96; el resto, 0;
    - en CMA-1100 y CMA-1200 el residuo es exactamente la suma de las domiciliaciones que quedan abiertas (ver «Este cambio»);
    - CMA-1100 muestra «Desde BIN-1100: Cuenta bancaria equivocada…».
  - **Bancos, piezas del kit:**
    - `BL0003651` muestra sus registros N43 22/23 en `RawBankRecord`;
    - los ajustes se ven en `JournalEntryView` con nombre de cuenta, socio, asignación y «Cuadrado»;
    - en BANH-3100-USD los ajustes salen en MXN.
  - **Septiembre** (`phase_test`, sin ejecución): las tres rutas muestran «Sin ejecución activa», sin errores.
  - **Consola:** ningún error nuevo. Las únicas entradas son de un recargado en caliente a mitad de edición, con la firma antigua de `unmatchedByCategory` (`view.blocks is not iterable`).

## Sin verificar
- Septiembre con resultados: el backend aún no ha producido ninguna ejecución de `phase_test`.
- `ReasoningView` y `EvidenceList` no se usan dentro de las vistas: los muestra el `ItemPanel` que abre cada ficha o línea, y en las vistas no había tablas locales que sustituyeran.

## Peticiones a la coordinadora
- Ninguna sobre ficheros compartidos.
- Los `wip:` 3823989 y a98507d se quedan como están, como pidió la coordinadora. Los `feat:` de encima cierran cada paquete.
- Nota de vocabulario: `PROBLEM.md` llama N:1 a «una remesa contra varios pagos». La vista usa banco:libro, así que la remesa SEPA sale como 1:N y la nómina en dos lotes como N:1.

## Commits
- `3823989 wip: ap inbox with sankey, faceted list and document ficha`
- `a98507d wip: bank account grid and face-to-face reconciliation with balance bridge`
- `f03d696 docs: record ap and bank status for relay`
- `3b12453 fix: show what each bank category leaves without adjustment, by amount and across accounts`
- `5c9bb73 docs: record bank category fix and browser checks in status`
- `6fc315b Merge branch 'hackathon/frontend' into fe/tasks-ap-bank`
- `8226d9d feat: add ap inbox view with process map, policy cascade and kit document viewer`
- `8b472c5 feat: add bank reconciliation views with process map, kit raw record and journal entries`
- `3ae7fcd docs: report ap and bank status after kit integration`
- `84325ec fix: explain direct debits left without adjustment by their invoice in ap`
