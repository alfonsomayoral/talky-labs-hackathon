# AP tax components (#52)

`kalmora.ap_tax` implements the AP catalogue treatments in policies §1 and §2.3.
Pass the active package's `tax_codes.json` to `TaxCatalog`; no rates are inferred
from golden, vendor names, or historical output. `select_tax_code` records the
resolved document → order → vendor precedence. Resolve conflicting facts before
selecting a code. Supply the posting company's country from its master, not the
vendor's residence (a foreign vendor can use ES reverse-charge treatment).

`calculate_ap_tax` accepts explicit `POST` or `POST_PAYMENT_BLOCK` eligibility,
document currency, invoice date, and `TaxLine` fiscal bases. It calculates input
VAT on 47200000; reverse VAT on 47210000/47710000; no quota for exempt/REAV;
and non-deductible VAT as an addition to the resolved expense/asset account with
exactly one cost object. Input amounts are unsigned; credit-note reversal belongs
to the journal builder. The caller supplies resolved fiscal bases/grouping so
rounding follows the document's tax structure. Calculation rounds each supplied
base half up, then converts each posting at invoice-date FX with M0 `RateTable`.

For `SIMP`, supply a separate zero-base `TaxLine` with its explicit DUA quota and
reference. This disbursement increases supplier gross and 47200000 without
creating an expense base. Original ERP entry `1100-2025-5100000441` shows freight
442500 + duties 567460 + DUA VAT 4532744 = supplier 5542704; multiplying freight
by 21% would be incorrect. `tax_doc` for reverse/exempt must be zero; a supplied
ordinary VAT quota must match the catalogue. Upstream rejection precedence and
document-total validation remain outside this calculation module.

`TaxResult.components` exposes document/local amounts and fiscal `journal_lines`.
`tax_doc` excludes self-assessed VAT; `tax_local` includes the self-assessed
quota. Base, supplier, advance, retention and credit-note lines belong to #54.
The supplier line absorbs conversion/rounding differences after all components
are built. This module performs no I/O, writes no ledger, modifies no masters,
and does not emit `ap.jsonl` or implement extraction dependencies #41/#45/#50.

Reproduce synthetic checks and the source-only DUA evidence (no golden access):

```sh
PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_tax.py -v
KALMORA_PHASE_ERP=/path/participant/phase_dev/erp PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_tax.py -v
```
