# API contracts: input and output

Shared contract for backend and front end. Design rationale and alternatives are in [api.md](api.md); this file is what both sides build against. Status: **HTTP implemented** (see section 9 for what changed while building it); MCP not implemented. Where a shape comes from an existing Python type, the type is named so the contract can be generated from it instead of copied.

Legend: **[now]** the data exists in `src/` today; **[blocked: Mx]** depends on a milestone; **[assumption]** inferred, to confirm.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/v1`. Additive fields are not a breaking change; removals or meaning changes mean `/v2`. |
| Format | JSON, UTF-8, `Content-Type: application/json`. Upload is `multipart/form-data`. Errors are `application/problem+json`. |
| Names | `snake_case` everywhere, identical to the Python models (`debit`, `posting_date`, `book_line`). The front end does not rename fields. |
| Money | **Integer cents** as JSON numbers, in the company's local currency (EUR; MXN for company 3100). Never decimals, never strings. `amount_doc` is in the line's own `currency`. Safe: cents stay far below 2^53. |
| Decimals | FX `rate` and run costs are **strings** (`"1.0667"`) to avoid float loss. The raw ERP file holds a float; the API normalizes. |
| Dates | `YYYY-MM-DD`. Months `YYYY-MM`. Timestamps ISO 8601 UTC. |
| Ids | Opaque strings, passed through unchanged: `company` `"1100"`, `account` `"57200001"`, `book_line` `"1100-2024-5000000006#2"`, `bank_line` `"BL0000650"`, `doc_id` `"API004086"`. Account and company codes are strings, never numbers (leading zeros matter). |
| Null vs absent | A field that exists in the model but has no value is `null`. A field a model marks optional may be **absent**; clients must not treat absent and `null` differently. |
| Sign | `debit` and `credit` are both non-negative and at most one is positive. A balance is `debit - credit`: assets and expenses positive, liabilities and income negative. Open-item `balance` follows the same sign. |
| Phase | Selected by name in the path (`phase_dev`, `phase_test`), never by file path. |
| Read cache | Responses may be cached by the client per `(phase, package_id)`; a package is immutable. |

### 1.1 Response envelope

Every successful response, HTTP and MCP:

```json
{
  "data": { },
  "meta": {
    "phase": "phase_dev",
    "month": "2026-07",
    "schema_version": 1,
    "package_id": "<archive_sha256>",
    "sources": [{ "path": "participant/phase_dev/erp/journal_entries.jsonl", "sha256": "…" }]
  }
}
```

- `package_id` is the package `archive_sha256`; `sources` lists the manifest entries used to answer, so a number can be traced to a file.
- Endpoints that are not tied to a phase (`/packages`, `/jobs`) omit `phase`, `month` and `sources`.

### 1.2 Pagination (lists)

Request: `?limit=<n>&cursor=<opaque>`. HTTP default 100, max 1000. MCP default 25, max 100.

```json
{
  "data": { "items": [ ], "total": 36743, "next_cursor": "eyJvIjoxMDB9", "truncated": true },
  "meta": { }
}
```

- `total` is the count after filters. `next_cursor` is `null` on the last page. `truncated` is `true` when `next_cursor` is not `null`.
- Cursors are opaque and valid only for the same filters and package. A cursor from another query is `400 page.cursor_invalid`.
- Order is deterministic: journal by `(posting_date, id, line)`, balances by `(company, account)`, open items by `(company, account, partner, assignment)`, master tables by their natural id.

### 1.3 Errors

RFC 9457 problem details:

```json
{
  "type": "https://kalmora.example/problems/phase.not_found",
  "title": "Phase not found",
  "status": 404,
  "code": "phase.not_found",
  "detail": "No phase named 'phase_x' in any registered package.",
  "instance": "/v1/phases/phase_x/balances",
  "diagnostics": []
}
```

`code` is the stable machine value; `title`/`detail` are for people. `diagnostics` is used only by validation errors and holds the `Diagnostic` strings (`<path>: <problem>`).

| `code` | HTTP | When |
|---|---|---|
| `request.invalid` | 400 | Bad or unknown query parameter, malformed body. |
| `page.cursor_invalid` | 400 | Cursor does not match the query. |
| `package.unsafe_archive` | 400 | Absolute path, `..`, backslash, symlink or duplicate member in the ZIP. |
| `package.not_participant` | 400 | ZIP does not start with `participant/`. |
| `phase.not_found` / `package.not_found` / `job.not_found` | 404 | Unknown id. |
| `phase.not_loaded` | 409 | Phase is registered but its job has not reached `loaded`. |
| `ingestion.busy` | 409 | Another ingestion is running (one at a time, see §6). |
| `golden.forbidden` | 403 | Any attempt to reach golden through a solver-side resource. |
| `evaluation.unavailable` | 403 / 404 | Evaluator not enabled, or phase has no golden (`phase_test`). |
| `upload.too_large` | 413 | Above the configured limit (proposed 256 MB). |
| `entry.invalid` | 422 | `validate`/`simulate` body is not a valid entry; `diagnostics` filled. |
| `internal` | 500 | Unexpected. |

Validation findings of a *well-formed* request are data (`200` with `diagnostics`), not errors; see §4.9.

## 2. Shared types

Written in TypeScript notation for the front end. The Python source of truth is in brackets; generated OpenAPI replaces this block once it exists.

```ts
type CompanyCode = string      // "1000" | "1100" | "1200" | "1300" | "1910" | "2100" | "3100"
type AccountCode = string      // 8 digits, zero padded
type PartnerCode = string      // vendor "V100123", customer "C200001", company code, or "FACTOR-BAE"
type Cents = number            // integer, local currency
type IsoDate = string          // YYYY-MM-DD
type Currency = string         // ISO 4217

// kalmora.model.Provenance
interface Provenance { event_id: string; stage: string }

// kalmora.model.JournalLine
interface JournalLine {
  line?: number                // 1-based position in the entry
  account: AccountCode
  debit: Cents
  credit: Cents
  company?: CompanyCode        // inherited from the entry when absent
  currency?: Currency
  amount_doc?: number          // document currency cents, unsigned
  partner?: PartnerCode | null
  assignment?: string | null
  cost_center?: string | null  // exclusive with wbs
  wbs?: string | null
  tax_code?: string | null
  text?: string
  book_line?: string           // "<entry id>#<line>", only when the entry has an id
}

// kalmora.model.JournalEntry
interface JournalEntry {
  company: CompanyCode
  lines: JournalLine[]
  id?: string                  // "<company>-<year>-<number>"
  doc_type?: string            // WE KR KG DR ZP ZB DZ SB IC SA
  posting_date?: IsoDate
  document_date?: IsoDate
  reference?: string
  header_text?: string
  source?: string              // MM AP SD F110 CASHAPP BANKFEE … CLOSE_*; ":reversal" suffix
  currency?: Currency
  provenance?: Provenance      // only on solver adjustments
}

// kalmora.model.BalanceKey + balance
interface BalanceRow { company: CompanyCode; account: AccountCode; balance: Cents }

// kalmora.model.OpenItemKey + balance
interface OpenItemRow {
  company: CompanyCode
  account: AccountCode
  partner: PartnerCode | null  // null only in historical data (e.g. API004469 on 40700000)
  assignment: string | null
  balance: Cents
}

// kalmora.model.BankLine (+ owning account)
interface BankLineRow {
  account: string              // bank account id, e.g. "BIN-1100"
  bank_line: string
  booking_date: IsoDate
  value_date: IsoDate
  amount: Cents                // + money in, − money out
  currency: Currency
  text: string
}

// kalmora.model.FxRate
interface FxRateRow { date: IsoDate; base: "EUR"; currency: Currency; rate: string; source: string }

type Diagnostic = string       // "<path>: <problem>", e.g. "lines[2].partner: required for open-item account"
```

Master rows (`companies`, `accounts`, `cost-centers`, `vendors`, `customers`, `projects`, `tax-codes`) keep their **ERP shape unchanged** and may carry extra fields; the front end must ignore unknown fields. The guaranteed core:

```ts
interface Company    { code: CompanyCode; name: string; short: string; country: string; currency: Currency; role: string; tax_id: string; vat_id: string }
interface Account    { account: AccountCode; description: string; type: "BS" | "PL"; open_items: boolean }
interface CostCenter { id: string; company: CompanyCode; desc: string }
interface Vendor     { id: string; name: string; tax_id: string; country: string; currency: Currency; companies: CompanyCode[]; reconciliation_account: AccountCode; default_tax_code: string }
```

## 3. Ingestion

### 3.1 `POST /v1/packages` **[now]** (register) / **[assumption]** (job and load report)

Request: `multipart/form-data`, one part `archive` = the organizer ZIP. No other fields.

Response `202` (new) or `200` (same `archive_sha256` already registered):

```json
{ "data": { "package_id": "9f2c…", "job_id": "0b6f…", "status": "received", "already_registered": false } }
```

### 3.2 `GET /v1/jobs/{job_id}`

```ts
interface Job {
  job_id: string
  package_id: string
  status: "received" | "extracted" | "inventoried" | "loaded" | "failed"
  started_at: string
  ended_at: string | null
  phases: { phase: string; month: string; status: "pending" | "loading" | "loaded" | "failed" }[]
  error: { code: string; detail: string } | null      // only when failed
  load_report: LoadReport | null                        // only when loaded
}

interface LoadReport {
  phase: string
  counts: { companies: number; journal_entries: number; balance_accounts: number; open_item_keys: number;
            document_messages: number; bank_lines: number }
  issues: { code: string; severity: "info" | "warning"; detail: string; ref?: string }[]   // never blocking
}
```

`issues` examples (from `docs/discrepancies.md` and the ledger): open-item master vs `Ledger.open_items()` mismatch; `partner = null` on a partner-prefix account (API004469 / 40700000). Counts for `phase_dev`: 36,743 entries, 284 balance rows, 8,872 open-item keys **[now]**.

Poll until `loaded` or `failed`. No push.

### 3.3 `GET /v1/packages` and `GET /v1/packages/{package_id}`

```ts
interface PackageRecord {
  package_id: string                 // archive_sha256
  registered_at: string
  file_count: number
  phases: { phase: string; month: string }[]    // kalmora.model.ManifestPhase
  files?: { path: string; size: number; sha256: string }[]   // kalmora.model.ManifestFile, only on the single-package GET
}
```

## 4. Query

All under `/v1/phases/{phase}`; `phase` is `phase_dev` or `phase_test` and must be `loaded`, else `409 phase.not_loaded`. Filters are exact unless a name says otherwise. Unknown parameters are `400 request.invalid`.

### 4.1 `GET /v1/phases` and `GET /v1/phases/{phase}` **[now]**

```ts
interface PhaseSummary {
  phase: string; month: string; package_id: string
  status: "loaded" | "loading" | "failed"
  has_golden: boolean               // false for phase_test; the golden itself is never exposed
  counts: LoadReport["counts"]
  tasks: string[]                   // ["ap_documents","ar_billing_items","ar_receipts","bank_accounts","close","intercompany"]
}
```

`GET /v1/phases/{phase}` adds `load_report: LoadReport`.

### 4.2 Master data **[now]**

`GET …/companies`, `/accounts`, `/cost-centers`, `/vendors`, `/customers`, `/projects`, `/tax-codes` → `Page<row>` (§2).
`GET …/{collection}/{id}` → the single row. Filters: `companies`/`accounts`: none; `accounts`: `type=BS|PL`, `open_items=true|false`, `prefix`; `cost-centers`: `company`; `vendors`/`customers`: `company`, `q` (case-insensitive substring of `name`).

### 4.3 Task queues **[now]**

`GET …/tasks` → `{ "tasks": ["ap_documents", …] }`. `GET …/tasks/{task}` has **one shape per task** because the source files differ:

| `task` | `data` | Count in `phase_dev` |
|---|---|---|
| `ap_documents` | `{ "doc_ids": string[] }` | 305 |
| `ar_billing_items` | `{ "billing_items": string[] }` | 26 |
| `ar_receipts` | `{ "bank_lines": string[] }` | 32 |
| `bank_accounts` | `{ "accounts": string[] }` | 12 |
| `intercompany` | `{ "pairs": [CompanyCode, CompanyCode][], "accounts": AccountCode[] }` | 7 pairs, 8 accounts |
| `close` | `{ "month": "YYYY-MM", "steps": string[] }` | `ACCRUAL, PREPAID, WIP_REVENUE, FX_REVAL, BAD_DEBT, DOUBTFUL_RECLASS` |

Not paginated (small). Note: `close.steps` includes `DOUBTFUL_RECLASS`, which `output_models.CloseType` does not yet list; see §8.

### 4.4 Documents **[now]** (message level only)

`GET …/documents?kind=ap|ar` → `Page<DocumentMessage>`; `GET …/documents/{doc_id}` → one.

```ts
interface DocumentMessage {       // inbox/<kind>/<doc>/message.json, passed through
  doc_id: string                  // "API004086"
  channel: string                 // "facturae"
  received_at: string             // "2026-07-02T08:36:00"
  mailbox: string
  attachments: string[]           // file names inside the document folder
  source: string
  [extra: string]: unknown        // AR messages carry other fields
}
```

Attachment *content* (PDF, Facturae, CFDI, OCR) is **not parsed yet** **[blocked: M1/M2]**; the contract only lists attachment names.

### 4.5 Journal **[now]**

`GET …/journal-entries` → `Page<JournalEntry>`.

| Param | Meaning |
|---|---|
| `company` | exact |
| `account` | entries with at least one line on this account |
| `partner` | entries with at least one line for this partner |
| `doc_type`, `source`, `reference` | exact |
| `from`, `to` | inclusive range on `posting_date` |
| `include` | `lines` (default) or `header` to omit lines |

`GET …/journal-entries/{id}` → one `JournalEntry` with `book_line` on every line. `GET …/journal-lines?account=&company=&from=&to=…` → `Page<JournalLine & { entry_id: string; posting_date: IsoDate }>` for line-level views.

### 4.6 Balances **[now]**

`GET …/balances?company=&account=&account_prefix=&nonzero=true` → `Page<BalanceRow>`. Never mixes companies; MXN for 3100.
`GET …/balances:summary?company=` → `{ "company": …, "debit_total": Cents, "credit_total": Cents, "net": Cents }` (net is `0` for a closed consistent book).

### 4.7 Open items **[now]**

`GET …/open-items?company=&account=&partner=&assignment=&only_open=true` → `Page<OpenItemRow>`. `only_open` (default `true`) hides items whose balance is zero. `source=ledger|master` (default `ledger`) chooses the computed index or the ERP `open_items.jsonl` snapshot; they should agree, and the load report flags when they do not.

### 4.8 Bank and FX **[now]**

- `GET …/bank-accounts` → `BankAccount[]` (ERP row passed through, plus `months` derived from the statement files): `{ "id": "BIN-1000", "company": "1000", "bank": "Banco Ibérico del Norte", "gl_account": "57200001", "currency": "EUR", "statement_format": "n43", "roles": ["pool_header","payments","loans"], "months": ["2026-04", …] }`. `iban`, `bic` and `clabe` are also present in the source row. Filters: `company`.
- `GET …/bank-accounts/{id}/lines?month=&from=&to=&min_amount=&max_amount=&q=` → `Page<BankLineRow>`. `q` is a substring of `text`.
- `GET …/fx-rates?currency=&date=&from=&to=` → `Page<FxRateRow>`. With `date` and `currency`, the latest published rate **on or before** that date is returned (the latest published rate if that day has none, as documented in `FxRate`), with `effective_date` added.

### 4.9 Validate and simulate **[now]** (pure; nothing is stored)

`POST …/entries:validate`

```json
{ "entry": { "company": "1100", "posting_date": "2026-07-31", "lines": [
    { "account": "62600000", "debit": 3000, "credit": 0, "cost_center": "CC-1100-ADM" },
    { "account": "57200001", "debit": 0, "credit": 3000 } ] },
  "with_masters": true }
```

→ `{ "data": { "valid": true, "diagnostics": [] } }`. With `with_masters: true` the phase's companies, accounts, partners, cost centers, WBS and the close window (`min_date` = first day of the month, `max_date` = last day) are passed as `ValidationContext`, which turns on the existence checks **[assumption: the exact window comes from `tasks/close.month`]**. Without it only structural rules run. A malformed body is `422 entry.invalid`; a *valid request with findings* is `200` and `valid: false`.

`POST …/entries:simulate`

```json
{ "entry": { }, "provenance": { "event_id": "BL0002743", "stage": "bank_import" } }
```

→

```ts
{ valid: boolean
  diagnostics: Diagnostic[]
  balance_delta: { company: CompanyCode; account: AccountCode; before: Cents; delta: Cents; after: Cents }[]
  open_item_delta: { key: { company; account; partner; assignment }; before: Cents; after: Cents }[] }
```

Runs on `Ledger.project()` (a copy) and is discarded. A repeated `(event_id, stage)` is reported in `diagnostics`, as `Ledger.add_entry` refuses it.

### 4.10 Run reports **[now]**

`GET /v1/runs` → `Page<{ run_id; command: string[]; status: "completed"|"failed"; started_at; ended_at; elapsed_seconds; cost: CostSummary }>`; `GET /v1/runs/{run_id}` → full `RunReport`. `CostSummary.total` and `estimated_by_currency` values are decimal strings; `total` is `null` unless `status` is `no_llm`.

### 4.11 Submission **[now]** once a submission folder exists; rows **[blocked: M1–M6]**

`GET …/submission` → `{ "files": { "ap": { "present": bool, "rows": number }, … six keys } }`.
`GET …/submission/{module}?cursor=…` where `module` ∈ `ap | ar_billing | ar_cash | bank_rec | ic | close` → `Page<row>` with the row type of `kalmora.output_models` (`ApRow`, `ArBillingRow`, `ArCashRow`, `BankRecRow`, `IcRow`, `CloseRow`).
`GET …/submission:check` → structural check result (`--structure-only` of the comparator): `{ "ok": bool, "problems": { "module": string; "ref": string; "problem": string }[] }`.

### 4.12 Evaluation (evaluator side) **[now]**

Only registered when the process starts with an explicit evaluator directory; otherwise `404 evaluation.unavailable`. Never for `phase_test`.

`GET …/evaluation` → the comparator report summary: `{ "total": number, "modules": { "<module>": { "score": number, "weight": number } }, "reconciliation_ok": bool, "separation": { "violations": [] }, "report_id": string }`. Per-entity detail: `GET …/evaluation/{module}`. Raw golden rows are never returned, only comparator output.

## 5. MCP contracts

Server name `kalmora`; stdio default, Streamable HTTP optional. Every tool is read-only, takes a JSON object and returns the same `{ data, meta }` as HTTP in `structuredContent`, plus a short text summary. Pagination parameters are `limit` (default 25, max 100) and `cursor`. `phase` defaults to the only loaded phase and is **required** when several are loaded.

| Tool | Input | Output `data` |
|---|---|---|
| `list_phases` | – | `PhaseSummary[]` |
| `get_phase` | `phase` | `PhaseSummary & { load_report }` |
| `list_records` | `phase`, `table` ∈ `companies\|accounts\|cost_centers\|vendors\|customers\|projects\|tax_codes`, `id?`, `q?`, `company?` | `Page<row>` (§4.2) |
| `get_task` | `phase`, `task` | §4.3 shape |
| `get_document` | `phase`, `doc_id` | `DocumentMessage` |
| `query_journal` | filters of §4.5 | `Page<JournalEntry>` |
| `get_balances` | filters of §4.6 | `Page<BalanceRow>` |
| `get_open_items` | filters of §4.7 | `Page<OpenItemRow>` |
| `get_bank_lines` | `account`, filters of §4.8 | `Page<BankLineRow>` |
| `get_fx_rate` | `currency`, `date` | `FxRateRow & { effective_date }` |
| `validate_entry` | `entry`, `with_masters?` | §4.9 validate |
| `simulate_entry` | `entry`, `provenance` | §4.9 simulate |
| `list_packages` | – | `PackageRecord[]` |
| `get_job` | `job_id` | `Job` |
| `get_run` | `run_id?` | `RunReport` or run list |
| `get_submission` | `module?` | §4.11 |
| `get_evaluation` | `module?` | §4.12, **only if the evaluator is enabled** |

Resources (read-only, URI addressed): `kalmora://{phase}/manifest`, `kalmora://{phase}/tasks/{task}`, `kalmora://{phase}/load-report`, `kalmora://runs/{run_id}`. Tools are listed in a fixed order. Upload is **not** an MCP tool.

Error mapping: an HTTP problem becomes an MCP tool result with `isError: true` and the same `code`/`detail` in `structuredContent`; unknown tool or malformed arguments use the protocol's own error.

## 6. Limits and behaviors both sides depend on

- One ingestion at a time (`ingestion.busy`), max upload 256 MB **[assumption, to confirm]**.
- A package is immutable; re-upload is idempotent by `archive_sha256`. There is no delete.
- State survives restart because the extracted package stays on disk; memory is a rebuildable cache.
- `phase_test` has no golden: `has_golden = false` and every evaluator resource answers `evaluation.unavailable`.
- Nothing in the solver-side API can read a path containing `golden`.
- CORS: the front end origin must be allowlisted; default allows only `localhost`.

## 7. Working agreement for back and front

1. This file is the contract. A change to a shape is a change to this file first, in the same pull request.
2. The backend generates `openapi.json` from the Python types and commits it under `docs/`; once it exists, it wins over the TypeScript above, and the front end generates its client from it.
3. Until the backend exists, the front end mocks against the examples here. The sample values are real `phase_dev` values (company `1100`, account `57200001`, `BL0000650`, `API004086`) so mocks look like production.
4. Mark each endpoint as **[now]** or **[blocked]** in the issue that implements it; the front end must not depend on a blocked endpoint.

## 8. Open points that change the contract

- **`DOUBTFUL_RECLASS`**: present in `tasks/close.json` of July and handled by `score.py`, absent from `CloseType` and from `FORMATO_ENTREGA.md`. `submission/close` rows of that type cannot be typed until decided.
- **Document content**: attachment parsing (Facturae, PDF, CFDI, OCR) is not implemented; document endpoints return message metadata only.
- **`load_report` contents**: the checks listed in §3.2 are the intended ones; the final list is defined when the loader is written.
- **Who may start an ingestion**: HTTP only in v1; whether the agent may start one (`load_package(path)`) is open.
- **Upload limit and concurrency** (256 MB, one at a time) are proposals.
- **Memory with several phases loaded at once** is not measured.
- **MCP SDK version** for spec 2026-07-28 and Python 3.12 is not verified.

## 9. As built (HTTP): differences from the proposal above

Implemented in `kalmora.app` (use cases and ports), `kalmora.infra` (in-memory repository and file stores) and `kalmora.api` (FastAPI). Run with `kalmora serve` (needs `pip install 'kalmora-close[api]'`). Where this section and an earlier one disagree, **this section wins**.

| Topic | As built |
|---|---|
| Upload (3.1) | Extraction is synchronous, so a bad archive fails the request: `400 package.invalid_archive` (not a ZIP), `400 package.unsafe_archive` (bad member path, duplicate member, or no `participant/` root), `400 package.invalid` (no phase). The response is `202` with `status: "inventoried"`; only the load runs in the background. `package.not_participant` does not exist. |
| Job (3.2) | `load_report` is replaced by `load_reports: LoadReport[]`, one per phase, because a package can hold several phases. |
| Load report | Codes: `open_items.master_match` (info), `open_items.master_mismatch` (warning), `open_items.partner_null` (warning). Real `phase_dev` result: 36,743 entries, 284 balance rows, 8,872 open-item keys, **39 non-zero open items present in the ledger but not in the ERP `open_items` master** (for example `1100/55210000/1910/None`) and 3 open-item keys without partner. |
| Phases (4.1) | `GET /v1/phases` lists only loaded phases, so `status` is always `loaded`. A phase still loading answers `409 phase.not_loaded`; the loading/failed state is visible on the job. A phase name already loaded from another package is `409 phase.conflict`. |
| Documents (4.4) | Only AP messages exist: `inbox/ap/<doc>/message.json`. The AR inbox holds files (CSV, JSON notices, PDF) with no `message.json`, so `kind=ar` is valid but returns nothing. Each row has a derived `kind`. |
| Journal (4.5) | Sorted by `(posting_date, id)`. `include=header` replaces `lines` with `line_count`. `journal-lines` rows also carry `doc_type`. |
| Balance summary (4.6) | Without `company`: `{ "companies": [ { company, debit_total, credit_total, net } ] }`. With `company`: one object. |
| FX (4.8) | `date` requires `currency` (`400` otherwise). No rate on or before the date is `404 fx_rate.not_found`. `EUR` returns rate `"1"`. |
| Validate (4.9) | `with_masters` defaults to **true**. The close window is `<month>-01` to the last day of the phase month (`tasks/close.month`). Partners accepted = vendors + customers + group companies + `FACTOR-BAE`. |
| Simulate (4.9) | Works on a deep copy of the ledger; about 850 ms on `phase_dev`. A repeated `(event_id, stage)` across separate calls is allowed because nothing is stored. |
| Evaluation (4.12) | `modules` is `{ name: { score } }` (no `weight`: the scorer does not expose one). `GET .../evaluation/{module}` returns that module's full comparator section. Enabled with `kalmora serve --evaluator <dir>` where `<dir>/<phase>/golden` must exist; otherwise `404 evaluation.unavailable`. The structure check (`submission:check`) never needs golden. |
| Submission | The folder is `--submissions-dir/<phase>/<module>.jsonl` (default `outputs/submissions`). There is no upload endpoint for it yet. |
| Raw files (web app) | `GET /v1/phases/{phase}/files/{path}` and `GET /v1/runs/{run_id}/files/{path}` serve one file as is, **without envelope**; `path = __index.json` returns `[{path, size}]`. The phase's `golden/` is listed and served only with `kalmora serve --serve-golden` (so the web app can score runs). A run's files live in the bundle folder `--run-dir/<run_id>/` (`deliverables/*.jsonl`, `trace/*.jsonl`, `manifest.json`); a bundle with `manifest.json` and no `<run_id>.json` is listed too, and `/v1/runs` rows carry `has_files`, `dataset` and `month` (from the manifest, when present). Unknown or escaping paths are `404 file.not_found`. |
| Launch a close | `POST /v1/phases/{phase}/runs` → `202 {run_id}` runs the command given to `kalmora serve --close-command` (placeholders `{phase}`, `{phase_dir}`, `{month}`, `{out}`; it must write the six JSONL under `{out}/deliverables/`). The run's `manifest.json` starts as `status: running` and ends `completed` or `failed` with `exit_code`, `finished_at` and `runtime_s`, keeping any fields the command wrote (models, cost). Output goes to `{out}/run.log`. Follow it by polling `GET /v1/runs/{run_id}`. Without `--close-command`: `409 run.unavailable`. The command shipped with the backend is `kalmora close`: `--close-command 'python -m kalmora close {phase_dir} --out {out}'` runs the engines that exist (`ar_cash`, `bank_rec`, `ic` in recorded-only mode), optionally `--from-submissions <dir>` for modules with no engine here, and writes `deliverables/<module>.jsonl`, `trace/events.jsonl` and `tasks` in `manifest.json` (`running`, then `done`, `failed` or `unavailable`, rewritten as each module starts and ends). Events are appended when a module succeeds: first the findings its engine reports (AR cash and bank rec diagnostics, IC findings, close decisions, AP rows that could not be coded, with `evidence` when the engine gives it), then one event per delivered row; `policy_ref`, `model` and `confidence` stay `null` because no engine reports them. Findings without an item go to `tasks.<module>.diagnostics`. An engine's working files (IC audit, close handoff and decisions) are kept as `trace/<module>.zip`. The command's execution report is `{out}/run.json` under the bundle's `run_id`, so a run is listed once; the manifest takes `models`, `cost_usd_total` (`null` when a cost is unknown, never `0`), `cost`, `commit` and `policies_sha256` from it. A run still `running` when `kalmora serve` starts is marked `failed`. A module without engine or submission is `unavailable` and is not a failure; an engine that raises is `failed` and the command exits 1. No `attention.jsonl` is written: it would replace the web app's attention heuristics, and the engines do not grade their findings yet. |
| Extra routes | `GET /v1/health`, interactive docs at `/v1/docs`, generated schema at `/v1/openapi.json` (loose for request bodies: entries are free-form objects). |
| Query strictness | Any query parameter a route does not declare is `400 request.invalid`. |
| Extra error codes | `task.not_found`, `record.not_found`, `entry.not_found`, `document.not_found`, `bank_account.not_found`, `fx_rate.not_found`, `run.not_found`, `submission.not_found` (404); `submission.invalid` (422, unparseable JSONL); `route.not_found` (404), `method.not_allowed` (405); `phase.conflict` (409); `evaluation.failed` (500). |
| Limits | Upload max 256 MB (`--max-upload-mb`), one ingestion at a time (`409 ingestion.busy`). Measured on `phase_dev`: about 2 s to load, 330 MB resident, most queries under 60 ms. |
| Restart | `kalmora serve` reloads every package found in `--data-dir` at startup (`--no-restore` to skip). |
| Decimals | Any decimal number in an ERP master row is rendered as a string (the data layer parses decimals exactly), for example a vendor `rate` of `1.5` is `"1.5"`. |
