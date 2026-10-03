# M4-02 receivable availability by date

## Rule

AR balances are replayed from posted journal lines, in posting-date order, as each receipt's value date is reached. Applications proposed earlier in the same run reduce the remaining projected balance, so an item cannot be consumed twice. A later posting cannot make an invoice available to an earlier receipt.

If an invoice master row is absent but the bank narrative contains one explicit invoice reference, the engine can resolve it only against a positive 430 open item already posted by that receipt date, in the same company, customer, assignment, and currency. It never selects an item by amount alone. Unsupported references remain unapplied.

## Regression evidence

- A receipt on 2 July remains unapplied when its invoice is posted on 3 July, even though that item exists later in the month.
- A dated 430 open item with a matching explicit bank reference can be applied when the invoice master row is absent.
- The existing two-receipt regression applies the open item once and classifies the second receipt as an overpayment duplicate.

Run:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
```

## Phase validation

The July development run still emits 32 rows, with 27 correct applications and 5 unresolved. The official score remains **0.8922**. The 5 evaluator differences are unchanged: `BL0000201`, `BL0000276`, `BL0000544`, `BL0000567`, and `BL0000707`. `BL0000544` remains unresolved because the current solver-visible dated AR items do not provide a positive matching open item; invoice/reference candidate matching is followed up under M4-03 (#80). Grouped applications and the netting/duplicate cases are handled by their dependent issues. No balance is fabricated to improve the score.
