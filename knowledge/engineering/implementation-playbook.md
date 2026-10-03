# Design and Implementation Playbook

A workflow for turning a challenge task into maintainable software compatible with its evaluator.

## 1. Discover before designing

Before proposing an architecture:

- Inspect the actual repository tree, local instructions, and available tooling.
- Identify whether the request concerns analysis, deliverable generation, a rule engine, parser, interface, or evaluator improvement.
- Trace one operation end to end: task → source documents/masters → rule → decision → journal entry → JSONL → evaluation.
- Read the exact output format and scoring code before defining contracts.
- Use `phase_dev` for examples and calibration; distinguish phase-variable data from stable conventions.

At the time this playbook was written, the repository mainly contained challenge data, documentation, and `participant/score.py`; it did not contain a product application. Reconfirm the current state whenever starting a task.

## 2. Model the domain and boundaries

Define explicitly:

- **Input:** phase, closing date, task, source documents, master data, and required history.
- **Output:** one decision object per task key, containing reasons, classification, applications, and/or journal entry as required by the contract.
- **Invariants:** integer cents; balanced entry; local currency; valid keys and dates; coherent partner and cost object.
- **Evidence:** each decision must trace to source documents, ERP fields, policy, or a reproducible calculation.
- **Unknowns:** missing evidence does not become an invented approval, rejection, or adjustment; represent uncertainty as the contract allows.

When building software, keep ingestion, extraction, normalization, policy decisions, journal-entry construction, serialization, and evaluation distinct where that separation helps. Do not impose modules on a small script; preserve boundaries that prevent parsing concerns from changing accounting rules.

## 3. Design a vertical workflow first

For a new task, define one end-to-end case with:

1. An input key and its source document.
2. Required entities and relationships (company, vendor/customer, purchase order, receipt, open item, bank statement).
3. Rule ordering and the first condition that stops or changes the decision.
4. Expected journal entry, including taxes, withholdings, differences, and auxiliary objects.
5. Output structure and how the evaluator compares it.
6. A normal case and policy-derived edge cases.

Prefer pure, deterministic calculations and rules. Isolate OCR/parsing, file access, and heuristics so their effects can be reviewed without changing accounting logic.

## 4. Implement with source data in mind

- Preserve source data; do not overwrite ERP, inbox, tasks, or `golden` files.
- Use integer cents; do not use floating point for accounting amounts. Round per line according to policy.
- Preserve currency, company, and date during conversions; never combine currencies without an applicable rate.
- Validate accounts, partners, cost centers, WBS elements, documents, and bank-line references against the active phase's masters and inputs.
- Emit JSONL with one UTF-8 JSON object per line and keys matching `FORMATO_ENTREGA.md`.
- Keep scenario rules in configuration/data when they vary by company, contract, or phase; do not hardcode a conclusion learned from a single fixture.
- Record provenance and valid reason codes; do not disguise parsing failures as accounting decisions.

## 5. Evaluate the design

Assess the solution for:

- Accounting correctness and rule precedence.
- Coverage of task keys and edge cases.
- Idempotency: regenerating a deliverable does not duplicate effects.
- Traceability from each result to evidence.
- Exact compatibility with the schema and scorer.
- Explicit handling of errors, missing data, duplicates, and phase boundaries.

`phase_dev/golden/` helps explain examples and scoring in the development phase; do not tune heuristics to one answer set. `phase_test/` is the blind evaluation phase. Do not add or run tests unless the user explicitly requests testing or verification; if requested, use available tools and say what they cover.

## 6. Engineering handoff

Summarize:

- Which workflow was designed or implemented and which files it touches.
- Which contracts, policies, and data were consulted.
- Important design decisions and explicit assumptions.
- Checks performed, their results, and what remains outside scope.

Do not describe a plan as implemented or unexecuted work as verified.
