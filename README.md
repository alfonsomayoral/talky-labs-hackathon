# talky-labs-hackathon

Backend para el cierre contable del hackathon Kalmora. Python 3.12 o superior,
sin dependencias de runtime externas. M0 prepara datos, contratos y evaluación;
los motores de AP, AR, bancos y cierre se implementan en milestones posteriores.

## Desarrollo

`backend` es la rama de integración. Cada issue se trabaja en una rama
`codex/<issue>-<descripcion>`, se valida en un PR dirigido a `backend` y se
integra mediante squash. Los hitos revisados se publican en `main` con una release;
el frontend mantiene su rama de integración. CI comprueba `backend`, `main` y
los tags de release.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/kalmora doctor
.venv/bin/python -m unittest discover -s tests -v
```

Los paquetes originales se guardan en `data/`, las entregas e informes en
`outputs/` y las extracciones reutilizables en `.cache/`. Esos directorios se
excluyen de Git. Los datos originales y el scorer del organizador se preservan;
el solver no puede consultar `golden/`.

Registrar una copia de julio con hashes por archivo y mes obtenido de las entradas:

```bash
.venv/bin/kalmora import-package /ruta/participant.zip --destination data/julio
```

El destino debe ser nuevo: cada importación conserva los originales y escribe
`manifest.json`; se omiten los metadatos `__MACOSX`.

```bash
.venv/bin/kalmora inspect data/julio/participant/phase_dev
.venv/bin/kalmora ledger-summary data/julio/participant/phase_dev
```

`PhaseData` ofrece tablas e índices ERP, tareas, mensajes y extractos. El diario
se puede recorrer sin cargarlo completo; los decimales se leen con `Decimal`.
Las búsquedas por clave compuesta conservan sociedad, cuenta, socio y asignación.

Cada comando escribe un informe UUID en `outputs/runs/` con duración, entrada,
estado y código de salida. Se puede elegir otro destino con `--run-dir` antes
del subcomando. Las llamadas LLM futuras registrarán proveedor, modelo, tokens,
caché y tarifas explícitas; si faltan datos, el coste queda desconocido. Las
ejecuciones actuales sin llamadas LLM registran coste cero del programa.

## Entorno local

[Levantar backend, MCP, agente de chat y front](docs/local-setup.md): comandos,
variables de entorno y problemas frecuentes.

## Facturación AR desde soportes originales

`solve-ar-billing` usa por defecto `--engine sources`: lee los cinco tipos de
soporte de M2, conserva los hechos literales con sus citas y los conecta con los
maestros y el motor contable. Los PDF de texto requieren el extra `documents`:

```bash
.venv/bin/python -m pip install -e '.[documents]'
.venv/bin/kalmora solve-ar-billing data/julio/participant/phase_dev \
  --engine sources --mode record --work-dir outputs/m2/state \
  --output outputs/m2/record/ar_billing.jsonl
.venv/bin/kalmora solve-ar-billing data/julio/participant/phase_dev \
  --engine sources --mode replay --work-dir outputs/m2/state \
  --output outputs/m2/replay/ar_billing.jsonl
```

`record` captura la extracción nativa sin llamadas LLM. `replay` reutiliza esas
capturas y vuelve a normalizar y decidir con las entradas actuales; una captura
ausente, alterada o incompatible queda sin resolver. `--work-dir` contiene las
capturas, las evidencias por archivo y `ar-source-report.json`. Solo una fase
completamente resuelta publica `ar_billing.jsonl` y su archivo hermano
`pending_wip.jsonl`; los desconocidos y conflictos bloquean la publicación.
La numeración sigue el orden de tareas y las series derivadas del ERP, con la
misma convención operativa que v0.

El motor previo sigue disponible explícitamente:

```bash
.venv/bin/kalmora solve-ar-billing data/julio/participant/phase_dev \
  --engine v0 --output outputs/m2/v0/ar_billing.jsonl
.venv/bin/kalmora close data/julio/participant/phase_dev \
  --out outputs/m2/close --module ar_billing
```

v0 no admite `--mode replay`. El módulo `ar_billing` del cierre usa el recorrido
de fuentes y guarda sus evidencias en `trace/ar_billing.zip`. El lector nativo
cubre las plantillas de texto suministradas; escaneos y formatos desconocidos
siguen sin resolver. El adaptador LLM es opcional y no se activa automáticamente
desde estos comandos. M2 se cierra funcionalmente por decisión del usuario con
el recorrido de julio y la compatibilidad con v0; la validación completa de M1
sigue en #140. Esto no afirma calidad de proveedores ni un resultado de septiembre.

## Roadmap

[Guía de interfaces y reproducción de M0](docs/m0-backend.md).

[Revisión y validación de la release M0](docs/releases/v0.1.0.md).

[Hotfix v0.1.1: detección general de discrepancias](docs/releases/v0.1.1.md).

[Milestone M0](https://github.com/alfonsomayoral/talky-labs-hackathon/milestone/1):
ingesta, contratos contables, trazabilidad y evaluación reproducible.

[Enunciado y reglas](https://usetalky.com/hackathon/kalmora).
:)
