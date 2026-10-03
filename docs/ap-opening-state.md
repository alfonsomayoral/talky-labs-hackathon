# Evidence-bound AP opening state — #54

`resolve_ap_opening_state(company, vendor, currency, as_of, journal_entries,
purchase_orders, vendors, ap_invoices, tax_catalog, inventory_complete)` connects
the recorded advance baseline to evidenced historical credit consumption.
Its default path proves **zero historical credit consumption**; optional
`historical_credit_inputs` reconstruct positive usage only from associated
credit/original facts, real components and a corroborated recorded KG. See
[credit history/restoration](ap-credit-restoration.md). All arguments are keyword-only. It returns a frozen
`APOpeningStateResolution`: `RESOLVED` with an `AdvanceState`, or `UNKNOWN` with
`state=None`, plus the requested `scope`, `cutoff`, evidence, diagnostics and
source-only `reference_entry_errors`.

Both `as_of` and `inventory_complete` require `Fact/Evidence`. The cutoff must
be an exact ISO posting date. Only the literal boolean `True` establishes
inventory completeness; false, unknown and nonboolean observations abstain.
The assertion covers registered AP documents, the complete journal including
manual movements, PO and vendor masters through the cutoff. It is a supplied
assertion, not a fact inferred from finding no rows in a filtered input.

Each input iterable is materialized and copied once before either analysis, so
one-shot generators cannot accidentally give the second analyzer an empty
inventory. The adapter calls `resolve_historical_advances` and retains its actual
document/local balances, cumulative consumption and source validation errors.
The complete journal is passed through: the public historical engine corroborates
ordinary posted AP headers even when no 407 is visible. A missing/dangling GL
link, observed application without 407, or contradictory posting clocks prevents
a usable balance; a header is never silently discarded in favor of GL absence.
An unresolved advance history never becomes an empty usable state.

For the requested society/vendor/document-currency scope, the adapter checks:

- Recorded AP `KG`, linked credit-note records and records with unknown AP kind.
- Potential manual reversals: supplier debits against credited expense, asset,
  GR/IR, VAT or advance components. Unknown relevant movement amounts abstain;
  a credit belonging to another supplier never offsets the requested supplier's
  debit. Cash received against credited expense/asset without an AP partner may
  also be a manual refund and abstains. Accounts must be eight decimal digits;
  all debit/credit observations must be nonnegative integer cents. Explicit
  `source=OPENING`, `doc_type=SA` identifies aggregate recorded opening balances,
  which do not constitute that cash-refund transaction. This distinction follows
  the recorded-journal contract (`model/journal_entry.py`, opening balances and
  general-ledger SA and literal `APERTURA` reference) and the original ERP's
  seven `OPENING/SA` records explicitly labeled as opening balances. The source
  reference corroborates this contract; it is not used as a matching heuristic.
  This classification never
  overrides linked AP credit evidence and never substitutes for complete period
  inventory. No ID, posting day or amount pattern establishes that classification.
  Ordinary cash settlement is not credit consumption. A favorable price
  difference with a credited supplier liability is not a supplier reversal.
- Company, partner, document currency, posting date and linked AP observations.
  Missing or contradictory relevant observations never select the less
  restrictive source. An exclusion needs a complete, concordant observation of
  another dimension, or concordant posting clocks strictly after cutoff.
- Explicit nonposting records with `journal_entry=None`, `posted_on=None`, a
  nonposting decision and a literal credit number. These do not consume only
  when the complete journal also contains no same-number posting in a potentially
  matching company. A dangling link or an absent field is not that proof.

Any uncovered historical credit or potential reversal in scope causes `UNKNOWN`,
even when the original invoice cannot be linked. Supplied historical credit
inputs must match the exact AP/GL link, original snapshot, clocks, dimensions and
signed cents before their positive bucket usage is retained. Missing evidence
never creates a positive baseline or clears another uncovered movement. It does not strip prefixes, associate credits by
amount, infer returned quantities, restore advances or restore receipt capacity.

The returned state contains the historical advance balances and **no new
events or publications**. Its `credits` retain the evidenced positive historical
usage, or empty usage proved for the returned scope and cutoff. Original-invoice snapshots and their SHA-bound
bucket capacities still belong to the original/credit engines. This result does
not authorize credit imputation, tax treatment or posting.

Initialize this baseline **once**, before processing new tasks. Do not call it to
reset consumption between documents. The caller preserves receipt consumption,
previous posted events, committed credit reservations and publications; it must
not replace an already evolving transaction state with a fresh opening state.
No `ap_transaction.py` behavior or contract is changed by this adapter.

```python
opening = resolve_ap_opening_state(
    company=company, vendor=vendor, currency=currency,
    as_of=cutoff_fact, inventory_complete=inventory_fact,
    journal_entries=journal_rows, purchase_orders=po_rows,
    vendors=vendor_rows, ap_invoices=invoice_rows, tax_catalog=tax_catalog,
)
if opening.status == "RESOLVED":
    # Only at initial construction; keep the independently evidenced receipt state.
    baseline = APTransactionState(consumption=receipt_baseline,
                                  advances=opening.state)
```

Focused synthetic tests cover incomplete evidence, unknown kinds/movement
amounts, unposted corroboration, linked scope/date contradictions, manual
reversals, source-only 407 diagnostics, cutoff boundaries, generators and
immutability. The opt-in original ERP regression proves empty credit history for
`1200/V100160/EUR` and `1200/V100145/EUR`, preserves the three exhausted foreign
advances of `1100/V100121/USD`, and abstains for a vendor with recorded KG.
It reads original ERP only; no golden, September data or provider call is used.

```sh
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp PYTHONPATH=src:tests \
  .venv/bin/python -m unittest test_ap_opening_state -v
```
