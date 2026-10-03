# AP source line binding

`kalmora.ap_line_source_bridge` checks that posting line inputs are supported by
the independent normalized financial attachments supplied as `amount_sources`.
It does not read files, invoke a provider, decide eligibility or publish state.

```python
result = validate_ap_line_sources(
    bindings=(APLineSourceBinding("posting-row", "inbox/ap/T/invoice.pdf", 1),),
    amount_sources=normalized_financial_facts,
    valuation_lines=posting.valuation_lines,
    quantity_lines=posting.quantity_lines,
    price_lines=observed_price_lines,
    currency=posting.header.currency,
    amounts_required=True,
)
```

The signature also accepts optional `views` containing `APLineFacts`. Those
views must match the actual source path, one-based index, complete field
candidate lists, value types and evidence in the accepted `DocumentFacts`.
The bridge rebuilds its authoritative views from the supplied sources; an
invented line object cannot override extraction observations.

Each posting line needs an explicit binding. Every source row in every
financial attachment must be covered exactly once, and the same source/index
cannot be assigned to several posting lines. Two equivalent PDF/XML rows may
bind to one posting line, even at different indices. Their amounts are compared
independently and never added together. Missing row bindings, index gaps,
explicit row counts that exceed the observations, and unavailable line
inventories produce `UNKNOWN`; no line is manufactured from header totals.
Two different rows of the same attachment cannot be merged into one posting
line, even when they have equal amounts.

`quantity_milli` and unit are checked when a quantity input consumes receipts.
A priced or quantified valuation also needs an observed quantity. Invoice
unit price is compared as exact decimal cents from normalized `unit_price_e4`;
the conversion does not round or divide the source net by quantity. Fields
reach consensus across the views explicitly bound to the same posting line.
For example, an unobserved unit in XML remains unknown in that source view,
while the corresponding PDF's observed unit can support the posting. Different
source values remain `UNKNOWN`, without selecting a preferred attachment.

Observed `net_cents` is the net posting basis. It remains distinct from an
`amount_cents` before discounts. When no net observation exists, the observed
line amount can supply the basis if it is not accompanied by a nonzero or
unresolved discount. The bridge never subtracts a discount or infers
quantity-times-price equals net. A before-discount amount accompanied by a
discount but no explicit net keeps the net unresolved.

`amounts_required=False` allows the ordered coordinator to check quantities
before line amounts or prices are available. Supplying `price_lines=()` does
not require a unit price. After quantity clearance, a price phase can pass
price inputs with `amounts_required=False`. Immediately before posting,
`amounts_required=True` requires a net amount for each independent view. A
known net contradicted by caller inputs raises `ValueError` in every phase.
Direct expense lines without receipt quantities or price checks do not need
source quantity, unit or unit price.

When observed, source row/document currencies must agree with the supplied
posting currency. Missing currency is preserved and never defaulted. The
coordinator remains responsible for the invoice header's identity, fiscal
date, currency and number, policy precedence, allocation, FX and journal
validation.

Results expose `status` (`CLEAR` or `UNKNOWN`), all used `Evidence`, compact
diagnostics, bindings, independent source views, hashes and bridge version.
Missing/contradictory required facts produce `UNKNOWN`; resolved facts that
contradict caller amounts, quantities, units or checked prices raise
`ValueError`. Synthetic tests include the previously observed price-variance
evasion and partial-quantity allocation, independent views, provenance,
coverage, discounts and ordered quantity/price stages.
