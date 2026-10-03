# Revisión de evidencias ACCRUAL

Fecha: 2026-10-03. Revisión de fuentes de julio en `data/julio/participant/phase_dev/`. No se ha consultado `golden/close.jsonl`, modificado el solver ni ejecutado el motor/evaluador completos. Los identificadores señalados por evaluación se han utilizado únicamente para localizar documentos y asientos originales.

## Conclusión

Hay una mejora general demostrable: separar republicaciones de una misma estimación histórica de obligaciones distintas. El agente principal ya ha incorporado esta corrección en `tools/m6_sources.py:80`: conservar el último cierre por referencia y periodo, después sumar referencias independientes del mismo periodo. No existe evidencia positiva suficiente para crear los dos devengos ausentes de julio ni para excluir automáticamente la representación de mercado solo porque su devengo empeore la comparación.

La política requiere consumo sin factura, no solamente un proveedor conocido (`POLITICAS_CONTABLES.md:150`). El histórico puede estimar el importe una vez aceptada la existencia de consumo, pero no convierte cualquier compra antigua en consumo actual. La tolerancia del 15 % tampoco autoriza cambiar importes o activar proveedores para coincidir con una referencia (`POLITICAS_CONTABLES.md:151`).

## Dos series sin evidencia actual suficiente

### Consultoría 1000 / V100125

Hechos observados:

- Ficha en `erp/vendors.jsonl:125`: `PROF_CORP`, sin pedido, cuenta de gasto 62300000.
- Último devengo original: `erp/journal_entries.jsonl:33070`, asiento `1000-2026-1000000123`, cierre 31/05/2026, periodo completo de mayo, 3.438.739 céntimos, CC-1000-DIR.
- Su factura `API004005` fue recibida el 04/06 y contabilizada el 05/06 (`erp/ap_invoices.jsonl:3885`; asiento original en `erp/journal_entries.jsonl:33597`). Ya no es consumo pendiente de facturar.
- No se encontró factura de este proveedor entre las entregas AP de julio, ni devengo original del 30/06/2026.
- El histórico completo contiene diez meses con este servicio, con varios huecos largos: entre diciembre de 2025 y mayo de 2026 no hay otro devengo. Los importes registrados oscilan entre 1.043.397 y 4.192.373 céntimos.

Desconocido: si hubo una nueva prestación en julio y cuál fue su importe. Un único mes dentro de la ventana reciente no demuestra consumo mensual continuado. Ampliar la ventana para recuperar meses antiguos no resuelve este desconocido.

### Material de oficina 1200 / V100147

Hechos observados:

- Ficha en `erp/vendors.jsonl:147`: `OFFICE`, sin pedido, gasto 62900000.
- Último devengo original: `erp/journal_entries.jsonl:33158`, asiento `1200-2026-1000000202`, periodo completo de mayo, 216.592 céntimos, CC-1200-ADM.
- Factura `API004027` recibida el 08/06, contabilizada el 09/06 (`erp/ap_invoices.jsonl:3907`; diario `erp/journal_entries.jsonl:33818`).
- No se encontró factura AP recibida en julio para esta sociedad/proveedor ni devengo al 30/06.
- Hay quince meses con compra en el histórico completo, con huecos. Los cuatro últimos importes observados son 104.214 (enero), 214.210 (febrero), 43.427 (marzo) y 216.592 (mayo). No constituyen un canon estable.

Desconocido: si se consumió material adicional en julio. Mantener esta ausencia documentada es más defendible que crear un mes de gasto desde una compra anterior ya facturada.

## Representación de mercado 1300 / V100173

Hechos observados:

- Ficha `erp/vendors.jsonl:173`: sin pedido, `MARKET_REP_FEE`, gasto 62300000.
- La factura original `inbox/ap/API004299/factura_26012023.pdf`, página 1, indica periodo 01/06/2026–30/06/2026 y servicio de representación y gestión de desvíos de junio. Su base es 6.850 EUR por un mes. Se recibió el 02/07 (`inbox/ap/API004299/message.json:4`).
- La liquidación `inbox/ar/billing/BILL-MKT-1300-01-202606/documento.pdf`, página 1, también corresponde a junio. Indica que los honorarios se facturan aparte y se compensan en el pago.
- `item.json:7` identifica julio como mes de la tarea; esto no cambia junio como periodo económico de la liquidación.
- `erp/ap_invoices.jsonl` contiene veinte facturas mensuales consecutivas, de octubre de 2024 a mayo de 2026, todas de 685.000 céntimos. No hay asientos `CLOSE_ACCRUAL` de este proveedor en el diario original.
- El contrato de ventas `erp/sales_contracts.jsonl:83` tiene vigencia hasta 2030. No incluye una cláusula de precio/obligación AP que pruebe honorarios de julio.
- La política define la compensación de honorarios del representante (`POLITICAS_CONTABLES.md:113`), pero no establece una excepción explícita al devengo de este servicio.

Inferencia admisible: la secuencia mensual continuada respalda que el servicio probablemente continúe. Si se decide devengar julio, esa recurrencia debe constar como supuesto y la cuantía como estimación. No es un hecho documental de julio.

Inferencia no demostrada: cero devengos históricos no prueba ausencia de consumo ni una exclusión contable. Tampoco el silencio de la enumeración de servicios en §5 justifica una lista de exclusión por `archetype`. No recomiendo eliminar el ajuste únicamente para obtener mayor score. La discrepancia se debe conservar o someter a aclaración del organizador.

## Corrección general de identidad histórica

El diario puede republicar una obligación pendiente en dos cierres. Ejemplo: `ACCR-API003793`, periodo de abril, importe 485.791 céntimos, aparece al 30/04 (`erp/journal_entries.jsonl:30859`) y 31/05 (`:33069`). Ambos cierres representan la misma exposición, con retrocesión intermedia; no dos servicios independientes.

También ocurre con `ACCR-API003695`, periodo marzo–abril: `erp/journal_entries.jsonl:30906` y `:33097`, con los mismos componentes. Se deben sumar las líneas de gasto de cada asiento por cuenta/objeto, pero conservar una sola muestra por referencia y periodo. Las referencias distintas del mismo periodo sí son aditivas.

Esta corrección tiene evidencia causal independiente de golden. Su impacto en score debe medirse solamente después de congelar la nueva salida, como está haciendo el agente principal.

## Trabajo recomendado

- Mantener los controles contra extrapolar compras/profesionales aislados sin consumo actual.
- Conservar los límites de evidencia y los supuestos de recurrencia en diagnósticos y decisiones de cierre.
- Para mejorar cobertura sin inventar consumo, obtener evidencia positiva del mes: prestación aceptada, contrato con obligación mensual vigente, suministro actual medido o comunicación de gasto incurrido pendiente de factura.
- No variar la mediana, crear proveedores concretos o excluir representación para encajar con objetivos observados en evaluación.

Comprobaciones de esta revisión: lectura estructurada de fichas, histórico AP y diario completo; extracción de texto de las dos páginas PDF originales mediante `DocumentRouter` y el Python del runtime; inspección de las decisiones/facts ya generadas. No se han ejecutado pruebas del solver ni cambiado entradas.
