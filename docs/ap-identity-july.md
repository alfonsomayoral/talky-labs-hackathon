# AP identity on July 2026 (#42)

`resolve_ap_identity(documents, message, PhaseData, semantic=None)`
(`src/kalmora/ap_identity_sources.py`) binds one task's normalized attachment
facts and `message.json` to the exact identity core (`ap_identity.py`).

- Vendor: exact `supplier_tax_id` (on an art. 43 certificate, `certificate_tax_id`).
  If no tax ID was observed, a sender/uploader email domain is used only when it
  matches exactly one master vendor. A tax ID not in the master gives
  `VENDOR_NOT_IN_MASTER`. When the master tax ID or the sender domain is ambiguous,
  an `LLMSemanticResolver` result is accepted only if it selects one of
  `supplier_candidates`.
- Recipient: exact `recipient_tax_id`. If none was observed, an exact company
  master name (ignoring case and spacing) from `recipient_name`/`customer_name`.
- Company: the single company of the documentary PO(s). Otherwise the recipient,
  if the vendor is unknown or enabled for it. Otherwise the vendor's single
  affiliation. Otherwise unresolved. A recipient different from the company gives
  `WRONG_ADDRESSEE`, including 1100 vs UTE 1910 in both directions.

## Result (305 tasks; replay, two recorded semantic resolutions)

| check | correct |
|---|---|
| company | 302 / 305 |
| vendor_id | 305 / 305 |
| identity reasons (`VENDOR_NOT_IN_MASTER`, `WRONG_ADDRESSEE`) | 304 / 305 |

Without the semantic resolutions, the numbers are company 300 and vendor 303.

Semantic resolution only runs for tasks where the binding leaves a non-empty set
of master vendors (`supplier_candidates`). July has two:

- API005206: the sender domain is shared by V100053 and V100073, and the
  extraction has no header facts. Selected: V100053, proved by its NIF in the PDF.
- API005600: certificate extraction failed (`field`), and the domain is shared
  by five vendors. Selected: V100116, proved by name and NIF.

The candidates and their attributes come only from `erp/vendors.jsonl`. A
selection outside the set, or any abstention, leaves the vendor unknown. The
model's self-reported confidence is never used. Recording cost: 2 provider
calls, estimated USD 0.00062 (`gpt-6-luna`, reasoning `low`, budget USD 1).

15 tasks have an attachment whose PDF extraction failed (`grounding`/`field`).
There are 3 mismatches, all on company:

- 2 failed extractions: API004161 and API004227. The vendor is known from the
  domain but is enabled for both 1100 and 1910, and there is no recipient evidence.
- API005227: addressed to UTE 1910 with its tax ID, no PO, vendor enabled for
  1100/1200/1910. Golden expects 1100 + `WRONG_ADDRESSEE`. No documentary or
  master fact links the supply contract to 1100, so the binding keeps 1910 and
  does not invent a wrong addressee.

## Reproduce

```sh
# replay only (uses recordings in the state dir; no provider)
PYTHONPATH=src .venv/bin/python tools/validate_ap_identity_july.py \
  ../participant/phase_dev ../.kalmora-cache/july
# record missing semantic resolutions first (USD 1 cap), then evaluate
set -a; source /path/to/openai.env; set +a
PYTHONPATH=src .venv/bin/python tools/validate_ap_identity_july.py \
  ../participant/phase_dev ../.kalmora-cache/july --record-resolutions
```

The tool prints one JSON line per mismatch and a final count line. It is the
only code that reads `golden/ap.jsonl`. The binding and the resolution requests
read masters only through `PhaseData`. The resolution config is stored as
`resolution-config.json` in the state dir.
