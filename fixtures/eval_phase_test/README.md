# Golden previsto de septiembre (`phase_test`)

**No es el golden oficial.** Es la salida de la cadena de prototipos del research sobre `phase_test`: cada tarea usa la salida real de la anterior (AP → facturación → cobros → bancos → intragrupo → cierre) y se escribe con el formato de `phase_dev/golden/`.

La misma cadena sobre julio, sin consultar el golden, saca **98,78/100** con `score.py`.

## Puntuar una ejecución de septiembre

```bash
python score.py fixtures/eval_phase_test participant/phase_test <carpeta_con_los_6_jsonl>
```

`score.py` lee `<evaluador>/golden/`; por eso el golden vive aquí y no dentro de `phase_test/`, que sigue sin golden.

## Qué fiabilidad tiene

- Una nota alta significa que coincide con los prototipos, no que sea correcta.
- Lo más débil:
  - importes de `ACCRUAL` en el cierre: son estimaciones, porque el golden real usa facturas de octubre;
  - factura intragrupo en tránsito: solo se marca 1000→1200;
  - cobros con empate de facturas y el duplicado de un pago parcial (BL0000809).
- No se pueden deducir de los datos: ids y fecha de contabilización de los asientos, el registro FACe (`null`) y `tagged` de `summary.json` (aproximado).
- El ejemplo `API005263` de `FORMATO_ENTREGA.md` está alterado a propósito (proveedor y PEP); aquí va en `HOLD` por cambio de cuenta.
