# AR numbering compatibility

The source billing runner preserves the operational numbering convention used
by v0: resolved invoices receive the smallest unused positive position in their
company/series, in the order of `tasks/ar_billing_items.json`. Existing gaps are
filled before appending after the greatest occupied position. Pending and
unresolved billing items consume no number.

This is a compatibility convention derived from the existing workflow and the
active ERP invoice inventory. A gap alone does not prove that a number was
reserved. The convention uses no golden output, company-prefix catalogue or
invented source fact. It keeps the generated invoice IDs usable by subsequent
AR cash processing, which refers to those IDs and journal assignments.

`allocate_invoice_numbers(data, items, preliminary_run)` derives each series
prefix and numeric width from the invoice already built by the typed engine,
then allocates against `erp/ar_invoices` in task order. It returns only an explicit
`{billing_item: invoice_number}` mapping and mutates no source, invoice or ledger.
Year changes/new series follow the typed engine's existing ERP-derived prefix.

The runner first builds its pure `BillingRun` to identify valid billable items,
allocates their numbers, and rebuilds once with
`build_ar_billing(..., invoice_numbers=numbers)`. The engine constructs invoices
and journal entries with the final number, preserving the receivable assignment,
invoice field and journal reference consistently. Accounting amounts, dates,
history checks and pending WIP use the same inputs in both builds.

The optional override API checks known task IDs, source-series identity and
existing/current numeric-position collisions, including differently padded
versions of the same position. Without overrides, the typed engine's existing
max-plus-one numbering remains unchanged. The mapping is a computation for this
run; it is not a persisted ERP reservation.

Validation covers task order, gaps, collision aliases, default behavior, year and
series changes, pending/unresolved items, and consistent invoice/journal/430
assignments. The nine focused tests pass. A source-grounded July build produced
25 invoices and one pending certification with no unresolved items; every number
matched v0's existing `next_number` convention over the same ERP inventory.
The municipal service/revision sequence remains `SU26-00107` through
`SU26-00116`. This comparison used no golden output or provider calls.
