# AP chronology on July (#46)

`ap_chronology_sources.notice_events` turns each classified inbox notice into an
`ApEvent`: reception is the message `received_at`; vigency comes only from the
extracted facts (`certificate_valid_from/until`, `factoring_effective_date`,
`embargo_date`, `bank_details_effective_date`). Vendor/company come from
`resolve_ap_identity` (supplier or certified NIF, else exact sender domain);
certificates apply to every company of the vendor. A bank letter is verified
only when its sender domain equals the vendor master email domain.
`invoice_events` adds the ERP history (`registered_events`: certificates,
registered factor, garnishments) and calls `invoice_state`. Tie-break: reception,
validity start, event ID (`doc_id/attachment`). A garnishment registered in the
master snapshot applies to invoices dated on/after its `from_date`.

## Result (replay, 305 tasks)

`tools/validate_ap_chronology_july.py` predicts payee/payment_block with complete
inventory = ERP snapshot + all month notices, then compares with `golden/ap.jsonl`.

| | tasks |
|---|---|
| posted, match | 202 |
| posted, unknown | 40 |
| other decision (duplicate/reject/hold/not invoice), match | 57 |
| other decision, unknown | 6 |
| mismatch | 0 |

The only July payee (API004175, `FACTOR`) matches through the registered
factor (`erp/vendors` V100092, valid from 2025-03-12). No July invoice carries a
payment block; 26 certificate selections come from `erp/contractor_certificates`
and one from the inbox. All 31 selected events carry document and vigency.

Unknowns (46) are invoice inputs, not chronology (`INVOICE_INPUT_UNKNOWN`):
attachments that failed extraction or have no type, invoices whose only date is
an ambiguous dd/mm value, and the 2 vendors not in the master (API005601,
API005602). Notices bound: 5 events, including the bank letter API005195 (typed
from its `notice_type_hint`); API005600 (certificate) failed extraction.

Rules with no July example are covered by `tests/test_ap_chronology_sources.py`
and `tests/test_ap_chronology.py`: embargo received before/after, registered
garnishment from its date, bank letter received in month but effective later,
unverified sender, certificate expired at invoice date, same-receipt tie-break.

Reproduce:
`PYTHONPATH=src .venv/bin/python tools/validate_ap_chronology_july.py --phase participant/phase_dev --state .kalmora-cache/july`
