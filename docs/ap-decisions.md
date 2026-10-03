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
