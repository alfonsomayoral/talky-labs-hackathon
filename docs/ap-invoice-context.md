# Ordinary AP invoice source context (#140)

`kalmora.ap_invoice_context.resolve_ap_invoice_context` connects verified
`APTaskSources` to `APDocumentBridge`, exact ERP identity, `POQuery`,
`APOrderBridge`, and a structural `APInvoiceRequest`. It prepares observations;
the existing rejection, HOLD, chronology, payment and transaction engines still
decide and post.

```python
context = await resolve_ap_invoice_context(
    task,
    data=phase_data,
    baseline=verified_erp_baseline,
    state=current_ap_state,
    receipt_as_of=observed_cutoff_fact,
    expected_company=observed_company_fact,  # optional; otherwise an exact PO may prove it
    financial_source_paths=(primary_attachment_path,),  # required for several financial attachments
    resolver=recorded_semantic_resolver,  # optional; exact matching needs none
)
```

The phase planner first calls `load_prepared_ap_sources` and the current ERP
baseline/opening-state loader. This context does not extract, authenticate a
prepared manifest, create a recording, inspect Golden, contact a provider,
consume a receipt, publish an AP row or write an input. `APOrderBridge.from_phase`
checks that baseline source hashes and the phase month still match the original
ERP before using its purchase-order text and historical receipt certainty. A
fresh `PhaseData` avoids reusing the caller's cached old masters.

## Returned contract

`APInvoiceContext` contains the complete source bridge, every financial source,
an optional primary source, financial header consensus, exact identity, optional
scope and duplicate observation, reception/date facts, per-line PO query,
reference match and candidates, evidenced rejection/HOLD fields, diagnostics,
order snapshot hash and an optional coordinator request.

`RESOLVED` means the structural source/identity/PO projection is resolved. It
does **not** mean the invoice may post or that every policy gate is known.
`UNKNOWN` keeps missing, invalid or contradictory prerequisites visible and may
still carry a useful request for an earlier non-posting decision. `UNSUPPORTED`
explicitly identifies credit notes and advance requests; those require their
separate adapters. Unclassified sources and failed companions keep the context
`UNKNOWN` even when another attachment is a usable invoice.

`financial_source_paths` selects exactly one primary row projection. Every
financial attachment remains in `request.amount_sources` for independent
arithmetic and CFDI comparison, and every source remains in the bridge. Choosing
the PDF cannot discard an unknown companion or choose its supplier/total over a
contradicting XML. Rows in separate attachments are not merged by ordinal; their
source relationships and monetary bindings belong to the monetary planner.

## Source and scope invariants

- Supplier and recipient IDs come from the consensus of all financial
  attachments and exact tax-ID/VAT aliases in active masters.
- An expected company is an explicit caller `Fact`, or the company of observed
  exact PO references whose supplier, currency and creation date match the
  observed invoice. A foreign supplier's cited PO never proves ordering company.
- The resolved recipient can supply an observational scope when ordering
  company is unproved. It does not manufacture `order_company`, an expected
  company, or a clear wrong-addressee check.
- Reception comes from the source message and must fall in the active ERP month.
  Invoice date comes from normalized source facts. Neither is replaced with a
  journal date, month end or another clock.
- Duplicate amount is observed consensus `gross_cents`. Unknown gross stays
  unknown; payable, net-plus-tax or vendor currency never fill it here.
- PO queries require positive observed milli quantity, observed UOM, scope,
  invoice date and an observed valid receipt cutoff. No PO unit or default
  month-end cutoff is inferred. Contradicting references remain unresolved.
- `APOrderBridge` checks exact references and scope before bounded semantic
  resolution. A unique scope-only candidate remains `UNCONFIRMED`. The returned
  receipt IDs use established historical capacity and the explicit cutoff;
  ambiguous history remains `UNKNOWN`. No split between PO positions is invented.

## Policy facts and coordinator connection

The adapter passes through evidenced applicable flags, source amounts and
certification observations. An explicit vendor withholding value establishes
the master requirement; an omitted key does not. An explicit guarantee basis
point establishes applicability; absence does not establish zero. A positively
identified SISP/PAUT construction regime establishes construction/ISP
applicability; other or absent tax codes do not prove non-construction here.
Matched PO positions or an explicit PO-required master establish quantity/price
applicability. An exact observed invoice IBAN and explicit master IBAN can prove
whether accounts differ; sender domains never verify a bank change.

CFDI comparison retains independent PDF/XML field views. The XML's observed
Comprobante structure establishes applicability; a missing twin does not turn
the check off. These views use the source's normalized fields; format-specific
number and monetary semantics must be established upstream rather than choosing
an attachment's contradictory interpretation.

`request.posting`, `request.header` and `request.duplicate_inventory_complete`
are initially `None`. The phase planner must provide the complete chronological
duplicate inventory, strict source-bound notices/inventory evidence, resolved
fiscal applicability and source monetary semantics before calling the coordinator
for a posting result. `guarantee_applicable` and `source_payable_basis` are passed
only when explicit facts resolve them; payable basis must be
`BEFORE_APPLIED_ADVANCES` or `AFTER_APPLIED_ADVANCES`. Missing values stay unknown.

The monetary adapter creates the `APHeader`, real `APPostingInputs` and evidenced
`APLineSourceBinding` relationships from the complete source set and line
contexts. It must retain contradictions, active ERP catalogues, cutoff and
historical consumption. An ordinary coordinator request can be evaluated with
`posting=None` for an evidenced earlier non-posting decision. A structural
request alone cannot authorize a POST.

The context deliberately does not invoke broad legacy source helpers that infer
PO UOM, choose a default receipt cutoff, treat empty history as unused receipts,
or verify bank details from domains. It does not implement a second fiscal
decision engine or imply validation of September or the full July close.

## Targeted verification

`PYTHONPATH=src python -m unittest discover -s tests -p test_ap_invoice_context.py -v`
uses synthetic November 2031 masters, invoices and history with different IDs.
It covers exact resolution without interpretation, scope-only candidates,
foreign-vendor references, wrong addressee, mandatory source projection,
preserved CFDI/header/total contradictions and companions, missing UOM/cutoff,
omitted versus explicit master facts, historical consumption, stale ERP,
unknown amounts and explicitly unsupported credit/advance requests.
