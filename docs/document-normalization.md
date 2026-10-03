# Deterministic document interpretation

`classify_document(DocumentFacts)` returns `DocumentClassification` with
`document_type`, `status` (`CLASSIFIED`, `UNKNOWN`, `CONFLICT`), source evidence,
diagnostics and a version. It recognizes the nine AP policy types from explicit
titles/hints. A generic CFDI format is insufficient: source `cfdi_type` I/E
distinguishes invoice/credit note. Conflicting hints remain explicit. Classification
does not authorize posting, supplier updates, or payment.

`normalize_document_facts(DocumentFacts)` returns `NormalizedDocument`:
`raw` is a deep copy, `facts` retains all normalized candidates and their original
evidence, `diagnostics` describes failures/rounding, and `conflicts` lists disagreeing
candidates. Consumers must handle diagnostics and conflicts before accounting use.
Each attachment is normalized independently; mixed physical document paths return
an empty normalized result with `MIXED_SOURCE`. Compare PDF/XML afterwards.

Money becomes integer cents with ROUND_HALF_UP (a rounding diagnostic is emitted).
Quantity becomes exact integer milli units; unit prices become exact integer e4
major-currency units. Rates become integer e4 ratios (`21%` and `0.21` become 2100).
Prices/rates/quantities exceeding precision fail rather than round. Existing unit
fields require real integers; booleans and floats cannot be numeric facts. Source
signs remain unchanged. There is no FX conversion, posting sign inference or PPA
calculation. A caller needing unit price in cents can use Decimal(e4)/100.

Both European and English grouped decimals are accepted when unambiguous.
Single separators with three trailing digits such as `1,234` are ambiguous;
`0.125` is decimal. XML physical paths in XML attachments use dot-decimal notation.
Whitespace grouping must contain groups of three. ISO dates/timestamps retain
their source calendar date. Numeric day/month dates with both components at most
12 and different are ambiguous. Currency codes are uppercased; `$` never determines
USD or MXN. Tax IDs/IBAN remove whitespace, dots and hyphens without inventing
registry validity. Document numbers retain their punctuation.

Flat `line.N.field`, `lines.N.field`, and `lines[N].field` all use **one-based** N;
zero is rejected. A nested `lines` list maps its zero-based Python indices to line
1 onward. Output uses flat `line.N.field` so each cell retains its evidence and
conflicts. Aliases include invoice/document number, buyer/recipient tax ID,
document/canonical currency and current/previous/cumulative certification amounts.
Unknown fields remain available without AP-specific inference. An explicitly
observed None remains None; absent fields are not fabricated.

These functions are stdlib-only, never call an LLM, and never inspect golden data,
filenames for business classifications, or held-out annotations. Raw inputs and
versioned transforms allow replay and audit.
