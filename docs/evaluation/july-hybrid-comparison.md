# Frozen July comparison (#222)

## Protocol fixed before the first holdout capture

This comparison applies September's source-bound hybrid design to the existing
July sample: 12 tuning cases and eight previously sealed holdout cases, containing
22 original attachments. Selection, labels, quality thresholds and semantic
candidate construction remain unchanged. It is a heterogeneous document sample,
not an estimate of accuracy across the whole accounting close or unseen layouts.

The candidate is the provisionally approved `gpt-6-luna`, reasoning `low`, prompt
`document-observations-v17`, schema `document-interpretation-v3`. XML extraction
is deterministic. Native tables use a separately recorded
`outside_native_invoice_table` interpretation followed by verified composition;
unsupported layouts and scans use complete interpretation. Image-only pages
retain full original 300 DPI renders and exact-pixel overlapping strips. OCR
aids do not enter prompts. Page and native-row coverage are checked after
composition. Raw provider facts and composed facts remain separate artifacts.

Both partitions use one validation attempt and at most two transport attempts
per operation, concurrency two, no request timeout and no output-token cap.
This respects the sample's frozen holdout retry policy. It measures the same
hybrid source handling as September without adding source-validation repair
attempts to the holdout. Semantic requests come only from observations and
original ERP rows. Source documents and masters are untrusted data, and no
golden, annotation, selection rationale or review registry enters a model prompt.

The combined experimental budget is USD 5. The holdout client receives the
remaining budget after retaining all known costs and unknown-cost reservations
from tuning. Rates are conservative bounds from the
[official Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna):
USD 0.25/M input and USD 0.75/M output, including the documented long-context
cache-write/output ceiling. Input reservation is 900000 tokens, within the
verified model capacity; it is not an output limit. Actual token usage, elapsed
time and the supplied price assumptions remain archived. Estimates are not bills.

Original-source inventory found 294 PDFs / 310 pages and 58 XML attachments
across July inboxes, with three scanned PDFs / three pages and zero PDF parse
failures. The 20-case acceptance sample is evaluated separately from those
phase-wide source counts. Independent visual transcriptions of the three scans
were prepared before new model outputs, without reading holdout labels.

The source/configuration/module fingerprints are persisted in the local
`outputs/hotfix-222/july-frozen-comparison/freeze.json` before paid work.
No configuration is adjusted and no successful alternative answer is selected
after examining holdout outputs or labels. Failures remain in every denominator.
Opening the sealed holdout labels happens only at the offline evaluator boundary,
after both partitions' captures and original-image review. The label byte SHA-256
remains `e471a50c39383d96681a891f7fb142696dfb60fb3d41408165720de266f0c866`.

## Baseline and evaluation

The baseline reuses all previous v10 Luna tuning captures, including three failed
cases, plus the existing exact original-image quotation review. Its current
offline report measures 68/94 critical fields (72.34%), 78/114 required fields
(68.42%) and 481/546 grounded observations (88.10%). It fails acceptance. It is
an archived baseline, not a new live run.

New captures are fresh. Offline replay prohibits network/provider imports,
checks original and snapshot hashes, replays raw model/XML facts and recomputes
native composition. The evaluator retains exact numerators/denominators, extra
observations, ambiguous text, semantic selection, conflicts, cost and failures.
Independent image reviews bind each exact field/value/quote to the actual
captured source/page/image/transformation hashes. Unverified or wrong image
quotes fail the evidence gate. Evaluation results will be recorded below;
the July organizer golden's accounting score is outside this document benchmark.

## Measured result, 2026-10-03

The candidate **fails both partitions**. The frozen configuration/module hashes
were unchanged throughout capture and evaluation. No case was rerun or chosen
from competing successful answers. The holdout labels were opened at the offline
evaluator boundary after every capture and the independent original-image review.
The sanitized, versioned result is [july-hybrid-results.json](july-hybrid-results.json).

| Measure | Archived v10 tuning | New v17 tuning | New v17 holdout |
| --- | --- | --- | --- |
| Cases with accepted captures | 9/12 | 8/12 | 7/8 |
| Critical required-field exactness | 68/94 (72.34%) | 39/94 (41.49%) | 153/189 (80.95%) |
| Required-field exactness | 78/114 (68.42%) | 45/114 (39.47%) | 160/199 (80.40%) |
| Grounded returned observations | 481/546 (88.10%) | 599/647 (92.58%) | 420/433 (97.00%) |
| Critical prediction precision | 66/68 (97.06%) | 39/40 (97.50%) | 152/152 (100%) |
| Correct unique semantic selections / required checks | — | 0/4 | 1/8 |

The new partitions cost an estimated USD 0.03774625 and USD 0.03183175,
USD 0.06957800 total, with no unknown-cost reservation. Each case stayed below
the unchanged USD 0.10 cost gate. Observed p95 elapsed times, including failed
cases, were 33.11 and 32.10 seconds; no time threshold was reinstated. The old
baseline used different price assumptions and fewer cases, so these figures
do not establish a percentage cost or speed improvement.

Seventeen accepted original attachments replayed with zero provider calls and
network forbidden. Independent H07 review verified 66 exact raw/normalized image
observations against the original 300 DPI full-page render; all three retained
crops matched their declared parent pixels. One derived count was left unreviewed
in that registry. T12 returned 26 row IDs but omitted row descriptions/explicit
unknowns and failed coverage, so no accepted T12 image facts were credited.

This reveals integration defects as well as model omissions. T01/H08 returned
invoice rows despite outside-table scope; T10 returned unsupported `bank_details`;
T06 failed literal grounding. Some accepted responses omit headers or return
notice/certificate fields under names not mapped to required canonical slots.
Deterministic XML retains original leaf values but its projection of totals,
document types, row counts and proof units does not fully match the benchmark
contract. H07's literal units are returned as `uom`, while the reference slots
use `unit`. These are not all incorrect character transcriptions.

Semantic extraction issued only PO/receipt requests; it did not archive supplier
selections for seven holdout checks. Those unimplemented checks stay in the
denominator; 1/1 supplied holdout selection was correct, but 1/8 required coverage
is below the 80% gate. Exactness is below 95% and grounding below 100%, so neither
partition can be approved despite correct supported tables and the reviewed scan.

Issue #222 remains open for contract alignment, complete semantic integration and
acceptance. The old holdout is now consumed: subsequent changes require a fixed
new protocol with fresh reserved originals, rather than tuning to these answers
and claiming a new blind pass. This benchmark does not change Luna's provisional
approval or the already merged September extraction capability.
