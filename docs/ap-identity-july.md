# AP identity on July 2026 (#42)

`resolve_ap_identity(documents, message, PhaseData, semantic=None)`
(`src/kalmora/ap_identity_sources.py`) binds one task's normalized attachment
facts and `message.json` to the exact identity core (`ap_identity.py`).

- Vendor: exact `supplier_tax_id` (on an art. 43 certificate, `certificate_tax_id`).
  If no tax ID was observed, a sender/uploader email domain is used only when it
  matches exactly one master vendor. A tax ID not in the master gives
  `VENDOR_NOT_IN_MASTER`. When the master is ambiguous, an `LLMSemanticResolver`
  result is accepted only if it selects one of the core's candidates.
- Recipient: exact `recipient_tax_id`. If none was observed, an exact company
  master name (ignoring case and spacing) from `recipient_name`/`customer_name`.
- Company: the single company of the documentary PO(s). Otherwise the recipient,
  if the vendor is unknown or enabled for it. Otherwise the vendor's single
  affiliation. Otherwise unresolved. A recipient different from the company gives
  `WRONG_ADDRESSEE`, including 1100 vs UTE 1910 in both directions.

## Result (replay, 305 tasks, no provider calls)

| check | correct |
|---|---|
| company | 300 / 305 |
| vendor_id | 303 / 305 |
| identity reasons (`VENDOR_NOT_IN_MASTER`, `WRONG_ADDRESSEE`) | 304 / 305 |

15 tasks have an attachment whose PDF extraction failed (`grounding`/`field`).
12 of them still resolve through the sender domain plus a single affiliation.
There are 5 mismatches:

- 3 failed extractions: API004161 and API004227 (vendor known from the domain but
  enabled for 1100 and 1910, no recipient evidence), and API005600 (domain shared by
  two vendors, so the binding abstains).
- API005206: extracted, but no header identity facts (no supplier/recipient tax
  ID or name). The sender domain is shared by V100053 and V100073, so the binding
  abstains. A semantic resolver run over the parsed document and those two
  candidates could settle it. The replay has no such recording.
- API005227: addressed to UTE 1910 with its tax ID, no PO, vendor enabled for
  1100/1200/1910. Golden expects 1100 + `WRONG_ADDRESSEE`. No documentary or
  master fact links the supply contract to 1100, so the binding keeps 1910 and
  does not invent a wrong addressee.

## Reproduce

```sh
PYTHONPATH=src .venv/bin/python tools/validate_ap_identity_july.py \
  ../participant/phase_dev ../.kalmora-cache/july
```

The tool prints one JSON line per mismatch and a final count line. It is the
only code that reads `golden/ap.jsonl`. The binding reads masters only through
`PhaseData`.
