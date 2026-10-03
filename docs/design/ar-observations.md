# AR observations and source workflow — #56/#57

Status: **native extraction and source workflow implemented**. The five supplied
text-template families now use the shared #137/#138 capture/replay boundary and
the #57 reference resolver. The user authorized functional M2 closure using the
working v0 convention and July validation; AP integration #140 remains separate
M1 work. September coverage and live provider extraction quality are not claimed.

`kalmora.billing.extraction` supplies literal native observations and explicit
unit normalization. `observations` adapts them to the existing `BillingFacts`
union; `resolution` checks existing master identities; `source_runner` connects
these stages to the billing engine, CLI and close runner. Native execution makes
zero provider calls. An optional `LLMBillingExtractor` uses the shared typed DTO
and grounding checks, but it is not an automatic CLI fallback.

## Facts, normalization and decisions

The implemented flow is:

1. The router retains each original attachment as its own `ParsedDocument`.
2. `NativeBillingExtractor` supplies literal observations with evidence, captured
   through `RecordedExtractor`. PDF and
   `item.json` remain separate; metadata never fills missing document fields.
3. `normalize_billing_facts` converts those observations to the units and
   field names below, retaining raw facts and conversion provenance separately.
4. `resolve_billing_references` checks printed contracts, customers and plants
   against current masters. Exact matching precedes optional bounded semantic
   resolution through `RecordedResolver`.
5. `adapt_billing_sources` combines complementary attachments without replacing
   missing fields from metadata or discarding conflicting candidates. It supplies
   typed engine inputs or diagnostics with `facts=None`.
6. `build_ar_billing` applies eligibility, period/history checks, prices,
   deductions, taxes, dates and journal rules. The source runner allocates numbers
   in task order from ERP-derived company/series and rebuilds coherent invoice
   references and receivable assignments. Pending items consume no number.
7. Export publishes `ar_billing.jsonl` and `pending_wip.jsonl` only after complete
   task coverage and an unchanged input snapshot. Evidence and source failures
   remain available in the work directory even when publication is blocked.

**Stages 2–3, shared capture/replay and #57 are connected.** Captures retain
literal strings; normalized cents and MWh are a separate deterministic stage.
The envelope remains `ar-observations-v1`, with versioned AR literal schema,
prompt, native parser and normalizer identities. Replay verifies original and
transformation hashes plus the extraction configuration. Semantic recordings
also bind candidate attributes, literal facts and current phase context. A cache
miss, invalid capture or changed configuration stays unresolved on replay; it
never triggers a provider callback.

## Envelope and fields

`BillingObservations` contains the `BillingType`, one `DocumentFacts`, explicit
`row_counts`, and `schema_version`. Its JSON uses the existing `DocumentFacts`
`typed-v1` codec, preserving all candidates and exact Decimal values. Extra
envelope/observation fields and incompatible versions fail rather than disappear.

The combined support supplies `currency` normalized from a literal code/symbol;
it must match the active company's currency. An observed `contract_reference` is
optional, but when present must match the task's reference or an evidenced #57
binding to that same identity. Neither field is inferred from a filename. The
resolver selects existing IDs; it cannot replace the metadata's identities.

| Type | Required document fields | Complete table and row fields |
| --- | --- | --- |
| Certification | `month`, `cumulative_cents`, `previous_cents`, `current_cents`, `status_text`, `authority_text` | `chapter`: `number`, `description`, `amount_cents` |
| Monthly service | `month`, `canon_cents`, `canon_status_text`, `authority_text` | `extra`: `order`, `description`, `amount_cents`, `status_text` |
| Price revision | `old_fee_cents`, `new_fee_cents`, `effective_date`, `approval_date`, `status_text`; optional `decree` | `revision_month`: `month` |
| PPA | `period`, `share_bp`, `price_mwh_cents` | `plant`: `reference`, `mwh_milli` |
| Market settlement | `period`, `deviations_cents` | `plant`: `reference`, `amount_cents`; optional `mwh_milli` |

Row keys use one-based indices, e.g. `chapter.1.amount_cents`. A declared count
must match contiguous rows. Empty extras require `row_counts={"extra": 0}`;
absence of extra fields alone does not establish an empty table. Other tables
must contain at least one row. The native normalizer re-reads a bounded original
table and checks its final row before declaring coverage; a partial capture cannot
shrink that count. An unrecognized row blocks normalization. Counts remain
parser/reviewer metadata, not confidence scores or proof of general OCR quality.
Conflicting table counts across attachments remain unresolved.

Money is a strict integer number of local cents; MWh is integer thousandths;
`share_bp` is an integer from 0 to 10,000. PPA price is a finite, nonnegative
Decimal or decimal string in cents/MWh. Floats and booleans are rejected as
numeric values. The adapter never rounds or calculates an invoice. Market
deviations retain their observed sign. Dates/months must already be valid ISO
values. Prior normalization must preserve ambiguous separators and unknown units
as diagnostics rather than guessing from locale or target totals.

## Approval observations

Raw status observations preserve literal source text; normalization only applies
explicit whitespace, case and lexical aliases, never a model-produced `approved`
boolean.
The adapter has a bounded lexical mapping for observed `CONFORME`,
`APROBADA/APROBADO`, `APROVADA/APROVADO`, the overlapping July service text
`CONFORMEConforme`, and `RESUELVO: aprobar la revisión de precios`.
`PENDIENTE DE APROBACIÓN`, `PENDIENTE DE CONFORMIDAD` and `No facturar` are
explicit pending observations. Other text returns `UNKNOWN_STATUS`.

This normalization does not authorize an invoice. The billing engine still
decides certification eligibility, skips pending certification, excludes pending
extras and checks decree/history/periods. Missing approval stays unresolved; it
never becomes `False`. A pending monthly canon or decree is unresolved because
the existing service/revision engine contracts cannot represent those decisions.
Contradictory status candidates remain separate, with `CONFLICT`.

Certifications and monthly service also require literal `authority_text` locating
the printed signer role: Dirección Facultativa (optionally Ingeniero or Arquitecto)
and Técnico municipal respectively. Missing or unfamiliar roles stay unresolved;
the word `CONFORME` alone does not establish the required authority. Current
source quotations establish the block location; later source evaluation must
check that the role and status actually apply to the same certification/service.

## Source identity and resolution

The adapter binds the observation hash to its `ParsedDocument` and requires a
source path inside the current billing item's folder. Each candidate must carry
the same attachment path, a matching block/page locator, and a nonempty quotation
present in that original text after whitespace normalization. This verifies
location, **not the correctness of normalized units, semantic labels or OCR**.
Image-only observations require later reviewed image support; this increment
does not silently promote image transcription or unverified processing aids.

Printed contract/customer names and references are checked against the active
masters, with company, metadata customer and billing kind as hard constraints.
Energy plants are restricted further to the contract's eligible cost centers.
A lone candidate does not prove a match. Residual ambiguity can use the supplied
recorded resolver, which must cite the original and select only eligible existing
IDs; absent evidence or competing candidates remain unresolved. Duplicate plants
are rejected. Raw wrapped names retain their original quotation before whitespace
normalization for exact matching. Native July uses exact matches without provider
resolution; live semantic quality is still separate acceptance work.

The return value retains all original observations. On the first blocking
condition it has no engine facts and one structured diagnostic (code, field,
reason, candidate facts when applicable). The caller records it as unresolved;
it must not pass empty/default facts into the engine or publish a partial invoice.

## Development sample

[ar-observations-july.json](../fixtures/ar-observations-july.json) re-expresses
seven cases from the existing source-reviewed `tests/fixtures/billing-july.json`:
Spanish and Mexican approved certifications, the Portuguese pending certification,
a monthly service with explicit zero extras, a revision, PPA and market settlement.
Original attachment hashes were checked against the July source package during
sample preparation. The annotation's own hash is included.

The sample is **development annotation**, not a model capture, reserved benchmark,
fresh field-level quality evaluation or accounting answer. It includes no invoice,
decision or journal output. Its normalized values come from the existing reviewed
annotation, quotations locate them on the original page, and table counts are
declared derived metadata. Printed plant descriptions replace fixture-internal
cost-center IDs; the adapter obtains those IDs from the active masters.

The seven annotations remain useful for the isolated adapter. The source runner
reads original files and captures new literal facts; it does not load this sample.
Example annotation usage:

```python
observations = BillingObservations.from_dict(case["observations"])
# document is the router's original, hash-checked ParsedDocument for this item.
adaptation = adapt_billing_observations(data, item, observations, document)
if adaptation.facts is not None:
    # Aggregate resolved item facts, then invoke the unchanged billing engine.
    facts_by_item[item.id] = adaptation.facts
else:
    unresolved_by_item[item.id] = adaptation.diagnostics
```

## Remaining acceptance work

- Evaluate live AR model extraction and semantic resolution separately. The
  optional AR prompt/DTO adapter has injected-client checks, not provider quality
  acceptance; the seven annotations are not recordings or a held-out benchmark.
- Evaluate scanned documents, new layouts, authority scope and omitted rows
  against originals. The current native reader covers the supplied text templates;
  image-only evidence and unsupported layouts remain unresolved.
- Broaden source examples for extraordinary services and absent/conflicting
  evidence. The selected July monthly annotation still contains no extras.
- Complete M1 integration in #140 and assess September independently. This work
  is deferred from functional M2 closure by the user's decision. See the separate
  [July verification](../verification/m2-source-workflow.md) for the frozen-output
  evaluator result and its limits.
