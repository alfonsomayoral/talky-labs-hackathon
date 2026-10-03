# AP order integration — #43 / #140

`APOrderBridge.from_phase(phase_path, baseline)` loads the active phase's original
PO and receipt text only when every source hash still matches its ERP baseline.
`resolve(query, invoice_date=..., receipt_as_of=..., state=..., document=...,
resolver=...)` returns reference resolution separately from quantity readiness.

Exact PO/position, material, normalized whole-description and receipt-reference
matches use `POCatalog` first and do not invoke `SemanticResolver`. A sole
scope-only candidate stays UNCONFIRMED. Exact PO numbers shared by several
positions cannot become an inferred position or quantity split.

Only a residual description/reference with evidence in the supplied parsed
source can reach semantic ranking. Structural retrieval drops the whole-
description comparison, retaining company, supplier, currency, PO creation date,
project, material, unit, position and every receipt reference. Hard conflicts and
unknown receipt references do not reach the model. The candidate limit is
explicit; an oversized pool abstains instead of silently truncating it.

Candidate IDs encode actual ERP position keys. The request includes source
evidence, query, both dates, catalogue/history fingerprint and current consumption
fingerprint. Master, parser, source, context or state changes invalidate compatible
recordings. A returned selection is checked with the shared grounded-resolution
validator, must identify exactly one supplied position and must cite the residual
description/reference rather than merely a supplier/company field. The selected
PO is then structurally revalidated. Request mutation and invented IDs or splits
are rejected. Semantic quality remains an independent document-evaluation concern.

`APOrderMatch.quantity_status` is AVAILABLE, INSUFFICIENT or UNKNOWN. The selected
candidate's receipt list and capacity contain only proven historical capacities.
Its `quantity_line` supplies explicit eligible IDs to the actual allocator; the
allocator still checks concurrent invoice lines, scope and cumulative usage.
If proven supply is insufficient and relevant historical capacity is unknown,
the bridge preserves UNKNOWN and returns no quantity line. It never converts this
uncertainty into QTY_NOT_RECEIVED. Current state cannot discard historical usage
or posted identities, or invent usage for an unknown receipt.

`resolve_lines(lines: Sequence[POQueryLine], invoice_id=..., ...)` validates
observed totals and scope before resolving every portion, then returns
`APOrderBatchMatch(reference_status, quantity_status, matches, quantity_lines,
diagnostics)`. Each output `InvoiceQuantityLine` keeps its original row total and
all resolved `OrderPortion(order, quantity_milli, receipt_ids)` quantities. All
matches retain candidates, filter discard reasons and semantic evidence. No
partial successful invoice is published when any portion is unresolved.

The batch invokes #44 as a pure preview against the same immutable historical
snapshot. This catches two individually available rows competing for one receipt.
Known joint deficits return INSUFFICIENT; deficits involving relevant unknown
historical capacity return UNKNOWN and no quantity lines. Already-allocated
identities also cannot authorize reuse. The preview never returns or commits its
tentative consumption state. Call the real allocator again against current
state before valuation/posting; selection alone does not reserve a receipt.

`resolve_facts(facts, company=..., vendor=..., currency=..., invoice_id=..., ...)`
uses `ap_order_sources.order_queries_from_facts`, which consumes the shared
document normalizer. Company/vendor/currency come from resolved identity; the
observed document and per-row currencies must agree. Supported canonical
observations include flat `line.N.*`, nested observed `lines`, structured XML
`line.N.delivery.K.document_number`, and existing receipt/project vocabulary.
The adapter checks attachment hashes/path when a `ParsedDocument` is supplied.
It requires positive observed quantity and unit, preserves every evidence item,
and never computes quantity from price, amount or receipt supply.

MULTI_PO uses separate observed rows or explicit per-row `po_portions` with
their stated quantities. The adapter flattens those observations before shared
normalization. A bare MULTI_PO marker, aggregate unbound delivery references,
conflicting facts or unobserved portion quantities remain UNKNOWN. No model or
proportional allocation manufactures a split. Receipt visibility uses the
explicit observed cutoff; invoice date remains unchanged for PO/fiscal/FX.

`semantic_called` means the resolver boundary was invoked, including a cache hit;
provider calls/costs come from its recording metrics. Synthetic fixture replay
is tested separately and cannot be promoted to real recorded replay. This module
does not claim full July coverage, real model quality or September acceptance.
