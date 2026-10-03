# Source review of historical USD credit notes — M6

Read-only review, 2026-10-03. Sources inspected: July original ERP, policies, bank/inbox/tasks references, current fixture handoff and frozen output. No solver/evaluator execution or golden access in this review.

## Conclusion

There is no source-supported clearing rule that removes these six USD credit notes. They are explicitly open, positive/debit balances in the original `erp/open_items.jsonl`, and every assignment has exactly one journal entry: the original AP credit-note posting. None has a subsequent payment, refund, clearing, or FX/reversal posting under the same assignment. The current projected handoff also lists no local-only transaction for any of these six positions.

Do not add a `kind == credit_note` exclusion, a reference/ID exclusion, or vendor netting merely to eliminate evaluation extra keys. Both the accounting policy and the documented ledger model work at the individual open-item grain. The unresolved question is whether the organizer intended foreign-currency credit notes to be outside the stated FX scope despite their being monetary open balances. That cannot be answered from the available clearing evidence.

## Original evidence

All six are company `1000`, local currency EUR, account `41000000`, source-document currency USD. Amounts below are integer cents in the named currency.

| AP document | Vendor | Assignment | AP source line | Original journal line / entry | Open-item source line | USD principal | EUR carrying | July FX change |
|---|---|---|---:|---|---:|---:|---:|---:|
| API005452 | V100137 | NC-FV-2025-11411 | 4160 | 8029 / 1000-2025-5200000001 | 19 | 19,615 | 18,950 | -3,242 |
| API005455 | V100137 | NC-FV-2025-11418 | 4163 | 7980 / 1000-2025-5200000002 | 20 | 22,980 | 22,190 | -3,787 |
| API005487 | V100136 | NC-2025-009296 | 4172 | 12828 / 1000-2025-5200000004 | 16 | 52,384 | 47,125 | -5,174 |
| API005504 | V100136 | NC-2025-009297 | 4178 | 17193 / 1000-2025-5200000006 | 17 | 61,651 | 55,597 | -6,225 |
| API005513 | V100136 | NC-2025-009298 | 4180 | 19603 / 1000-2025-5200000007 | 18 | 41,749 | 37,912 | -4,478 |
| API005529 | V100137 | NC-FV-2026-11421 | 4191 | 25258 / 1000-2026-5200000001 | 21 | 67,431 | 56,789 | -2,788 |

File roots: `data/julio/participant/phase_dev/erp/ap_invoices.jsonl`, `journal_entries.jsonl`, and `open_items.jsonl`. AP rows classify all six as `kind: credit_note`, `decision: POST`, `cases: [CREDIT_NOTE]`. The vendor reconciliation line is a debit in each case with explicit USD `amount_doc` and its own NC assignment. The AP document log has no `resolved_on` value for these rows; that alone would not prove a balance, but the journal and open-item snapshot do.

The six carrying balances total 238,563 EUR cents. Their original positive principals total 265,810 USD cents. The closing source `erp/fx_rates.jsonl:473` gives EUR-base USD rate 1.2487 on 2026-07-31. Individually rounded principal/rate minus carrying reproduces the six current frozen-output changes above, totaling -25,694 EUR cents (a 256.94 EUR asset decrease / FX expense). This reproduces the accounting arithmetic only, not the intended evaluation acceptance.

## Settlement search

- All original journal lines with each vendor/NC assignment were read, not merely AP-document metadata. Each has exactly one match, its AP original.
- Exact NC references were also searched in original bank, inbox, and tasks: no text matches. Historical AP documents are represented in ERP; no historical inbox directory was found for these six IDs.
- Neither vendor appears in `erp/sepa_remittances.jsonl`; vendor masters (`vendors.jsonl:136–137`) specify SWIFT as their payment method.
- V100136 has 24 AP postings and 21 SWIFT postings; V100137 has 24 AP postings and 21 SWIFT postings. The invoices paid by SWIFT have zero local open balances after original entries. Each vendor's remaining original open balance is exactly the sum of its three credit-note debit positions: 140,634 EUR cents and 97,929 EUR cents respectively. The SWIFT payments therefore do not provide evidence that these NC assignments were settled or netted.
- Last original SWIFT entries for these suppliers are `journal_entries.jsonl:35605–35606`, on 2026-07-10. They clear invoice assignments `2026-009278` and `FV-2026-11395`, not any NC reference. Payment local carrying debits equal those invoices' local carrying liabilities.
- In `outputs/m6-score/final/dependencies.json`, all six FX facts retain positive USD principals and `local_only_transactions: []`, so M1–M5 projected adjustments have not cleared them either.

## Contracts and code

- `data/julio/participant/POLITICAS_CONTABLES.md:160–163`: revalue open foreign-currency items at month-end SYN-BCE; the examples name USD/GBP vendor invoices. No explicit credit-note exclusion or automatic cross-assignment vendor netting rule is given.
- `src/kalmora/ledger.py:117–131`: open-item balance is signed debit minus credit by company/account/partner/assignment. Positive positions are assets owed to the company and remain open until cleared.
- `tools/m6_sources.py:340–379`: foreign AP positions include foreign-currency AP records with vendor reconciliation lines, suppress local zero balances, and preserve signed documentary principal. On these six records this matches the original sources.
- `src/kalmora/close/engine.py:202–219`: derives a local valuation delta without modifying the foreign principal. The six current deltas agree with original principals, carrying balances, and closing rate.

## Minimum defensible next work

No current scoring-oriented omission of these six is justified. Preserve them and document the discrepancy/uncertain organizer scope in issue #251. An explicit organizer clarification that historical open foreign-currency credit notes are excluded would justify a general documented policy change; a confirmed clearing source would justify removing only positions actually cleared after projecting that source.

A separate general robustness improvement is worth tracking: when an item has a nonzero local balance plus local-only settlements whose foreign amount cannot be reconstructed, do not silently assume the original foreign principal is still outstanding. Require documentary payment-currency evidence or emit an unresolved-principal diagnostic and preserve unknown. Original SWIFT entries here are local-only EUR lines; fully settled invoices are filtered by local zero, so this risk does not explain these six extra keys. No implementation change was made for this prospective case.
