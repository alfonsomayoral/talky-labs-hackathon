# M4-03 exact and grouped applications

## Resolution rule

The solver accepts one exact invoice reference, a unique exact single amount, or the unique subset of due open invoices whose balances equal the receipt. Candidate invoices are restricted to the receipt's company, customer, currency, value date, and positive ERP balance. A receipt is left unapplied when several invoice sets have the same exact total; the source policy does not establish an oldest-invoice-first rule.

## July development evidence

The 27 existing applications remain unchanged. Two evaluator differences are grouped receipts with multiple exact subsets in the structured source data:

- `BL0000201` has **three** possible due-invoice sets totaling 534,990.00 EUR.
- `BL0000276` has **three** possible due-invoice sets totaling 152,838.64 EUR.

Neither bank narrative nor an attached remittance supplies invoice references for those receipts. Selecting one set by age would add a rule absent from the package policy, so both remain unapplied with a diagnostic. This is an explicit abstention, not an amount mismatch.

The scorer remains **0.8922** (27/32 fully correct); the three other differences are tracked by the temporal-balance, netting, and duplicate/overpayment issues. The official scorer is used for this comparison; its golden data is not read by solver code.

## Validation

- A unique two-invoice subset is applied and creates balanced adjustment lines.
- A receipt with multiple exact subsets is left unapplied.
- Matching totals cannot override company or currency constraints.
- The existing ambiguity test continues to reject equal-value invoice candidates.

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
```
