# HOLD gates on July 2026 (#49)

`ap_hold_sources.resolve_hold_sources(doc_id, documents, message, data, notices, state)`
binds one task's INVOICE attachments (CFDI XML + PDF are merged), its `message.json`
and the phase masters to `ap_holds.evaluate_holds`. It reuses `resolve_ap_identity`
(#42), `invoice_events` + `event_support_facts` (#46), `POCatalog` (#43) and
`allocate_receipts` (#44). It never reads golden and never commits consumption.

Source decisions:

- **Vendor:** the identity binding's vendor; a tax ID `NOT_FOUND` in the master is
  `VENDOR_NOT_IN_MASTER`.
- **Bank:** invoice `iban` against the master `bank.iban`, `clabe` or `account`. An
  observed absence, or a parsed XML e-invoice without PaymentDetails, cannot differ.
  For a differing account, a signed letter or factor support comes from the month's
  notices, an inventory declared complete. A letter is verified only when its sender
  is the vendor's registered address (#46).
- **Domain:** the sender domain is a look-alike of the master email domain when the
  two differ but one label contains the other, the label is equal under another TLD,
  or `SequenceMatcher` ≥ 0.8. A domain that is merely different is not a look-alike.
- **Receipts:** for vendors with `po_required`, an invoiced albarán (`delivery_reference`,
  `receipt_reference`, Facturae delivery notes; a trailing `(dd/mm)` is stripped) with
  no goods receipt of that vendor in the ERP by the **month end** is `QTY_NOT_RECEIVED`.
  Otherwise each line resolves its PO position and is allocated atomically. When the
  invoice unit is absent, the PO's single unit applies. When positions are ambiguous,
  the PO item whose text starts the printed concept is selected.
- **Price:** invoice `unit_price_e4/100` against the PO unit price, using the merged
  strict >2% / >EUR 150 rule with SYN-BCE FX at the invoice date.

Cutoff: the arrival-date cutoff produced false `QTY_NOT_RECEIVED` on API004204 and
API004217, where receipts were posted in July after the invoice arrived. Policy §2.2
only says the albarán "no tiene entrada de mercancía", without an arrival bound. The
close therefore sees July receipts up to month end.

## July result (305 tasks, replay only)

| Group | Count |
| --- | --- |
| Golden HOLD, same reason | 16 / 19 |
| Golden HOLD, missed | 3 |
| Golden POST, predicted HOLD (false hold) | 1 |
| Golden POST, CLEAR | 120 |
| Golden POST, UNKNOWN (insufficient evidence) | 94 |
| Golden POST, no INVOICE facts (extraction error/classification) | 27 |

By reason: VENDOR_NOT_IN_MASTER 2/2, BANK_DETAILS_CHANGED 1/2, QTY_NOT_RECEIVED 8/9,
PRICE_VARIANCE 5/6. DUPLICATE/REJECT tasks are decided earlier. The gates also predict
one HOLD in each of those groups, but that HOLD is never emitted.

Explained mismatches:

- **API004126** (QTY, predicted CLEAR): the Facturae XML carries the albarán only
  inside the free-text item description. The XML extractor yields no delivery
  reference, and the PO position has enough receipts.
- **API004214** (PRICE, UNKNOWN): the lines print no concept or item, and the PO has
  several items with the same unit. The position stays ambiguous, and it is not
  matched by price.
- **API005230** (BANK, predicted CLEAR): a Facturae without PaymentDetails or sender,
  and no notice exists for the vendor. The sources show no bank evidence.
- **API004204** (golden POST, predicted QTY): albarán AL-086421 (dated 31/07) has
  no goods receipt in the ERP. The policy literal gives HOLD; golden posts it.

UNKNOWN on POST invoices (94) comes from extraction gaps: line quantities missing
(45), invoice date/company missing (18), CFDI/PDF without an extracted IBAN (19), and
PO positions unconfirmed, conflicting or not found (12). They are never turned into
CLEAR or HOLD.

Reproduce (replay only; golden is read only by this evaluation tool):

```
PYTHONPATH=src .venv/bin/python tools/validate_ap_holds_july.py \
  --phase /Users/alfonsomayoral/Talky/participant/phase_dev \
  --state /Users/alfonsomayoral/Talky/.kalmora-cache/july
```
