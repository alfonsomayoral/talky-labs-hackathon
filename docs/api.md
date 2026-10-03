# Read API for the front end and an MCP agent: design record

Working record. Questions are written before they are researched; decisions are appended under each question. Status: **revised after alignment with the user (see "Revision 1"); awaiting approval to implement**. Nothing in `src/` has been changed.

Goal (from the request): decide which API can be derived from the information and models we already have, to serve (a) a front end and (b) an agent, possibly through MCP.

## Known facts (observed, not decided)

- Python >= 3.12, **zero runtime dependencies** (`pyproject.toml`), CLI-only entry point (`kalmora`), no server code.
- Models are `TypedDict`/`NamedTuple` in `kalmora.model` (ERP shapes) and `kalmora.output_models` (six delivery rows). Plain JSON, integer cents, `Decimal` only for FX rates and costs.
- Readers that exist: `PhaseData` (phase tables, `iter_journal`), `Ledger` (`balances`, `open_items`, `project`, `add_entry` with `(event_id, stage)` idempotency), `validation.validate_entry` (returns diagnostics), `RunRecorder` (`outputs/runs/<uuid>.json`), `evaluation` package (comparator; only reader of golden, see ADR 0001), `register_package` (manifest).
- Solver engines for M1-M6 do not exist yet; `output_models` are types only. Delivery is six JSONL files per phase, one submission, no resubmission (M7-09).
- `phase_dev` is July 2026 with golden; `phase_test` is September 2026 and has no golden. The solver must never read golden.
- Data scale in `phase_dev`: about 36.7k journal entries, 21.7k goods receipts, 2.4k FX rates, 305 AP documents, 12 bank accounts.

## Questions

### Q1. Who are the consumers and what jobs does each need?
*Why it matters:* the front end (people reviewing a close) and an agent (automated reasoning and tool calls) have different needs; one API shape may not serve both.
*Owner:* product (user). *Acceptance:* a list of consumer jobs, each traceable to data we already have.

### Q2. Which resources can be exposed from existing data, and which are not available yet?
*Why it matters:* avoids designing endpoints for data M1-M6 have not produced.
*Acceptance:* every resource maps to a model or reader; unavailable ones are marked with the milestone that unblocks them.

### Q3. Read-only or also able to trigger actions (run engines, post adjustments, submit)?
*Why it matters:* delivery is a single irreversible submission; an agent able to write is a risk surface.
*Acceptance:* a stated write policy with the guards for each action.

### Q4. What transport and protocol for the front end?
*Why it matters:* zero-dependency constraint, typed models, and a front end that needs a stable contract.
*Acceptance:* a choice with the dependency cost, and how the contract (schema) is published.

### Q5. How does an agent consume it: MCP server, plain HTTP tool calls, or both?
*Why it matters:* MCP has its own primitives (tools, resources, prompts) and transports; duplicating logic across two surfaces is a maintenance cost.
*Acceptance:* a choice grounded in the current MCP specification, with the mapping of our resources to MCP primitives.

### Q6. How are the two surfaces kept from diverging?
*Why it matters:* one source of truth for operations, schemas and errors.
*Acceptance:* a single service layer both surfaces call; schemas generated from the existing types.

### Q7. How is the golden boundary enforced through an API?
*Why it matters:* ADR 0001 says solver code cannot read golden; an API for the agent must not leak it (evaluation results are fine, raw golden is not).
*Acceptance:* a rule for which resources are solver-side and which evaluator-side, and how a client is prevented from crossing.

### Q8. How is money, identity and pagination represented over the wire?
*Why it matters:* integer cents must not become floats in JSON; journal is large; keys (`OpenItemKey`, `book_line`) are composite.
*Acceptance:* conventions for amounts, ids, cursors and filters, with the size limits that apply to agent context.

### Q9. How is provenance and auditability exposed?
*Why it matters:* every adjustment has `(event_id, stage)`, run reports hold cost and status, and the manifest holds hashes; the front end and agent need to cite evidence.
*Acceptance:* each answer carries the identifiers needed to trace it back to a source file or run.

### Q10. Security: authentication, authorization and exposure.
*Why it matters:* the data is synthetic but the pattern must hold; MCP over HTTP has specific requirements (origin checks, localhost binding, authorization).
*Acceptance:* a baseline for local use and what changes if exposed beyond localhost.

### Q11. Versioning and phase selection.
*Why it matters:* `phase_dev` and `phase_test` coexist; schemas (`schema_version`) will evolve.
*Acceptance:* how a client selects a phase and how breaking changes are signaled.

### Q12. Where does it live in the repository and in the milestones?
*Why it matters:* no milestone currently covers an API; M7 is integration and delivery.
*Acceptance:* a module boundary, a proposed milestone/issue placement and an implementation scope.

## Evidence

- Measured: loading all of `phase_dev` into a `Ledger` takes about 1.6 s (36,743 entries, 284 balance rows, 8,872 open-item keys). Holding one `Ledger` per phase in memory is viable; no database is needed.
- [MCP changelog, spec 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/changelog): protocol sessions and the `initialize` handshake are removed (stateless); every request carries its version in `_meta`; `server/discover` is mandatory; list results carry `ttlMs`/`cacheScope`; `tools/list` should be deterministic; `structuredContent` may be any JSON value and `outputSchema` is JSON Schema 2020-12; HTTP+SSE is deprecated in favor of Streamable HTTP; Roots, Sampling and Logging are deprecated. This spec is labelled a release candidate in its [announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/), so the previous revision (2025-11-25) must still be negotiable.
- Transports: stdio and Streamable HTTP are the two standard ones, and clients are recommended to support stdio whenever possible ([transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)).
- Security: local servers must bind to localhost, validate `Origin` and answer 403 when it is present and invalid ([MCP security guidance via SDK docs](https://ts.sdk.modelcontextprotocol.io/v2/serving/http.html)). The [Python SDK deploy guide](https://py.sdk.modelcontextprotocol.io/run/deploy/) defaults to a localhost Host allowlist (421 otherwise), is stateless under 2026-07-28, and leaves health checks and workers to the ASGI server.
- Not verified this session: the exact Python SDK version that supports 2026-07-28, its Python 3.12 compatibility, and the tool-annotation field names (`readOnlyHint`) in that revision. These are listed as risks, not facts.

## Decisions

### Q1. Consumers and jobs
**Decision (assumption, flagged):** two consumers, both read-oriented.
- *Front end, a close reviewer:* see what the phase contains, trace a number to its entries, review each of the six task queues and, once engines exist, the proposed row with its evidence; compare a submission with the golden in development.
- *Agent:* answer factual questions about the books (balance, open items, entries, bank lines, FX rate), check a candidate entry (`validate_entry`), simulate its effect on balances, and read the submission and run reports.
The real front-end team and agent runtime are not in the repository, so these jobs are inferred from the six tasks and the existing readers. They are not a stated requirement; the request itself says "quizás" for MCP.

### Q2. Resources available now
Each maps to an existing reader. Solver side unless stated.

| Resource | Source | Available |
|---|---|---|
| Phases, month, manifest and hashes | `register_package`, `Manifest` | now |
| Companies, accounts, cost centers, vendors, customers, projects, tax codes | `PhaseData.table`, `Company`, `Account`, `CostCenter` | now |
| Task queues (six) and their item ids | `PhaseData.tasks` | now |
| AP documents and inbox messages | `PhaseData.table("document_messages")` | now |
| Journal entries (filter by company, account, date, doc_type, reference) | `PhaseData.iter_journal`, `JournalEntry` | now |
| Balances per `(company, account)` and open items per `OpenItemKey` | `Ledger.balances`, `Ledger.open_items` | now |
| Bank accounts and statement lines | `PhaseData.table("bank_lines")`, `BankLine` | now |
| FX rate for a date and currency | `fx_rates.jsonl`, `money.py` | now |
| Validate an entry; simulate it on a copy of the ledger | `validate_entry`, `Ledger.project` + `add_entry` | now |
| Run reports and cost | `RunReport` in `outputs/runs` | now |
| Submission rows, one per delivery file, plus structural check | `output_models`, comparator `--structure-only` | now, once a submission exists |
| Evaluation report (**evaluator side**, `phase_dev` only) | `evaluation` package | now |
| Proposed row per task item with evidence | engines M1-M6 | **blocked** until M1-M6 |
| Trial balance rebuilt from ERP plus six outputs | M7-03 (#107) | **blocked** |

### Q3. Read-only or writable
**Decision: read-only in v1.** Delivery is a single submission (M7-09) and the scored output is produced by the engines, so the API must not be a second way to write it. Two operations look like writes but are not: `validate_entry` is pure, and a simulation runs on `Ledger.project()` (a copy) and is discarded. Running engines and packaging stay on the CLI. A later write path (for example "accept this proposed row") needs its own decision and an ADR.

### Q4. Front-end transport
**Decision: HTTP + JSON, versioned under `/v1`, built with FastAPI, shipped as an optional extra** (`pip install kalmora-close[api]`), so the core package keeps its zero-dependency runtime. FastAPI plus Pydantic generates an OpenAPI 3.1 contract directly from the existing `TypedDict` models, which is the published schema the front end needs.
Alternatives considered: standard-library `http.server` (no validation, no schema generation, hand-written contract that would drift); GraphQL (the shapes are fixed and shallow, the cost is not justified); WebSocket/SSE push (nothing produces progress events until engines exist).

### Q5. Agent surface
**Decision: an MCP server, with stdio as the default transport and Streamable HTTP mounted on the same ASGI app as an option.** stdio is what a local agent (Claude Code, desktop clients) launches without any network exposure; Streamable HTTP covers a remote or in-product agent. HTTP+SSE is deprecated and is not offered.
Mapping of primitives:
- **Resources** (read-only, addressable, cacheable): `kalmora://{phase}/manifest`, `.../tasks/{task}`, `.../companies/{code}`, `.../runs/{run_id}`, and schemas.
- **Tools** (parameterized queries and computation): `query_journal`, `get_balances`, `get_open_items`, `get_bank_lines`, `get_fx_rate`, `validate_entry`, `simulate_entry`, `get_submission`, `get_evaluation` (evaluator side only, see Q7). All declared read-only. Tool lists are returned in deterministic order, as the spec asks.
- **Prompts:** none in v1. Reusable review prompts can be added later without changing the data surface.
Official Python SDK, pinned, negotiating the previous revision as a fallback because 2026-07-28 is a release candidate.

### Q6. One source of truth
**Decision: a transport-free service layer, two thin adapters.** `kalmora.service` holds typed functions over a `PhaseContext` (one cached `PhaseData` + `Ledger` per phase, loaded at startup in about 1.6 s). `kalmora.api` (FastAPI) and `kalmora.mcp` call it and add nothing else. Input and output schemas come from the `TypedDict` models through Pydantic `TypeAdapter`, so OpenAPI and MCP `outputSchema` are generated from the same types. Errors map once: a `Diagnostic` list is data, not an exception, in both surfaces.

### Q7. Golden boundary
**Decision: two services, and the solver-side one never imports `kalmora.evaluation`.** The default process (HTTP and MCP) exposes solver-side resources only. Evaluation resources (`get_evaluation`, comparator diff) are registered only when the process is started with an explicit `--evaluator <dir>` flag, and only for a phase that has golden; for `phase_test` they answer a refusal, mirroring the comparator's behavior. Raw golden rows are never returned, only the comparator report. The existing separation check from ADR 0001 (`evaluation/boundary.py`) is extended to cover the new packages. `PhaseData` already rejects any path containing `golden`, which stays the second guard.

### Q8. Wire conventions
- **Money:** JSON integers in cents, field names unchanged from the models (`debit`, `credit`, `net`...). Never floats. Cents stay far below 2^53. FX `rate` and run costs are decimal **strings**.
- **Dates and months:** `YYYY-MM-DD` and `YYYY-MM`.
- **Identity:** `book_line` is returned as the existing `<entry id>#<line>` string. `OpenItemKey` is an object with its four fields (partner and assignment may be `null`), not a tuple, plus no invented composite id.
- **Pagination:** cursor-based. HTTP: default 100, max 1000. MCP tools: default 25, max 100, because tool output enters the model context. Every list returns `total`, `next_cursor` and a `truncated` flag.
- **Aggregation first:** the agent gets `get_balances` and `get_open_items` computed server-side with filters, so it never has to page through 36,743 entries to answer a total.
- **Filters** are explicit parameters (company, account, partner, date range, doc_type, reference), never free-form query strings.

### Q9. Provenance and auditability
**Decision: every response carries an envelope** `{ data, meta }`, where `meta` has `phase`, `month`, `schema_version`, and the manifest `sha256` of each source file used. Adjustment entries always include their `provenance` `(event_id, stage)`. Run reports are a resource, so cost and status are citable. For MCP, the same `meta` is returned inside `structuredContent` and `_meta` carries the server identity as the spec asks.

### Q10. Security baseline
- stdio: no network exposure; no authentication needed.
- HTTP and MCP over HTTP: bind `127.0.0.1` by default; validate `Host` and `Origin` against an allowlist (403 or 421 otherwise), as the MCP guidance and SDK require.
- Read-only and synthetic data bound the damage. If it is ever exposed beyond localhost, a bearer token for REST and the MCP authorization flow for MCP become mandatory; this is documented as out of scope for v1 rather than half-built.
- `phase_test` inputs and golden are never reachable through a path parameter: phases are selected by name from the manifest, not by file path.

### Q11. Versioning and phase selection
**Decision:** URL prefix `/v1`, phase as a path segment (`/v1/phases/{phase}/...`), phases discovered from the manifest. `schema_version` in `meta`. MCP uses protocol version negotiation, and its resource URIs carry the phase. A breaking change means `/v2`; additive fields do not.

### Q12. Placement and scope
**Decision:** new packages `kalmora.service`, `kalmora.api`, `kalmora.mcp`, with the extra `api` in `pyproject.toml`. Proposed as a **separate milestone "M8 — API de lectura y MCP"**, not inside M0-M7: all scoring comes from the six delivery files, so the API earns no points and must not compete with M1-M6 for time. Slices, each shippable alone:
1. Service layer and phase/master/ledger reads.
2. HTTP adapter with generated OpenAPI.
3. MCP adapter (stdio first, then Streamable HTTP).
4. Submission, run and evaluator-side resources.
`AGENTS.md` says not to add or run tests unless asked; implementation will follow that unless you ask for tests.

## Gaps found while deciding (new questions, resolved)

- **G1. Does the front need live progress?** No: engines do not exist and the CLI is synchronous. Defer; revisit when M7-01 (#105) orders the six engines.
- **G2. Load time and memory per request?** Resolved by Q6: load once per phase, measured 1.6 s.
- **G3. SDK compatibility with 2026-07-28 and Python 3.12?** **Open risk, not resolved:** not verified. The first implementation step is to pin a version and confirm it before writing adapters.
- **G4. Real consumers unknown.** Recorded as an assumption in Q1. It affects only the front-end resource shapes, not the service layer.

## Revision 1: ingestion API added (user alignment)

The user extended the scope: besides read APIs there must be an API to **upload the input data, load it and process it**, and then query it (HTTP and MCP). This supersedes Q3 (read-only) and the "CLI-only loading" assumption. Answers given by the user:

- **"Process" means ingestion and normalization only** (validate, register with hashes, parse, load). No accounting decisions. Running the M1-M6 engines is a later job type, not part of this scope.
- **Upload unit is the complete organizer ZIP**, reusing `register_package` (unsafe paths rejected, sha256, phase detection).
- **Storage is in memory for now, behind a repository proxy**, so the store can later be swapped (the repo's DuckDB landing-database proposal in `knowledge/reference/landing-db.html` stays the candidate) without touching the API.

### R1. Write policy (replaces Q3)
Ingestion is the **only** write. A registered package is immutable: the ZIP is extracted once to a data directory (`register_package` already refuses an existing destination) and never edited. Re-uploading a ZIP with the same `archive_sha256` returns the existing package instead of an error (idempotent). There is no delete or overwrite in v1. Everything else stays read-only. Engine runs and submission packaging remain on the CLI.

### R2. Repository port
A `PhaseRepository` protocol is the only thing the service layer talks to:
- `packages()`, `register(archive) -> PackageRecord`, `phases()`, `phase(name)`;
- `rows(phase, table, filters, cursor, limit) -> Page`, `get(phase, table, key)`;
- `journal(phase, filters, cursor, limit)`, `balances(phase, filters)`, `open_items(phase, filters)`.
First implementation, `InMemoryPhaseRepository`, wraps `PhaseData` and `Ledger` (about 1.6 s per `phase_dev`). Because packages stay extracted on disk, **memory is a cache**: on restart the repository rescans the data directory and reloads, so state is not lost. A `DuckDbPhaseRepository` can implement the same port later. The golden boundary lives in the port: `rows`/`get` never reach `golden`, as `PhaseData` already guarantees.

### R3. Ingestion flow and job model
Upload is large (61 MB for `phase_dev`) and loading has stages, so it is a job.
1. `POST /v1/packages` (multipart ZIP) returns `202` with `job_id` and `package_id` (= `archive_sha256`), or `200` with the existing package if the hash is known.
2. The job moves through `received -> extracted -> inventoried -> loaded`, or `failed` with the reason.
3. "Loaded" per phase means: tables indexed, `Ledger` built, and a **load report** produced with non-blocking diagnostics (for example the ERP `open_items` master vs `Ledger.open_items()`, and known source discrepancies such as API004469). Diagnostics never block the load; they are data.
4. `GET /v1/jobs/{job_id}` returns status, stage and report. Polling only; no push.

### R4. Final API surface (HTTP, `/v1`)
Ingestion
- `POST /v1/packages`, `GET /v1/packages`, `GET /v1/packages/{package_id}` (manifest)
- `GET /v1/jobs/{job_id}`

Query (per phase, paginated, explicit filters)
- `GET /v1/phases`, `GET /v1/phases/{phase}` (month, counts, load status, load report)
- `GET /v1/phases/{phase}/companies | accounts | cost-centers | vendors | customers | projects`
- `GET /v1/phases/{phase}/tasks/{task}` (six task queues) and `.../documents` (AP documents, inbox)
- `GET /v1/phases/{phase}/journal-entries?company&account&partner&doc_type&reference&from&to`
- `GET /v1/phases/{phase}/balances?company&account_prefix`
- `GET /v1/phases/{phase}/open-items?company&account&partner&assignment&only_open`
- `GET /v1/phases/{phase}/bank-accounts/{id}/lines?from&to`
- `GET /v1/phases/{phase}/fx-rates?currency&date`
- `POST /v1/phases/{phase}/entries:validate` and `entries:simulate` (pure, nothing stored)

Evaluator side (only with an explicit `--evaluator` start flag, never for `phase_test`)
- `GET /v1/phases/{phase}/evaluation`

### R5. MCP surface
Same service calls as the query endpoints, as read-only tools: `list_phases`, `get_phase`, `list_records` (table + filters), `query_journal`, `get_balances`, `get_open_items`, `get_bank_lines`, `get_fx_rate`, `validate_entry`, `simulate_entry`, `list_packages`, `get_job`. Resources: manifest, task queues, load report. **Upload is HTTP only**: moving a 61 MB binary through an MCP tool call is a poor fit, so the agent can observe ingestion (`list_packages`, `get_job`) but not start it. Which side may start it is an open point below.

### R6. Gaps found (new questions)
- **N1. Can the agent start an ingestion?** Recommended default: no. A local agent could be given a `load_package(path)` tool later, but it needs a path allowlist.
- **N2. Maximum upload size and concurrency.** Not decided; proposed 256 MB and one active ingestion at a time, because `register_package` stages a full copy and the in-memory load is single-process.
- **N3. Memory budget.** Not measured for several phases at once; `phase_dev` plus `phase_test` loaded together has not been tried. Measure before relying on it.
- **N4. Parsing of documents (PDF, Facturae, CFDI, OCR) is not implemented** in `src/`. R3 "loaded" therefore covers the ERP, bank and task data that `PhaseData` already reads; the document parsing of the landing proposal arrives with M1/M2 and fills the same port. This is a limit of v1, not a hidden assumption.
