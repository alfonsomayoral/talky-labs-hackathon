# AP rejections — July validation (#48)

`ap_rejection_sources.rejection_stage(sources, message, data)` binds one invoice's
normalized attachments (`invoice_sources(task.attachments)` from the replay loader),
the M1-04 identity binding and the ERP masters to the eight ordered rejection gates.
Only `tools/validate_ap_rejections_july.py` reads `golden/`, as evaluation.

Reproduce (replay only, no provider calls):

```
PYTHONPATH=src .venv/bin/python tools/validate_ap_rejections_july.py \
  participant/phase_dev .kalmora-cache/july [--details]
```

## Result over the 305 July tasks

| Outcome | Tasks |
| --- | --- |
| Golden REJECT matched (decision and reason) | 13 / 18 |
| Golden REJECT missed (stage UNKNOWN or CLEAR) | 5 |
| False REJECT on non-rejected tasks | 0 |
| Non-rejected, gates CLEAR | 223 |
| Non-rejected, stage UNKNOWN (missing prerequisite) | 21 |
| No invoice-classified attachment | 26 |
| Every invoice attachment failed extraction | 15 |
| VENDOR_NOT_IN_MASTER (HOLD, identity scope; stage UNKNOWN) | 2 |

By reason: ISP_NOT_APPLIED 3/3, VAT_RATE_INCORRECT 3/3, ARITHMETIC_ERROR 2/2,
CERTIFICATION_CUMULATIVE_BILLED 2/2, CFDI_MISMATCH 1/1, WRONG_ADDRESSEE 2/3,
MANDATORY_FIELD_MISSING 0/2, WITHHOLDING_MISSING 0/2.

## Binding decisions July exposed

- Applicable VAT: PO item tax codes, else vendor default (policy §1). A code of
  another country than the posting company (ES group company → PT company) is a
  cross-border case, not a rate check.
- Only invoice-level rates count; a PDF line rate such as the 5.11 % electricity tax
  is not VAT. A 0 % component beside charged VAT (canon, tasas, suplidos) is a
  non-subject levy, and its zero quota does not contradict the charged one.
- Withholding and previous-certification amounts printed as `-x` are deductions.
- PDF net falls back to the sum of every line when the header base is not printed.
- XML gross is InvoiceTotal/Total plus withholding. Arithmetic is checked on the
  PDF when one exists; its XML twin is compared under CFDI_MISMATCH.
- Rule fix: cumulative billing compares the billed net with the certified totals
  by proximity. Billed lines are rounded on their own and differed by 1–4 cents
  from the "a origen" total in both July cases.

## Remaining mismatches

- API005223, API005224 (MANDATORY_FIELD_MISSING): the PDF shows no recipient NIF,
  but the extraction neither observed it nor recorded an explicit MISSING unknown.
  The gate stays UNKNOWN by contract.
- API005219 (WITHHOLDING_MISSING): the notary PDF extraction has no base, VAT or rate,
  so the earlier VAT gate is unknown.
- API005220 (WITHHOLDING_MISSING): the rent PDF prints no withholding or payable line.
  An absent line is not an explicit absence, so the gate stays UNKNOWN.
- API005227 (WRONG_ADDRESSEE): an electricity invoice without a PO, addressed to UTE
  1910, a company the vendor serves. No document or master evidence names another
  ordering company. Supply-contract ownership is not in the package.

The 21 non-rejected UNKNOWN stages are missing prerequisites, not errors:
- 6 CFDI PDFs omit the currency or date needed for a complete comparison.
- 6 works-subcontractor invoices carry no certification breakdown.
- 6 invoices print no VAT rate.
- 3 carry no observable withholding.
