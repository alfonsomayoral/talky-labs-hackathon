# M4-03 — Revisión semántica con evidencia

## Decisión

La integración compartida de M1 ya está disponible. `review_ar_cash` construye el
resultado determinista y revisa exclusivamente los cobros sin ajuste con un
`SemanticResolver` explícito. No instancia proveedores ni consume presupuesto
por defecto. El llamante puede inyectar LLMSemanticResolver o el resolver de replay
existente; se reutilizan ResolutionRequest/ResolutionResult y validate_resolution.

```python
from kalmora.ar_cash.semantic import review_ar_cash
reviewed = await review_ar_cash(data, resolver=resolver, use_preparsed=True)
# reviewed.run mantiene los contratos JSONL y decisiones contables.
# json.dump(reviewed.reviews, output) conserva las propuestas/abstenciones.
```

## Invariantes

- Candidatos con saldo positivo, sociedad/moneda compatibles, fecha de factura y
  vencimiento disponibles a la fecha del cobro. Cliente compatible si está identificado.
- Las aplicaciones deterministas anteriores reducen los saldos usados en la revisión.
- Máximo configurable de candidatos; al superarlo se abstiene sin llamar al resolver.
- La fuente es la fila literal del JSONL bancario, con ruta relativa y SHA-256 del
  fichero. No se atribuye un resumen generado al original ni se leen PDFs/XML/golden.
- La auditoría guarda fuente, candidatos, contexto, hash de petición, resultado y
  citas de evidencia. Rechaza IDs inventados, evidencia ajena y mutaciones de petición.
- Una asociación semántica no prueba un pago: incluso SELECTED mantiene el asiento
  determinista intacto y `accounting_applied=false`. Las cantidades y residuales
  siguen en el motor contable. El destinatario debe aportar evidencia de aplicación
  suficiente antes de registrar la propuesta como pago.

## Validación

Seis pruebas nuevas: selección con evidencia sin asiento; abstención; moneda,
sociedad y fecha; límites; IDs inventados/mutación; cobros ya resueltos sin llamada;
y consumo previo de saldo (algunos controles comparten caso). Pruebas sin red ni
modelo facturable. El ejemplo de fuente real disponible es el JSONL bancario; la
revisión no finge que existan avisos de aplicación para los cinco pendientes.

Julio sigue con 27/32 cobros exactos y score 0,8922. Esta integración no convierte
las tres combinaciones exactas de BL0000201/BL0000276 en evidencia de un conjunto.
#80 permanece abierto por esas aplicaciones sin soporte y las partidas/referencias
que faltan para BL0000544/BL0000707. El bloqueo ya no es la integración del resolver.
