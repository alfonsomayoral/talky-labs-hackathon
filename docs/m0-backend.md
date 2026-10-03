# M0: interfaces del backend y entrega al compañero

La integración se hace en `backend`, mediante ramas y PRs por issue. Están
implementadas #27–#31, #33–#34 y #36–#38. Los contratos de salida (#32) y el
scorer/comparador (#35) pertenecen a `danielorlando97`. M0 sigue abierto hasta
integrar y validar esas dos capacidades.

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
leer `golden`, ni mediante rutas indirectas. El evaluador tiene acceso separado
a los originales preservados, `golden` y `score.py`. El código de producción de
M0 no implementa el scorer, comparador ni los seis formatos de entrega.

La prueba opcional de integración con el ZIP es una comprobación de la base
contable: el registrado coincide exactamente con `trial_balance_recorded` por
sociedad/cuenta; los 435 grupos golden cuadran. No certifica que los motores
de AP/AR/bancos/cierre estén implementados ni que se cumplan los contratos #32.

[La matriz](coverage.md) distingue reglas previstas, convenciones M0 y evidencia
de julio. [El registro de discrepancias](discrepancies.md) documenta los límites
del scorer y excepciones. En particular, API004469 tiene `partner=null` en 407;
la validación mantiene el socio obligatorio y el comparador debe mostrar la
discrepancia expresamente. No modificar el golden para ocultarla.
