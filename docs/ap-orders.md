# Deterministic PO candidate resolution — partial #43

`POCatalog.from_phase` reads supplied orders and GR/SES receipts. `POQuery` carries
resolved company/vendor/currency, unit, quantity and source evidence, with optional
PO/position, exact material/concept, project or receipt/albarán references. Queries
can represent explicit portions of the same invoice line via `portion_id`.

The core retrieves date-visible positions within scope. Exact source references
confirm positions; missing/obsolete references can recover by exact material,
concept or receipt association. Case/whitespace normalization of concepts is only
an exact lookup convention, not an LLM or fuzzy semantic inference. Scope alone
is insufficient to confirm a unique candidate. Contradictory valid references,
ambiguous matches and missing evidence do not become invented correspondences.
An explicit existing order cannot be replaced to conceal a conflicting project,
unit or position. An explicit position constrains recovery even without a PO
number. Every asserted receipt reference must resolve: conflicting associations
return `CONFLICT`; missing or not-yet-visible references return `UNKNOWN` with
diagnostics and no selected candidate or usable receipt supply.

Resolved candidates retain source/master evidence, exact PO price and eligible
receipt quantities minus explicit prior consumption. Receipt deficits do not
erase the PO: #44 allocates atomically and #49 handles QTY_NOT_RECEIVED. No state
is committed by this lookup. Foreign company/vendor/currency and future orders
or receipts cannot provide supply. No golden data is read.
Visibility here uses the invoice date as a conservative cutoff; this is a stated
lookup convention, not an inferred date of invoice reception. Later receipt
availability must be supplied through a future explicit processing-date adapter.

Pending #41/#42: actual normalized line facts and identity; unresolved semantics
or implicit MULTI_PO splits require upstream evidence. Map resolved source portions
to #44 OrderPortion, preserving original invoice-line totals; never split an
unresolved aggregate by this function. #45 recovers coding and #51 values prices.
Full phase validation is still pending, so this core does not close the issue.
