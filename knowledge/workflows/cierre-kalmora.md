# Cierre contable aplicado a Kalmora

Esta guía conecta los conceptos del curso con las tareas del hackathon. El manual del participante manda en todos los casos específicos.

## Reglas de contabilización del proyecto

- Importes en céntimos enteros, moneda local de la sociedad; cantidades en milésimas.
- Cada asiento debe cuadrar entre debe y haber.
- Las cuentas de partidas abiertas llevan socio conforme al manual.
- Gasto, ingreso e inmovilizado llevan centro de coste o PEP, nunca ambos.
- El plan de cuentas y las imputaciones habituales se contrastan con `phase_*/erp/` y el diario histórico.
- La fase dev corresponde a julio de 2026 e incluye `golden`; la fase test corresponde a septiembre de 2026 y no lo incluye.

## AP — Proveedores

Clasifica documentos antes de crear asientos: no todo documento recibido es factura. Para facturas, el orden de decisión es duplicado, rechazo, retención, bloqueo de pago y contabilización. No mezcles el estado de pago con el reconocimiento de la factura.

Con pedido y recepción, el valor recibido se carga a GR/IR (`40090000` en el manual) y las diferencias admitidas se imputan al gasto con el objeto de coste correspondiente. Comprueba IVA deducible/autorrepercutido, retención fiscal, garantía de obra, anticipos y beneficiario del pago. La tabla de reglas está en [POLITICAS_CONTABLES.md §2](../../participant/POLITICAS_CONTABLES.md).

## AR — Clientes y cobros

Factura solo el servicio, certificación o producción respaldado por aprobación/medición/contrato. La obra pendiente de aprobación no se factura; se evalúa para WIP revenue al cierre. Los servicios extraordinarios requieren conformidad, las revisiones de precio siguen fecha de efectos aprobada y la energía sigue medición y contrato.

Los abonos importados se encuentran inicialmente en `55500000`: aplícalos a facturas o pagarés identificados y lleva las diferencias a la categoría documentada. Si la causa de un pago corto es desconocida, deja saldo abierto en vez de inventar una penalidad o descuento. Consulta [POLITICAS_CONTABLES.md §3](../../participant/POLITICAS_CONTABLES.md).

## Conciliación bancaria e intragrupo

Empareja líneas `bank_line` con líneas 572 del diario; puede haber relaciones 1:1 o agrupadas. Clasifica libro y banco por separado y registra ajustes solo para categorías que la política marca como ajustables. El pooling omitido afecta también al saldo intercompany, pero se ajusta desde conciliación bancaria para no duplicarlo.

En intragrupo, concilia cuentas de facturas, pooling, préstamos, intereses y UTE por ambas sociedades. Antes de ajustar, determina si es factura en tránsito, cómputo de días, socio incorrecto, duplicado o pooling no registrado. El interés de KMI-2025-01 es act/360 según la política.

## Asientos de cierre

- **ACCRUAL:** gasto consumido sin factura y sin pedido, estimado con histórico; no periodifiques lo ya recogido en GR/IR.
- **PREPAID:** diferimiento de cobertura futura y reconocimiento mensual de su parte devengada.
- **WIP_REVENUE:** obra ejecutada pendiente de certificación aprobada; contrapartida de ingreso según política.
- **FX_REVAL:** revalora saldos en moneda extranjera al tipo de cierre publicado para el caso.
- **BAD_DEBT:** calcula provisión requerida neta de la anterior solo en saldos elegibles; excluye administraciones e intragrupo conforme al manual.
- **DOUBTFUL_RECLASS:** reclasifica factura a factura en el mes de declaración del concurso.

Fecha de asiento: último día del mes; las reversiones automáticas del día 1 no se entregan. Las cuentas, porcentajes, tolerancias y signos exactos se consultan en [POLITICAS_CONTABLES.md §§4–6](../../participant/POLITICAS_CONTABLES.md).

## Control final

Antes de entregar, comprueba que:

- no haya duplicados entre documentos del mes e histórico;
- las decisiones se apoyen en documentos y maestros reales de la fase;
- las partidas abiertas se apliquen con la asignación correcta y sin forzar diferencias;
- cada asiento esté equilibrado, con sociedad, socio, cuenta y objeto de coste correctos;
- los movimientos bancarios no se contabilicen dos veces;
- las cifras estén en céntimos y fechas ISO (`YYYY-MM-DD`);
- cada JSONL tenga una línea JSON válida por objeto y cumpla el esquema de entrega.
