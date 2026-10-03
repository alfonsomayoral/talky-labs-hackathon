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
