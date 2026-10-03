# AP withholdings and contractual guarantees (#53)

`kalmora.ap_withholding` consumes the active `tax_codes.json` through
`WithholdingCatalog`. It covers IRPF15/7/19, MXISR10, MXIVAR, MXFLETE and PTIRS25.
Tax withholding credits use the catalogue account (47510000 in the package),
preserve vendor and tax code, and use the supplied base **without** VAT. Each
resolved fiscal base/code is rounded half up before invoice-date FX conversion.

`select_withholdings` accepts confirmed document or PO codes ahead of the vendor
default, whose `+` syntax supports `MXISR10+MXIVAR`. An explicit empty tuple means
confirmed no withholding. Missing document withholding and mandatory professional
or rental withholding checks remain the eligibility validator's responsibility;
an extractor must not turn missing evidence into a confirmed empty tuple.
Omitting every source raises an error; `vendor=None` explicitly represents an
observed null withholding field in the master and permits no withholding.
Different withholding treatments on distinct lines require separate bases.

`ContractGuarantee(base_doc, contract_reference, rate=500)` explicitly identifies
the contractual eligible base. The policy's 5% is credited to **40000900** with
the vendor and invoice-number assignment. The contract reference is retained in
the result component. A reverse-charge code alone never triggers a guarantee.
This module does not use the AR catalogue's `RET_GAR5`/43000900 or MX5MILL.

`calculate_ap_withholdings` requires `POST`/`POST_PAYMENT_BLOCK` eligibility and
returns `WithholdingResult` containing separate tax and guarantee document/local
totals and posting components. #54 deducts them from supplier gross, absorbs FX
rounding in the supplier line, and reverses all debit/credit sides for credit
notes. No source, ledger or simulated state is modified by this function.

## MXIVAR evidence

The catalogue describes two thirds of professional VAT, but explicitly supplies
`rate: 1067` (10.67%). Policy §2.3 also says 10.67%. All **15** MXIVAR postings in
the original development ERP use `round_half_up(base * 1067 / 10000)` and differ
from `round_half_up(rounded_VAT * 2 / 3)`:

| ERP entry | Base MXN cents | Recorded MXIVAR | 1067 bps | 2/3 of rounded VAT |
|---|---:|---:|---:|---:|
| 3100-2024-5100000003 | 2485484 | 265201 | 265201 | 265118 |
| 3100-2025-5100000002 | 5557163 | 592949 | 592949 | 592764 |
| 3100-2026-5100000095 | 4369401 | 466215 | 466215 | 466069 |

The implementation uses the active catalogue rate, with no special fixed amount
or golden-derived heuristic. Optional source checks reconstruct all 15 entries
from `erp/journal_entries.jsonl` and assert the competing formula differs.

The optional source regression also reconstructs all 167 withholding quotas
across the seven codes: IRPF19 (64), MXFLETE (27), IRPF15 (23), MXISR10 (15),
MXIVAR (15), IRPF7 (12), and PTIRS25 (11). It excludes exempt disbursements from
the eligible fee base and preserves signed credit-note rounding. This reads only
original ERP history, without golden outputs.

```sh
PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_withholding.py -v
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_withholding.py -v
```

Synthetic composition tests verify balanced ES/PT/MX debit/credit journals,
supplier payable, withholding accounts/vendor, guarantee assignment, cost
objects, currency and credit-note reversal. Full document adapters, AP delivery
and golden evaluation remain outside this module and must be integrated before
claiming an end-to-end M1 deliverable.
