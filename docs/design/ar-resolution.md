# AR document references — #57

`kalmora.billing.resolution` links observed references to existing masters before
the accounting engine runs. It does not alter source facts, invoice calculation,
accounts, taxes, DIR3, due dates or delivery schemas. The metadata in `item.json`
still identifies the company, customer and contract; the existing engine validates
that exact relationship.

## Exact references and residual semantics

`resolve_billing_references(data, item, observations, document, *, resolver=None,
raw_facts=None, max_candidates=100)` first verifies the attachment path/hash and
each observation's original quotation, then validates the metadata contract and
customer. It retains printed contract references from normalized observations and
also accepts literal `contract_name` and `customer_name` from `raw_facts`.

IDs match literally. Human names/descriptions match after whitespace collapse and
case folding; accents and punctuation are preserved. There is no similarity
ranking, prefix shortcut or automatic selection of a singleton candidate.
Contradictory observations stop resolution before any semantic call. An exact
printed identity outside the eligible scope fails immediately. A resolved document
contract/customer that differs from the metadata also fails; it never substitutes
a new metadata identity.

Absent document contract/customer names do not assert a document match. The exact
metadata remains available, as in the existing billing contract. An absent plant
reference cannot supply an allocation. Duplicate source rows resolving to one
plant remain unresolved.

The optional injected shared `SemanticResolver` handles only references without a
unique exact match. It receives one bounded `ResolutionRequest` per unresolved
reference and must either select one eligible existing ID with source proof or
explicitly abstain. Requests include the original document, reference field/value,
expected metadata identities, candidate IDs/attributes and hard constraints.

| Request builder | Allowed candidates |
| --- | --- |
| `billing_contract_request` | Sales contracts of the exact company/customer and billing kind |
| `billing_customer_request` | Customer of the exactly verified metadata contract |
| `billing_plant_request` | Cost centers of the company listed in that contract's `plants` |

The builders also accept an absent reference for callers preparing independent
semantic requests from documents without printed IDs. The automatic workflow uses
only source observations already present; it does not interpret silence as proof.
Candidate sets over the configured limit fail; they are never truncated or ranked.
Master attributes sent to the resolver exclude accounting/tax configuration,
amounts, DIR3 and payment terms.

Every semantic selection is revalidated against the shared candidate/proof
contract. Its proof must additionally refer to the specific printed reference and
its original source locator. Proof for another row on the same document cannot
bind this row. More than one selected ID, missing reasons, changed requests,
changed facts, changed masters, wrong source hashes or ungrounded evidence fail.
The first unresolved reference stops further semantic requests for that attachment.

## Immutable bindings and reporting

`BillingReferences` stores immutable `ReferenceResolution` records containing the
printed reference, exact/semantic method, selection/abstention status, candidate
IDs, request fingerprint, reason and original/semantic evidence. Proofs are stored
as serialized JSON; `.evidence` and `.to_dict()` return independent copies.

The result binds the item metadata, original bytes, parsed transformation,
normalized observation envelope and active master snapshot by SHA-256. The
adapter consumes `.reference_id(...)` and `.plant_id(...)` with its current
`data`/`item` to reject stale bindings. The printed name stays in the original
observations; only the typed engine input receives the selected master ID.
Any resolution diagnostic prohibits applying the attachment's bindings.

The runner can inject the shared `RecordedResolver` to capture or replay semantic
requests. Source/candidate/context changes alter the existing recording key;
successful selections and abstentions retain their evidence and fingerprints.
This module creates no client, provider, cache or posting by itself.

## Validation and limits

The focused tests use independent in-memory master rows and an injected fake
resolver. They cover exact references with zero resolver calls, bounded semantic
aliases, singleton non-matches, conflicts, wrong contracts/companies, abstentions,
source-row proof, binding invalidation, literal name cross-checks, forbidden
accounting attributes and duplicate plants. No real provider call is needed.

The 11 focused tests pass. A read-only native extraction/resolution scan over all
26 July billing attachments also resolved every printed contract/customer/plant
reference without a semantic resolver or provider calls. The scan exposed one
wrapped Mexican customer name; correcting extraction to retain the complete
source text removed that abstention without weakening matching rules.

Native extraction and the end-to-end July run are recorded in the accompanying
[AR source workflow design](ar-source-runner.md). Provider quality on unfamiliar
aliases and scanned-only support still require source-grounded capture/evaluation;
passing deterministic examples does not establish that quality.
