# Close dependency contract v1

Runtime authority: `src/kalmora/close/contracts.py`, schema
`kalmora.close.dependencies/v1`. Both real adapters and the explicitly authorized
fixture adapter use this contract; there is no private fixture-only close model.
Output authority remains the shared `CloseRow`/`JournalEntry`/`JournalLine` types.
The shared CloseType receives only the compatible `DOUBTFUL_RECLASS` literal.

## Envelope

`phase`, `month` (YYYY-MM), `closing_date` (month-end), `sources` (relative original
file path to SHA-256), `dependencies`, `facts`, optional `recorded_events`, and
`payload_sha256`. The payload is canonical UTF-8 JSON, sorted keys, compact
separators, final LF; hash the whole envelope without `payload_sha256`. Nonfinite
JSON is rejected. Monetary calculation inputs are integer local/document cents;
FX conversion uses shared RateTable and explicit currencies.

Every dependency supplies `producer`, phase/month, provenance (`real` or
`golden_fixture`), source SHA-256, explicit completeness, expected/observed task
identities and owned postings. All five producers are required. A missing,
cross-phase, duplicate-owner or incomplete handoff fails closed. Coverage hashes
prove consistency of a snapshot, not that a provider's asserted coverage is true.

Each posting supplies a stable business key, `(event_id, stage)` owner, original
aliases when present, evidence and a balanced shared journal. Mock/real transient
IDs are not accounting identities. Same-business replacements are deduplicated;
contradictory financial representations fail. The journal fingerprint deliberately
ignores metadata enrichment of legacy document currencies, while FX principal is
validated separately. Real integration must review semantic-key mappings rather
than relying on journal IDs alone.

## Producer obligations

| Producer | Required accounting/factual delivery | July fixture coverage | Owned postings |
|---|---|---:|---:|
| AP | Full receipt register including non-posting decisions; posted journals; supplier/invoice identities, service coverage, cost objects, foreign principal | 305/305 documents | 242 |
| Billing | Issued journals/invoice due dates and original pending certification facts including current amount, chapters, customer/project and approval status | 26/26 items | 25 |
| Bank reconciliation | Adjustments and reconciled closing positions; event dates, account currencies and statement principal | 12/12 accounts | 56 |
| Cash application | Applications and adjustments retaining invoice/promissory-note identity; no second bank adjustment | 32/32 receipts | 32 |
| IC | Owned corrections with cause, company, account, partner, assignment and document/local currency distinction; service exclusions/positive coverage | 7/7 pairs | 4 |

IC fixture coverage assumes its exception report is exhaustive. Absence of an
exception is NOT real positive reconciliation evidence. The real adapter must
supply that evidence before #171 can pass. The fixture has 359 prior-stage
postings; no master opening balance is added on top of the ERP journal.

`facts` holds accrual series, prepaids, pending certifications, FX positions,
billed-invoice metadata, ageing evidence, DocumentFacts and explicit limitations.
There are 76 saved documentary observations in the July fixture. Historical
coverage and original currencies/amounts are not manufactured from closing
answers. Original documents are parsed through DocumentRouter; observed fields
retain shared Evidence and DocumentFacts with explicit fixture versions.

## Coverage and ownership details

AP decisions are retained even without a journal. Invoice existence is not
inferred from posting presence. PO-required/GR-IR-recognized services and services
owned by an IC correction are excluded from ACCRUAL. The fixture keeps group
corrections in IC and does not create group-supplier accrual series. Real adapters
must supply stable `ic_owned_services` links; this fixture's list is empty because
no selected series is group-owned, not because an empty real IC handoff is accepted.

An unassigned historical loan principal is bound to the single documented loan;
this binding is recorded explicitly and original entries remain unchanged. Open
foreign supplier invoices and credit notes retain their signed documentary
principal until a clearing source proves settlement. Historical FX omissions
do not establish a general credit-note exclusion from policy §5.
Any future multiple-loan ambiguity requires explicit per-position binding rather
than copying this fixture assumption.

Missing dates, contradictory periods and inferred recurring discrete consumption
are documented. `engine_data_complete` means enumerated engine facts passed its
checks, not universal service coverage. Forty adapter diagnostics/limitations are
retained. Historical min/max rate scenarios quantify estimator dispersion but
cannot bound completely unobserved work.

## Replay and real-provider substitution

The engine constructor revalidates the sealed handoff and makes a private copy.
Replay verifies ERP/tasks and the sealed facts without reopening inbox/bank files.
Tests replace fixture provenance/IDs with real handoffs while preserving business
identity, and reject changed financial payloads. These are contract substitution
tests, not evidence that current real M1–M5 producers have been connected.

For #171, run actual M1–M5, retain their versions/hashes and positive coverage,
build the same envelope without any golden_fixture dependency, validate source
links and stage ownership, then freeze and compare M6. Merely relabelling fixture
provenance as real is not valid integration evidence.
