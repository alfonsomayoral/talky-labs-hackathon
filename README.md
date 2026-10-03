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

## Roadmap

[Milestone M0](https://github.com/alfonsomayoral/talky-labs-hackathon/milestone/1):
ingesta, contratos contables, trazabilidad y evaluación reproducible.

[Enunciado y reglas](https://usetalky.com/hackathon/kalmora).
