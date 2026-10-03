# Prepared AR observation boundary — #56

Status: **preparatory implementation**, not automatic AR extraction or final M2
acceptance. The shared extractor/recorder from #137/#138 is delivered. AP
integration #140 remains a gate for complete AR integration. #56 stays open.

`kalmora.billing.observations` supplies a versioned, provider-independent
`BillingObservations` envelope and a deterministic adapter to the existing
`BillingFacts` union. It does not change the shared document modules, billing
engine, output contracts or CLI. No provider calls or tests were performed for
this increment, following the repository's instruction to test only on request.

## Facts, normalization and decisions

The intended flow is:

1. The router retains each original attachment as its own `ParsedDocument`.
2. An AR extractor supplies literal observations with evidence. PDF and
   `item.json` remain separate; metadata never fills missing document fields.
3. A deterministic AR normalizer converts those observations to the units and
   field names below, retaining raw facts and conversion provenance separately.
4. `adapt_billing_observations(data, item, observations, document)` supplies typed
   engine inputs or a diagnostic with `facts=None`.
5. `build_ar_billing` applies eligibility, period/history checks, prices,
   deductions, taxes, dates and journal rules. Export remains a separate step.

**Stages 2–3 and their provider capture/replay connection remain to be integrated.**
The new adapter consumes the declared normalized boundary, not the generic
extractor's current field names or unvalidated provider JSON. Its schema version
is `ar-observations-v1`; this is not a claim that an AR prompt has been evaluated.
Future recordings must bind original/transformation hashes, model, prompt,
normalizer and schema versions through the existing #138 recorder.

## Envelope and fields

`BillingObservations` contains the `BillingType`, one `DocumentFacts`, explicit
`row_counts`, and `schema_version`. Its JSON uses the existing `DocumentFacts`
`typed-v1` codec, preserving all candidates and exact Decimal values. Extra
envelope/observation fields and incompatible versions fail rather than disappear.

Every document supplies `currency` normalized from a literal currency code/symbol;
it must match the active company's currency. An observed `contract_reference` is
optional, but when present must match the task's reference. Neither field is
inferred from a filename. The adapter does not create customer or contract IDs.

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
must contain at least one row. Counts come from parser/reviewer-established
complete tables, not confidence scores. **An internally consistent count cannot
prove that every original row was extracted**; source evaluation must measure
that independently.

Money is a strict integer number of local cents; MWh is integer thousandths;
`share_bp` is an integer from 0 to 10,000. PPA price is a finite, nonnegative
Decimal or decimal string in cents/MWh. Floats and booleans are rejected as
numeric values. The adapter never rounds or calculates an invoice. Market
deviations retain their observed sign. Dates/months must already be valid ISO
values. Prior normalization must preserve ambiguous separators and unknown units
as diagnostics rather than guessing from locale or target totals.

## Approval observations

`status_text` is literal source text, not a model-produced `approved` boolean.
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
the printed signer role: Dirección Facultativa (optionally its Ingeniero title)
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

For energy, printed plant names/IDs are compared exactly with the active phase's
cost-center master, filtered by company and the verified contract's plant IDs.
A unique candidate without an exact reference match remains unresolved. Duplicate
plants are rejected. Semantic matching, alternative references and evaluated AR
associations/abstentions belong to #57; no shared resolver is modified here.

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

Example integration shape, not an executed result:

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

- Connect an AR-specific literal schema/prompt and deterministic normalization
  with #137/#138, retaining observations independent of item metadata.
- Evaluate field labels, units, approval authority/scope, table completeness and
  omitted rows against originals, including pending/unknown/contradictory cases.
- Extend the sample with service extras and absent/conflicting evidence; the
  selected July monthly case contains no extras and does not exercise them.
- Capture/replay real AR extraction and resolution, including invalidation and
  zero new provider calls on replay; the sample is not a recording.
- Connect/evaluate #57 and demonstrate the complete current-phase billing flow
  after #140. September and final M2 acceptance are not claimed by this increment.
