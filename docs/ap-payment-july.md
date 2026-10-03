# AP payment metadata: July replay (#50)

`tools/validate_ap_payment_july.py` replays the recorded July extraction
(`load_ap_sources`, no network) and compares the results with
`golden/ap.jsonl`. Only this tool reads golden data. Notices are bound by
`ap_chronology_sources.notice_events`, scope by `ap_identity_sources`, and
payment metadata by `ap_payment_sources`. Duplicates, rejections and holds
are passed as CLEAR, so the tool measures only `payment_block`/`payee` and
the NOT_INVOICE actions.

| Check | Match | Mismatch | Unknown |
|---|---|---|---|
| NOT_INVOICE action (12 golden) | 11 | 1 | — |
| payment_block + payee (305 tasks) | 283 | 0 | 22 |

The FACTOR payee (API004175, V100092 registered factor) and all 282 null
cases match. July has no expired certificate or embargo case; the synthetic
tests cover those rules.

Unexplained mismatches: none. The gaps are all upstream unknowns:

- **1 action.** API005600 (art. 43 certificate) failed extraction. The bank
  letter API005195 is typed from its `notice_type_hint` and emits
  UPDATE_BANK_DETAILS.
- **20 payment unknowns.** Attachments that failed extraction or were
  classified UNKNOWN, so there is no document type.
- **2 payment unknowns.** API005601 and API005602 have no resolved
  company/vendor scope.

Inference used for completeness: an unclassified document hides a notice
only for the kinds its literal subject could name. An invoicing subject
(`factura*`, `FRA`) hides none. The hidden notice applies only to the
document's sender-resolved vendor, or to every vendor if that is unknown,
and only to invoices received after it. Absence is proved only for the
remaining kinds.

Day/month-ambiguous invoice dates are evaluated under both readings. They
count only when both give the same result.

Reproduce:

```
PYTHONPATH=src .venv/bin/python tools/validate_ap_payment_july.py
```
