# AP phase execution from saved sources (#140)

`run_ap_phase(phase, manifest, receipt_as_of=Fact(...), posting_date=Fact(...))`
connects authenticated source packets to the real identity/order, duplicate,
rejection, HOLD, payment, fiscal, journal and atomic posting engines. It returns
`APPhaseRun(report, rows, state, tax_catalog)` without writing a deliverable.
Source extraction remains a separate `prepare-ap` operation; this runner makes
no provider, extractor or semantic-resolver calls.

```sh
kalmora solve-ap PHASE --sources SAVED/phase-sources.json \
  --receipt-cutoff-fact receipt-clock.json --posting-date-fact posting-clock.json \
  --output DELIVERY/ap.jsonl --report REPORTS/ap-run.json
```

Each clock file contains `{"value": "YYYY-MM-DD", "evidence": {"document":
"operator/run-manifest", "field": "selected-processing-cutoff"}}`. The caller
records the chosen execution boundary explicitly. There is no invoice-date or
month-end default. Omitted facts remain unknown; earlier duplicate/rejection/HOLD
decisions can still succeed without monetary posting inputs.

The CLI writes the audit for every canonical task. It exports through
`write_phase_ap_jsonl` only when every task has an evidenced AP decision, and
returns zero only after that complete validated export. An incomplete run returns
one, preserves any existing AP file even with `--overwrite`, and reports
`publication.exported=false`. `--overwrite` only applies to complete results.
Outputs and run reports must be outside original inputs, prepared source state
and Golden. AP output, audit and clock inputs require distinct file paths.

## State and precedence

Each invocation starts from its own active ERP receipt baseline. Tasks are
processed in observed reception order. Received financial observations cover
the current duplicate inventory; a computed prior decision replaces its received
status for subsequent tasks. Missing potentially prior invoice observations do
not prove a negative duplicate result. Explicit different financial types and
proved future messages are excluded from that ordinary-invoice inventory.

`APQuantityCheckInputs` separates evidenced receipt/price controls from monetary
preparation. A quantity shortage can produce `HOLD / QTY_NOT_RECEIVED` even when
line net, coding, posting date or advance applicability remains unknown. A
tentative allocation changes no state. The real transaction boundary publishes
an AP row, source observation and receipt consumption together only after journal
and output validation. Nonposting decisions have no journal or consumption.

Strict phase notice context keeps scope, signatures, bank certificates,
invoice restrictions, validity and receipt clocks. Standalone notices resolve
exact internal IDs or observed tax identifiers against active masters. Contractor
certificates bind their subject, including their documented nonmonetary scope
projection; the authority issuing a certificate is not the contractor.

## Audit and replay contract

The report contains exact task keys, processing order, every task result and
diagnostic, source header/identity/order contexts, evidence, resulting rows,
monetary preparation status, source/ERP/configuration hashes and implementation
hashes. `accounting_run=true` means the policy engines ran; `complete` separately
states coverage. Documentary extraction quality is `NOT_EVALUATED` here.
`advances_opening_status` and `credits_opening_status` are `NOT_LOADED` for this
receipt-only initial state: it never claims empty historical credit capacity.

Originals, saved facts, masters and implementation bytes are checked again
before returning a result. Saved-source reopen operations pin directories and
use `O_NOFOLLOW`; redirects into original inputs or Golden are refused before
reading their bytes. The stable run hash excludes duration and absolute execution
paths, allowing an identical replay from the same saved sources and fresh ERP
baseline. The report explicitly records zero new provider calls/cost.

Downstream modules may inspect unresolved reports immediately, but must gate
delivery/phase completion on `APPhaseRun.complete` and a verified export receipt.
`plan-ap` remains the separate source/context audit and does not run accounting.

## Scope of this increment

Ordinary invoices with explicit source net, resolved coding/fiscal applicability,
proved no advance application, and single-position monetary lines can reach real
posting. Known no-action notices and strict operative notices can reach
`NOT_INVOICE`. Positive advance applications, credit-note dispatch, DUA and
multipart monetary lines remain unsupported. Multiple financial attachments need
explicit row equivalences that this phase adapter does not yet generate.
Unresolved facts never become invented HOLD reasons, zero amounts or padded rows.

Synthetic saved-source integration covers POST/HOLD/REJECT/DUPLICATE/NOT_INVOICE,
balanced entries, supplier dimensions, prior rejection status, receipt state,
complete export, incomplete preservation, mutation detection and replay with
network/Golden unavailable. These checks do not claim the July or September
accounting datasets have passed full acceptance or comparison.
