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
