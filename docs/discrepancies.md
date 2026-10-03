# Source discrepancies and operational decisions

The machine-readable register is [discrepancies.json](discrepancies.json). Evidence refers to immutable participant archive SHA-256 `c813449eab9ddc7fc28b04eff85518957035e895b5500fd19e26c0d8ef7f0109`, policies, delivery specification, scorer, and the audited roadmap. Originals and golden stay unchanged.

`resolved` means an explicit convention can be used by M0 interfaces. `known_exception` preserves a concrete unexplained source case and names its future investigation. `followup` requires integration work before closure. These statuses do not claim that accounting rule engines are implemented.

| Decision | Status | Operational consequence |
|---|---|---|
| Document/local currency | resolved | AP headers remain in document currency; journal entries use local currency. Keep both and FX evidence. API004482 demonstrates USD 240000 against EUR 193767. |
| Rounding | resolved | Round FX per line and balance vendor/customer; truncate PPA. ±2 scorer cents do not define arithmetic. |
| SWIFT-API004253 | known_exception | 76800000 appears on debit. Preserve evidence; investigate historical rates and bank/book amounts in #77. Never generalize its sign. |
| Close aggregation | resolved | Audit 76 individual rows and 64 scoring keys independently. |
| Scorer field gaps | followup | #32 and #35 are pending teammate interfaces; require field, chronology, attribution and item validation beyond score. |
| Company omitted by je_match | followup | Validate company explicitly and test a wrong-company negative fixture after teammate integration. |
| Synthetic NIF | resolved | Preserve raw identities and master correspondence; checksum invalidity alone cannot reject synthetic data. |

M0 handoff: `kalmora.facts.DocumentFacts` stores a source SHA-256, extractor version and named lists of `Fact(value, Evidence(document, field, page=None, quote=None))`. Keep every attachment's evidence and conflicting values. `FactsCache(directory).load(source_bytes, version, config)` returns facts or `None`; `.store(source_bytes, facts, config)` writes atomically and rejects a mismatched source hash. Changed bytes, extractor version or configuration produce another key. Extraction implementations remain M1/M2 work.

`RunRecorder(output_dir, command, input_metadata)` is a context manager. Use `.record_call(provider, model, input_tokens=None, output_tokens=None, pricing=None, usage=None)` for real provider calls and `.record_cache_hit()` for cache reuse. Pricing must supply `input_rate`, `output_rate`, `unit="per_token"`, `currency`, and `provenance`; values are exact Decimal strings. Unknown token counts or prices leave costs unknown. Code-only runs report zero with status `no_llm`. Currency totals remain separate. The report at `.path` records UUID, UTC times, elapsed time, usage, assumptions, cache hits, and failure state atomically. It never calls a provider itself.

Validation: `PYTHONPATH=src python3 -m unittest discover -s tests`. This validates M0 facts, cache, run metrics and coverage structure. It does not satisfy pending output-contract or evaluator acceptance checks.

Additional known exception: API004469 / journal 1100-2026-5100000822 has `partner=null` on its first 40700000 advance line, despite §1 requiring supplier partner; creditor partner is V100121. Preserve golden and strict partner validation; expose discrepancy in teammate comparator. The audited 36,743 ledger groups reproduce recorded TB; all 435 golden journal groups balance. Those aggregate checks do not resolve this missing dimension.
