# Ordinary AP monetary preparation

`kalmora.ap_posting_source_bridge.prepare_ap_invoice_posting` prepares tentative
`APHeader` and `APPostingInputs` from a verified `APInvoiceContext`. It does not
decide eligibility, publish journals, consume receipts or replace the caller's
advance/credit state. `READY` means the monetary inputs are technically prepared;
the ordered coordinator may still return `REJECT`, `HOLD` or `UNKNOWN`.

```python
prepared = prepare_ap_invoice_posting(
    invoice_context,
    data=phase_data,
    baseline=erp_baseline,
    state=evolving_state,
    posting_date=observed_posting_date_fact,
    coding_catalog=coding_catalog,
    tax_catalog=tax_catalog,
    withholding_catalog=withholding_catalog,
    rates=source_rate_table,  # required only for foreign document currency
    bindings=independent_row_bindings,  # optional for one financial attachment
    advance_plan=observed_no_advance_application_fact,
    guarantee_plan=observed_guarantee_plan,
)
# No state update here. Only a later coordinator COMMITTED result updates state.
request = prepared.request
```

`APPostingPreparation` exposes `status` (`READY`, `UNKNOWN`, `UNSUPPORTED`),
`request`, optional `header`/`posting`, `evidence`, `diagnostics`,
`source_hashes` and `version`. Incomplete/unsupported preparation preserves the
original structural request, including independent amount sources and early
rejection facts. It never substitutes fabricated headers to force the quantity
gate. Malformed caller contracts raise `TypeError`/`ValueError`; missing or
contradictory supported source facts produce `UNKNOWN`.

The first supported scope is an ordinary invoice with an explicit nonnegative
`net_cents` on each projected source row, either one confirmed PO position or a
direct expense demonstrated by an explicit `quantity_check_applicable=False`.
An unconfirmed PO match, an optional-PO vendor or a missing reference does not
demonstrate a direct expense. Printed PO references still pass through the real
source-line guard. `amount_cents`, quantity times unit price, and header net are
not substitutes for an absent row net. Source discounts do not change this rule.

With one financial attachment the adapter can bind each existing row to itself.
Several financial attachments require caller-supplied `APLineSourceBinding`
equivalences. Every row of every independent view must be covered by the source
guard; PDF/XML amounts are compared rather than added. Coding candidates from
all bound row/header views reach consensus before the coding engine is called.
No primary attachment overrides a contradictory companion's account, code or
cost object. Explicit unknown document coding does not fall back to a vendor.
Observed line VAT also reaches consensus across bound views, independently of
the aggregate header tax. Failed/unclassified companion sources or unresolved
financial-source diagnostics block monetary READY while preserving the request.

The adapter reuses `CodingCatalog.resolve`/`order_record` and the existing
`ValuationLine`, `TaxLine`, `WithholdingBase` and `CodedAPLine` contracts. The
active phase's masters validate supplier affiliations, expense/account existence,
tax country and CC/WBS ownership. Document/confirmed PO/default/history precedence
belongs to `CodingCatalog`. Contextual history is considered only with the
observed literal description and its project context. Conflicting or invalid
higher precedence fields remain unresolved.

An observed project name binds to an active company-scoped project ID through
`resolve_ap_project_binding` before creating `CodingQuery`. Exact names permit
only case/whitespace normalization and must be unique in that company. The source
name and invoice/ERP join evidence remain intact; missing or ambiguous bindings
stay `UNKNOWN` without substituting a PO/default project.

`calculate_ap_tax` and `calculate_ap_withholdings` run disposable mathematical
previews with the technical `POST` calculation parameter. This parameter grants
no policy decision and no result is committed. Their net/tax/gross must match
the independent printed header consensus; observed withholding, guarantee and
payable must agree too. Missing deductions are not defaulted to zero: a computed
zero comes from the resolved explicit withholding treatment/guarantee
non-applicability, with master and policy evidence retained. A printed payable
requires the observed `source_payable_basis` (`BEFORE_APPLIED_ADVANCES` or
`AFTER_APPLIED_ADVANCES`), even in this no-application increment.

`advance_plan` is currently `Fact(False, Evidence(...))`, an upstream explicitly
evidenced statement that this invoice applies no advance. Missing/unknown
applicability stays `UNKNOWN`; `True` is `UNSUPPORTED`. An observed nonzero or
unresolved `advance_amount_cents`, or an opposed `advance_applicable`, contradicts
that no-application plan. The
adapter neither reconstructs nor resets `AdvanceState`; the phase runner must
retain its opening baseline, used amounts, credit reservations, events and
publications. Positive 407 applications and their classification/bindings remain
a later increment.

For a demonstrated applicable guarantee, supply
`APGuaranteePostingPlan(base_doc: Fact, contract_reference: Fact)`. In v1 both
Facts must match the accepted financial header's `guarantee_base_cents` and
`contract_reference` candidates, share one source document, and identify an
eligible base no greater than net. The existing engine applies the contractual
5%. An external contract requiring separate scope/line resolution is not yet
supported. Absent guarantee applicability never means false.

Posting date is an explicit Fact within the active phase. No receipt visibility
cutoff is generated: the context's existing observed cutoff is preserved.
Document currency remains on the AP header. Local currency follows policy §1;
foreign previews require the exact active `RateTable`, selecting the invoice
date or the latest published earlier observation. FX evidence retains the exact
source row. Supplied coding/tax/withholding/FX catalog behavior must agree with
the active phase for every used treatment. ERP/master hashes are pinned and
verified again before READY; a stale input snapshot is unresolved.
Close-task, supplementary-master and used FX paths are validated with the source
loader's phase guard before fresh `PhaseData` construction or file reads. Hash
revalidation repeats the path guard, so a symlink redirected outside the active
phase or toward Golden never becomes a readable posting source.

DUA/import postings, credit notes, positive advances and source rows split over
several PO positions are explicitly unsupported. The adapter does not invent
splits, recover corrupted PO references or choose fiscal treatment from a VAT
percentage alone. Applicability, duplicate/event inventory completeness and
payment decisions remain with the phase planner and coordinator.

Focused synthetic tests use arbitrary 2044 dates and opaque identities. They
connect READY inputs to the real coordinator, cover early wrong-addressee
rejection and ordered quantity/price HOLDs, independent-source coding conflicts,
foreign cost/tax dimensions, exact historical FX selection, withholding/guarantee
observations, missing facts/masters and immutable exhausted advance state.
