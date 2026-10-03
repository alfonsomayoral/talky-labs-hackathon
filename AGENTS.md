# Engineering Agent Instructions

## Repository purpose

This repository contains the synthetic Grupo Kalmora month-end close challenge: policies, phase-specific ERP data, inbox documents, tasks, a development reference set (`golden`), and an evaluator. Do not assume a product application already exists. Inspect the current tree before choosing a language, architecture, libraries, or integration points.

## Context to load

Read only what the task needs, in this order:

1. [Knowledge map](knowledge/README.md).
2. [Domain vocabulary](CONTEXT.md).
3. The authoritative source linked from the map: policies, format, tasks, and active-phase master data.
4. Existing code and its contracts; inspect `participant/score.py` for scoring behavior.
5. [Engineering playbook](knowledge/engineering/implementation-playbook.md) when designing or changing software.

## Source precedence

- The user's current request defines the product outcome.
- Repository instructions and evaluator contracts define engineering constraints.
- `participant/POLITICAS_CONTABLES.md` governs accounting decisions in the Kalmora challenge.
- The active phase's `tasks/`, master data, and documents determine the available facts.
- `participant/FORMATO_ENTREGA.md` and `participant/score.py` define the output interface and evaluation.
- `knowledge/reference/course-eight-modules.md` provides general concepts and mental models. It never overrides an explicit challenge policy.

Do not turn a general teaching rule, inference, or course example into a fact from the dataset. When evidence is missing, preserve the unknown and document the decision.

## Working method

For every design or implementation request:

1. **Discover:** identify the phase, task, inputs, outputs, contracts, constraints, existing code, and relevant edge cases.
2. **Model:** express entities, states, invariants, and accounting decisions using [CONTEXT.md](CONTEXT.md). Separate observed facts, explicit rules, and inferences.
3. **Design:** choose the smallest solution that covers the full workflow; define module boundaries, data, and error behavior before coding when they are affected.
4. **Implement:** follow repository conventions, preserve JSONL contracts, use integer cents, and keep traceability to source evidence.
5. **Review:** inspect changes for consistency with the task, policies, and evaluator. Do not add or run tests unless the user explicitly asks to test or verify the implementation.
6. **Deliver:** summarize files and changes, important decisions, checks performed, and concrete limitations.

Work end to end within the authorized scope. Resolve routine choices from the available evidence; ask only about ambiguities that block a correct decision or when an external/destructive action requires authorization.

## Data and phases

- Use `participant/phase_dev/` for development; its `golden/` directory is a reference for the July 2026 phase.
- Use `participant/phase_test/` as the September 2026 evaluation phase; do not assume it contains `golden/` or use hidden data.
- Do not modify source inputs to make a solution easier. Generate deliverables in the destination requested by the user.
- The journal already contains historical transactions. Do not record them again; distinguish pending tasks, existing entries, and necessary adjustments.
