# Deterministic PO candidate resolution — #43

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
unit or position. An existing PO belonging to another company/vendor/currency,
or created after the invoice date, is also a conflict; it cannot be treated as
an obsolete number and replaced. An explicit position constrains recovery even without a PO
number. Every asserted receipt reference must resolve: conflicting associations
return `CONFLICT`; missing or not-yet-visible references return `UNKNOWN` with
diagnostics and no selected candidate or usable receipt supply.

Exact PO/position, material and delivery associations take priority over wording
differences. An exact description can distinguish multiple structurally valid
positions. If the anchored position is already unique, different descriptive
wording does not trigger semantic ranking. Material, unit, project, position and
receipt contradictions remain hard constraints. Each excluded position retains
its `PODiscard(order, reasons)` in `POResolution.discarded`; candidates, including
ambiguous ones, remain visible rather than being selected by repeated amounts.

Resolved candidates retain source/master evidence, exact PO price and eligible
receipt quantities minus explicit prior consumption. Receipt deficits do not
erase the PO: #44 allocates atomically and #49 handles QTY_NOT_RECEIVED. No state
is committed by this lookup. Foreign company/vendor/currency and future orders
or receipts cannot provide supply. No golden data is read.
`resolve` and `resolve_lines` accept an optional `receipt_as_of` ISO date for
receipt visibility, including explicit albarán references. It defaults to the
invoice date for compatibility. The caller supplies an observed arrival or
processing date and enforces the active phase's cutoff; the catalogue never
infers it from the newest receipt or the end of a month. PO creation remains
constrained by `invoice_date`, which must also remain unchanged for FX and fiscal
calculations. A receipt between invoice issue and arrival can therefore be
available while a receipt after the explicit cutoff stays unavailable. A future
asserted receipt reference stays UNKNOWN rather than supplying quantity.

`POQueryLine(line_id, quantity_milli, uom, portions)` conserves each observed
invoice row. `validate_query_lines` rejects missing/zero quantities, duplicated
portion IDs, inconsistent scopes/units or portions whose sum differs from the
observed total. `ap_order_sources.order_queries_from_facts` consumes existing
`DocumentFacts`/normalization and preserves source evidence; it cannot invent
an implicit MULTI_PO split. `APOrderBridge.resolve_lines` combines resolved
portions into #44 `InvoiceQuantityLine`/`OrderPortion` and previews joint receipt
capacity. #45 recovers coding and #51 values prices independently.

The focalized source audit reconstructs the active-phase catalogue and confirms
one actual receipt ID for every received position: 1,410 July and 1,448 September
positions, against all 21,699/23,870 original receipt rows. Synthetic variants
cover missing/erroneous references, ambiguity and partial received quantities.
See [the criterion/evidence matrix](ap-order-validation.md). Document extraction,
identity resolution, semantic quality measurements and full AP orchestration keep
their own issue boundaries; lookup never claims approval or posts an entry.
