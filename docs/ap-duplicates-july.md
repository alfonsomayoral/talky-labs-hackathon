# AP duplicates on July (#47)

`ap_duplicate_sources.month_duplicate_results(tasks, data, statuses=None)` binds
the replayed July sources (`documents.ap_sources.load_ap_sources`) and ERP
history (`registered_duplicate_records`) to `ap_duplicates.duplicate_result`.
Per task it uses the attachments whose classified types agree. Number, currency,
gross (or net + tax) and service period are used only when all candidates
agree. Vendor and company come from `resolve_ap_identity`, and reception from
`message.received_at`. The binding never reads golden data.

Engine changes made for this binding:

- **Service period.** ERP history never records one. Only two distinct explicit
  periods exclude a match, and a missing period no longer blocks.
- **Number prefix.** The letter prefix before the first digit is dropped (policy
  §2.1 "sin prefijos"). Four July resends add `F-` to the number.

If the document has no currency fact, the vendor master `currency` is used
for the amount comparison, with the master as evidence (§1 "la ficha manda").
A DUPLICATE match that does not establish the same supplier (§2.2.1 "mismo
proveedor") becomes `UNKNOWN DUPLICATE_FRAUD_SIGNAL:<SENDER_DOMAIN|IBAN>:<original>`,
so the HOLD stage decides. That happens when the sender's domain differs from
the vendor master's email domain, or when the document's IBAN is neither the
master IBAN nor the original's.

A task that cannot be bound (15 failed PDF extractions, untyped PDFs, missing
facts) is reported as `UNKNOWN DUPLICATE_FACTS_UNBOUND`. It blocks a `CLEAR`
only for documents it could precede: those with the same or an unknown vendor,
received at or after it. `statuses` carries upstream month decisions (REJECT
from #48, stacked on this branch). Without it, every month document counts as
RECEIVED.

## Result (305 tasks, 14 golden duplicates, `statuses` not supplied)

| Outcome | Count |
| --- | --- |
| Predicted `DUPLICATE` | 19 |
| Correct, with the same `duplicate_of` | 10 |
| False duplicates | 9 |
| Missed duplicates | 4 |
| `CLEAR` | 120 |
| `UNKNOWN` | 156 |
| Out of scope (non-invoice type) | 10 |

### Explained mismatches

- **API004206, 004242, 004323, 004466, 004478, 004480: false duplicates
  pending #48.** Each is a corrected reissue of an earlier July original
  (API005226, 005223, 005228, 005225, 005219, 005220) that golden rejects, with
  the same number and gross. Once #48's REJECT reaches `statuses`, the engine
  returns UNKNOWN instead: the correction link is not explicit. That leaves 3
  false duplicates.
- **Known divergence, kept by policy: API004468 / API005203 (false + missed)
  and API005197 → API004288 (missed).** Golden names the lower `doc_id` as the
  first document, even though the copy was received earlier (05203 on 07-08 vs
  04468 on 07-20; 05197 on 07-13 vs 04288 on 07-17). The binding follows
  policy reception order. API005197 is also untyped.
- **API005224: false duplicate.** It is a later copy of API004222. Golden
  rejects it as `MANDATORY_FIELD_MISSING` (the copy lacks the recipient NIF)
  rather than treating it as a duplicate.
- **API005230: false duplicate.** Golden holds it as `BANK_DETAILS_CHANGED`,
  but its Facturae XML is byte-identical to API004112. It has no IBAN and no
  sender, so the task itself carries no supplier signal. API005229, by
  contrast, now gets `DUPLICATE_FRAUD_SIGNAL:SENDER_DOMAIN` from its
  look-alike sender domain.
- **API005205: missed.** Its gross (9 789,98) differs from the original
  API004302 (9 808,24). The policy duplicate test requires equal amounts.
- **API005206: missed.** The PDF replay yields no facts.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python tools/validate_ap_duplicates_july.py \
  --phase ../participant/phase_dev --state ../.kalmora-cache/july
```

The script is replay-only and runs in about 5 s. Only it reads `golden/ap.jsonl`.
