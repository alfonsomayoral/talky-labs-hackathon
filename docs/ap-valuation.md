# Net AP valuation core — partial #51

`kalmora.ap_valuation.value_ap_lines` accepts an explicit AP `decision`, invoice
scope/date, `ValuationLine` amounts in document cents, company-owned cost coding,
the #44 allocation result, explicit `OrderPrice` values and M0 `RateTable` for FX.
It returns typed net posting components, not a final AP JSONL or journal entry.

Policy authority: `POLITICAS_CONTABLES.md` §§1 and 2.3. A matched line debits the
explicit GR/IR account (policy account 40090000) at quantity × PO price,
with vendor partner. Its signed price difference uses the supplied expense/asset
account and exactly one cost center or WBS. A direct line without PO uses that
account and cost object for its full net. Favorable differences are credits.

Quantities are summed per invoice line and PO position before `line_amount`
rounding. This documented component convention makes value independent of receipt
fragmentation. Each posting component converts separately at the invoice-date FX
rate (last available), using M0 money functions. `net_local` sums those rounded
components so the later supplier settlement can absorb conversion differences.
`net_doc` equals both invoice-line total and signed component total. Currency and
company are never combined across invoices. Scope and quantity mismatches fail.

`VALUED` requires the upstream POST or POST_PAYMENT_BLOCK decision. Other valid
decisions return `INELIGIBLE` with no components; missing/blocked allocations return
`UNALLOCATED`. No price tolerance, tax, fraud, certificate or payee rule is inferred.
Input net values are unsigned document cents. #54 reverses eligible credit-note
debit/credit sides after validating the original imputation and fiscal evidence.
Master existence and cost-object ownership must be validated by the caller using
M0 validation; the core checks the explicit assignment's company and exclusivity.

## Integration boundaries

- #43/#44 adapters provide resolved quantities and historical consumption.
- #45 supplies expense/asset accounts and company-owned cost objects through
  the deterministic coding resolver; recovery remains outside valuation.
- #49/#50 supply eligibility and price-tolerance/payment-block decisions. Retain
  tentative #44 state only after every posting stage succeeds.
- #52/#53 supply fiscal components; #54 assembles complete scoped journals with
  credits and advances. They use `net_local` as the posting contribution rather
  than independently converting its total.
- #55 exports validated delivery rows. #140 binds documentary facts to these
  interfaces and owns full-phase coverage and final evaluation.

Synthetic tests compose a net-only supplier fixture and validate Debe/Haber with
M0. They cover fragmented receipts, multiple prices, signed differences, direct
expense/asset coding, FX boundaries and scope isolation, without reading golden.
