# M4-04 partial receipts and promissory notes

## Application rules

A cash receipt smaller than the balance is applied only when exactly one due receivable remains possible for the identified customer, company, and currency. The uncollected portion stays open; the solver does not invent a penalty or settle the full invoice.

A note is applied only after its maturity date and when its 431 open item is positive as of the receipt date. The adjustment credits 431 with assignment `PAG<number>`; the underlying invoice in 430 is not credited a second time.

## Regression evidence

- A unique 8,000-cent payment applies partially to a 10,000-cent invoice, leaving the other 2,000 cents open.
- A matured note clears the 431 assignment and balances against 555.
- The same note remains unapplied one day before maturity, even when the receipt equals its face value.
- Existing timeline tests ensure each receipt consumes an open item only once.

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ar_cash*.py' -v
```

## Phase validation

The July development submission remains structurally valid. No matured promissory note is applied in the July task rows, so the maturity behavior is covered by the synthetic boundary tests rather than claimed as a phase example. The official AR Cash score is **0.8922** (27/32 fully correct); these changes introduce no new mismatches. Other unresolved application cases remain covered by #80 and #82–#83. Issue #81 depends on #80 and stays open until that dependency is complete.
