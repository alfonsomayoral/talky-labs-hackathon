# Deterministic AP rejection checks (#48)

`ap_rejections.evaluate_rejections(fields)` computes the eight invoice rejection
conditions in policy §2.2 order. `fields` maps the names below to sequences of M0
`Fact(value, Evidence(...))`. The caller supplies independently extracted and
master-resolved facts; this module does not extract, infer identities, read ERP,
read golden data, serialize an AP answer or create an entry. It applies to
ordinary invoices; document-type dispatch, duplicates and posting are separate.

| Rule | Explicit inputs |
| --- | --- |
| Missing mandatory field | `recipient_nif` (text; observed `None`/blank means absent) |
| Wrong addressee | `recipient_company`, `order_company` (resolved legal entities, including 1910/1100) |
| ISP not applied | `isp_required` boolean; `charged_vat_cents` |
| Incorrect VAT | `vat_check_applicable` boolean; `vat_lines` list of `{applied_rate, applicable_rate}` fractions |
| Missing withholding | `withholding_required` boolean; `withholding_cents` |
| Arithmetic | `net_cents`, `tax_cents`, `gross_cents` in one document currency |
| Cumulative billed | `certification_applicable`; `billed_net_cents`, `certification_current_cents`, `certification_cumulative_cents` |
| CFDI mismatch | `cfdi_applicable`; independent `cfdi_pdf`/`cfdi_xml` dictionaries |

The adapter must declare non-applicability explicitly (e.g. exempt VAT or a
non-CFDI invoice). No missing field becomes `False`. Equal source candidates
resolve together; contradictory candidates remain unknown and retain all proof.
Invalid input types produce a diagnostic and unknown rule. `RuleCheck.violation`
is `True`, `False`, or `None`. Known checks require evidence, including evidence
supporting non-applicability. Checks retain the original document/field/page.

`RuleStage` contains `status`, `reason`, and all ordered `checks`. The internal
status `UNKNOWN` means the caller needs more evidence; it is **not** a new
`ap.jsonl` decision. The first unknown stops progression just as an earlier
violation takes precedence. A `CLEAR` result means only rejection gates passed;
the caller must first clear duplicate detection and then evaluate HOLD/payment
rules. A known later mismatch cannot override an earlier unresolved rule.

`spanish_standard_vat_rate(Fact(activity, evidence))` implements 10% for explicitly
classified waste collection/treatment, street cleaning and water, and 21% for
explicit `OTHER_STANDARD`. It refuses unknown, exempt, reverse-charge or foreign
regimes. Applicable rates for other regimes come from their explicit policy and
tax adapters. Mixed VAT lines are checked individually. Amounts use exact integer
document cents; arithmetic checks gross = base + VAT before withholding,
guarantee and advance deductions. Billing the first certification, where current
and cumulative coincide, is not cumulative overbilling.

CFDI comparison covers number, date, issuer/recipient tax IDs, currency, net,
tax and gross. A difference in any known independently extracted pair proves
mismatch. Equality requires all pairs; absent values cannot prove equality.
Do not manufacture a PDF view from the XML or silently choose between competing
extractions. Further normalization/source adaptation belongs to #41.

Validation uses synthetic facts, all eight reasons, ordering, absent/conflicting
facts, malformed values, mixed rates, first certifications and incomplete CFDIs.
July extraction and final output integration remain dependencies (#41–#43/#47
and #32); this isolated rule core does not certify the July milestone.

## HOLD gates (#49)

`ap_holds.evaluate_holds(fields, quantity_check=..., price_check=...)` evaluates
vendor absence, bank safety, receipt quantity, then price variance. Call it only
after duplicate and rejection stages are known clear. `fields` uses the same M0
candidate sequences, with explicit booleans `vendor_in_master`, `bank_differs`,
`signed_change_supported`, `factoring_supported`, `similar_domain`,
`quantity_check_applicable`, and `price_check_applicable`. A supplier disabled for
one company is not automatically absent from the vendor master.

Bank safety follows three-valued logic:
`similar_domain OR (bank_differs AND NOT(signed_change_supported OR factoring_supported))`.
No similar-domain detector is invented here. Domain similarity is supplied with
explicit evidence. A signed change must support the actual invoice IBAN, company,
vendor and applicable chronology. Factoring support likewise requires the invoice
IBAN to match the evidenced factor account; active factoring cannot approve an
arbitrary IBAN. `ap_chronology.event_support_facts` provides those temporal support
predicates. Missing support remains unknown unless the source inventory is known
complete. An unchanged IBAN can clear the bank branch despite missing letters;
a similar-domain flag still triggers HOLD even when an IBAN change is supported.

`receipt_quantity_check(HoldScope(...), allocation, evidence=..., catalog_complete=Fact(...))`
consumes #44's `AllocationResult`. Complete allocation proves receipt coverage;
`INSUFFICIENT_RECEIPTS` proves shortage only with an explicitly complete eligible
receipt catalog. Reference ambiguity, incorrect references, units, replay and
scope problems remain unresolved diagnostics, rather than fabricated shortage.
The result's scope must match all four invoice dimensions. Neither check commits
the allocator's provisional consumption snapshot. Commit it only after every
eligibility gate and posting succeed; blocked invoices preserve prior state.

`price_variance_check(scope, invoice_date_fact, lines, allocation=..., rates=..., rate_evidence=...)`
uses `PriceLine(line_id, invoice_unit_price_cents_facts, portions)` and
`PricePortion(OrderKey, quantity_milli, po_unit_price_cents_facts)`. Unit prices
are exact Decimal/text/integer document cents per unit; quantities are thousandths.
Price portions must cover exactly the #44 allocation by original line and PO
position. Receipt fragmentation cannot change the price check. The comparison
does not aggregate unrelated invoice lines.

The policy's **strict** percentage test is `invoice_price * 100 > PO_price * 102`
for each PO portion. The EUR test sums signed quantity × unit-price differences
for each original invoice line. Favorable differences reduce that line's monetary
difference; they cannot erase an independently excessive unit-price percentage.
Zero-priced order lines with a positive invoice price exceed percentage tolerance.
Equality at 2% or EUR 150 is allowed; either excess is sufficient for HOLD.

For other currencies the EUR 150 threshold remains EUR, including company 3100
whose local currency is MXN. Use M0 `RateTable.as_of(invoice_date, document_currency)`:
SYN-BCE units of document currency per EUR, latest publication on/before invoice
date. Compare `line_difference_document_cents > 15000 * rate` directly. This avoids
rounding the converted amount before checking a strict threshold. It is equivalent
to converting to EUR exactly; posting still uses the separate per-line cent
rounding convention. Future rates, unsupported rates, missing rate evidence and
conflicting prices cannot clear the gate. A proved percentage excess suffices
without FX. Each computation retains date, price and rate source evidence.

HOLD tests cover all four reasons/order, all 81 bank truth-table combinations,
atomic shortages, unresolved references, 2%/EUR150 equality and smallest excesses,
EUR/USD/MXN, invoice-date FX fallback, missing/future FX, multi-PO invoices,
receipt fragmentation, and company/vendor/currency isolation.
