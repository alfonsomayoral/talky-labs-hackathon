# Independent AP acceptance — 3 October 2026

The independent audit accepts the implemented accounting and validation capabilities under the user's provisional documentary-base authorization. It does not accept an invalid row or claim a complete monthly delivery. Issue #54's module criteria have concrete original-source and replay evidence; #55's auditor now exposes independently validated accounting rows, preserved failures and replay scope instead of rejecting every v0 row solely for delivery metadata.

The exact authorization, identical for both phases, is:

> Usuario, chat M1 no LLM, 2026-10-03: Pero #222 es solo un hotfix, el resto puedes seguir asumiendo que funciona. Incluso una parte de v0 y continuar para ver si puedes aceptar o no el resto de issues no?

This reference is retained in [documentary-authorization.json](../outputs/m1-owned-validation/independent-acceptance/documentary-authorization.json) and both public reports. It is an explicit provisional assumption, not a claim that declared source unknowns have been resolved. No provider was called and no Golden data was read by this audit.

## Final v3 snapshot and independent phases

Backend `766efed` introduced `document-normalization-v3` and `xml-source-extractor-v3`. The old v2 artifacts were retained; new deterministic sources were prepared through the public `prepare-ap` CLI into independent destinations:

| Evidence | July | September |
| --- | --- | --- |
| Original phase | `Downloads/participant/phase_dev` | Preserved ZIP phase `outputs/m1-owned-validation/original-september/participant/phase_test` |
| New manifest | [sources-v3/july/phase-sources.json](../outputs/m1-owned-validation/independent-acceptance/sources-v3/july/phase-sources.json) | [sources-v3/september/phase-sources.json](../outputs/m1-owned-validation/independent-acceptance/sources-v3/september/phase-sources.json) |
| Preparation proof | [July proof](../outputs/m1-owned-validation/independent-acceptance/sources-v3/july/independent-preparation-proof.json) | [September proof](../outputs/m1-owned-validation/independent-acceptance/sources-v3/september/independent-preparation-proof.json) |
| Source fingerprint | `f9ce069a174c2d08af069a6e5c40819ac7afdeae09279fe9aef90eac1180010d` | `d0980f26a9ae4e15584dc691d0fc09e49f85ebf51ee31e851b00fa6b25e31419` |
| Exact task keys / delivered v0 rows | 305 / 305 | 297 / 297 |
| XML attachments prepared | 58 | 48 |
| Source attachments still unknown | 262 | 265 |
| Pinned original task/inbox/ERP files in audit | 651 | 636 |

Both phases use the same deterministic configuration, no residual extractor, no PDF-vision option, and no provider configuration. The configuration fingerprint is `27d031b437fc3440316b86b0f759fa7743cf143e40a7f4f8ffd5fb0e0665b24e`. The final installed rules fingerprint is `faace9eccbde0868cf887b961c0a771066546a2289333cb41d3301c1b2b3f718`; individual module hashes are retained in each audit. Actual input/fact fingerprints differ. The [public independent-phase comparison](../outputs/m1-owned-validation/independent-acceptance/v3-public-audit-comparison.json) passes with no differences. It verifies compatibility, not completeness or reference correctness. No July state, ERP or captures were substituted into September.

Public preparation exits `1` when sources remain unknown, while successfully publishing its manifest. The wrapper initially treated that useful diagnostic status as fatal; verification then loaded the already prepared manifests with the strict public loader, without preparing them again. Logs preserve both the actual CLI summaries and that wrapper mistake. Initial attempts also rejected the CLI's default run-log destination; successful calls explicitly selected a destination inside the independent evidence directory. These are local harness observations, not #222 failures. Original hashes match the previous pinned audit; preparation and audit guards allowed writes only inside independent evidence.

## Real v0 rows under contract projection

The producer outputs remain unchanged. `--project-v0` creates a separate validation view and retains every removed value with its JSON pointer. Only known `action_data`, coded-line `goods_receipts`, and inapplicable optional null fields on known non-posting decisions are removed. No decision, reason, account, partner, amount, currency, cost object, PO or journal is corrected.

The independent [projection round-trip check](../outputs/m1-owned-validation/independent-acceptance/v0-projection-summary.json) restores all removed metadata and reproduces the decoded original rows exactly. Unknown fields are retained for validation. Raw/projection hashes match the previous snapshot after the v3 source refresh:

| Bytes | July SHA-256 | September SHA-256 |
| --- | --- | --- |
| Unchanged raw producer | `1556f096277bcfeffc0e1aaa549115ac9533c57208a9a7c58eb85edae5b83b14` | `da043cd4fe1097c91174ab19957e67e5b115e13ca879b22492d3e593eb5df9cd` |
| Separate projected view | `31035b3dc03800900a91371f81ed2b1e4e5adf1f8a3b7c2cd3f824c561ee280d` | `9cc54f1cb7e46923cee0503d6c1e532e660b3908e603cb3d20ca5e116a22ee72` |

The final public audit validates the projection against active company/account/partner/CC/WBS/PO masters, the tax catalogue, document/local cents, posting windows and M0 journal validation:

| Independent criterion | July | September |
| --- | ---: | ---: |
| Structural contract passes | 305 | 297 |
| Strict accounting row passes | 298 | 285 |
| Strict row failures | 7 | 12 |
| Posting rows passing strict row and master checks | 236 / 243 | 221 / 233 |
| Master-scope passes | 305 | 297 |
| Posting journals passing M0 validation | 242 / 243 | 232 / 233 |
| Non-posting rows carrying a journal | 0 / 62 | 0 / 64 |
| Document-currency conservation PASS | 236 | 224 |
| Document-currency conservation FAIL | 1 | 3 |
| Document-currency conservation INCONCLUSIVE | 6 | 6 |
| Transaction replay supplied to this monthly audit | absent | absent |
| Monthly acceptance / new monthly score | false / none | false / none |

Counts are different predicates: a balanced local journal can still fail document-currency conservation or another row condition. Missing foreign document cents remain inconclusive; a known coded-net mismatch fails. A passing master-scope check does not independently prove factual policy applicability or the accuracy of cost assignment. The provisional documentary assumption remains visible beside those distinctions.

Final reports and guards are [July audit](../outputs/m1-owned-validation/independent-acceptance/v3-july-audit.json), [July proof](../outputs/m1-owned-validation/independent-acceptance/v3-july-audit-proof.json), [September audit](../outputs/m1-owned-validation/independent-acceptance/v3-september-audit.json) and [September proof](../outputs/m1-owned-validation/independent-acceptance/v3-september-audit-proof.json). Report self-hashes are `ad3880e1abc7e1664712e6edbd7745ad1d7f3276f187a7b40e92ffba340934d4` and `6708816332852e9d831d63629713aa411b702a85cc31ac0e5773b60d2abc0bc5`. Both public CLI calls return `1` with useful `COMPLETE_DELIVERY / BLOCKED` reports. Their accounting summaries preserve `delivery_ready_for_evaluation=false` and `monthly_acceptance=false`.

The remaining row failures include missing supplier on an open-item advance account, inconsistent supplier/header cents, insufficient foreign document cents, ambiguous GR/IR-to-cost correspondence, and document base/cost differences; September also contains rejection-reason and charged-VAT/cost-account failures. Every affected document and diagnostic is retained in the reports. No source or original output was repaired to make validation pass. No new scorer run was performed because the raw outputs are unchanged; the separate existing evaluation evidence remains authoritative for reference comparisons.

## Actual #282 runner observation, retained as history

Fresh guarded `run_ap_phase` processes were executed against the earlier `fb93a76/#282` implementation plus the stable local validator fixes and saved v2 sources. [Execution manifest](../outputs/m1-owned-validation/independent-acceptance/execution-manifest.json), [July report](../outputs/m1-owned-validation/independent-acceptance/july-first/report.json), [September report](../outputs/m1-owned-validation/independent-acceptance/september-first/report.json) and their complete state/proof files identify exact implementation hashes. They are not evidence for running the subsequently integrated XML v3 implementation.

The operator explicitly selected receipt cutoffs and simulated posting dates `2026-07-31` and `2026-09-30`. These are simulation boundaries, not assertions of actual arrival/posting dates and never substitutes for invoice dates. The stable attempts used a maximum 600 seconds: approximately 254 seconds for July and 243 seconds for September. Initial attempts were rejected because the implementation changed during execution, not because they timed out; those logs remain preserved.

| Actual runner result | July | September |
| --- | ---: | ---: |
| Decisions emitted / journals / published rows | 0 / 0 / 0 | 0 / 0 / 0 |
| UNKNOWN tasks | 301 | 297 |
| Unsupported credit/advance tasks | 4 | 0 |
| Prepared monetary tasks blocked by `gross_cents` | 40 | 33 |
| Prepared tasks with unresolved financial inventory | 14 | 15 |
| Receipt history usages retained before/after | 10,461 / 10,461 | 10,667 / 10,667 |
| Advance / credit opening state | NOT_LOADED / NOT_LOADED | NOT_LOADED / NOT_LOADED |

These runs demonstrate strict saved-fact/ERP loading and explicit abstention, not successful monthly accounting or replay. The root authorized skipping a second empty execution of each phase. Equality of empty output bytes is not called transaction replay. No state was moved between phases. Both processes made zero provider calls and recorded no attempted Golden/network access.

The interface gap is concrete. The runner expects `gross_cents`; saved source headers resolve net, tax and payable but do not supply that field. These two original examples were examined rather than filled in:

| Original example | Net cents | Tax cents | Payable cents | `gross_cents` |
| --- | ---: | ---: | ---: | --- |
| July `API004193`, `facturae_2026-024821.xml` | 251,412 | 52,797 | 304,209 | absent / UNKNOWN |
| September `API004560`, `facturae_F2606362.xml` | 4,771,279 | 1,001,969 | 5,773,248 | absent / UNKNOWN |

[Earlier resolved-header evidence](../outputs/m1-owned-validation/independent-acceptance/gross-interface-evidence.json) retains the actual runner diagnostics. [New v3 source evidence](../outputs/m1-owned-validation/independent-acceptance/gross-interface-evidence-v3.json) confirms the same normalized values and absence of `gross_cents`. XML `InvoiceTotal` is retained raw as `3042.09` / `57732.48`; this audit does not define a new mapping or assume absent deductions are zero. Other observed limits include missing UOM/flags and unresolved PDF source fields. Adopting resolved documentary facts into the monthly runner is #140's integration scope; the observation does not invalidate the independent accounting modules or create a new #222 prerequisite.

## Independent acceptance of #54 and #55 capabilities

Issue #54's [criterion matrix](ap-credit-acceptance.md) has independent module approval: inverse original coding, approved exact foreign PO/supplier request, historical carrying, evidenced monetary/non-monetary differences, cents/scope/rollback. Two rows from the owned `build_ap_credit_delivery` producer match their original-source evaluation subset exactly by accounts, partners, CC/WBS, currency and cents; the separate [evaluation](../outputs/m1-owned-validation/owned-credit-evaluation/evaluation.json) reports no `ENTRY_RULE` or `REFERENCE_ENTRY_RULE` differences. Golden was confined to that separate evaluator, never this producer or audit.

The subsequent [owned-credit replay proof](../outputs/m1-owned-validation/owned-credit-replay/proof.json) executes actual transaction factories for those two original-source credit deliveries, reproduces rows and complete per-transaction state, rejects duplicate publication, and preserves 82 original sources with zero provider/Golden/network attempts. This is stronger than comparing two row files. It proves those two resolved transactions, not an entire month's decisions or historical receipt/407 integration. Unknown classification, original links, allocations or approval still block the affected operation; they are not guessed. The explicit scope supports independent acceptance of #54 without claiming #140 integration is finished.

For #55, the independent review approves the new metadata projection and per-criterion audit. Fourteen focused projection/audit regressions pass, including malformed decisions/lines, unknown metadata, missing foreign cents, exact preservation and both final fixes: snapshot validation after per-document checks, and failure of known coded-net differences. Root's two-credit replay and DUPLICATE-policy regressions also passed independently. This validates the implemented acceptance library, active master checks, guarded evidence and export/replay mechanics. It does not turn the remaining 7/12 failing rows or an absent monthly replay into passes. The auditor exposes the exact conditions needed for complete monthly acceptance; monthly adoption, decisions and publication remain with the integrated workflow owner.

## Reproduction without a provider or reference rows

[run_prepare_sources.py](../outputs/m1-owned-validation/independent-acceptance/run_prepare_sources.py) wraps the unchanged public CLI with source/write/network guards. A fresh reproduction selects new destinations; `--verify-existing` verifies the preserved preparation without rewriting it. The manifest's residual configuration is null for both phases.

[run_public_audit.py](../outputs/m1-owned-validation/independent-acceptance/run_public_audit.py) wraps the unchanged public `tools/validate_ap_delivery.py` entry point, supplies `--project-v0` and reads the exact authorization from the JSON file. Select a new report label because public report publication rejects overwriting an existing report:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python \
  outputs/m1-owned-validation/independent-acceptance/run_public_audit.py \
  /Users/juanjosefernandezmorales/Downloads/participant/phase_dev \
  outputs/m1-owned-validation/integrated-producer/july-final-first/bundle \
  outputs/m1-owned-validation/independent-acceptance/sources-v3/july/phase-sources.json \
  fresh-july-review
```

Use September's own original phase, bundle and `sources-v3/september/phase-sources.json` in a separate process. [summarize_final_audits.py](../outputs/m1-owned-validation/independent-acceptance/summarize_final_audits.py) checks self-hashes through the public comparison API, compares frozen rules/configuration and verifies that raw/projected bytes still match the preserved earlier snapshot. The projection round-trip script and accounting-validation script provide the independent row-by-row cross-check; neither produces replacement accounting data. Evidence and code review were read-only for source/tests, with no Git/GitHub mutations and no complete-suite rerun.
