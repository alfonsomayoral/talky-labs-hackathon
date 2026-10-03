# fe/tasks-ic-close — 3.E Intragrupo + 3.F Cierre y balance

## Hecho

### 3.E Intragrupo (`/tareas/intragrupo`)

- `src/features/tasks/ic/model.ts` (funciones puras, 6 tests en `model.test.ts`):
  - `icMatrix`: parejas de `tasks/intercompany.json` con sus diferencias y Σ|diferencia| en EUR (`itemEurCents`).
  - `pairBooks`: movimientos del mes de las dos sociedades en las cuentas intragrupo, con la otra como socio (`1000` o `V-IC1000`). Añade los apuntes que replican uno de la otra parte (misma referencia e importe) con otro socio y los marca `wrongPartner`. Deja fuera las valoraciones `CLOSE_FX` y sus retrocesiones. Las líneas EUR de 3100 se valoran por `amount_doc`.
  - `interestCheck`: intereses de `KMI-2025-01` con act/360 (`loanInterest` del kit) frente a 30/360, y lo que registró cada parte con la referencia `KMI-INT-<mes>`.
- `src/features/tasks/ic/IcPage.tsx`:
  - `ProcessMap('ic')` con `?nodo=`.
  - Matriz sociedad × sociedad: cada pareja con su número de diferencias y su importe en EUR, o «Cuadra».
  - Lista de diferencias, que abre la partida en el panel.
  - Ficha de la pareja (`?pareja=`): causa y detalle, asiento corrector con `JournalEntryView` o la nota cuando va sin ajuste. En `INTEREST_DAY_COUNT`, el cálculo act/360 con lo que registró cada parte. Debajo, los dos libros del mes con el neto por cuenta.

### 3.F Cierre (`/tareas/cierre`)

- `src/features/tasks/close/model.ts` (funciones puras, 9 tests en `model.test.ts`):
  - `closeRowsOf` (filas entregadas de una partida; agrupa los tramos de ACCRUAL).
  - `vendorHistory` (neto facturado por mes en los 12 meses anteriores, sin abonos, y media de los meses con factura).
  - `prepaidFraction` (`(k/n)` de la cabecera del asiento).
  - `fxBreakdown` y `fxTarget` (divisa × tipo de cierre, valor contable = valor − importe).
  - `agingOf` (antigüedad sobre las partidas abiertas de 43000000 con umbrales estrictos > 180 y > 365, `floor` al 50 %; con concurso, 100 % incluidas 43600000 y 43000900). Da 1.263.240 en C200076, igual que el golden.
- `src/features/tasks/close/ClosePage.tsx`:
  - `ProcessMap('close')` con `?nodo=` y pestañas por tipo (`?tipo=`). Sin `tipo`, abre la pestaña de la partida de `?item=`, para que el enlace de Facturación a la obra pendiente la muestre resaltada.
  - Periodificaciones: proveedor, sparkline del histórico, media mensual, importe periodificado, veces la media, tramos y «A revisar».
  - Gastos anticipados: diferimiento o imputación y calendario k/n de la cobertura. El proveedor de las facturas del mes sale de la partida AP.
  - Valoración en divisa: importe en divisa, tipo de cierre, valor a cierre, valor contable y valoración, en la moneda de la sociedad (MXN en 3100).
  - Deterioro: tramos de antigüedad, factura a factura, y provisión necesaria, anterior y dotación.
  - Obra pendiente y reclasificación: lista simple con enlace al documento.

### Balance de sumas y saldos (`/balance`)

- `src/features/ledger/model.ts` (funciones puras, 6 tests en `model.test.ts`):
  - `gapWaterfall`: hueco en EUR sumando las tareas en el orden de `PIPELINE`. Los tramos suman registrado − después; el test fija que el hueco no es aditivo.
  - `heatMap`: Σ|valor| en EUR por sociedad y grupo del plan, para hueco después, hueco antes o movimiento.
  - `relevantRows`, `remainingDiff`.
- `src/features/ledger/LedgerPage.tsx`:
  - Indicadores: hueco registrado y después en EUR, % cerrado y nota del scorer.
  - Cascada del hueco cerrado por tarea.
  - Mapa de calor sociedad × grupo, con selector de medida (`?medida=`) y filtro por celda (`?celda=`).
  - Tabla registrado / entrega / después / correcto / diferencia en moneda local, que abre `/datos/cuentas/:cuenta`.
  - Sin golden, muestra solo el movimiento. Con el golden de referencia (hueco después 0), el mapa abre en «Hueco antes».

## Verificación

- Tras `git merge origin/hackathon/frontend`, sin `KALMORA_DEV_PHASE`: `typecheck` y `lint` sin errores, `test` con `Test Files 46 passed (46)` y `Tests 315 passed (315)`, y `build` correcto.
- En el navegador (puerto 5176), con julio y la referencia golden, cero errores en consola en `/balance`, `/tareas/intragrupo` y `/tareas/cierre` con sus parámetros:
  - Puerta 3, intragrupo: en `?pareja=1000-3100`, el prestamista registró 25.833,33 € y el prestatario 25.000,00 € (marcado «≠ act/360»). La diferencia es +833,33 € y el asiento corrector de 3100 es de 15.750,27 MXN.
  - Socio equivocado: `CP2607281100` sale en el libro de 1100 con «socio 1200». La diferencia de los netos es −144.158,89 €.
  - Puerta 3, cierre: `FX_REVAL GL:16330000` de 3100 (5.000.000 € × 18,900400, valor contable 100.495.500 MXN) da −5.993.500,00 MXN y está «A revisar».
  - Periodificaciones: 45 partidas con histórico.
  - Deterioro de C200076: provisión necesaria 12.632,40 €.
  - Anticipados: calendario 7/12, 4/12, 2/12, 1/12 y 1/6.
  - `?item=close:WIP_REVENUE/2100/BILL-CV-OB-2100-2503-202607` abre la pestaña de obra pendiente con la fila resaltada y el panel abierto.
  - Balance: la cascada va de 69,8 M€ a 0 € y suma por tareas (AP +20,3 M€, facturación +15,6 M€, bancos +1,2 M€, cobros +29,3 M€, intragrupo +382 k€, cierre +3,1 M€). El filtro por celda funciona.

## Sin verificar

- Con una ejecución real del agente o con `phase_test`: solo con la referencia golden de julio. En particular, la cascada con hueco restante, la marca de diferencias de la tabla del balance y los estados sin `foreign`/`rate` en `FX_REVAL` o sin `target`/`previous` en `BAD_DEBT`.
- La antigüedad del deterioro usa `open_items.jsonl` del maestro tal cual. No descuenta los cobros del mes que aplica AR cash.

## Peticiones a la coordinadora

- Ninguna sobre ficheros compartidos.

## Commits

- `f10dc5c feat: add trial balance page with gap waterfall, heat map and account table`
- `8491c49 feat: add intercompany view with pair matrix, both books and loan interest check`
- `0a62b5c feat: add close view with accrual history, prepaid calendar, FX breakdown and debt aging`
- `781b88c fix: open the close tab of the item in the URL`
- Merge de `origin/hackathon/frontend` sin conflictos.
