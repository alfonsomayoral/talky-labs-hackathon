# Receipt allocation core — partial #44

`kalmora.ap_allocation.allocate_receipts` accepts explicit invoice quantities,
resolved PO portions, PO units, receipt candidates (GR or service SES), and an
immutable `ConsumptionState`. No extraction or ERP access occurs in this module.
Quantities use integer thousandths; floats, booleans and nonpositive quantities
are rejected. Convert source quantities with M0 `quantity_milli` if necessary.

## Inputs and result

- `OrderKey` includes company, vendor, currency, PO and position. An invoice can
  contain multiple PO portions; their quantities must sum to its line quantity.
- `InvoiceQuantityLine.references_resolved=False` explicitly represents ambiguity.
  Empty portions represent an absent reference. This kernel never chooses a PO.
- `OrderPortion.receipt_ids` limits supply to explicitly referenced receipts.
  Without this list, supplied eligible receipts are preferred by posting date and
  receipt ID. An integer capacity flow can reassign tentative quantities within
  resolved candidate edges to honor overlapping explicit references. Thus an
  earlier flexible line cannot incorrectly starve a later restricted line. Stable
  flow traversal is an implementation convention, not a policy rule.
- `Receipt.key` is company plus receipt ID; duplicates in that company fail even
  if they claim different vendors, currencies or PO positions.
- `ALLOCATED` returns receipt-level quantities and a new state. `BLOCKED` returns
  diagnostics, no allocations and the original state. All invoice lines succeed
  together or none consume supply. Partial receipts can satisfy partial invoices.
- `INSUFFICIENT_RECEIPTS` reports requested and achievable quantities for the
  deficient portion after competing invoice portions share receipt capacity.
  Other codes distinguish unknown references, scope/unit mismatches, unresolved
  ambiguity, malformed portions, and a previously allocated invoice key.

Policy authority: `POLITICAS_CONTABLES.md` §§1, 2.2 (`QTY_NOT_RECEIVED`) and 2.3
(invoice quantity against receipts). The module's diagnostics are internal facts,
not AP decisions or delivery reason codes. Quantity conservation and receipt
non-reuse are explicit #44 requirements.

## Integration still required

#43 must recover and confirm references, split MULTI_PO quantities, resolve units
and supply receipts eligible for the invoice date. The historical adapter must
seed consumption from already invoiced receipts and provide the catalog covering
every prior usage. Missing historical receipts are rejected instead of resetting
consumption. Persist snapshots outside this pure module and serialize concurrent
updates; a stale snapshot must never overwrite newer consumption.

Allocate tentatively, then retain the returned state only when #45/#49/#50/#51
and posting succeed. Rejected/held documents must retain the old snapshot. #51
consumes the allocation result and explicit PO prices. Credit-note releases and
receipt reversals require an integration policy and are deliberately unsupported;
negative quantities cannot silently restore supply. #32 owns output adaptation.

The synthetic tests calculate quantities independently and read no package or
golden data. This partial core does not complete the original issue.
