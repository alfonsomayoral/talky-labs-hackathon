# Engineering Agent Context

Use this knowledge base as a context map for designing and implementing accounting automation for the challenge. Start with the specific task; do not load every document if one authoritative source is enough.

## Navigate by task

| If you need to… | Read first |
|---|---|
| Understand domain terms and boundaries | [CONTEXT.md](../CONTEXT.md) |
| Design or implement a solution | [Engineering playbook](engineering/implementation-playbook.md) |
| Understand course principles and mental models | [Eight course modules](reference/course-eight-modules.md) |
| Resolve one of Kalmora's six tasks | [Kalmora close workflows](workflows/kalmora-close-workflows.md) and the relevant policy section |
| Parse phase inputs (sources, formats, parsing, accounting content) | [Data sources reference](reference/data-sources.html) |
| Load phase inputs into a normalized landing database | [Landing DB proposal](reference/landing-db.html) · [DDL](reference/landing-db.sql) |
| Generate deliverable files | [Delivery format](../participant/FORMATO_ENTREGA.md) |
| Understand companies, phases, or data layout | [Participant README](../participant/README.md) |
| Check scoring compatibility | `participant/score.py` and `participant/phase_dev/golden/` |

## Source authority

1. The user's request defines the change outcome.
2. Task schemas and `participant/score.py` define interfaces and evaluation.
3. `participant/POLITICAS_CONTABLES.md` defines accounting rules for the scenario.
4. Active-phase source data provides facts and evidence.
5. `reference/course-eight-modules.md` provides general concepts only.

When sources conflict, do not blend the rules or average their outcomes. Follow the higher-authority source, explain the discrepancy, and avoid inventing missing facts.

## Curated context

- [Course reference](reference/course-eight-modules.md) summarizes all eight modules read from the course site.
- [Kalmora workflows](workflows/kalmora-close-workflows.md) condenses the challenge tasks, dependencies, and controls.
- `CONTEXT.md` contains domain vocabulary; keep it concise and free of implementation decisions.

Do not duplicate the participant manual, JSONL schemas, ERP masters, or phase data here. Link to the source of truth instead.
