<<<<<<< HEAD
# talky-labs-hackathon

Backend para el cierre contable del hackathon Kalmora. Python 3.12 o superior,
sin dependencias de runtime externas. M0 prepara datos, contratos y evaluación;
los motores de AP, AR, bancos y cierre se implementan en milestones posteriores.

## Desarrollo

`backend` es la rama de integración. Cada issue se trabaja en una rama
`codex/<issue>-<descripcion>`, se valida en un PR dirigido a `backend` y se
integra mediante squash. `main` y el trabajo de frontend siguen su propio flujo.

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

## Roadmap

[Milestone M0](https://github.com/alfonsomayoral/talky-labs-hackathon/milestone/1):
ingesta, contratos contables, trazabilidad y evaluación reproducible.

[Enunciado y reglas](https://usetalky.com/hackathon/kalmora).
=======
# Talky Labs Accounting Challenge

This repository contains the synthetic Grupo Kalmora month-end close challenge: accounting policies, phase-specific ERP data, source documents, task definitions, a development answer set, and a scorer. It is primarily a data challenge repository; inspect the current tree before assuming there is an application to extend.

## For coding agents

- Start with [AGENTS.md](AGENTS.md) for repository-specific engineering instructions.
- Use [CONTEXT.md](CONTEXT.md) for canonical domain language.
- Use the [knowledge map](knowledge/README.md) to load only the context needed for the task.

## Authoritative challenge material

- [Scenario and phase layout](participant/README.md)
- [Accounting policies](participant/POLITICAS_CONTABLES.md)
- [JSONL delivery contract](participant/FORMATO_ENTREGA.md)
- `participant/score.py` and `participant/phase_dev/golden/` for the development evaluator and reference results.

Challenge data and policy rules are synthetic. For each accounting decision, use the active phase's source documents and challenge policies rather than treating general course notes as controlling rules.
>>>>>>> main
