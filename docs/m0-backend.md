# M0: interfaces del backend y entrega al compañero

La integración se hace en `backend`, mediante ramas y PRs por issue. Están
implementadas #27–#31, #33–#34, #35 y #36–#38. El #32 (contratos de salida) se
depreca: el formato lo fija `FORMATO_ENTREGA.md` y los tipos de fila están en
`kalmora.output_models`. El comparador (#35) está en `kalmora.evaluation` y se
describe en [docs/design/comparator.md](design/comparator.md).

## Reproducción de julio

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/kalmora doctor
.venv/bin/kalmora import-package /ruta/participant.zip --destination data/julio
.venv/bin/kalmora inspect data/julio/participant/phase_dev
.venv/bin/kalmora ledger-summary data/julio/participant/phase_dev
KALMORA_PARTICIPANT_ZIP=/ruta/participant.zip .venv/bin/python -m unittest discover -s tests -v
```

La importación requiere un destino nuevo. Si ya está registrado, ejecutar
directamente `inspect` y `ledger-summary`. `manifest.json` contiene hashes de
los originales, del ZIP y las fases/meses descubiertos. El paquete de julio
tiene 830 archivos útiles, 7 sociedades, 36.743 asientos y 305 mensajes AP.
Los 1.062 movimientos bancarios incluyen los distintos meses suministrados.

Cada ejecución escribe un informe UUID en `outputs/runs/`. `--run-dir` se
coloca antes del subcomando. Registra entradas, duración, estado y código de
salida; un comando fallido conserva su informe. El coste cero actual corresponde
a ejecuciones del programa sin llamadas LLM.

## Datos y estado contable

```python
from pathlib import Path
from kalmora.data import PhaseData
from kalmora.ledger import Ledger
from kalmora.money import RateTable
from kalmora.validation import validate_entry

data = PhaseData(Path("data/julio/participant/phase_dev"))
recorded = Ledger.from_entries(data.iter_journal())
projected = recorded.project()
balances = recorded.balances()  # {(sociedad, cuenta): debe - haber}
open_items = recorded.open_items()  # {(sociedad, cuenta, socio, asignación): saldo}
rates = RateTable(data.table("fx_rates"))
```

`PhaseData.table` mantiene la forma original JSON; `get` y `find` proporcionan
índices y búsquedas. El diario se recorre en streaming. Los lectores conservan
los enteros y usan `Decimal` para fracciones; rechazan NaN/Infinity. Las claves
compuestas de partidas abiertas incluyen las cuatro dimensiones anteriores.
El libro conserva los grupos originales y referencias `id_asiento#line`.
Sus entradas públicas son copias; las proyecciones no modifican el registrado.

Los saldos están en moneda local, en céntimos enteros. Se conservan los campos
originales de moneda documental y `amount_doc` en las líneas; las necesidades
de detalle FX se consultan en las entradas originales. `RateTable` usa unidades
de divisa por EUR, el último tipo disponible hasta la fecha y redondeo por línea.
La moneda local es MXN en 3100 y EUR en las otras seis sociedades del paquete.
Las cantidades están en milésimas; PPA admite truncamiento explícito.

`validate_entry(entry, context=None)` devuelve diagnósticos. El contexto opcional
aporta registros de `companies`, `accounts`, `partners`, `cost_centers`, `wbs`
y límites `min_date`/`max_date`. Los registros de objetos de coste pueden incluir
la sociedad propietaria. Las comprobaciones de existencia requieren esos
maestros; los contratos de salida añaden los campos obligatorios de cada tarea.

Después de validar con los maestros necesarios, insertar un ajuste con
`projected.add_entry(entry, event_id="identificador estable", stage="etapa")`.
La inserción comprueba invariantes contables y conserva la procedencia. Repetir
el mismo evento/etapa falla, también al reconstruir desde entradas guardadas.
`bank_import` y `cash_application` son etapas distintas del mismo cobro: la
primera registra Dr 572 / Cr 555; la segunda aplica Dr 555 / Cr 430.

## Evidencia documental y métricas

`DocumentFacts(sha256, extractor_version, fields)` contiene listas de
`Fact(value, Evidence(document, field, page=None, quote=None))` por campo.
Conservar candidatos contradictorios y evidencia de cada adjunto.
`FactsCache(directory).load(source_bytes, version, config)` devuelve hechos o
`None`; `.store(source_bytes, facts, config)` escribe atómicamente. Cambiar
bytes, versión o configuración invalida la clave. La caché conserva los
`Decimal`, su escala y valores anidados. Los extractores PDF/XML son M1/M2.

`RunRecorder(output_dir, command, input_metadata)` funciona como contexto.
El evaluador puede pasar hash de paquete, fase y mes en `input_metadata`.
`record_call(provider, model, input_tokens, output_tokens, pricing, usage)`
registra llamadas reales; `record_cache_hit()` registra reutilización. Las
tarifas incluyen `input_rate`, `output_rate`, `unit="per_token"`, `currency`
y `provenance`. Si falta uso o tarifa, el coste queda desconocido. Los totales
de distintas monedas se mantienen separados. El recorder no llama proveedores.

## Acuerdo con contratos y evaluación

Los módulos de solver leen ERP, tareas, banco e inbox con `PhaseData`; no pueden
leer `golden`, ni mediante rutas indirectas. El evaluador (`kalmora.evaluation`)
tiene acceso separado a los originales preservados, `golden` y `score.py`; ningún
módulo del solver lo importa (`kalmora evaluate` informa de cualquier violación).
`kalmora.output_models` solo describe la forma de una fila de cada fichero de entrega.

La prueba opcional de integración con el ZIP es una comprobación de la base
contable: el registrado coincide exactamente con `trial_balance_recorded` por
sociedad/cuenta; los 435 grupos golden cuadran. No certifica que los motores
de AP/AR/bancos/cierre estén implementados.

[La matriz](coverage.md) distingue reglas previstas, convenciones M0 y evidencia
de julio. [El registro de discrepancias](discrepancies.md) documenta los límites
del scorer y excepciones. En particular, API004469 tiene `partner=null` en 407;
la validación mantiene el socio obligatorio y el comparador muestra la
discrepancia aplicando la regla general a los datos de referencia
(`REFERENCE_ENTRY_RULE`). La entrega conserva su propio diagnóstico `ENTRY_RULE`
si también incumple la regla. No hay excepciones por ID ni por mes, y no se
modifica el golden para ocultar discrepancias.

## Evaluación contra el golden

```bash
.venv/bin/kalmora evaluate data/julio/participant/phase_dev ENTREGA \
    --evaluator data/julio/participant/phase_dev --text
```

`--evaluator` es la fase que contiene `golden/`; sin él solo se puede usar
`--structure-only` (comprueba la entrega sin golden). `phase_test` no tiene golden:
el comando se niega a puntuar. El scorer se carga de `<paquete>/participant/score.py`
y se verifica contra `manifest.json`. La nota por módulo y el total son exactamente
los de `score.py`; el informe JSON (`outputs/evaluations/<uuid>.json`) añade, por
entidad, el estado, las diferencias tipadas y las diferencias en campos que el scorer
no puntúa (`unscored`), más diagnósticos de la entrega y un bloque de conciliación
por módulo. Un fallo de conciliación o una violación de frontera devuelve código 1.

El comparador valida campos obligatorios, tipos y enums con los tipos de fila
existentes antes de puntuar; no convierte floats ni booleanos a céntimos.
`--structure-only` conserva los errores en el informe y devuelve código 1 si el
formato es inválido. Las filas JSONL que no son objetos producen un error con
archivo y línea. Las líneas de ajustes llevan sociedad explícita. La evaluación
requiere el manifiesto del paquete registrado y rechaza un scorer modificado.
Los datos originales y los importes de las notas del scorer se mantienen intactos.

Referencias medidas en julio: el golden usado como entrega da 100,0 en todos los
módulos; una entrega vacía da 3,54 (el scorer da 0,2359 a `ar_cash` vacío).
