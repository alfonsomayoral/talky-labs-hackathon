# fe/tasks-ar — 3.B Facturación + 3.C Cobros

Base: `hackathon/frontend` en `94d5948` (kit confirmado). Antes de la PR, fusionado `origin/hackathon/frontend` (`ed15952`) sin conflictos.

## Hecho

### 3.B Facturación (`/tareas/facturacion`)

- `src/features/tasks/ar-billing/ArBillingPage.tsx`:
  - indicadores: base facturada y a cobrar en EUR, facturas por FACe y obra pendiente de certificar;
  - `ProcessMap('ar_billing')`; la rama elegida filtra la lista (`?rama=`);
  - lista agrupada por tipo de contrato con filtros de tipo, sociedad y búsqueda; la ficha va en `?factura=`.
- `InvoicePreview.tsx`: vista previa de la factura junto al PDF recibido (`DocumentViewer`):
  - fecha, vencimiento con sus días, impuesto con su descripción, moneda y los tres DIR3 de FACe;
  - líneas con PEP o centro de coste y cuenta;
  - cascada base → impuesto → total → retención → deducciones (`MX5MILL`, `ADV_AMORT`) → a cobrar, con dos comprobaciones: que las líneas sumen la base y que el importe a cobrar cuadre;
  - en certificaciones, «a origen − anterior»: el anterior es el último acumulado aprobado de `billing_history`, con los meses pendientes que absorbe y el porcentaje del contrato ejecutado;
  - en `SKIP_PENDING_APPROVAL`, aviso y enlace a su fila `WIP_REVENUE` de cierre (`close:WIP_REVENUE/<soc>/<partida>`), o aviso de que falta;
  - asiento de la factura (`JournalEntryView`) y botón «Razonamiento», que abre el panel de partida.
- `billingModel.ts`: `billingListRows`, `invoiceNumber`, `invoiceFigures`, `certificationCalc`, `wipFor` y `billingSummary`.

### 3.C Cobros (`/tareas/cobros`)

- `src/features/tasks/ar-cash/ArCashPage.tsx`:
  - `ProcessMap('ar_cash')`, que filtra la lista (`?rama=`);
  - vaciado de la 55500000 por sociedad: lo que metió el extracto frente a lo que saca el ajuste;
  - lista de abonos con barra de reparto, resultado y diferencias; la ficha va en `?cobro=`.
- `ReceiptDetail.tsx`:
  - barras enfrentadas «Origen» y «Destino», que siempre suman lo mismo. En origen van el abono, la penalidad y la compensación; en destino, facturas, pagarés, duplicado, cedida y no cliente. Lo que no se explica aparece como «Queda en 55500000»;
  - registro crudo del extracto (`RawBankRecord`);
  - partidas abiertas del cliente antes y después del cobro;
  - asiento de ajuste.
- `cashModel.ts`: `allocation`, `suspenseClearing` y `customerOpenItems`. Este último parte de `open_items` más las facturas del mes ya contabilizadas en la fecha del cobro, y aplica antes los cobros anteriores del mes; así el duplicado encuentra su factura ya saldada.

## Verificación

- `npm run typecheck` sale con 0. `npm run lint` sale con 0. `npm run test`: 43 ficheros y 294 tests en verde tras fusionar `ed15952`, 19 de ellos nuevos (`billingModel.test.ts` y `cashModel.test.ts`). `npm run build` termina bien.
- En el navegador, puerto 5175, con julio y la referencia golden:
  - Facturación:
    - 26 partidas, 25 facturas, 1 pendiente;
    - `BILL-CV-OB-2100-2503-202607` en SKIP, con un anterior de 3.297.190,25 (cert. nº 14), un presente de 289.902,73 (WIP) y enlace a Cierre;
    - `BILL-CV-OB-3100-2501-202607` con 5 al millar y anticipo en MXN y las dos comprobaciones en verde;
    - FACe en las facturas a clientes públicos.
  - Cobros:
    - 32 abonos; la 55500000 queda vacía en 1100, 1200, 1300, 2100 y 3100;
    - `BL0000161` con penalidad: dos facturas saldadas y Dr 70590000 por 2.127,95;
    - `BL0000567` con compensación: `EN26-00014` baja de 731.423,86 a 292.569,55;
    - `BL0000808` como duplicado: Cr 43800000 por −702.913,97;
    - `BL0000085` como cedida, sin tocar la 430;
    - la rama «Aplicación parcial» del mapa filtra exactamente `BL0000257`, `495`, `701` y `707`.
  - Consola: sin errores en una pestaña nueva.

## Sin verificar

- Septiembre y ejecuciones que no son golden: solo he probado con la referencia de julio.
- Los pagarés (`BL0000713`) solo existen en septiembre: la barra y la cuenta 43100000 se han probado con tests, no en el navegador.
- Pantallas estrechas (menos de 1180 px): la ficha pasa a una columna, pero no la he revisado a fondo.

## Peticiones a la coordinadora

- Ninguna obligatoria.
- Para Cierre (3.F): la ficha de Facturación enlaza la obra pendiente con `close:WIP_REVENUE/<soc>/<billing_item>` mediante el peek. Conviene que la vista `/tareas/cierre` acepte `?item=` como las demás.

## Commits

- `7b234df feat: add billing view with decision map, invoice preview and certification calc`
- `c35bfd0 feat: add cash application view with suspense clearing, receipt split and customer open items`
