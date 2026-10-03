# #43 modular acceptance evidence

Authority: original `POLITICAS_CONTABLES.md` §1–2 and `FORMATO_ENTREGA.md` AP;
active-phase PO positions and GR/SES receipts. Exact reference association,
receipt quantity readiness, and final posting eligibility remain separate.
The existing shared `SemanticResolver` protocol is consumed without modifying
the extraction/LLM layer, invoking a real provider or reading golden.

| #43 criterion | Implemented capability | Reproducible evidence |
|---|---|---|
| Company/vendor/project/date/concept candidates | `POCatalog` filters company/vendor/currency, PO creation date, unit, project, item, material and exact whole-concept; excluded positions carry specific reasons | `test_ap_orders`: scope/unit/date conflicts, exact/missing/erroneous references, description discard reasons, multiple equal candidates |
| Exact before semantic | Exact PO/item, material and receipt anchors resolve without model calls; unique scope alone stays UNCONFIRMED | Bridge exact-anchor tests, including different description wording and existing foreign/future PO contradictions |
| Positions and receipts | GR/SES association and explicit delivery IDs; observed receipt cutoff independent of invoice date; historical unknowns never become available zero-consumption assumptions | Catalog receipt conflicts/cutoffs; bridge historical/partial/cutoff/quantity tests; all original received positions audit |
| MULTI_PO per line | Only observed positive portions whose quantities sum to the observed row; preserve line identity, scope/unit and evidence | Source nested/flat facts and unsupported bare marker tests; bridge two-PO conserved row and cross-scope/nonconserving rejection |
| Bounded shared semantic ranking | Existing `ResolutionRequest` with reusable `Candidate`/`ResolutionResult`/`SemanticResolver`, explicit hard constraints, fingerprint and max one position per portion | Fixture provider/replay tests: missing proof, candidate limits, ungrounded IDs, mutation, ambiguity/abstention, hard conflicts and structural revalidation |
| Selection cannot authorize reuse | Immutable batch preview through #44; no state returned; allocator checks joint capacity, prior identities and original usage again | Two competing rows, partial historical consumption, unknown residual capacity, already-allocated identity tests |
| Active-phase reconstruction | Catalogue/bridge rebuild from active originals; source hash/certainty mismatch blocks cross-phase reuse | Bridge phase hash tests; source-only July and September audits below |

## Source-only audits

`test_ap_order_sources` reconstructs each supplied phase's catalogue from original
`erp/purchase_orders.jsonl` and `erp/goods_receipts.jsonl`. Catalogue construction
validates every receipt's actual PO/item/vendor. It then feeds an actual receipt
ID and observed quantity/unit through `DocumentFacts`, normalization and
`POCatalog` for every received position (one receipt per position, including
recurring positions). IDs and dates come from those rows, without special cases.

| Active source | Orders | Receipts validated | Positions confirmed |
|---|---:|---:|---:|
| July `phase_dev` | 655 | 21,699 | 1,410 |
| September `phase_test` | 676 | 23,870 | 1,448 |

Original table SHA-256 fingerprints (identical before and after validation):

| Phase/table | SHA-256 |
|---|---|
| July purchase_orders | `7d4d92e468096ae5ee824801bd651c4d262046639797cb167451173c0c0afeac` |
| July goods_receipts | `47a1e2e5c739271d1d047cd3ebb805e170c35e3a03b13b871f130bb1e78e3c84` |
| September purchase_orders | `ef8e634fb0589611452577d31fa5f2ce98cde0350c8e4b357e3b3d2d32c35ed4` |
| September goods_receipts | `9771d6fcd913bf8e7fce69c97e10bc23fa8c9d3f394b5c142549b1c95639362f` |

September evidence reads only those two original ERP members from
`kalmora_participant_test.zip` into a temporary directory. No golden member is
opened, extracted or supplied to any solver. Synthetic tests vary invoice/receipt
dates, IDs, quantities, units, projects and scopes instead of encoding source IDs.

```sh
PYTHONPATH=src python3.12 -m unittest discover -s tests -p 'test_ap_order*.py' -v
KALMORA_ORDER_PHASE=/path/participant/phase_dev PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_order_sources.py -v
KALMORA_ORDER_PHASE=/path/original/phase_test PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_order_sources.py -v
KALMORA_ORDER_ZIP=/path/kalmora_participant_test.zip PYTHONPATH=src python3.12 -m unittest discover -s tests -p test_ap_order_sources.py -v
```

The audit emits its table hashes, order/receipt counts and position count as a
single JSON report. The ZIP mode reads only the two exact ERP members and never
extracts archive contents.

## Input and output contract

Identity supplies company/vendor/currency. Document observations supply invoice
date, row quantity/unit, optional exact PO/item/material/project/concept and
delivery references. `order_queries_from_facts` returns READY with complete
`POQueryLine` rows or UNKNOWN with diagnostics and no partial rows.

For an explicitly split row, use observed fields of this shape (raw quantity
strings or already normalized integer `quantity_milli`):

```json
{"quantity": "2", "uom": "hours", "po_reference": "MULTI_PO",
 "po_portions": [{"po_reference": "PO-A", "po_item": 10, "quantity": "0.75"},
                 {"po_reference": "PO-B", "po_item": 20, "quantity": "1.25"}]}
```

`resolve_facts` or `resolve_lines` returns all portion reports/candidates plus
conserved `InvoiceQuantityLine`/`OrderPortion` inputs. AVAILABLE is a reproducible
quantity preview, never a posting/approval decision or committed reservation.
UNKNOWN returns no usable invoice lines. INSUFFICIENT retains resolved lines for
downstream quantity policy. The caller preserves the same receipt cutoff and
reruns allocation against current state before committing any ledger entry.

All own modular #43 criteria have implementations and focalized evidence.
Real semantic quality/captures remain measured in #139/#222, while complete
document traversal and accounting belong to #140 as the issue explicitly says.
Those independent validations are not claimed here and do not become new #43
acceptance conditions. Extraction of a missing unit or unstated quantity split
cannot be repaired by this catalogue; the supported response is abstention.
