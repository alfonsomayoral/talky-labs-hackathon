# Document landing

Install `kalmora-close[landing]` (DuckDB **1.5.5**) and use one database outside
the original input directory for each phase. The loader is format ingestion;
it does not decide accounting treatments, classify invoices, reconcile accounts,
or replace `Ledger`.

```python
from pathlib import Path
from kalmora.landing import LandingStore

with LandingStore(Path('build/current/landing.duckdb')) as store:
    counts = store.import_phase(Path('/path/to/participant/phase_dev'))
    vendor = store.get('vendors', 'V100001')
    pending = store.table('tasks/ap_documents')
    statements = store.rows('bank_statement', chain_ok=True)
    lines = store.rows('bank_line', currency='EUR')
```

These are examples, not fixed phase names, dates, companies, or IDs. All eight
landing tables accept parameterized equality filters through `rows`:
`source_file`, `parse_issue`, `task_item`, `bank_statement`, `bank_line`,
`inbound_item`, `document`, and `document_line`. Arbitrary SQL, file readers,
extensions and unregistered ERP paths are not exposed by the query interface.
The private DuckDB connection also disables external access.

`table`, `get`, and `find` adapt the existing M0 ERP/task readers, preserving
JSON shapes, nested objects, text IDs, integer cents and exact `Decimal` rates.
Every adapter call verifies the catalogued ERP/task hashes. ERP is not copied
into extra database tables and `Ledger` stays unchanged. The only derived ERP
adapter is `table('journal_lines')`, which attaches the entry identity/company/
posting date and `line_ref` to each original line, retaining its original fields
and exposing `debit_cents`, `credit_cents` and `amount_doc_cents` aliases.

## Schema and source contract

Schema version **1** is stored in `landing_meta`. The packaged `schema.sql`
implements the eight tables from the reviewed
[landing proposal](../knowledge/reference/landing-db.html) and
[reference DDL](../knowledge/reference/landing-db.sql). Intentional adjustments:

- Phase labels are configurable, rather than a two-value phase check.
- PDF sources have format `PDF`; cataloguing never claims text or OCR extraction.
- Document method is initially `UNEXTRACTED`, then `FACTS` when caller-supplied
  facts are stored, unless the caller explicitly supplies a supported `method`.
- `document.facts_json` preserves the complete typed `DocumentFacts` envelope,
  and `extractor_version` fixes the extraction identity.
- Unreadable sources retain `NULL` hashes (and unknown sizes if stat fails),
  `FAILED` status and a `READ_ERROR`, rather than invented hashes. Repeat-load
  verification refuses such an inventory until the read failure is fixed and
  the phase rebuilt.
- Exact M0 adapters replace inferred DuckDB JSON views, avoiding floating-point
  inference or fixed-scale FX truncation. No duplicate accounting logic is added.
- N43 header dates use the offsets verified against the originals,
  `[20:26]` and `[26:32]`; the reference HTML's `[22:28]` date offset does not
  match these bytes. Monetary offsets agree with the source reference.

Files are catalogued by phase-relative path, SHA-256, size, family and format.
Only `erp/`, `tasks/`, `bank/` and `inbox/` are eligible. `golden/`, `__MACOSX`,
`score.py` and `scorer.py` are excluded. Symlinks and escaping paths are rejected,
including metadata attachment references. Originals are read, never rewritten.
Source parsing failures are recorded as `FAILED` plus `parse_issue`; valid
neighboring files continue loading. Missing attachments/task references and
bank balance/twin discrepancies are extraction diagnostics, not accounting reasons.

Bank loaders parse N43, camt.053 XML and bank CSV independently from their
JSONL twins. Original full descriptions/references and original-currency
information are retained. Exact amounts, booking dates, currencies and available
native IDs must agree with the twin before its solver ID is assigned. Each
statement records `chain_ok` and `twin_ok`; a mismatch creates an issue and leaves
its source `PARTIAL` without manufacturing line IDs. CSV running balances are
checked as well as statement opening/closing balances.

## Supplying extracted document facts

Import creates one `document` placeholder per declared source attachment,
including separate PDF and XML rows for the same inbound item. No parser or
LLM is invoked automatically. The extraction pipeline delivers `DocumentFacts`
to the single writer:

```python
store.store_facts('inbox/ap/CASE/attachment.pdf', facts)
```

The facts must match the registered SHA-256 and unchanged original attachment.
Every raw candidate, conflicting value and `Evidence` survives in `facts_json`.
Fractional values remain `Decimal` with the existing `typed-v1` encoding; any
float is refused. A second identical envelope is a no-op; a different envelope
or extractor version requires an explicit rebuild, rather than overwriting
evidence. PDF/XML facts are never silently merged.

Raw extraction may use flat fields such as `supplier_tax_id`, `recipient_tax_id`,
`document_number`, `document_date`, `document_type_hint`, `net`, `tax`, `gross`,
`iban`, `po_reference`, `receipt_reference`, and `line.<id>.<field>`. These are
retained verbatim and are **not** interpreted as normalized monetary units.
Type hints stay source facts, not accounting classifications.

Only a singleton candidate whose field exactly names a typed document column
is projected: for example `net_cents=1234`, `currency='EUR'`,
`issue_date='2027-02-03'`, or `issuer_tax_id_norm='...'`. Integer monetary/quantity
units are required; `'12.34'`, `Decimal('12.34')`, and `1234.0` cannot be inserted
as cents. Missing and ambiguous fields stay SQL `NULL`; conflicting candidates
also produce `FIELD_CONFLICT`. Raw `net='12.34'` remains solely in `facts_json`
until deterministic normalization supplies `net_cents`.

The optional singleton `fields['lines']` holds a list of normalized dictionaries
with `document_line` column names (`kind`, `amount_cents`, `quantity_milli`,
`unit_price_e4`, `rate_bp`, `po_ref`, etc.). The writer assigns `document_id` and
1-based `seq`, validates exact integer units and inserts transactionally. Keep
original flat line facts/evidence alongside this normalized projection.

## Idempotence, concurrency and reconstruction

`import_phase` runs the complete import in a transaction. A repeat import checks
the full source path/hash inventory, preserving rows and extraction facts when
unchanged. Changed or removed originals, a different source root/phase, and unknown schema
versions are explicit errors. There is no in-place migration or silent update;
rebuild into a **new output database** from unchanged originals, then replay
extraction envelopes. Malformed inputs remain reproducibly catalogued on reload.

An exclusive nonblocking POSIX file lock allows one writer per database, and
owner PID/thread checks prohibit connection sharing between extraction workers.
Parallel workers return envelopes to their coordinator; only that coordinator
calls `store_facts`. The lock is released by context-manager exit and by the OS
after a process failure. DuckDB transactions/primary keys add duplicate and
partial-write protection. This version requires a POSIX host (the CI runs Linux).

## Reproducible validation

```sh
python -m pip install -e '.[landing]'
PYTHONPATH=src python -m unittest discover -s tests -p test_landing.py -v
KALMORA_LANDING_PHASE=/path/to/participant/phase_dev \
  PYTHONPATH=src python -m unittest discover -s tests -p test_landing.py -v
```

The regular fixture uses a different phase/month and verifies reload/rebuild,
source mutation, missing golden, safe bounded queries, malformed JSON/XML,
bank twin conflicts, separate PDF/XML facts, exact Decimal/int values, conflicting
candidates, rollback on invalid normalized lines, and exclusive writer ownership.
The opt-in real-source check compares complete catalog/task/ERP/journal/bank
readings to M0, verifies all bank chains/twins, reloads, and rebuilds independently.
July evidence: **817 sources, 396 task items, 48 statements, 1,062 bank lines,
339 inbound items, 354 independent document placeholders, zero parse issues**.
`document_line` is empty until extraction/normalization supplies facts; raw PDF
and XML document extraction belongs to the extraction pipeline, not this loader.
