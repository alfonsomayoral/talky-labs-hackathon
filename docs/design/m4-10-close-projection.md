# M4-10 — Publicar saldos de cobros para cierre

## Pregunta y decisión

¿Cómo consumir cobros y conciliación sin volver a contabilizar el histórico ni
ocultar los cobros pendientes? Publicar una proyección independiente del libro
registrado, con los ajustes de M3 y M4 y cobertura explícita. No es el cierre
completo: AP, facturación, IC y ajustes de cierre tienen sus propios propietarios.

## Contrato

`ar_cash.journal_entries(data, run)` convierte cada ajuste una sola vez y conserva
sociedad, cuenta, tercero, asignación e importes enteros. Su propietario es
`(bank_line, cash_application)`. El importador bancario conserva `bank_import`.
No vuelve a interpretar aplicaciones ni residuales: el asiento ya contiene las
cuentas 430/431, 438, 553, 565, 470, 759 o 7059 que correspondan.

`ar_cash.projection.project_cash(data, cash, bank)` publica `recorded` y `projected`
como libros independientes. Exige cobertura exacta de tasks/ar_receipts; toma el
histórico hasta el mes de cierre, añade los ajustes validados de M3 y M4 y conserva
los cobros sin ajuste en `unresolved`. Repetir un propietario falla, incluso tras
restaurar la proyección. `projection_report` expone por sociedad y cuenta, y por
partida abierta, saldo registrado, ajuste y saldo proyectado; también los asientos.
565 se publica en saldos de cuenta, no como partida abierta según contrato Ledger.

Los importes son céntimos locales. Una cuenta bancaria de moneda distinta de la
local se rechaza expresamente: esta interfaz no inventa una conversión FX.

## Reproducción

Desde el repositorio, con PHASE apuntando al phase_dev real (no al golden):

```sh
KALMORA_PHASE_DEV="$PHASE" PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -q
PYTHONPATH=src python -m kalmora project-ar-cash "$PHASE" --use-preparsed --output /tmp/m4-projection.json
```

Se consultan snapshots normalizados mediante DocumentRouter; no se parsean PDFs/XML
del inbox. La conciliación conserva su lector bancario existente. Los outputs se
escriben atómicamente fuera de la fase y del golden.

## Validación y límites

35 pruebas AR Cash superadas, incluyendo seis nuevas de proyección. La prueba
real verifica separación del histórico, rechazo de replay de todos los ajustes,
identidad del balance y BL0000706: Dr572/Cr555 por 51.496.121 céntimos una vez y
Dr555/Cr430 una vez. La aplicación conserva el resto de un pago parcial.

Julio publica cinco pendientes: BL0000201, BL0000276, BL0000544, BL0000567,
BL0000707; `complete=false`. Mantener esos importes pendientes es parte del
contrato de publicación, no una afirmación de conciliación completa. Se conservan
diagnósticos por cobro y del run. No se modifica ninguna fuente ni se lee golden
para decidir aplicaciones. Los bloqueos funcionales siguen en #80 y #82.
