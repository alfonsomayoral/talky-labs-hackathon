# Explicit AP duplicates and reissues (#47)

`ap_duplicates.duplicate_result(current, history, ...)` compares explicit
`model.ap_duplicate_record.DuplicateRecord` observations from ERP and the month.
It returns `DUPLICATE`, `REISSUE`, `CLEAR` or `UNKNOWN`, with source evidence,
`duplicate_of`/`reissue_of` and diagnostics. It does not emit the AP contract,
infer document facts or mutate input state.

Scope includes company, vendor, currency and document type. Same vendor,
normalized number and integer gross amount identify a duplicate. Distinct
explicit service periods exclude recurring monthly invoices even when amounts
and numbers match. Distinct numbers or amounts are also distinct. Receipt time
then document ID identifies the first document, independent of iterable order.
Exact timestamp ties use document ID; a date-only historical receipt on the
same day cannot prove the first document and remains unknown.

Normalization removes hyphens, slashes and whitespace and normalizes letter
case. It preserves leading zeros, letters, suffixes and period punctuation.
The policy requires removing prefixes but cannot identify arbitrary prefixes
from an ambiguous number. `confirmed_prefixes` therefore requires an explicitly
evidenced vendor profile supplied by the caller; no F/FV/TKD prefixes or numeric
suffixes are guessed. Conflicting prefix interpretations fail visibly.

The original ERP log demonstrates `REJECT.corrected_by -> posted doc_id` with
the same invoice number, including corrections that do not necessarily alter
gross. This exact pointer confirms an exception for that target document.
The explicit correction link also survives a changed invoice number.
Unlinked rejected documents cannot be presumed corrected. A rejected original
linked to another correction cannot become the duplicate root for a retry;
the actual corrected document can. `HOLD` with subsequent resolution and a
journal entry remains the same document, not a new corrected reissue.
`RECEIVED` represents an explicit earlier monthly observation, whose reception
alone is sufficient to anchor another received copy. A duplicate log record
must have an evidenced matching original before its `duplicate_of` is reused.

`registered_duplicate_records(PhaseData)` joins `ap_invoices` and
`ap_document_log` by company/doc_id. It retains original log decision and
`corrected_by`; invoice rows provide amount/currency. Log-only rows retain
missing amount/currency instead of borrowing a vendor default or corrected
invoice amount. Identity conflicts fail. No golden data is read.

Negative/reissue conclusions require `inventory_complete=True`. Missing
amount/currency/status or same-day ordering can still block that conclusion.
One known service period and one missing period cannot establish equal coverage.
An earlier matching record with unknown amount can also block selecting a later
document as the *first* duplicate. Scope-mismatched and future records do not.

Validation: 14 synthetic policy tests cover ordering, number variants, explicit
correction links, rejected/held statuses, recurring months, unknown roots,
missing data, no mutation and company/vendor/currency isolation. Run
`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ap_duplicates.py' -v`.

Limits: #41/#42 must supply extracted amount, exact reception, resolved identity,
service coverage where relevant and normalization evidence. Full July
decision/reason evaluation and #32/#35 integration remain outstanding, so this
work is a draft deterministic foundation rather than an issue closure.
