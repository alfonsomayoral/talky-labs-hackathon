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

A task that cannot be bound (15 failed PDF extractions, untyped PDFs, missing
facts) is reported as `UNKNOWN DUPLICATE_FACTS_UNBOUND`. It blocks a `CLEAR`
only for documents it could precede: those with the same or an unknown vendor,
received at or after it. `statuses` carries upstream month decisions (for
example REJECT from #48). Without it, every month document counts as RECEIVED.

## Result (305 tasks, 14 golden duplicates)

| Outcome | Count |
| --- | --- |
| Predicted `DUPLICATE` | 16 |
| Correct, with the same `duplicate_of` | 9 |
| False duplicates | 7 |
| Missed duplicates | 5 |
| `CLEAR` | 113 |
| `UNKNOWN` | 166 |
| Out of scope (non-invoice type) | 10 |

Most `UNKNOWN` results (113) are blocked by an earlier unbound task whose vendor
is unknown.

### Explained mismatches

- **API004206, 004323, 004466, 004480: false duplicates.** Each is a corrected
  reissue of an earlier July original (API005226, 005228, 005225, 005220) that
  golden rejects, with the same number and gross. These clear once the #48
  REJECT reaches `statuses`. The engine then returns UNKNOWN: the correction
  link is not explicit.
- **API004468 / API005203 (false + missed) and API005197 → API004288 (missed).**
  Golden names the lower `doc_id` as the first document, even though the copy
  was received earlier (05203 on 07-08 vs 04468 on 07-20; 05197 on 07-13 vs
  04288 on 07-17). The binding follows policy reception order. API005197 is also
  untyped and has no currency.
- **API005229, API005230: false duplicates.** These are resends of API004180 and
  API004112 with changed bank details. Golden holds them as
  `BANK_DETAILS_CHANGED`, ahead of the duplicate check that the policy order
  places first.
- **API005205: missed.** Its gross (9 789,98) differs from the original
  API004302 (9 808,24). The policy duplicate test requires equal amounts.
- **API005208: missed.** The original API004305 PDF has no currency fact, so the
  engine cannot compare scopes.
- **API005206: missed.** The PDF replay yields no facts.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python tools/validate_ap_duplicates_july.py \
  --phase ../participant/phase_dev --state ../.kalmora-cache/july
```

The script is replay-only and runs in about 5 s. Only it reads `golden/ap.jsonl`.
