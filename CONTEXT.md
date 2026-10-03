# Dominio contable de Kalmora

Vocabulario canónico para hablar del dominio del reto y mantener consistentes diseño, implementación y entregables. Este archivo define términos; las reglas detalladas viven en las políticas del participante.

## Entidades y documentos

**Sociedad**:
Una entidad jurídica del grupo que contabiliza sus propias operaciones, moneda local, saldos y asientos.
_Evitar_: compañía cuando se pueda confundir con el grupo entero.

**Socio**:
La contraparte asociada a una partida abierta: proveedor, cliente, sociedad del grupo o factor, según la cuenta.
_Evitar_: partner sin explicar qué tipo de contraparte es.

**Documento AP**:
Un documento recibido en el circuito de cuentas a pagar; puede ser factura, abono, solicitud de anticipo u otro aviso que no es factura.
_Evitar_: factura para cualquier archivo de la bandeja.

**Factura**:
Documento que solicita el pago de una operación; en AP debe validarse y en AR respalda el derecho de cobro según prestación, contrato y reglas del caso.
_Evitar_: cobro, pago o asiento como sinónimos de factura.

**Pedido**:
Autorización previa de compra con posiciones, cantidades, precios y condiciones; por sí solo no equivale a recepción ni a factura contabilizada.
_Evitar_: obligación contabilizada.

**Recepción**:
Evidencia de mercancía o servicio recibido. Se contrasta con pedido y factura para confirmar cantidades y conformidad.
_Evitar_: factura o pedido.

**Partida abierta**:
Importe individual pendiente de compensar en una cuenta de cliente, proveedor u otra cuenta auxiliar.
_Evitar_: saldo agregado cuando se necesita identificar factura, vencimiento o asignación.

**Asignación**:
Referencia que vincula una partida con su documento o con el cobro/pago que la compensa.
_Evitar_: conciliación bancaria; son relaciones distintas.

## Contabilidad y cierre

**Asiento**:
Registro atómico de una operación formado por líneas en Debe y Haber cuyo total debe ser igual.
_Evitar_: movimiento de banco si no implica por sí mismo un asiento.

**Devengo**:
Reconocimiento del ingreso o gasto cuando ocurre la prestación o consumo, con independencia del cobro o pago.
_Evitar_: criterio de caja.

**Partida monetaria**:
Derecho u obligación cuyo importe se cobra o paga en una cantidad fija o determinable de moneda; puede requerir valoración de cierre si está en divisa.
_Evitar_: activo no monetario a coste histórico.

**Periodificación**:
Ajuste que asigna al periodo correcto un ingreso o gasto por diferencia entre devengo y facturación, cobro o pago.
_Evitar_: reclasificación de vencimiento.

**Gasto anticipado**:
Pago ya realizado por un servicio que todavía no se ha consumido; el tramo futuro permanece como activo.
_Evitar_: gasto devengado no facturado.

**Gasto devengado no facturado**:
Servicio ya consumido al cierre cuya factura aún no se recibió; se reconoce gasto y obligación estimada.
_Evitar_: gasto anticipado.

**PEP**:
Elemento del proyecto de obra al que se imputan costes/ingresos de construcción cuando así lo exige la política.
_Evitar_: centro de coste para una imputación que debe llevar PEP.

**Centro de coste**:
Objeto de imputación organizativo usado en gastos/ingresos de estructura o servicio cuando no corresponde PEP.
_Evitar_: informar simultáneamente centro de coste y PEP en una línea.

## Operaciones

**Three-way match**:
Control que compara pedido, recepción y factura antes de liberar la factura para pago.
_Evitar_: conciliación de pago con extracto bancario.

**GR/IR**:
Cuenta puente entre bienes/servicios recibidos y facturas recibidas; el reto usa la cuenta `40090000` según su manual.
_Evitar_: gasto final o banco.

**Conciliación bancaria**:
Correspondencia entre líneas del extracto y líneas contables de la cuenta 572, con diferencias clasificadas por causa.
_Evitar_: forzar igualdad mediante asientos sin soporte.

**Residuo de cobro**:
Diferencia entre abono recibido y aplicaciones a documentos, clasificada solo cuando exista causa respaldada.
_Evitar_: ajuste arbitrario para cerrar la cuenta.

**Deterioro**:
Corrección de valor por riesgo de pérdida recuperable; no extingue automáticamente el derecho de cobro.
_Evitar_: baja definitiva o condonación.

**Obra pendiente de certificar (WIP revenue)**:
Obra ejecutada al cierre aún no aprobada/certificada que se trata conforme a la regla específica de cierre del reto.
_Evitar_: factura AR aprobada.
